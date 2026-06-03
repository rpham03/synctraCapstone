"""Chat route that uses a Colab-hosted NLP tool router.

Parallel to chat.py so the existing Ollama-backed chat route stays
unchanged. One Colab server (tool/colab_course_import_agent_server.py)
serves both POST /plan and POST /api/generate behind a single ngrok or
cloudflared tunnel.

To enable, add this once in backend/app/main.py:

    from app.api.v1.routes import chat_colab
    app.include_router(
        chat_colab.router,
        prefix="/api/v1/chat-colab",
        tags=["chat-colab"],
    )

Configuration — set this once in backend/.env:

    OLLAMA_HOST=https://your-tunnel.trycloudflare.com

OLLAMA_HOST is the shared tunnel URL used by both:
  * course_import.py for /api/generate
  * chat_colab.py    for /plan and the ai_agent /api/generate fallback

Optional overrides (only set if you split the server across two tunnels):

    COLAB_NLP_ROUTER_HOST   Separate tunnel hosting only /plan.
    COLAB_AI_AGENT_HOST     Separate tunnel hosting only /api/generate.
"""

from __future__ import annotations

import os
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.core.config.settings import settings


router = APIRouter(tags=["chat-colab"])


CLARIFICATION_ACTION = "clarification"
DEFAULT_TIMEOUT_S = 60.0
AI_AGENT_TIMEOUT_S = 120.0


def _shared_colab_host() -> str:
    """Default tunnel URL used by both /plan and /api/generate."""
    host = (
        os.getenv("OLLAMA_HOST")
        or settings.ollama_host
        or ""
    ).strip()
    return host.rstrip("/") if host else ""


def _nlp_router_host() -> str:
    """Tunnel URL for POST /plan. Falls back to OLLAMA_HOST."""
    host = (
        os.getenv("COLAB_NLP_ROUTER_HOST")
        or os.getenv("COLAB_ROUTER_HOST")
        or _shared_colab_host()
    ).strip()
    if not host or _is_local_host(host):
        raise HTTPException(
            status_code=503,
            detail=(
                "Colab NLP router is not configured. Set OLLAMA_HOST in "
                "backend/.env to the tunnel URL printed by "
                "tool/colab_course_import_agent_server.py "
                "(run it with --nlp-router-model-dir to enable /plan)."
            ),
        )
    return host.rstrip("/")


def _ai_agent_host() -> str | None:
    """Tunnel URL for the ai_agent fallback. Reuses OLLAMA_HOST by default."""
    host = (
        os.getenv("COLAB_AI_AGENT_HOST")
        or os.getenv("COLAB_COURSE_IMPORT_HOST")
        or settings.colab_course_import_host
        or _shared_colab_host()
    ).strip()
    if not host or _is_local_host(host):
        return None
    return host.rstrip("/")


def _ai_agent_model() -> str:
    return (
        os.getenv("COLAB_AI_AGENT_MODEL")
        or os.getenv("COLAB_COURSE_IMPORT_MODEL")
        or settings.colab_course_import_model
        or "Qwen/Qwen2.5-3B-Instruct"
    ).strip()


def _is_local_host(host: str) -> bool:
    """Local ollama hosts can't reach the Colab NLP router; ignore them here."""
    return any(needle in host for needle in ("localhost", "127.0.0.1", "0.0.0.0"))


class ChatColabRequest(BaseModel):
    """Body for a Colab-backed chat request."""

    message: str
    clarification_pending: bool = False
    today: str | None = None  # Optional YYYY-MM-DD override for the router.


class PlannedToolCall(BaseModel):
    name: str
    arguments: dict[str, Any]
    confidence: float
    reason: str


class ToolExecution(BaseModel):
    tool_call: PlannedToolCall
    result: dict[str, Any]


class ChatColabResponse(BaseModel):
    assistant_message: str
    tool_executions: list[ToolExecution]
    needs_clarification: bool = False
    clarification_question: str | None = None
    clarification_options: list[str] = []


async def _fetch_plan(
    client: httpx.AsyncClient,
    message: str,
    *,
    clarification_pending: bool,
    today: str | None,
) -> list[dict[str, Any]]:
    """Ask the Colab NLP router for planned tool calls."""

    payload: dict[str, Any] = {
        "message": message,
        "clarification_pending": clarification_pending,
    }
    if today:
        payload["today"] = today

    try:
        response = await client.post(f"{_nlp_router_host()}/plan", json=payload)
        response.raise_for_status()
    except httpx.ConnectError as exc:
        raise HTTPException(
            status_code=503,
            detail=(
                "Could not reach the Colab NLP router. Start "
                "tool/colab_nlp_router_agent_server.py in Colab and set "
                "COLAB_NLP_ROUTER_HOST to its public tunnel URL."
            ),
        ) from exc
    except httpx.TimeoutException as exc:
        raise HTTPException(
            status_code=504,
            detail="Colab NLP router timed out while planning the request.",
        ) from exc
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Colab NLP router error: {exc.response.text}",
        ) from exc

    body = response.json()
    calls = body.get("tool_calls") or body.get("plan") or []
    if not isinstance(calls, list):
        raise HTTPException(
            status_code=502,
            detail=f"Colab NLP router returned unexpected payload: {body!r}",
        )
    return calls


async def _call_ai_agent(client: httpx.AsyncClient, message: str) -> dict[str, Any]:
    """Send an ai_agent message to the Colab Ollama-compatible endpoint."""

    host = _ai_agent_host()
    if not host:
        return {
            "error": (
                "No Colab AI agent host configured. Set COLAB_AI_AGENT_HOST "
                "or COLAB_COURSE_IMPORT_HOST to the tunnel URL of an "
                "Ollama-compatible /api/generate endpoint."
            ),
            "message": message,
        }

    payload = {
        "model": _ai_agent_model(),
        "prompt": message,
        "stream": False,
        "options": {"temperature": 0.2, "syntra_mode": "ai_agent"},
    }
    try:
        response = await client.post(
            f"{host}/api/generate",
            json=payload,
            timeout=AI_AGENT_TIMEOUT_S,
        )
        response.raise_for_status()
    except httpx.RequestError as exc:
        return {"error": f"Colab AI request failed: {exc}", "message": message}

    data = response.json()
    return {
        "assistant_message": str(data.get("response") or "").strip(),
        "raw": data,
    }


async def _execute_local_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Execute a Synctra tool via the existing chat agent dispatcher.

    Imported lazily so this route does not crash to import time if the
    chat agent module is not on disk in a given environment.
    """

    try:
        from app.services.chat_agent_common import execute_tool  # type: ignore
    except Exception as exc:
        return {
            "error": (
                "Cannot dispatch tool calls: app.services.chat_agent_common "
                f"is unavailable ({type(exc).__name__}: {exc})."
            ),
            "tool": name,
            "arguments": arguments,
        }

    try:
        return await execute_tool(name, arguments)
    except Exception as exc:
        return {
            "error": f"{type(exc).__name__}: {exc}",
            "tool": name,
            "arguments": arguments,
        }


@router.get("/health")
async def health() -> dict[str, Any]:
    """Probe the Colab NLP router and ai_agent endpoints."""

    summary: dict[str, Any] = {}
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            host = _nlp_router_host()
            response = await client.get(f"{host}/health")
            response.raise_for_status()
            summary["nlp_router"] = {"host": host, "ok": True, "agent": response.json()}
        except HTTPException as exc:
            summary["nlp_router"] = {"ok": False, "error": exc.detail}
        except Exception as exc:
            summary["nlp_router"] = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

        ai_host = _ai_agent_host()
        if ai_host:
            try:
                response = await client.get(f"{ai_host}/health")
                response.raise_for_status()
                summary["ai_agent"] = {"host": ai_host, "ok": True, "agent": response.json()}
            except Exception as exc:
                summary["ai_agent"] = {
                    "host": ai_host,
                    "ok": False,
                    "error": f"{type(exc).__name__}: {exc}",
                }
        else:
            summary["ai_agent"] = {"ok": False, "error": "not configured"}

    return summary


@router.post("/", response_model=ChatColabResponse)
async def chat_with_colab_router(payload: ChatColabRequest) -> ChatColabResponse:
    """Plan a chat message via Colab and execute the planned tool calls."""

    async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT_S) as client:
        planned = await _fetch_plan(
            client,
            payload.message,
            clarification_pending=payload.clarification_pending,
            today=payload.today,
        )

        executions: list[ToolExecution] = []
        assistant_parts: list[str] = []
        needs_clarification = False
        clarification_question: str | None = None
        clarification_options: list[str] = []

        for raw_call in planned:
            tool_call = PlannedToolCall(
                name=str(raw_call.get("name", "ai_agent")),
                arguments=dict(raw_call.get("arguments") or {}),
                confidence=float(raw_call.get("confidence", 0.0)),
                reason=str(raw_call.get("reason", "")),
            )

            if tool_call.name == CLARIFICATION_ACTION:
                needs_clarification = True
                clarification_question = (
                    str(tool_call.arguments.get("question") or "").strip() or None
                )
                opts = tool_call.arguments.get("options") or []
                clarification_options = [str(o) for o in opts] if isinstance(opts, list) else []
                executions.append(
                    ToolExecution(
                        tool_call=tool_call,
                        result={
                            "needs_clarification": True,
                            "question": clarification_question,
                            "options": clarification_options,
                        },
                    )
                )
                continue

            if tool_call.name == "ai_agent":
                ai_message = str(tool_call.arguments.get("message") or payload.message)
                ai_result = await _call_ai_agent(client, ai_message)
                executions.append(ToolExecution(tool_call=tool_call, result=ai_result))
                if ai_result.get("assistant_message"):
                    assistant_parts.append(str(ai_result["assistant_message"]))
                continue

            result = await _execute_local_tool(tool_call.name, tool_call.arguments)
            executions.append(ToolExecution(tool_call=tool_call, result=result))

        assistant_message = "\n".join(part for part in assistant_parts if part).strip()
        if not assistant_message and needs_clarification and clarification_question:
            assistant_message = clarification_question

        return ChatColabResponse(
            assistant_message=assistant_message,
            tool_executions=executions,
            needs_clarification=needs_clarification,
            clarification_question=clarification_question,
            clarification_options=clarification_options,
        )

# Ollama local LLM agent with the same schedule tools as the OpenAI agent.
from __future__ import annotations

import json
from typing import Any

import httpx

from app.core.config.settings import settings
from app.services.chat_agent_common import (
    MAX_TOOL_ROUNDS,
    coerce_text,
    coerce_tool_name,
    execute_tool,
    ollama_tools,
    system_instructions,
)


def _parse_tool_arguments(raw: Any) -> dict[str, Any]:
    """Ollama may return tool arguments as a JSON string or an object."""
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        if not raw.strip():
            return {}
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


class OllamaAgentService:
    async def _chat(self, messages: list[dict[str, Any]]) -> dict[str, Any]:
        host = (settings.ollama_host or "http://localhost:11434").rstrip("/")
        model = (settings.ollama_model or "llama3.2").strip()
        payload = {
            "model": model,
            "messages": messages,
            "tools": ollama_tools(),
            "stream": False,
        }
        # Colab / remote tunnels need longer inference time than local Ollama.
        timeout = 180.0 if not host.startswith("http://localhost") and not host.startswith("http://127.0.0.1") else 120.0
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.post(f"{host}/api/chat", json=payload)
                resp.raise_for_status()
                return resp.json()
        except httpx.ConnectError as e:
            raise RuntimeError(
                "Cannot connect to the LLM server at "
                f"{host}. For local: run `ollama serve`. "
                "For Colab: run colab_course_import_agent_server.py with --tunnel cloudflared "
                "and set OLLAMA_HOST to the tunnel URL in backend/.env."
            ) from e
        except httpx.HTTPStatusError as e:
            detail = e.response.text[:400] if e.response is not None else str(e)
            raise RuntimeError(f"Ollama error {e.response.status_code}: {detail}") from e

    async def run_turn(
        self,
        user_message: str,
        *,
        history: list[dict[str, str]] | None = None,
    ) -> str:
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system_instructions()},
        ]
        for item in history or []:
            role = item.get("role", "user")
            content = coerce_text(item.get("content"))
            if role in ("user", "assistant") and content.strip():
                messages.append({"role": role, "content": content})
        messages.append({"role": "user", "content": user_message})

        for _ in range(MAX_TOOL_ROUNDS):
            data = await self._chat(messages)
            msg = data.get("message") or {}
            tool_calls = msg.get("tool_calls") or []

            if not tool_calls:
                content = coerce_text(msg.get("content")).strip()
                return content or "I could not generate a reply. Please try again."

            messages.append(msg)

            for call in tool_calls:
                fn = call.get("function") or {}
                if isinstance(fn, str):
                    fn = {"name": fn, "arguments": call.get("arguments", {})}
                name = coerce_tool_name(fn.get("name"))
                args = _parse_tool_arguments(fn.get("arguments"))
                result = await execute_tool(name, args)
                messages.append(
                    {
                        "role": "tool",
                        "content": json.dumps(result),
                        "name": name,
                    }
                )

        return (
            "I used several tools but need a simpler question. "
            "Try asking about one assignment or one time range."
        )

#!/usr/bin/env python3
"""Google Colab course-import AI server.

Standalone script — copy this file into a Colab notebook cell or upload it.
It does not import from the Synctra FastAPI app; run it on Colab GPU and exposes
two endpoints behind one tunnel:

  * POST /api/generate  — Ollama-compatible, used by course_import.py
  * POST /plan          — trained NLP tool router, used by chat_colab.py

Canonical copy in repo: ``backend/scripts/colab_course_import_agent_server.py``

Colab quick start (course import only)::

    !pip -q install fastapi uvicorn transformers accelerate torch
    !python colab_course_import_agent_server.py --tunnel cloudflared

Colab quick start with the trained chat router enabled::

    !pip -q install fastapi uvicorn transformers accelerate torch
    !python colab_course_import_agent_server.py \\
        --tunnel cloudflared \\
        --nlp-router-model-dir /content/syntra_tool_router \\
        --nlp-agent-path /content

When the server prints a public tunnel URL, put it in your **local** backend
``backend/.env``::

    OLLAMA_HOST=https://your-tunnel-url.trycloudflare.com

Then restart the Synctra backend. ``course_import.py`` posts to
``{OLLAMA_HOST}/api/generate`` and ``chat_colab.py`` posts to
``{OLLAMA_HOST}/plan``. One tunnel, two routes.

Optional Colab env vars::

    COLAB_COURSE_MODEL=Qwen/Qwen2.5-3B-Instruct
    COLAB_COURSE_MAX_NEW_TOKENS=4096
    COLAB_AGENT_BACKEND=transformers   # or mock for tunnel testing
    COLAB_TUNNEL=cloudflared           # or ngrok
    SYNTRA_TOOL_ROUTER_MODEL=/content/syntra_tool_router
    SYNTRA_AGENT_PATH=/content
    SYNTRA_TOOL_ROUTER_THRESHOLD=0.80
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import platform
import re
import stat
import subprocess
import sys
import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol
from urllib.request import urlretrieve

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field


DEFAULT_MODEL = "Qwen/Qwen2.5-3B-Instruct"
DEFAULT_MAX_NEW_TOKENS = 4096
COURSE_SYSTEM_PROMPT = (
    "You are a strict JSON extraction service for a course calendar app. "
    "Return exactly one JSON object and no markdown, commentary, or code fences."
)
AI_AGENT_SYSTEM_PROMPT = (
    "You are Synctra's helpful academic assistant. "
    "Answer the student's request directly and clearly. "
    "Do not return JSON unless the user asks for JSON."
)
SYSTEM_PROMPT = COURSE_SYSTEM_PROMPT


class GenerateRequest(BaseModel):
    """Subset of Ollama /api/generate used by course_import.py."""

    model: str | None = None
    prompt: str
    stream: bool = False
    format: dict[str, Any] | str | None = None
    options: dict[str, Any] = Field(default_factory=dict)


class GenerateResponse(BaseModel):
    model: str
    created_at: str
    response: str
    done: bool = True


class AgentBackend(Protocol):
    model_name: str

    def generate(self, prompt: str, options: dict[str, Any]) -> str:
        """Return course-import JSON or an ai_agent assistant response."""


def extract_json_object(text: str) -> str | None:
    """Extract the first balanced JSON object from an LLM response."""
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)

    start = text.find("{")
    if start == -1:
        return None

    depth = 0
    in_string = False
    escaped = False

    for index in range(start, len(text)):
        char = text[index]
        if escaped:
            escaped = False
            continue
        if char == "\\" and in_string:
            escaped = True
            continue
        if char == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]

    return None


def normalize_json_response(text: str) -> str:
    """Return compact JSON when possible, otherwise pass through raw text."""
    json_text = extract_json_object(text)
    if not json_text:
        return text.strip()

    try:
        parsed = json.loads(json_text)
    except json.JSONDecodeError:
        repaired = re.sub(r",\s*([}\]])", r"\1", json_text)
        try:
            parsed = json.loads(repaired)
        except json.JSONDecodeError:
            return json_text.strip()

    parsed.setdefault("class_events", [])
    parsed.setdefault("assignments", [])
    return json.dumps(parsed, ensure_ascii=False, separators=(",", ":"))


class MockAgent:
    """Fast startup mode for checking tunnels and local request wiring."""

    model_name = "mock-course-import-agent"

    def generate(self, prompt: str, options: dict[str, Any]) -> str:
        if str(options.get("syntra_mode") or options.get("mode") or "") == "ai_agent":
            return f"(Mock Colab ai_agent) I received: {prompt[:200]}"
        return json.dumps({"class_events": [], "assignments": []})


class TransformersAgent:
    """Small instruct-model backend suitable for Colab T4/L4 runtimes."""

    def __init__(self, model_name: str, max_new_tokens: int) -> None:
        self.model_name = model_name
        self.max_new_tokens = max_new_tokens
        self._tokenizer = None
        self._model = None

    def _load(self) -> None:
        if self._model is not None and self._tokenizer is not None:
            return

        try:
            import torch
            from transformers import AutoModelForCausalLM, AutoTokenizer
        except ImportError as exc:
            raise RuntimeError(
                "Missing model dependencies. In Colab run: "
                "!pip -q install transformers accelerate torch"
            ) from exc

        print(f"[agent] loading model: {self.model_name}", flush=True)
        self._tokenizer = AutoTokenizer.from_pretrained(
            self.model_name,
            trust_remote_code=True,
        )
        self._model = AutoModelForCausalLM.from_pretrained(
            self.model_name,
            torch_dtype="auto",
            device_map="auto",
            trust_remote_code=True,
        )
        self._model.eval()

    def _render_prompt(
        self,
        prompt: str,
        *,
        system_prompt: str,
        expects_json: bool,
    ) -> dict[str, Any]:
        assert self._tokenizer is not None
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ]
        if getattr(self._tokenizer, "chat_template", None):
            return self._tokenizer.apply_chat_template(
                messages,
                add_generation_prompt=True,
                return_dict=True,
                return_tensors="pt",
            )

        suffix = "JSON:" if expects_json else "Assistant:"
        rendered = f"{system_prompt}\n\nUser request:\n{prompt}\n\n{suffix}"
        return self._tokenizer(rendered, return_tensors="pt")

    def generate(self, prompt: str, options: dict[str, Any]) -> str:
        self._load()
        assert self._model is not None
        assert self._tokenizer is not None

        import torch

        mode = str(options.get("syntra_mode") or options.get("mode") or "course_import")
        is_ai_agent = mode == "ai_agent"
        encoded = self._render_prompt(
            prompt,
            system_prompt=AI_AGENT_SYSTEM_PROMPT if is_ai_agent else COURSE_SYSTEM_PROMPT,
            expects_json=not is_ai_agent,
        )
        first_device = next(self._model.parameters()).device
        encoded = {
            key: value.to(first_device) if torch.is_tensor(value) else value
            for key, value in encoded.items()
        }

        temperature = float(options.get("temperature", 0) or 0)
        max_new_tokens = int(
            options.get("num_predict")
            or os.getenv(
                "COLAB_CHAT_MAX_NEW_TOKENS" if is_ai_agent else "COLAB_COURSE_MAX_NEW_TOKENS",
                self.max_new_tokens,
            )
        )
        generation_kwargs: dict[str, Any] = {
            "max_new_tokens": max_new_tokens,
            "do_sample": temperature > 0,
            "pad_token_id": self._tokenizer.eos_token_id,
        }
        if temperature > 0:
            generation_kwargs["temperature"] = temperature

        with torch.inference_mode():
            output_ids = self._model.generate(**encoded, **generation_kwargs)

        input_len = encoded["input_ids"].shape[-1]
        new_tokens = output_ids[0][input_len:]
        text = self._tokenizer.decode(new_tokens, skip_special_tokens=True)
        if is_ai_agent:
            return text.strip()
        return normalize_json_response(text)


class NlpRouterBackend:
    """Wraps the trained NlpToolCallingAgent for the /plan endpoint.

    Loaded lazily so the rest of the server still works if the trained
    model directory is missing.
    """

    def __init__(
        self,
        *,
        model_dir: str,
        agent_path: str,
        confidence_threshold: float,
    ) -> None:
        if agent_path and agent_path not in sys.path:
            sys.path.insert(0, agent_path)
        try:
            from nlp_tool_calling_agent import NlpToolCallingAgent  # type: ignore
        except ImportError as exc:
            raise RuntimeError(
                f"Cannot import nlp_tool_calling_agent from {agent_path}. "
                "Use --nlp-agent-path to point at the directory containing "
                "nlp_tool_calling_agent.py."
            ) from exc

        from datetime import date as _date

        self.model_dir = model_dir
        self.confidence_threshold = confidence_threshold
        self._lock = threading.Lock()
        self._agent = NlpToolCallingAgent(
            today=_date.today(),
            model_dir=model_dir,
            confidence_threshold=confidence_threshold,
        )
        self.has_trained_model = self._agent.intent_model is not None

    def plan(
        self,
        message: str,
        *,
        clarification_pending: bool,
        today: str | None,
    ) -> list[dict[str, Any]]:
        from dataclasses import asdict
        from datetime import date as _date

        with self._lock:
            if today:
                try:
                    self._agent.today = datetime.strptime(today, "%Y-%m-%d").date()
                except ValueError as exc:
                    raise ValueError(f"today must be YYYY-MM-DD: {exc}") from exc
            else:
                self._agent.today = _date.today()
            calls = self._agent.plan(
                message,
                clarification_pending=clarification_pending,
            )
        return [asdict(call) for call in calls]


class PlanRequest(BaseModel):
    """Body for POST /plan, consumed by backend/.../chat_colab.py."""

    message: str
    clarification_pending: bool = False
    today: str | None = None  # Optional YYYY-MM-DD override.


def create_app(
    agent: AgentBackend,
    *,
    nlp_router: NlpRouterBackend | None = None,
) -> FastAPI:
    app = FastAPI(title="Colab Synctra Agent", version="0.2.0")

    endpoints = ["/api/generate"]
    if nlp_router is not None:
        endpoints.append("/plan")

    @app.get("/health")
    def health() -> dict[str, Any]:
        body: dict[str, Any] = {
            "ok": True,
            "model": agent.model_name,
            "ollama_compatible": True,
            "endpoints": endpoints,
        }
        if nlp_router is not None:
            body["nlp_router"] = {
                "model_dir": nlp_router.model_dir,
                "has_trained_model": nlp_router.has_trained_model,
                "confidence_threshold": nlp_router.confidence_threshold,
            }
        return body

    @app.post("/api/generate", response_model=GenerateResponse)
    def generate(request: GenerateRequest) -> GenerateResponse:
        if request.stream:
            raise HTTPException(
                status_code=400,
                detail="Streaming is not supported by this Colab adapter.",
            )

        try:
            response_text = agent.generate(request.prompt, request.options)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

        return GenerateResponse(
            model=request.model or agent.model_name,
            created_at=datetime.now(timezone.utc).isoformat(),
            response=response_text,
            done=True,
        )

    if nlp_router is not None:

        @app.post("/plan")
        def plan(request: PlanRequest) -> dict[str, Any]:
            if not request.message.strip():
                raise HTTPException(status_code=400, detail="message is required")
            try:
                calls = nlp_router.plan(
                    request.message,
                    clarification_pending=request.clarification_pending,
                    today=request.today,
                )
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            return {"tool_calls": calls}

    return app


def cloudflared_download_url() -> str:
    machine = platform.machine().lower()
    if machine in {"x86_64", "amd64"}:
        return (
            "https://github.com/cloudflare/cloudflared/releases/latest/download/"
            "cloudflared-linux-amd64"
        )
    if machine in {"aarch64", "arm64"}:
        return (
            "https://github.com/cloudflare/cloudflared/releases/latest/download/"
            "cloudflared-linux-arm64"
        )
    raise RuntimeError(f"Unsupported cloudflared CPU architecture: {machine}")


def ensure_cloudflared() -> str:
    existing = shutil_which("cloudflared")
    if existing:
        return existing

    target = Path(tempfile.gettempdir()) / "cloudflared"
    if not target.exists():
        print("[tunnel] downloading cloudflared", flush=True)
        urlretrieve(cloudflared_download_url(), target)
        target.chmod(target.stat().st_mode | stat.S_IXUSR)
    return str(target)


def shutil_which(command: str) -> str | None:
    for directory in os.environ.get("PATH", "").split(os.pathsep):
        candidate = Path(directory) / command
        if candidate.exists() and os.access(candidate, os.X_OK):
            return str(candidate)
    return None


def start_cloudflared_tunnel(port: int) -> subprocess.Popen[str]:
    binary = ensure_cloudflared()
    proc = subprocess.Popen(
        [
            binary,
            "tunnel",
            "--url",
            f"http://127.0.0.1:{port}",
            "--no-autoupdate",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )

    def read_output() -> None:
        assert proc.stdout is not None
        for line in proc.stdout:
            line = line.rstrip()
            print(f"[cloudflared] {line}", flush=True)
            match = re.search(r"https://[-a-zA-Z0-9]+\.trycloudflare\.com", line)
            if match:
                url = match.group(0)
                print("\n[tunnel] public URL:", url, flush=True)
                print("[tunnel] set OLLAMA_HOST to this URL in backend/.env\n", flush=True)

    threading.Thread(target=read_output, daemon=True).start()
    return proc


def start_ngrok_tunnel(port: int, token: str | None) -> Any:
    try:
        from pyngrok import ngrok
    except ImportError as exc:
        raise RuntimeError(
            "Install ngrok support first: !pip -q install pyngrok"
        ) from exc

    if token:
        ngrok.set_auth_token(token)
    tunnel = ngrok.connect(port, "http")
    print("\n[tunnel] public URL:", tunnel.public_url, flush=True)
    print("[tunnel] set OLLAMA_HOST to this URL in backend/.env\n", flush=True)
    return tunnel


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run an Ollama-compatible course-import AI server in Colab."
    )
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=int(os.getenv("PORT", "8001")))
    parser.add_argument(
        "--backend",
        choices=["transformers", "mock"],
        default=os.getenv("COLAB_AGENT_BACKEND", "transformers"),
        help="Use mock to test the tunnel without loading a model.",
    )
    parser.add_argument(
        "--model", default=os.getenv("COLAB_COURSE_MODEL", DEFAULT_MODEL)
    )
    parser.add_argument(
        "--max-new-tokens",
        type=int,
        default=int(os.getenv("COLAB_COURSE_MAX_NEW_TOKENS", DEFAULT_MAX_NEW_TOKENS)),
    )
    parser.add_argument(
        "--tunnel",
        choices=["none", "cloudflared", "ngrok"],
        default=os.getenv("COLAB_TUNNEL", "none"),
    )
    parser.add_argument("--ngrok-token", default=os.getenv("NGROK_AUTHTOKEN"))
    parser.add_argument(
        "--preload",
        action="store_true",
        help="Load the model before starting uvicorn.",
    )
    parser.add_argument(
        "--nlp-router-model-dir",
        default=os.getenv("SYNTRA_TOOL_ROUTER_MODEL"),
        help=(
            "Directory written by one_click_train_nlp_router_colab.py. "
            "When set, exposes POST /plan for the chat_colab.py backend route."
        ),
    )
    parser.add_argument(
        "--nlp-agent-path",
        default=os.getenv("SYNTRA_AGENT_PATH"),
        help=(
            "Directory containing nlp_tool_calling_agent.py. Defaults to the "
            "folder this script lives in."
        ),
    )
    parser.add_argument(
        "--nlp-confidence-threshold",
        type=float,
        default=float(os.getenv("SYNTRA_TOOL_ROUTER_THRESHOLD", "0.80")),
        help="Minimum classifier confidence before trusting a model label.",
    )
    args, unknown = parser.parse_known_args(argv)
    if unknown:
        print(f"[server] ignoring unknown notebook args: {unknown}", flush=True)
    return args


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)

    if args.backend == "mock":
        agent: AgentBackend = MockAgent()
    else:
        agent = TransformersAgent(args.model, args.max_new_tokens)
        if args.preload:
            agent._load()

    nlp_router: NlpRouterBackend | None = None
    if args.nlp_router_model_dir:
        agent_path = args.nlp_agent_path or str(Path(__file__).resolve().parent)
        try:
            nlp_router = NlpRouterBackend(
                model_dir=args.nlp_router_model_dir,
                agent_path=agent_path,
                confidence_threshold=args.nlp_confidence_threshold,
            )
            print(
                f"[nlp] loaded tool router from {args.nlp_router_model_dir} "
                f"(trained_model={nlp_router.has_trained_model}); "
                "POST /plan is enabled.",
                flush=True,
            )
        except Exception as exc:
            print(
                f"[nlp] failed to load NLP router: {exc}",
                file=sys.stderr,
                flush=True,
            )
            nlp_router = None
    else:
        print(
            "[nlp] no --nlp-router-model-dir; /plan endpoint disabled.",
            flush=True,
        )

    if args.tunnel == "cloudflared":
        start_cloudflared_tunnel(args.port)
        time.sleep(2)
    elif args.tunnel == "ngrok":
        start_ngrok_tunnel(args.port, args.ngrok_token)

    print(
        f"[server] starting on http://{args.host}:{args.port} "
        f"with backend={args.backend} model={agent.model_name}",
        flush=True,
    )
    print("[server] health check: GET /health", flush=True)
    print("[server] Ollama-compatible endpoint: POST /api/generate", flush=True)
    if nlp_router is not None:
        print("[server] NLP tool router endpoint: POST /plan", flush=True)

    try:
        import uvicorn
    except ImportError as exc:
        raise RuntimeError(
            "Install server dependency first: !pip -q install uvicorn"
        ) from exc

    app = create_app(agent, nlp_router=nlp_router)
    config = uvicorn.Config(app, host=args.host, port=args.port)

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        uvicorn.Server(config).run()
        return

    print(
        "[server] detected notebook event loop; running uvicorn in a background thread",
        flush=True,
    )
    server = uvicorn.Server(config)
    server_thread = threading.Thread(target=server.run, daemon=True)
    server_thread.start()
    try:
        while server_thread.is_alive():
            time.sleep(1)
    except KeyboardInterrupt:
        server.should_exit = True
        server_thread.join(timeout=10)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)

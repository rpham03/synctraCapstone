#!/usr/bin/env python3
"""Synctra Google Colab LLM server (course import + chat).

Standalone script — copy into a Colab notebook or upload this file.
Exposes Ollama-compatible endpoints so your **local** Synctra backend can use
Colab GPU instead of local Ollama:

- ``POST /api/generate`` — course-import JSON extraction (course_import.py)
- ``POST /api/chat`` — schedule assistant with tool calling (chat tab)

Canonical copy: ``backend/scripts/colab_course_import_agent_server.py``

Colab quick start::

    !pip -q install fastapi uvicorn transformers accelerate torch
    !python colab_course_import_agent_server.py --tunnel cloudflared --preload

When cloudflared prints a public URL, set in **local** ``backend/.env``::

    OLLAMA_HOST=https://your-tunnel-url.trycloudflare.com
    OLLAMA_MODEL=qwen2.5:3b

Restart the local backend (``uvicorn app.main:app --reload``).
Tool execution (Canvas, calendar, tasks) still runs locally; Colab only
runs the Hugging Face model.

Default model (free on Hugging Face, fits Colab T4):

    Qwen/Qwen2.5-3B-Instruct

Optional env vars::

    COLAB_LLM_MODEL=Qwen/Qwen2.5-3B-Instruct
    COLAB_COURSE_MAX_NEW_TOKENS=4096
    COLAB_CHAT_MAX_NEW_TOKENS=1024
    COLAB_AGENT_BACKEND=transformers   # or mock
    COLAB_TUNNEL=cloudflared
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


# Free HF instruct model — strong tool use for calendar/scheduling on Colab T4.
DEFAULT_MODEL = "Qwen/Qwen2.5-3B-Instruct"
DEFAULT_COURSE_MAX_TOKENS = 4096
DEFAULT_CHAT_MAX_TOKENS = 1024

COURSE_SYSTEM_PROMPT = (
    "You are a strict JSON extraction service for a course calendar app. "
    "Return exactly one JSON object and no markdown, commentary, or code fences."
)
AI_AGENT_SYSTEM_PROMPT = (
    "You are Synctra's helpful academic assistant. "
    "Answer the student's request directly and clearly. "
    "Do not return JSON unless the user asks for JSON."
)

TOOL_CALL_BLOCK_RE = re.compile(
    r"<tool_call>\s*(\{.*?\})\s*</tool_call>",
    re.DOTALL | re.IGNORECASE,
)


class GenerateRequest(BaseModel):
    """Ollama /api/generate — used by course_import.py."""

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


class ChatRequest(BaseModel):
    """Ollama /api/chat — used by the Synctra chat agent."""

    model: str | None = None
    messages: list[dict[str, Any]]
    tools: list[dict[str, Any]] = Field(default_factory=list)
    stream: bool = False
    options: dict[str, Any] = Field(default_factory=dict)


class ChatResponse(BaseModel):
    model: str
    created_at: str
    message: dict[str, Any]
    done: bool = True


class LlmBackend(Protocol):
    model_name: str

    def generate(self, prompt: str, options: dict[str, Any]) -> str:
        """Course-import JSON string."""

    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        options: dict[str, Any],
    ) -> dict[str, Any]:
        """Ollama-shaped assistant message (content and/or tool_calls)."""


def extract_json_object(text: str) -> str | None:
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


def ollama_tools_to_hf(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    converted: list[dict[str, Any]] = []
    for tool in tools:
        fn = tool.get("function") if isinstance(tool.get("function"), dict) else tool
        if not isinstance(fn, dict):
            continue
        name = fn.get("name")
        if not name:
            continue
        converted.append(
            {
                "type": "function",
                "function": {
                    "name": name,
                    "description": fn.get("description", ""),
                    "parameters": fn.get("parameters") or {"type": "object", "properties": {}},
                },
            }
        )
    return converted


def normalize_ollama_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Map Ollama chat messages to HF chat-template roles."""
    out: list[dict[str, Any]] = []
    for msg in messages:
        role = str(msg.get("role", "user"))
        content = msg.get("content", "")
        if role == "tool":
            name = msg.get("name") or msg.get("tool_name") or "tool"
            text = content if isinstance(content, str) else json.dumps(content)
            out.append(
                {
                    "role": "tool",
                    "name": name,
                    "content": text,
                }
            )
            continue
        if isinstance(content, list):
            parts = []
            for part in content:
                if isinstance(part, dict):
                    parts.append(str(part.get("text") or part.get("content") or ""))
                else:
                    parts.append(str(part))
            content = "\n".join(p for p in parts if p)
        out.append({"role": role, "content": str(content)})
    return out


def parse_tool_calls_from_text(text: str) -> tuple[str, list[dict[str, Any]]]:
    """Parse Qwen-style <tool_call>{...}</tool_call> blocks into Ollama tool_calls."""
    tool_calls: list[dict[str, Any]] = []
    for match in TOOL_CALL_BLOCK_RE.finditer(text):
        raw = match.group(1).strip()
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            continue
        name = payload.get("name") or payload.get("tool") or ""
        arguments = payload.get("arguments") or payload.get("parameters") or {}
        if not name:
            continue
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments)
            except json.JSONDecodeError:
                arguments = {}
        tool_calls.append(
            {
                "function": {
                    "name": str(name),
                    "arguments": arguments if isinstance(arguments, dict) else {},
                }
            }
        )

    content = TOOL_CALL_BLOCK_RE.sub("", text).strip()
    return content, tool_calls


def build_ollama_message(text: str) -> dict[str, Any]:
    content, tool_calls = parse_tool_calls_from_text(text)
    message: dict[str, Any] = {"role": "assistant", "content": content}
    if tool_calls:
        message["tool_calls"] = tool_calls
        if not content:
            message["content"] = ""
    return message


class MockBackend:
    """Tunnel / wiring test without loading a model."""

    model_name = "mock-synctra-colab-llm"

    def generate(self, prompt: str, options: dict[str, Any]) -> str:
        if str(options.get("syntra_mode") or options.get("mode") or "") == "ai_agent":
            return f"(Mock Colab ai_agent) I received: {prompt[:200]}"
        return json.dumps({"class_events": [], "assignments": []})

    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        options: dict[str, Any],
    ) -> dict[str, Any]:
        last_user = ""
        for msg in reversed(messages):
            if msg.get("role") == "user":
                last_user = str(msg.get("content", ""))
                break
        return {
            "role": "assistant",
            "content": (
                f"(Mock Colab agent) I received: {last_user[:200]}. "
                "Switch COLAB_AGENT_BACKEND=transformers to use the real model."
            ),
        }


class TransformersBackend:
    """Qwen2.5 (or any HF instruct model) on Colab GPU."""

    def __init__(
        self,
        model_name: str,
        *,
        course_max_tokens: int,
        chat_max_tokens: int,
    ) -> None:
        self.model_name = model_name
        self.course_max_tokens = course_max_tokens
        self.chat_max_tokens = chat_max_tokens
        self._tokenizer = None
        self._model = None

    def _load(self) -> None:
        if self._model is not None and self._tokenizer is not None:
            return

        try:
            from transformers import AutoModelForCausalLM, AutoTokenizer
        except ImportError as exc:
            raise RuntimeError(
                "Missing dependencies. In Colab run: "
                "!pip -q install transformers accelerate torch"
            ) from exc

        print(f"[agent] loading Hugging Face model: {self.model_name}", flush=True)
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
        print("[agent] model ready", flush=True)

    def _run_generate(
        self,
        encoded: dict[str, Any],
        *,
        max_new_tokens: int,
        options: dict[str, Any],
    ) -> str:
        import torch

        assert self._model is not None
        assert self._tokenizer is not None

        first_device = next(self._model.parameters()).device
        encoded = {
            key: value.to(first_device) if torch.is_tensor(value) else value
            for key, value in encoded.items()
        }

        temperature = float(options.get("temperature", 0) or 0)
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
        return self._tokenizer.decode(new_tokens, skip_special_tokens=True)

    def generate(self, prompt: str, options: dict[str, Any]) -> str:
        self._load()
        assert self._tokenizer is not None

        mode = str(options.get("syntra_mode") or options.get("mode") or "course_import")
        is_ai_agent = mode == "ai_agent"
        messages = [
            {
                "role": "system",
                "content": AI_AGENT_SYSTEM_PROMPT if is_ai_agent else COURSE_SYSTEM_PROMPT,
            },
            {"role": "user", "content": prompt},
        ]
        encoded = self._encode_messages(messages, tools=None)
        max_new = int(
            options.get("num_predict")
            or os.getenv(
                "COLAB_CHAT_MAX_NEW_TOKENS" if is_ai_agent else "COLAB_COURSE_MAX_NEW_TOKENS",
                self.chat_max_tokens if is_ai_agent else self.course_max_tokens,
            )
        )
        text = self._run_generate(encoded, max_new_tokens=max_new, options=options)
        if is_ai_agent:
            return text.strip()
        return normalize_json_response(text)

    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        options: dict[str, Any],
    ) -> dict[str, Any]:
        self._load()
        normalized = normalize_ollama_messages(messages)
        hf_tools = ollama_tools_to_hf(tools)
        encoded = self._encode_messages(normalized, tools=hf_tools or None)
        max_new = int(
            options.get("num_predict")
            or os.getenv("COLAB_CHAT_MAX_NEW_TOKENS", self.chat_max_tokens)
        )
        text = self._run_generate(encoded, max_new_tokens=max_new, options=options)
        return build_ollama_message(text)

    def _encode_messages(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
    ) -> dict[str, Any]:
        assert self._tokenizer is not None
        template_kwargs: dict[str, Any] = {
            "add_generation_prompt": True,
            "return_dict": True,
            "return_tensors": "pt",
        }
        if tools and getattr(self._tokenizer, "chat_template", None):
            template_kwargs["tools"] = tools
            try:
                return self._tokenizer.apply_chat_template(messages, **template_kwargs)
            except TypeError:
                pass

        if getattr(self._tokenizer, "chat_template", None):
            return self._tokenizer.apply_chat_template(messages, **template_kwargs)

        rendered = "\n".join(
            f"{m.get('role', 'user').upper()}: {m.get('content', '')}" for m in messages
        )
        rendered += "\nASSISTANT:"
        return self._tokenizer(rendered, return_tensors="pt")


def create_app(backend: LlmBackend) -> FastAPI:
    app = FastAPI(title="Synctra Colab LLM Server", version="0.2.0")

    @app.get("/health")
    def health() -> dict[str, Any]:
        return {
            "ok": True,
            "model": backend.model_name,
            "ollama_compatible": True,
            "endpoints": ["/api/generate", "/api/chat"],
            "provider": "huggingface-transformers-colab",
        }

    @app.get("/api/tags")
    def tags() -> dict[str, Any]:
        """Minimal Ollama tags stub so health probes succeed."""
        return {
            "models": [
                {
                    "name": backend.model_name,
                    "model": backend.model_name,
                    "modified_at": datetime.now(timezone.utc).isoformat(),
                    "size": 0,
                }
            ]
        }

    @app.post("/api/generate", response_model=GenerateResponse)
    def generate(request: GenerateRequest) -> GenerateResponse:
        if request.stream:
            raise HTTPException(status_code=400, detail="Streaming not supported.")
        try:
            response_text = backend.generate(request.prompt, request.options)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

        return GenerateResponse(
            model=request.model or backend.model_name,
            created_at=datetime.now(timezone.utc).isoformat(),
            response=response_text,
            done=True,
        )

    @app.post("/api/chat", response_model=ChatResponse)
    def chat(request: ChatRequest) -> ChatResponse:
        if request.stream:
            raise HTTPException(status_code=400, detail="Streaming not supported.")
        try:
            message = backend.chat(request.messages, request.tools, request.options)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

        return ChatResponse(
            model=request.model or backend.model_name,
            created_at=datetime.now(timezone.utc).isoformat(),
            message=message,
            done=True,
        )

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


def start_cloudflared_tunnel(
    port: int,
    *,
    wait_for_url_s: float = 60,
    backend_app: bool = False,
) -> subprocess.Popen[str]:
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
    url_ready = threading.Event()

    def read_output() -> None:
        assert proc.stdout is not None
        for line in proc.stdout:
            line = line.rstrip()
            print(f"[cloudflared] {line}", flush=True)
            match = re.search(r"https://[-a-zA-Z0-9]+\.trycloudflare\.com", line)
            if match:
                url = match.group(0)
                print("\n[tunnel] public URL:", url, flush=True)
                if backend_app:
                    print(
                        "[flutter] run with: "
                        f"flutter run -d chrome --dart-define=API_BASE_URL={url}",
                        flush=True,
                    )
                else:
                    print(
                        "[backend .env] COLAB_AI_AGENT_HOST="
                        f"{url}\n[backend .env] COLAB_COURSE_IMPORT_HOST={url}\n",
                        flush=True,
                    )
                url_ready.set()

    threading.Thread(target=read_output, daemon=True).start()
    if not url_ready.wait(wait_for_url_s):
        print(
            "[tunnel] no trycloudflare.com URL printed yet. "
            "Make sure the backend is running on the requested port, then rerun this cell.",
            flush=True,
        )
    return proc


def start_ngrok_tunnel(port: int, token: str | None) -> Any:
    try:
        from pyngrok import ngrok
    except ImportError as exc:
        raise RuntimeError("Install ngrok: !pip -q install pyngrok") from exc

    if token:
        ngrok.set_auth_token(token)
    tunnel = ngrok.connect(port, "http")
    print("\n[tunnel] public URL:", tunnel.public_url, flush=True)
    print("[tunnel] set OLLAMA_HOST in backend/.env to this URL\n", flush=True)
    return tunnel


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Synctra Colab LLM server (course import + chat)."
    )
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=int(os.getenv("PORT", "8001")))
    parser.add_argument(
        "--backend",
        choices=["transformers", "mock"],
        default=os.getenv("COLAB_AGENT_BACKEND", "transformers"),
        help="mock = test tunnel without GPU model load",
    )
    parser.add_argument(
        "--model",
        default=os.getenv("COLAB_LLM_MODEL", os.getenv("COLAB_COURSE_MODEL", DEFAULT_MODEL)),
    )
    parser.add_argument(
        "--max-new-tokens",
        type=int,
        default=int(os.getenv("COLAB_COURSE_MAX_NEW_TOKENS", DEFAULT_COURSE_MAX_TOKENS)),
        help="Max tokens for /api/generate (course import).",
    )
    parser.add_argument(
        "--chat-max-new-tokens",
        type=int,
        default=int(os.getenv("COLAB_CHAT_MAX_NEW_TOKENS", DEFAULT_CHAT_MAX_TOKENS)),
        help="Max tokens per /api/chat turn.",
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
        help="Load the HF model before starting uvicorn (recommended).",
    )
    args, unknown = parser.parse_known_args(argv)
    if unknown:
        print(f"[server] ignoring unknown notebook args: {unknown}", flush=True)
    return args


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)

    if args.backend == "mock":
        backend: LlmBackend = MockBackend()
    else:
        backend = TransformersBackend(
            args.model,
            course_max_tokens=args.max_new_tokens,
            chat_max_tokens=args.chat_max_new_tokens,
        )
        if args.preload:
            backend._load()

    if args.tunnel == "cloudflared":
        start_cloudflared_tunnel(args.port)
        time.sleep(2)
    elif args.tunnel == "ngrok":
        start_ngrok_tunnel(args.port, args.ngrok_token)

    print(
        f"[server] Synctra Colab LLM on http://{args.host}:{args.port} "
        f"backend={args.backend} model={backend.model_name}",
        flush=True,
    )
    print("[server] GET  /health", flush=True)
    print("[server] POST /api/generate  (course import)", flush=True)
    print("[server] POST /api/chat      (schedule chat + tools)", flush=True)

    try:
        import uvicorn
    except ImportError as exc:
        raise RuntimeError("Install uvicorn: !pip -q install uvicorn") from exc

    app = create_app(backend)
    config = uvicorn.Config(app, host=args.host, port=args.port)

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        uvicorn.Server(config).run()
        return

    print(
        "[server] notebook event loop detected; uvicorn running in background thread",
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

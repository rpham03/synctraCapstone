#!/usr/bin/env python3
"""Colab server that exposes the trained Syntra NLP tool router over HTTP.

This wraps tool/nlp_tool_calling_agent.py in a FastAPI app, loads the
classifier produced by tool/one_click_train_nlp_router_colab.py, and
makes it reachable from the Synctra backend via a public tunnel URL.

Run inside a Colab cell (after training the model in another cell):

    !pip install -q fastapi uvicorn nest_asyncio
    !python /content/colab_nlp_router_agent_server.py \\
        --model-dir /content/syntra_tool_router \\
        --agent-path /content \\
        --port 8000 \\
        --tunnel cloudflared

The script prints a public tunnel URL; copy it into the backend env var:

    export COLAB_NLP_ROUTER_HOST=https://abc123.trycloudflare.com

Endpoints exposed:

    GET  /health             readiness probe
    POST /plan               body: {message, clarification_pending?, today?}
                             returns: {tool_calls: [{name, arguments, ...}]}

The backend route at backend/app/api/v1/routes/chat_colab.py is the
intended consumer.
"""

from __future__ import annotations

import argparse
import os
import platform
import re
import stat
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import asdict
from datetime import date, datetime
from pathlib import Path
from typing import Any
from urllib.request import urlretrieve


DEFAULT_AGENT_FILENAME = "nlp_tool_calling_agent.py"


def _shutil_which(command: str) -> str | None:
    for directory in os.environ.get("PATH", "").split(os.pathsep):
        candidate = Path(directory) / command
        if candidate.exists() and os.access(candidate, os.X_OK):
            return str(candidate)
    return None


def _cloudflared_download_url() -> str:
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


def _ensure_cloudflared() -> str:
    existing = _shutil_which("cloudflared")
    if existing:
        return existing

    target = Path(tempfile.gettempdir()) / "cloudflared"
    if not target.exists():
        print("[tunnel] downloading cloudflared", flush=True)
        urlretrieve(_cloudflared_download_url(), target)
        target.chmod(target.stat().st_mode | stat.S_IXUSR)
    return str(target)


def _start_cloudflared_tunnel(port: int) -> subprocess.Popen[str]:
    binary = _ensure_cloudflared()
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
                print(
                    "[backend] set COLAB_NLP_ROUTER_HOST to this URL in backend/.env\n",
                    flush=True,
                )

    threading.Thread(target=read_output, daemon=True).start()
    return proc


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--model-dir",
        default=os.getenv("SYNTRA_TOOL_ROUTER_MODEL", "/content/syntra_tool_router"),
        help="Directory written by one_click_train_nlp_router_colab.py.",
    )
    parser.add_argument(
        "--confidence-threshold",
        type=float,
        default=float(os.getenv("SYNTRA_TOOL_ROUTER_THRESHOLD", "0.80")),
    )
    parser.add_argument(
        "--agent-path",
        default=os.getenv("SYNTRA_AGENT_PATH", str(Path(__file__).resolve().parent)),
        help=(
            "Directory containing nlp_tool_calling_agent.py. Defaults to the "
            "folder this script lives in."
        ),
    )
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=int(os.getenv("PORT", "8000")))
    parser.add_argument(
        "--ngrok-auth-token",
        default=os.getenv("NGROK_AUTH_TOKEN"),
        help="ngrok auth token. Required for stable Colab tunnels.",
    )
    parser.add_argument(
        "--tunnel",
        choices=["ngrok", "cloudflared", "none"],
        default=os.getenv("COLAB_NLP_ROUTER_TUNNEL", "cloudflared"),
        help="Public tunnel provider. cloudflared needs no account.",
    )
    parser.add_argument(
        "--no-tunnel",
        action="store_true",
        help="Compatibility flag. Same as --tunnel none.",
    )
    return parser


def _import_agent_module(agent_path: str):
    if agent_path and agent_path not in sys.path:
        sys.path.insert(0, agent_path)
    try:
        import nlp_tool_calling_agent  # type: ignore
    except ImportError as exc:
        candidate = Path(agent_path) / DEFAULT_AGENT_FILENAME
        raise SystemExit(
            f"Cannot import nlp_tool_calling_agent. Looked under {candidate}. "
            "Use --agent-path to point at the folder containing "
            f"{DEFAULT_AGENT_FILENAME}."
        ) from exc
    return nlp_tool_calling_agent


def main() -> None:
    args = _build_arg_parser().parse_args()

    try:
        import nest_asyncio
        import uvicorn
        from fastapi import FastAPI, HTTPException
        from pydantic import BaseModel
    except ImportError as exc:
        raise SystemExit(
            "Install server deps first:\n"
            "    pip install -q fastapi uvicorn nest_asyncio"
        ) from exc

    nest_asyncio.apply()
    agent_module = _import_agent_module(args.agent_path)
    NlpToolCallingAgent = agent_module.NlpToolCallingAgent

    agent = NlpToolCallingAgent(
        today=date.today(),
        model_dir=args.model_dir,
        confidence_threshold=args.confidence_threshold,
    )
    has_model = agent.intent_model is not None
    has_slot_model = agent.slot_model is not None
    if not has_model:
        print(
            f"[warning] no trained model found at {args.model_dir}; "
            "router will fall back to keyword heuristics.",
            file=sys.stderr,
        )
    if not has_slot_model:
        print(
            f"[warning] no slot model found at {Path(args.model_dir) / 'slot_model'}; "
            "router will fall back to regex slot extraction.",
            file=sys.stderr,
        )

    agent_lock = threading.Lock()
    app = FastAPI(title="Syntra NLP Tool Router")

    class PlanRequest(BaseModel):
        message: str
        clarification_pending: bool = False
        today: str | None = None  # YYYY-MM-DD override.

    @app.get("/health")
    def health() -> dict[str, Any]:
        return {
            "ok": True,
            "service": "syntra-nlp-router",
            "model_dir": args.model_dir,
            "has_trained_model": has_model,
            "has_slot_model": has_slot_model,
            "confidence_threshold": agent.confidence_threshold,
            "today": agent.today.isoformat(),
        }

    @app.post("/plan")
    def plan(request: PlanRequest) -> dict[str, Any]:
        if not request.message.strip():
            raise HTTPException(status_code=400, detail="message is required")

        with agent_lock:
            if request.today:
                try:
                    agent.today = datetime.strptime(request.today, "%Y-%m-%d").date()
                except ValueError as exc:
                    raise HTTPException(
                        status_code=400,
                        detail=f"today must be YYYY-MM-DD: {exc}",
                    ) from exc
            else:
                agent.today = date.today()

            calls = agent.plan(
                request.message,
                clarification_pending=request.clarification_pending,
            )

        return {"tool_calls": [asdict(call) for call in calls]}

    tunnel = "none" if args.no_tunnel else args.tunnel
    if tunnel == "cloudflared":
        _start_cloudflared_tunnel(args.port)
        time.sleep(2)
    elif tunnel == "ngrok":
        try:
            from pyngrok import ngrok
        except ImportError as exc:
            raise SystemExit(
                "pyngrok is required for the public tunnel. Install it or pass "
                "--tunnel cloudflared or --no-tunnel:\n    pip install -q pyngrok"
            ) from exc

        if args.ngrok_auth_token:
            ngrok.set_auth_token(args.ngrok_auth_token)
        public_url = ngrok.connect(args.port)
        print(f"[ngrok] public URL: {public_url}")
        print(
            "[backend] export COLAB_NLP_ROUTER_HOST=<that URL> on the backend, "
            "then POST /api/v1/chat-colab/."
        )

    print(
        f"[server] starting Syntra NLP router on http://{args.host}:{args.port}",
        flush=True,
    )
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()

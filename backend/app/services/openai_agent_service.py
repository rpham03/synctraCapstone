# OpenAI Responses API agent with schedule tools (Canvas, free slots, proposals).
from __future__ import annotations

import json
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from openai import OpenAI

from app.core.config.settings import settings
from app.services.chat_agent_common import (
    MAX_TOOL_ROUNDS,
    execute_tool,
    openai_tools,
    system_instructions,
)


class OpenAIAgentService:
    def __init__(self) -> None:
        self._client: OpenAI | None = None

    def _get_client(self) -> OpenAI:
        try:
            from openai import OpenAI
        except ModuleNotFoundError as exc:
            raise RuntimeError(
                "The optional OpenAI package is not installed. "
                "Install backend requirements or set CHAT_LLM_PROVIDER=ollama."
            ) from exc

        if self._client is None:
            api_key = (settings.openai_api_key or "").strip()
            if not api_key:
                raise RuntimeError("OPENAI_API_KEY is not configured.")
            self._client = OpenAI(api_key=api_key)
        return self._client

    async def run_turn(
        self,
        user_message: str,
        *,
        history: list[dict[str, str]] | None = None,
    ) -> str:
        client = self._get_client()
        model = (settings.openai_model or "gpt-4o-mini").strip()

        input_items: list[Any] = [
            {"role": "system", "content": system_instructions()},
        ]
        for item in history or []:
            role = item.get("role", "user")
            content = item.get("content", "")
            if role in ("user", "assistant") and content:
                input_items.append({"role": role, "content": content})
        input_items.append({"role": "user", "content": user_message})

        for _ in range(MAX_TOOL_ROUNDS):
            response = client.responses.create(
                model=model,
                input=input_items,
                tools=openai_tools(),
                store=False,
            )

            tool_calls = [
                item
                for item in (response.output or [])
                if getattr(item, "type", None) == "function_call"
            ]
            if not tool_calls:
                text = (response.output_text or "").strip()
                return text or "I could not generate a reply. Please try again."

            input_items.extend(response.output)

            for call in tool_calls:
                try:
                    args = json.loads(call.arguments or "{}")
                except json.JSONDecodeError:
                    args = {}
                if not isinstance(args, dict):
                    args = {}
                result = await execute_tool(call.name, args)
                input_items.append(
                    {
                        "type": "function_call_output",
                        "call_id": call.call_id,
                        "output": json.dumps(result),
                    }
                )

        return (
            "I used several tools but need a simpler question. "
            "Try asking about one assignment or one time range."
        )

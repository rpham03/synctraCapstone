# Chat service — routes messages to the trained NLP router, Ollama, OpenAI, or a keyword fallback.
"""Natural language chat handler for the Synctra schedule assistant."""

from __future__ import annotations

from typing import Any

from app.core.config.settings import settings
from app.services.chat_agent_common import sanitize_chat_reply
from app.services.chat_conversation_log import append_conversation_turn
from app.services.chat_client_context import (
    clear_client_context,
    get_schedule_proposals,
    set_calendar_events,
    set_client_today,
    set_tasks,
    set_timezone_name,
    set_timezone_offset_minutes,
)
from app.services.ollama_agent_service import OllamaAgentService
from app.services.openai_agent_service import OpenAIAgentService
from app.services.nlp_router_chat_service import NlpRouterChatService

# In-memory conversation per user_id (resets when the API restarts).
_history: dict[str, list[dict[str, str]]] = {}
_MAX_HISTORY_TURNS = 20


class ChatService:
    def __init__(self) -> None:
        self._nlp: NlpRouterChatService | None = None
        self._ollama: OllamaAgentService | None = None
        self._openai: OpenAIAgentService | None = None

    def _nlp_agent(self) -> NlpRouterChatService:
        if self._nlp is None:
            self._nlp = NlpRouterChatService()
        return self._nlp

    def _ollama_agent(self) -> OllamaAgentService:
        if self._ollama is None:
            self._ollama = OllamaAgentService()
        return self._ollama

    def _openai_agent(self) -> OpenAIAgentService:
        if self._openai is None:
            self._openai = OpenAIAgentService()
        return self._openai

    def _append_history(self, user_id: str, role: str, content: str) -> None:
        hist = _history.setdefault(user_id, [])
        hist.append({"role": role, "content": content})
        if len(hist) > _MAX_HISTORY_TURNS * 2:
            _history[user_id] = hist[-(_MAX_HISTORY_TURNS * 2) :]

    def _provider(self) -> str:
        """nlp | ollama | openai | auto"""
        return (settings.chat_llm_provider or "nlp").strip().lower()

    async def process_message(
        self,
        user_message: str,
        user_id: str,
        *,
        calendar_events: list[dict[str, Any]] | None = None,
        tasks: list[dict[str, Any]] | None = None,
        client_today: str | None = None,
        timezone_offset_minutes: int | None = None,
        timezone_name: str | None = None,
    ) -> tuple[str, list[dict[str, Any]]]:
        text = user_message.strip()
        if not text:
            return "Send me a message about your schedule or tasks.", []

        set_calendar_events(calendar_events)
        set_tasks(tasks)
        set_client_today(client_today)
        set_timezone_offset_minutes(timezone_offset_minutes)
        set_timezone_name(timezone_name)
        try:
            reply, proposals = await self._process_message_inner(text, user_id)
            append_conversation_turn(
                user_id=user_id,
                provider=self._provider(),
                user_message=text,
                assistant_reply=reply,
                schedule_proposals=proposals,
                client_today=client_today,
                timezone_name=timezone_name,
            )
            return reply, proposals
        except Exception as exc:
            append_conversation_turn(
                user_id=user_id,
                provider=self._provider(),
                user_message=text,
                assistant_reply=f"ERROR: {exc}",
                client_today=client_today,
                timezone_name=timezone_name,
            )
            raise
        finally:
            clear_client_context()

    async def _process_message_inner(self, text: str, user_id: str) -> tuple[str, list[dict[str, Any]]]:
        provider = self._provider()
        if provider in ("nlp", "nlp-router", "colab-nlp", "colab_nlp"):
            try:
                history = list(_history.get(user_id, []))
                reply = await self._nlp_agent().run_turn(
                    text,
                    user_id=user_id,
                    history=history,
                )
                reply = sanitize_chat_reply(reply)
                self._append_history(user_id, "user", text)
                self._append_history(user_id, "assistant", reply)
                return reply, get_schedule_proposals()
            except Exception as e:
                return f"{str(e)[:500]}", []

        use_ollama = provider == "ollama" or (
            provider == "auto" and not (settings.openai_api_key or "").strip()
        )
        use_openai = provider == "openai" or (
            provider == "auto" and (settings.openai_api_key or "").strip()
        )

        if use_ollama and provider != "openai":
            try:
                history = list(_history.get(user_id, []))
                reply = await self._ollama_agent().run_turn(text, history=history)
                reply = sanitize_chat_reply(reply)
                self._append_history(user_id, "user", text)
                self._append_history(user_id, "assistant", reply)
                return reply, get_schedule_proposals()
            except Exception as e:
                if use_openai and (settings.openai_api_key or "").strip():
                    pass  # fall through to OpenAI
                else:
                    return (
                        f"{str(e)[:500]}. "
                        "Use a tool-capable model, e.g. ollama pull llama3.2",
                        [],
                    )

        if use_openai and (settings.openai_api_key or "").strip():
            try:
                history = list(_history.get(user_id, []))
                reply = await self._openai_agent().run_turn(text, history=history)
                reply = sanitize_chat_reply(reply)
                self._append_history(user_id, "user", text)
                self._append_history(user_id, "assistant", reply)
                return reply, get_schedule_proposals()
            except Exception as e:
                return (
                    f"I hit an error talking to the AI service: {str(e)[:400]}. "
                    "Check OPENAI_API_KEY and billing, or set CHAT_LLM_PROVIDER=ollama.",
                    [],
                )

        return self._fallback_reply(text.lower()), []

    def _fallback_reply(self, text: str) -> str:
        """Keyword routing when no LLM is available."""
        if any(
            k in text
            for k in (
                "due",
                "deadline",
                "homework",
                "assignment",
                "this week",
                "what's due",
            )
        ):
            return (
                "I can help you think about deadlines. "
                "Open the Tasks tab or sync Canvas to see what is due soon. "
                "Start Ollama (ollama serve) or add OPENAI_API_KEY for the full agent."
            )

        if any(
            k in text
            for k in (
                "move",
                "reschedule",
                "tomorrow",
                "next week",
                "friday",
                "monday",
                "hours",
                "study",
            )
        ):
            return (
                "To schedule study time, run Ollama locally (ollama serve, ollama pull llama3.2) "
                "or set OPENAI_API_KEY — then Chat can propose blocks using your tools."
            )

        return (
            "I am Synctra, your schedule assistant. "
            "Run Ollama on your Mac for free AI chat, or configure OPENAI_API_KEY."
        )

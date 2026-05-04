# Chat service — receives natural language messages and routes them to schedule actions.
"""Natural language chat handler — parses user intent and updates the schedule."""


class ChatService:
    async def process_message(self, user_message: str, user_id: str) -> str:
        """
        Parse the user's message and route to the appropriate action.
        Uses lightweight keyword routing until an LLM is wired in.
        """
        _ = user_id  # reserved for per-user context when persistence exists
        text = user_message.strip().lower()
        if not text:
            return "Send me a message about your schedule or tasks."

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
                "Open the Tasks tab or sync Canvas to see what is due soon."
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
            )
        ):
            return (
                "To change a block, edit it in the schedule view. "
                "Automated reschedule from chat will come in a later iteration."
            )

        return (
            "I am here to help with your calendar and study plan. "
            "Ask what is due or describe what you want to work on next."
        )

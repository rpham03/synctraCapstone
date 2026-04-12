# Chat service — receives natural language messages and routes them to schedule actions.
"""Natural language chat handler — parses user intent and updates the schedule."""

class ChatService:
    async def process_message(self, user_message: str, user_id: str) -> str:
        """
        Parse the user's message and route to the appropriate action.
        Examples:
          - "move my study session to tomorrow" -> reschedule block
          - "add 2 hours for homework on Friday" -> create new block
          - "what's due this week?" -> query tasks
        """
        # TODO: integrate LLM for intent parsing
        return "I received your request. Scheduling logic coming soon."

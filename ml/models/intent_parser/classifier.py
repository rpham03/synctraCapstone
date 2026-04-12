# Classifies chat messages into schedule action intents (move, add, delete, query).
"""
Chat Intent Classifier
-----------------------
Maps natural language user messages to structured schedule actions.

Intents:
  - MOVE_BLOCK      "move my study session to tomorrow at 3pm"
  - ADD_BLOCK       "add 2 hours for CS homework on Friday"
  - DELETE_BLOCK    "remove my study block on Monday"
  - QUERY_SCHEDULE  "what's on my schedule this week?"
  - QUERY_TASKS     "what assignments are due soon?"
  - UNKNOWN
"""
from enum import Enum


class Intent(str, Enum):
    MOVE_BLOCK = "MOVE_BLOCK"
    ADD_BLOCK = "ADD_BLOCK"
    DELETE_BLOCK = "DELETE_BLOCK"
    QUERY_SCHEDULE = "QUERY_SCHEDULE"
    QUERY_TASKS = "QUERY_TASKS"
    UNKNOWN = "UNKNOWN"


class IntentClassifier:
    # TODO: replace with fine-tuned text classifier or LLM function-calling
    KEYWORDS = {
        Intent.MOVE_BLOCK: ["move", "reschedule", "shift"],
        Intent.ADD_BLOCK: ["add", "schedule", "block", "time for"],
        Intent.DELETE_BLOCK: ["remove", "delete", "cancel"],
        Intent.QUERY_SCHEDULE: ["schedule", "calendar", "today", "this week"],
        Intent.QUERY_TASKS: ["due", "assignment", "homework", "deadline"],
    }

    def predict(self, message: str) -> Intent:
        text = message.lower()
        for intent, keywords in self.KEYWORDS.items():
            if any(kw in text for kw in keywords):
                return intent
        return Intent.UNKNOWN

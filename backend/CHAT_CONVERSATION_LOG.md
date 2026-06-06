# Chat Conversation Log

The backend writes every completed chat turn to:

```text
backend/data/chat_conversations.jsonl
```

Each JSONL row contains:

- UTC timestamp
- user ID
- selected chat provider
- user message
- assistant reply
- schedule proposals returned to Flutter
- client date and timezone name

Full calendar and task context is not written to this file.

Environment settings:

```env
CHAT_CONVERSATION_LOG_ENABLED=true
CHAT_CONVERSATION_LOG_PATH=data/chat_conversations.jsonl
```

In the all-in-one Google Colab notebook, the file is located at:

```text
/content/syntra/backend/data/chat_conversations.jsonl
```

Download it from Colab:

```python
from google.colab import files
files.download('/content/syntra/backend/data/chat_conversations.jsonl')
```

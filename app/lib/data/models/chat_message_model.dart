// Data model for a single chat message exchanged between the user and the AI assistant.
enum MessageRole { user, assistant }

class ChatMessageModel {
  final String id;
  final String content;
  final MessageRole role;
  final DateTime timestamp;

  const ChatMessageModel({
    required this.id,
    required this.content,
    required this.role,
    required this.timestamp,
  });
}

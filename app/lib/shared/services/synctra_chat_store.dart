// Shared Sync It conversation — survives closing the calendar panel or switching tabs.
import 'package:flutter/foundation.dart';
import 'package:get_it/get_it.dart';

import '../../data/models/chat_message_model.dart';
import 'synctra_chat_constants.dart';

class SynctraChatStore extends ChangeNotifier {
  final List<ChatMessageModel> _messages = [];
  bool _loading = false;

  List<ChatMessageModel> get messages => List.unmodifiable(_messages);
  bool get loading => _loading;

  SynctraChatStore() {
    resetToWelcome();
  }

  static ChatMessageModel _welcomeMessage() => ChatMessageModel(
        id: 'welcome',
        content: SynctraChatConstants.welcome,
        role: MessageRole.assistant,
        timestamp: DateTime.now(),
      );

  void resetToWelcome() {
    _messages
      ..clear()
      ..add(_welcomeMessage());
    _loading = false;
    notifyListeners();
  }

  void addUserMessage(String text) {
    _messages.add(
      ChatMessageModel(
        id: DateTime.now().millisecondsSinceEpoch.toString(),
        content: text,
        role: MessageRole.user,
        timestamp: DateTime.now(),
      ),
    );
    notifyListeners();
  }

  void addAssistantMessage(String text) {
    _messages.add(
      ChatMessageModel(
        id: '${DateTime.now().millisecondsSinceEpoch}_resp',
        content: text,
        role: MessageRole.assistant,
        timestamp: DateTime.now(),
      ),
    );
    notifyListeners();
  }

  void setLoading(bool value) {
    if (_loading == value) return;
    _loading = value;
    notifyListeners();
  }
}

void registerSynctraChatStore() {
  final g = GetIt.instance;
  if (!g.isRegistered<SynctraChatStore>()) {
    g.registerSingleton(SynctraChatStore());
  }
}

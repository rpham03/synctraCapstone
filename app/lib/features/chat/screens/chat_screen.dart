// Chat interface — lets users update their schedule through natural language.
import 'package:flutter/material.dart';
import 'package:intl/intl.dart';

import '../../../core/theme/app_theme.dart';
import '../../../data/models/chat_message_model.dart';

class ChatScreen extends StatefulWidget {
  const ChatScreen({super.key});

  @override
  State<ChatScreen> createState() => _ChatScreenState();
}

class _ChatScreenState extends State<ChatScreen> {
  final _ctrl       = TextEditingController();
  final _scrollCtrl = ScrollController();
  bool _loading = false;

  final List<ChatMessageModel> _messages = [
    // Greeting from the AI on first open
    ChatMessageModel(
      id: 'welcome',
      content: "Hi! I'm Synctra, your AI schedule assistant. "
          "You can ask me things like:\n"
          "• \"Move my study session to tomorrow at 3pm\"\n"
          "• \"Add 2 hours for CSE 444 lab on Friday\"\n"
          "• \"What's due this week?\"\n"
          "• \"When can I meet with my group?\"",
      role: MessageRole.assistant,
      timestamp: DateTime.now(),
    ),
  ];

  @override
  void dispose() {
    _ctrl.dispose();
    _scrollCtrl.dispose();
    super.dispose();
  }

  Future<void> _send() async {
    final text = _ctrl.text.trim();
    if (text.isEmpty) return;

    // Append user message
    setState(() {
      _messages.add(ChatMessageModel(
        id: DateTime.now().millisecondsSinceEpoch.toString(),
        content: text,
        role: MessageRole.user,
        timestamp: DateTime.now(),
      ));
      _loading = true;
    });
    _ctrl.clear();
    _scrollToBottom();

    // TODO: call backend /api/v1/chat with the message
    await Future.delayed(const Duration(seconds: 1));

    setState(() {
      _messages.add(ChatMessageModel(
        id: '${DateTime.now().millisecondsSinceEpoch}_resp',
        content: "Got it! I'm working on that — scheduling logic coming soon.",
        role: MessageRole.assistant,
        timestamp: DateTime.now(),
      ));
      _loading = false;
    });
    _scrollToBottom();
  }

  void _scrollToBottom() {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (_scrollCtrl.hasClients) {
        _scrollCtrl.animateTo(
          _scrollCtrl.position.maxScrollExtent,
          duration: const Duration(milliseconds: 300),
          curve: Curves.easeOut,
        );
      }
    });
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: Row(children: [
          CircleAvatar(
            radius: 16,
            backgroundColor: AppColors.primary.withAlpha(30),
            child: const Icon(Icons.auto_awesome, size: 16, color: AppColors.primary),
          ),
          const SizedBox(width: 10),
          const Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text('Synctra AI', style: TextStyle(fontSize: 15)),
              Text('Schedule assistant', style: TextStyle(fontSize: 11, color: Colors.grey)),
            ],
          ),
        ]),
        actions: [
          IconButton(
            icon: const Icon(Icons.more_vert),
            onPressed: () {/* TODO: clear chat, version picker */},
          ),
        ],
      ),
      body: Column(
        children: [
          // ── Message list ──────────────────────────────────────────
          Expanded(
            child: ListView.builder(
              controller: _scrollCtrl,
              padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
              itemCount: _messages.length + (_loading ? 1 : 0),
              itemBuilder: (_, i) {
                if (_loading && i == _messages.length) return const _TypingIndicator();
                return _MessageBubble(message: _messages[i]);
              },
            ),
          ),

          // ── Suggestion chips ──────────────────────────────────────
          SizedBox(
            height: 42,
            child: ListView(
              scrollDirection: Axis.horizontal,
              padding: const EdgeInsets.symmetric(horizontal: 12),
              children: [
                "What's due soon?",
                "Plan my week",
                "Find group time",
                "Add homework block",
              ]
                  .map((s) => Padding(
                        padding: const EdgeInsets.only(right: 8),
                        child: ActionChip(
                          label: Text(s, style: const TextStyle(fontSize: 12)),
                          onPressed: () {
                            _ctrl.text = s;
                            _send();
                          },
                        ),
                      ))
                  .toList(),
            ),
          ),

          // ── Input bar ─────────────────────────────────────────────
          const Divider(height: 1),
          Padding(
            padding: EdgeInsets.fromLTRB(
                12, 8, 12, MediaQuery.of(context).viewInsets.bottom + 8),
            child: Row(children: [
              Expanded(
                child: TextField(
                  controller: _ctrl,
                  textCapitalization: TextCapitalization.sentences,
                  onSubmitted: (_) => _send(),
                  decoration: InputDecoration(
                    hintText: 'Ask me anything about your schedule…',
                    contentPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
                    border: OutlineInputBorder(borderRadius: BorderRadius.circular(24)),
                    isDense: true,
                  ),
                ),
              ),
              const SizedBox(width: 8),
              IconButton.filled(
                onPressed: _loading ? null : _send,
                icon: const Icon(Icons.send_rounded),
                style: IconButton.styleFrom(backgroundColor: AppColors.primary),
              ),
            ]),
          ),
        ],
      ),
    );
  }
}

// ── Sub-widgets ────────────────────────────────────────────────────────────────

class _MessageBubble extends StatelessWidget {
  final ChatMessageModel message;
  const _MessageBubble({required this.message});

  @override
  Widget build(BuildContext context) {
    final isUser = message.role == MessageRole.user;
    return Align(
      alignment: isUser ? Alignment.centerRight : Alignment.centerLeft,
      child: Container(
        constraints: BoxConstraints(
            maxWidth: MediaQuery.of(context).size.width * 0.78),
        margin: const EdgeInsets.only(bottom: 12),
        padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
        decoration: BoxDecoration(
          color: isUser ? AppColors.primary : Colors.white,
          borderRadius: BorderRadius.only(
            topLeft: const Radius.circular(18),
            topRight: const Radius.circular(18),
            bottomLeft: Radius.circular(isUser ? 18 : 4),
            bottomRight: Radius.circular(isUser ? 4 : 18),
          ),
          boxShadow: [
            BoxShadow(
              color: Colors.black.withAlpha(10),
              blurRadius: 4,
              offset: const Offset(0, 2),
            ),
          ],
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              message.content,
              style: TextStyle(
                color: isUser ? Colors.white : Colors.black87,
                height: 1.4,
              ),
            ),
            const SizedBox(height: 4),
            Text(
              DateFormat('h:mm a').format(message.timestamp),
              style: TextStyle(
                  fontSize: 10,
                  color: isUser ? Colors.white60 : Colors.grey[400]),
            ),
          ],
        ),
      ),
    );
  }
}

class _TypingIndicator extends StatelessWidget {
  const _TypingIndicator();

  @override
  Widget build(BuildContext context) {
    return Align(
      alignment: Alignment.centerLeft,
      child: Container(
        margin: const EdgeInsets.only(bottom: 12),
        padding: const EdgeInsets.all(14),
        decoration: BoxDecoration(
          color: Colors.white,
          borderRadius: BorderRadius.circular(18),
          boxShadow: [
            BoxShadow(color: Colors.black.withAlpha(10), blurRadius: 4),
          ],
        ),
        child: const Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            _Dot(delay: 0),
            SizedBox(width: 4),
            _Dot(delay: 200),
            SizedBox(width: 4),
            _Dot(delay: 400),
          ],
        ),
      ),
    );
  }
}

class _Dot extends StatefulWidget {
  final int delay;
  const _Dot({required this.delay});

  @override
  State<_Dot> createState() => _DotState();
}

class _DotState extends State<_Dot> with SingleTickerProviderStateMixin {
  late final AnimationController _ctrl;

  @override
  void initState() {
    super.initState();
    _ctrl = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 600),
    )..repeat(reverse: true);
  }

  @override
  void dispose() { _ctrl.dispose(); super.dispose(); }

  @override
  Widget build(BuildContext context) {
    return FadeTransition(
      opacity: _ctrl,
      child: Container(
        width: 7, height: 7,
        decoration: const BoxDecoration(
          color: Colors.grey, shape: BoxShape.circle),
      ),
    );
  }
}

// Embedded Synctra AI chat — used on Chat tab and beside the weekly task board.
import 'package:flutter/material.dart';
import 'package:get_it/get_it.dart';
import 'package:intl/intl.dart';

import '../../data/models/chat_message_model.dart';
import '../services/synctra_chat_constants.dart';
import '../services/synctra_chat_service.dart';
import '../services/synctra_chat_store.dart';
import 'sync_it_chrome.dart';

class SynctraChatPanel extends StatefulWidget {
  /// Smaller padding and bubbles when docked next to the week board.
  final bool compact;

  /// Show a small header row with title + clear menu.
  final bool showHeader;

  /// Quick prompts shown above the input (calendar: plan week, add blocks, etc.).
  final List<String>? suggestionChips;

  /// When set, shows a close control (e.g. calendar overlay sheet).
  final VoidCallback? onClose;

  const SynctraChatPanel({
    super.key,
    this.compact = false,
    this.showHeader = true,
    this.suggestionChips,
    this.onClose,
  });

  @override
  State<SynctraChatPanel> createState() => _SynctraChatPanelState();
}

class _SynctraChatPanelState extends State<SynctraChatPanel> {
  final _ctrl = TextEditingController();
  final _scrollCtrl = ScrollController();

  SynctraChatService get _chat => GetIt.instance<SynctraChatService>();
  SynctraChatStore get _store => GetIt.instance<SynctraChatStore>();

  @override
  void initState() {
    super.initState();
    _store.addListener(_onStoreChanged);
    WidgetsBinding.instance.addPostFrameCallback((_) => _scrollToBottom());
  }

  @override
  void dispose() {
    _store.removeListener(_onStoreChanged);
    _ctrl.dispose();
    _scrollCtrl.dispose();
    super.dispose();
  }

  void _onStoreChanged() {
    if (mounted) {
      setState(() {});
      _scrollToBottom();
    }
  }

  Future<void> _send() async {
    final text = _ctrl.text.trim();
    if (text.isEmpty || _store.loading) return;

    _store.addUserMessage(text);
    _store.setLoading(true);
    _ctrl.clear();

    final reply = await _chat.sendMessage(text);

    if (!mounted) return;
    _store.addAssistantMessage(reply.reply);
    _store.setLoading(false);
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

  void _clearChat() {
    _store.resetToWelcome();
  }

  @override
  Widget build(BuildContext context) {
    final messages = _store.messages;
    final loading = _store.loading;
    final scheme = Theme.of(context).colorScheme;
    final theme = Theme.of(context).textTheme;
    final hPad = widget.compact ? 12.0 : 16.0;
    final maxBubbleW = widget.compact ? 0.92 : 0.82;

    return ColoredBox(
      color: widget.compact ? scheme.surfaceContainerLowest : scheme.surface,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          if (widget.showHeader)
            DecoratedBox(
              decoration: BoxDecoration(
                color: scheme.primary.withValues(alpha: 0.08),
                border: Border(
                  bottom: BorderSide(color: scheme.primary.withValues(alpha: 0.3)),
                ),
              ),
              child: Padding(
                padding: EdgeInsets.fromLTRB(hPad, widget.compact ? 10 : 12, 8, 8),
                child: Row(
                  children: [
                    Icon(Icons.auto_awesome, size: 18, color: scheme.primary),
                    const SizedBox(width: 8),
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(
                            SyncItBranding.name,
                            style: theme.titleSmall?.copyWith(
                              fontWeight: FontWeight.w700,
                              color: scheme.primary,
                            ),
                          ),
                          Text(
                            SyncItBranding.tagline,
                            style: theme.labelSmall?.copyWith(color: scheme.onSurfaceVariant),
                          ),
                        ],
                      ),
                    ),
                    if (widget.onClose != null)
                      IconButton(
                        tooltip: 'Close',
                        icon: Icon(Icons.close, size: 20, color: scheme.onSurfaceVariant),
                        onPressed: widget.onClose,
                      ),
                    IconButton(
                      tooltip: 'Clear chat',
                      icon: Icon(Icons.delete_sweep_outlined, size: 20, color: scheme.onSurfaceVariant),
                      onPressed: _clearChat,
                    ),
                  ],
                ),
              ),
            ),
          Expanded(
            child: ListView.builder(
              controller: _scrollCtrl,
              padding: EdgeInsets.fromLTRB(hPad, 10, hPad, 6),
              itemCount: messages.length + (loading ? 1 : 0),
              itemBuilder: (_, i) {
                if (loading && i == messages.length) {
                  return _TypingIndicator(compact: widget.compact);
                }
                return _MessageBubble(
                  message: messages[i],
                  maxWidthFactor: maxBubbleW,
                  compact: widget.compact,
                );
              },
            ),
          ),
          if ((widget.suggestionChips ?? SynctraChatConstants.suggestionChips)
              .isNotEmpty)
            SizedBox(
              height: widget.compact ? 34 : 36,
              child: ListView(
                scrollDirection: Axis.horizontal,
                padding: EdgeInsets.symmetric(horizontal: hPad),
                children: (widget.suggestionChips ??
                        SynctraChatConstants.suggestionChips)
                    .map(
                      (s) => Padding(
                        padding: const EdgeInsets.only(right: 6),
                        child: ActionChip(
                          label: Text(s, style: TextStyle(fontSize: widget.compact ? 11 : 12)),
                          visualDensity: VisualDensity.compact,
                          side: BorderSide(color: scheme.outlineVariant),
                          onPressed: () {
                            _ctrl.text = s;
                            _send();
                          },
                        ),
                      ),
                    )
                    .toList(),
              ),
            ),
          Divider(height: 1, color: scheme.outlineVariant.withValues(alpha: 0.65)),
          Padding(
            padding: EdgeInsets.fromLTRB(
              hPad,
              8,
              hPad - 4,
              widget.compact ? 8 : MediaQuery.of(context).viewInsets.bottom + 12,
            ),
            child: Row(
              children: [
                Expanded(
                  child: TextField(
                    controller: _ctrl,
                    textCapitalization: TextCapitalization.sentences,
                    onSubmitted: (_) => _send(),
                    style: theme.bodyMedium?.copyWith(fontSize: widget.compact ? 13 : 14),
                    decoration: InputDecoration(
                      hintText: 'Ask about your week…',
                      isDense: widget.compact,
                      filled: true,
                      fillColor: scheme.surface,
                      contentPadding: EdgeInsets.symmetric(
                        horizontal: 14,
                        vertical: widget.compact ? 10 : 12,
                      ),
                      border: OutlineInputBorder(
                        borderRadius: BorderRadius.circular(20),
                        borderSide: BorderSide(color: scheme.outlineVariant),
                      ),
                      enabledBorder: OutlineInputBorder(
                        borderRadius: BorderRadius.circular(20),
                        borderSide: BorderSide(color: scheme.outlineVariant),
                      ),
                      focusedBorder: OutlineInputBorder(
                        borderRadius: BorderRadius.circular(20),
                        borderSide: BorderSide(color: scheme.primary, width: 1.5),
                      ),
                    ),
                  ),
                ),
                const SizedBox(width: 6),
                FilledButton(
                  onPressed: loading ? null : _send,
                  style: FilledButton.styleFrom(
                    minimumSize: Size(widget.compact ? 40 : 44, widget.compact ? 40 : 44),
                    padding: EdgeInsets.zero,
                    shape: const CircleBorder(),
                  ),
                  child: Icon(
                    loading ? Icons.hourglass_top_rounded : Icons.arrow_upward_rounded,
                    size: 18,
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class _MessageBubble extends StatelessWidget {
  final ChatMessageModel message;
  final double maxWidthFactor;
  final bool compact;

  const _MessageBubble({
    required this.message,
    required this.maxWidthFactor,
    required this.compact,
  });

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final theme = Theme.of(context).textTheme;
    final isUser = message.role == MessageRole.user;

    return Align(
      alignment: isUser ? Alignment.centerRight : Alignment.centerLeft,
      child: Container(
        constraints: BoxConstraints(
          maxWidth: 280 * maxWidthFactor,
        ),
        margin: EdgeInsets.only(bottom: compact ? 8 : 10),
        padding: EdgeInsets.symmetric(
          horizontal: compact ? 12 : 14,
          vertical: compact ? 8 : 10,
        ),
        decoration: BoxDecoration(
          color: isUser ? scheme.primary : scheme.surface,
          borderRadius: BorderRadius.only(
            topLeft: const Radius.circular(10),
            topRight: const Radius.circular(10),
            bottomLeft: Radius.circular(isUser ? 10 : 4),
            bottomRight: Radius.circular(isUser ? 4 : 10),
          ),
          border: isUser
              ? null
              : Border.all(color: scheme.outlineVariant.withValues(alpha: 0.65)),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              message.content,
              style: theme.bodyMedium?.copyWith(
                fontSize: compact ? 13 : 14,
                color: isUser ? scheme.onPrimary : scheme.onSurface,
                height: 1.4,
              ),
            ),
            const SizedBox(height: 3),
            Text(
              DateFormat('h:mm a').format(message.timestamp),
              style: theme.labelSmall?.copyWith(
                fontSize: 10,
                color: isUser
                    ? scheme.onPrimary.withValues(alpha: 0.7)
                    : scheme.onSurfaceVariant,
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _TypingIndicator extends StatelessWidget {
  final bool compact;
  const _TypingIndicator({required this.compact});

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return Align(
      alignment: Alignment.centerLeft,
      child: Container(
        margin: EdgeInsets.only(bottom: compact ? 8 : 10),
        padding: EdgeInsets.symmetric(horizontal: compact ? 12 : 16, vertical: compact ? 10 : 12),
        decoration: BoxDecoration(
          color: scheme.surface,
          borderRadius: BorderRadius.circular(10),
          border: Border.all(color: scheme.outlineVariant.withValues(alpha: 0.65)),
        ),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            _Dot(color: scheme.onSurfaceVariant),
            const SizedBox(width: 4),
            _Dot(color: scheme.onSurfaceVariant, delay: 200),
            const SizedBox(width: 4),
            _Dot(color: scheme.onSurfaceVariant, delay: 400),
          ],
        ),
      ),
    );
  }
}

class _Dot extends StatefulWidget {
  final Color color;
  final int delay;
  const _Dot({required this.color, this.delay = 0});

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
  void dispose() {
    _ctrl.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return FadeTransition(
      opacity: _ctrl,
      child: Container(
        width: 7,
        height: 7,
        decoration: BoxDecoration(color: widget.color, shape: BoxShape.circle),
      ),
    );
  }
}

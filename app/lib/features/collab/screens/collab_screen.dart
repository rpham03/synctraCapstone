// Collab screen — invite others, find shared free time, and manage group events.
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:go_router/go_router.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../../../core/theme/app_theme.dart';
import '../../../shared/widgets/synctra_empty_state.dart';
import '../../../shared/widgets/synctra_page_header.dart';

class _GroupSession {
  final String id;
  final String title;
  final DateTime start;
  final DateTime end;

  _GroupSession({
    required this.id,
    required this.title,
    required this.start,
    required this.end,
  });
}

class CollabScreen extends StatefulWidget {
  const CollabScreen({super.key});

  @override
  State<CollabScreen> createState() => _CollabScreenState();
}

class _CollabScreenState extends State<CollabScreen> {
  final List<_GroupSession> _sessions = [];
  static const _sessionsKey = 'synctra_collab_sessions_v1';
  static const _inviteLink = 'https://synctra.app/collab/join';

  @override
  void initState() {
    super.initState();
    _loadSessions();
  }

  Future<void> _loadSessions() async {
    final prefs = await SharedPreferences.getInstance();
    final raw = prefs.getString(_sessionsKey);
    if (raw == null || raw.isEmpty) return;
    try {
      final list = jsonDecode(raw) as List<dynamic>;
      final loaded = list.whereType<Map>().map((m) {
        return _GroupSession(
          id: m['id'] as String,
          title: m['title'] as String,
          start: DateTime.parse(m['start'] as String),
          end: DateTime.parse(m['end'] as String),
        );
      }).toList();
      if (!mounted) return;
      setState(() => _sessions.addAll(loaded));
    } catch (_) {}
  }

  Future<void> _persistSessions() async {
    final prefs = await SharedPreferences.getInstance();
    final payload = _sessions
        .map((s) => {
              'id': s.id,
              'title': s.title,
              'start': s.start.toIso8601String(),
              'end': s.end.toIso8601String(),
            })
        .toList();
    await prefs.setString(_sessionsKey, jsonEncode(payload));
  }

  void _invite() {
    Clipboard.setData(const ClipboardData(text: _inviteLink));
    ScaffoldMessenger.of(context).showSnackBar(
      const SnackBar(content: Text('Invite link copied to clipboard.')),
    );
  }

  void _findMeetingTime() {
    showModalBottomSheet<void>(
      context: context,
      showDragHandle: true,
      builder: (ctx) {
        return Padding(
          padding: const EdgeInsets.fromLTRB(24, 8, 24, 32),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Text('Suggested windows', style: Theme.of(ctx).textTheme.titleMedium),
              const SizedBox(height: 12),
              const Text(
                'Based on typical class hours, try proposing:\n'
                '• Tuesday 3:00–5:00 PM\n'
                '• Thursday 11:00 AM–1:00 PM\n'
                '• Saturday 10:00 AM–12:00 PM',
                style: TextStyle(height: 1.4),
              ),
              const SizedBox(height: 16),
              FilledButton(
                onPressed: () {
                  Navigator.pop(ctx);
                  if (mounted) context.go('/chat');
                },
                child: const Text('Ask AI to refine with your calendar'),
              ),
            ],
          ),
        );
      },
    );
  }

  void _mergeCalendars() {
    showDialog<void>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Merge calendars'),
        content: const Text(
          'Combine feeds in Synctra by linking each calendar’s iCal URL from the Calendar tab. '
          'All merged events appear in one view automatically.',
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx), child: const Text('Close')),
          FilledButton(
            onPressed: () {
              Navigator.pop(ctx);
              if (mounted) context.go('/calendar');
            },
            child: const Text('Open Calendar'),
          ),
        ],
      ),
    );
  }

  Future<void> _newGroupEvent() async {
    final result = await showDialog<_NewGroupEventResult>(
      context: context,
      builder: (ctx) => const _NewGroupEventDialog(),
    );

    if (result == null || !mounted) return;

    setState(() {
      _sessions.add(
        _GroupSession(
          id: DateTime.now().millisecondsSinceEpoch.toString(),
          title: result.title,
          start: result.start,
          end: result.end,
        ),
      );
    });
    await _persistSessions();
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      const SnackBar(content: Text('Group event added.')),
    );
  }

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return Scaffold(
      backgroundColor: scheme.surface,
      appBar: SynctraPageHeader(
        title: 'Collab',
        subtitle: 'Find time with your group',
        actions: [
          IconButton(
            icon: Icon(Icons.person_add_outlined, color: scheme.onSurfaceVariant, size: 22),
            tooltip: 'Invite',
            onPressed: _invite,
          ),
        ],
      ),
      body: ListView(
        padding: const EdgeInsets.fromLTRB(16, 8, 16, 88),
        children: [
          _FeatureCard(
            icon: Icons.group_outlined,
            color: AppColors.collabEvent,
            title: 'Find Meeting Time',
            subtitle: 'Let the AI compare calendars and suggest when everyone is free.',
            buttonLabel: 'Find Time',
            onTap: _findMeetingTime,
          ),
          const SizedBox(height: 12),
          _FeatureCard(
            icon: Icons.merge_type,
            color: AppColors.primary,
            title: 'Merge Calendars',
            subtitle: 'Combine two or more calendars into a single collaborative view.',
            buttonLabel: 'Merge',
            onTap: _mergeCalendars,
          ),
          const SizedBox(height: 24),
          Text(
            'Group Sessions',
            style: Theme.of(context)
                .textTheme
                .titleMedium
                ?.copyWith(fontWeight: FontWeight.bold),
          ),
          const SizedBox(height: 12),
          if (_sessions.isEmpty)
            const _EmptyCollab()
          else
            ..._sessions.map(
              (s) => Card(
                margin: const EdgeInsets.only(bottom: 8),
                child: ListTile(
                  leading: CircleAvatar(
                    backgroundColor: AppColors.collabEvent.withAlpha(36),
                    child: Icon(Icons.groups, color: AppColors.collabEvent),
                  ),
                  title: Text(s.title),
                  subtitle: Text(
                    '${MaterialLocalizations.of(context).formatShortDate(s.start)} · '
                    '${TimeOfDay.fromDateTime(s.start).format(context)} – '
                    '${TimeOfDay.fromDateTime(s.end).format(context)}',
                  ),
                ),
              ),
            ),
        ],
      ),
      floatingActionButton: FloatingActionButton.extended(
        onPressed: _newGroupEvent,
        icon: const Icon(Icons.add),
        label: const Text('New group event'),
      ),
    );
  }
}

// ── Sub-widgets ────────────────────────────────────────────────────────────────

class _FeatureCard extends StatelessWidget {
  final IconData icon;
  final Color color;
  final String title;
  final String subtitle;
  final String buttonLabel;
  final VoidCallback onTap;

  const _FeatureCard({
    required this.icon,
    required this.color,
    required this.title,
    required this.subtitle,
    required this.buttonLabel,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                CircleAvatar(
                  radius: 24,
                  backgroundColor: color.withAlpha(30),
                  child: Icon(icon, color: color),
                ),
                const SizedBox(width: 16),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(title,
                          style: const TextStyle(fontWeight: FontWeight.bold)),
                      const SizedBox(height: 4),
                      Text(
                        subtitle,
                        style: Theme.of(context).textTheme.bodySmall?.copyWith(
                              color: Theme.of(context)
                                  .colorScheme
                                  .onSurfaceVariant,
                            ),
                      ),
                    ],
                  ),
                ),
              ],
            ),
            const SizedBox(height: 12),
            Align(
              alignment: Alignment.centerRight,
              child: FilledButton(
                onPressed: onTap,
                style: FilledButton.styleFrom(
                  backgroundColor: color,
                  visualDensity: VisualDensity.compact,
                  tapTargetSize: MaterialTapTargetSize.shrinkWrap,
                ),
                child: Text(buttonLabel, style: const TextStyle(fontSize: 12)),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _EmptyCollab extends StatelessWidget {
  const _EmptyCollab();

  @override
  Widget build(BuildContext context) {
    return const SynctraEmptyState(
      icon: Icons.people_outline,
      title: 'No group sessions yet',
      message: 'Invite teammates and add a group event to get started.',
    );
  }
}

class _NewGroupEventResult {
  final String title;
  final DateTime start;
  final DateTime end;

  const _NewGroupEventResult({
    required this.title,
    required this.start,
    required this.end,
  });
}

/// Owns [TextEditingController]s so they are not disposed before the route closes.
class _NewGroupEventDialog extends StatefulWidget {
  const _NewGroupEventDialog();

  @override
  State<_NewGroupEventDialog> createState() => _NewGroupEventDialogState();
}

class _NewGroupEventDialogState extends State<_NewGroupEventDialog> {
  late final TextEditingController _titleCtrl;
  late DateTime _day;
  var _startT = const TimeOfDay(hour: 15, minute: 0);
  var _endT = const TimeOfDay(hour: 16, minute: 0);

  @override
  void initState() {
    super.initState();
    _titleCtrl = TextEditingController();
    _day = DateTime.now().add(const Duration(days: 1));
  }

  @override
  void dispose() {
    _titleCtrl.dispose();
    super.dispose();
  }

  void _submit() {
    final title = _titleCtrl.text.trim();
    if (title.isEmpty) return;

    final start = DateTime(
      _day.year,
      _day.month,
      _day.day,
      _startT.hour,
      _startT.minute,
    );
    var end = DateTime(
      _day.year,
      _day.month,
      _day.day,
      _endT.hour,
      _endT.minute,
    );
    if (!end.isAfter(start)) {
      end = start.add(const Duration(hours: 1));
    }

    Navigator.pop(
      context,
      _NewGroupEventResult(title: title, start: start, end: end),
    );
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: const Text('New group event'),
      content: SingleChildScrollView(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            TextField(
              controller: _titleCtrl,
              decoration: const InputDecoration(
                labelText: 'Title',
                border: OutlineInputBorder(),
              ),
              textCapitalization: TextCapitalization.sentences,
              autofocus: true,
            ),
            ListTile(
              contentPadding: EdgeInsets.zero,
              title: Text(MaterialLocalizations.of(context).formatMediumDate(_day)),
              trailing: const Icon(Icons.calendar_today),
              onTap: () async {
                final picked = await showDatePicker(
                  context: context,
                  initialDate: _day,
                  firstDate: DateTime.now(),
                  lastDate: DateTime.now().add(const Duration(days: 365)),
                );
                if (picked != null && mounted) {
                  setState(() => _day = picked);
                }
              },
            ),
            ListTile(
              contentPadding: EdgeInsets.zero,
              title: Text('${_startT.format(context)} – ${_endT.format(context)}'),
              trailing: const Icon(Icons.schedule),
              onTap: () async {
                final start = await showTimePicker(
                  context: context,
                  initialTime: _startT,
                );
                if (start == null || !mounted) return;
                final end = await showTimePicker(
                  context: context,
                  initialTime: _endT,
                );
                if (end == null || !mounted) return;
                setState(() {
                  _startT = start;
                  _endT = end;
                });
              },
            ),
          ],
        ),
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.pop(context),
          child: const Text('Cancel'),
        ),
        FilledButton(onPressed: _submit, child: const Text('Create')),
      ],
    );
  }
}

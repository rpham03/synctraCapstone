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
    final titleCtrl = TextEditingController();
    DateTime day = DateTime.now().add(const Duration(days: 1));
    var startT = const TimeOfDay(hour: 15, minute: 0);
    var endT = const TimeOfDay(hour: 16, minute: 0);

    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => StatefulBuilder(
        builder: (ctx, setModal) {
          return AlertDialog(
            title: const Text('New group event'),
            content: SingleChildScrollView(
              child: Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  TextField(
                    controller: titleCtrl,
                    decoration: const InputDecoration(
                      labelText: 'Title',
                      border: OutlineInputBorder(),
                    ),
                  ),
                  ListTile(
                    title: Text(MaterialLocalizations.of(ctx).formatMediumDate(day)),
                    trailing: const Icon(Icons.calendar_today),
                    onTap: () async {
                      final d = await showDatePicker(
                        context: ctx,
                        initialDate: day,
                        firstDate: DateTime.now(),
                        lastDate: DateTime.now().add(const Duration(days: 365)),
                      );
                      if (d != null) setModal(() => day = d);
                    },
                  ),
                  ListTile(
                    title: Text('${startT.format(ctx)} – ${endT.format(ctx)}'),
                    trailing: const Icon(Icons.schedule),
                    onTap: () async {
                      final s = await showTimePicker(context: ctx, initialTime: startT);
                      if (s == null || !ctx.mounted) return;
                      final e = await showTimePicker(context: ctx, initialTime: endT);
                      if (e == null || !ctx.mounted) return;
                      setModal(() {
                        startT = s;
                        endT = e;
                      });
                    },
                  ),
                ],
              ),
            ),
            actions: [
              TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Cancel')),
              FilledButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('Create')),
            ],
          );
        },
      ),
    );

    if (ok != true || !mounted) {
      titleCtrl.dispose();
      return;
    }
    final title = titleCtrl.text.trim();
    titleCtrl.dispose();
    if (title.isEmpty) return;

    final start = DateTime(day.year, day.month, day.day, startT.hour, startT.minute);
    var end = DateTime(day.year, day.month, day.day, endT.hour, endT.minute);
    if (!end.isAfter(start)) {
      end = start.add(const Duration(hours: 1));
    }

    setState(() {
      _sessions.add(
        _GroupSession(
          id: DateTime.now().millisecondsSinceEpoch.toString(),
          title: title,
          start: start,
          end: end,
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
        child: Row(
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
                          color: Theme.of(context).colorScheme.onSurfaceVariant,
                        ),
                  ),
                ],
              ),
            ),
            const SizedBox(width: 8),
            FilledButton(
              onPressed: onTap,
              style: FilledButton.styleFrom(backgroundColor: color),
              child: Text(buttonLabel, style: const TextStyle(fontSize: 12)),
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

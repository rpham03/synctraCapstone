// Collab screen — invite others, find shared free time, and manage group events.
import 'package:flutter/material.dart';

import '../../../core/theme/app_theme.dart';

class CollabScreen extends StatelessWidget {
  const CollabScreen({super.key});

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Collab'),
        actions: [
          IconButton(
            icon: const Icon(Icons.person_add_outlined),
            tooltip: 'Invite',
            onPressed: () {/* TODO: invite flow */},
          ),
        ],
      ),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          // ── "When 2 Meet" card ─────────────────────────────────────
          _FeatureCard(
            icon: Icons.group_outlined,
            color: AppColors.collabEvent,
            title: 'Find Meeting Time',
            subtitle: 'Let the AI compare calendars and suggest when everyone is free.',
            buttonLabel: 'Find Time',
            onTap: () {/* TODO: "When 2 Meet" flow */},
          ),
          const SizedBox(height: 12),

          // ── Merge calendars card ───────────────────────────────────
          _FeatureCard(
            icon: Icons.merge_type,
            color: AppColors.primary,
            title: 'Merge Calendars',
            subtitle: 'Combine two or more calendars into a single collaborative view.',
            buttonLabel: 'Merge',
            onTap: () {/* TODO: merge calendar flow */},
          ),
          const SizedBox(height: 24),

          // ── Group sessions list placeholder ────────────────────────
          Text('Group Sessions',
              style: Theme.of(context)
                  .textTheme
                  .titleMedium
                  ?.copyWith(fontWeight: FontWeight.bold)),
          const SizedBox(height: 12),
          const _EmptyCollab(),
        ],
      ),

      floatingActionButton: FloatingActionButton.extended(
        onPressed: () {/* TODO: create group event */},
        icon: const Icon(Icons.add),
        label: const Text('New Group Event'),
        backgroundColor: AppColors.collabEvent,
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
                  Text(subtitle,
                      style: TextStyle(color: Colors.grey[600], fontSize: 12)),
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
    return Center(
      child: Padding(
        padding: const EdgeInsets.symmetric(vertical: 32),
        child: Column(
          children: [
            Icon(Icons.people_outline, size: 56, color: Colors.grey[300]),
            const SizedBox(height: 12),
            Text('No group sessions yet',
                style: TextStyle(color: Colors.grey[500])),
            const SizedBox(height: 4),
            Text('Invite teammates to find a time that works for everyone.',
                style: TextStyle(color: Colors.grey[400], fontSize: 12),
                textAlign: TextAlign.center),
          ],
        ),
      ),
    );
  }
}

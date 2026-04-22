// Daily/weekly schedule view — shows AI-generated study and work blocks.
// Note: This screen is accessed via the "Suggest Schedule" FAB on CalendarScreen,
// not from the bottom nav bar. It shows multiple AI-generated schedule versions
// so the user can pick the best fit.
import 'package:flutter/material.dart';

import '../../../core/theme/app_theme.dart';
import '../../../data/models/schedule_block_model.dart';

class ScheduleScreen extends StatefulWidget {
  const ScheduleScreen({super.key});

  @override
  State<ScheduleScreen> createState() => _ScheduleScreenState();
}

class _ScheduleScreenState extends State<ScheduleScreen>
    with SingleTickerProviderStateMixin {
  late final TabController _tabCtrl;

  // TODO: replace with real AI-generated versions from backend
  final List<_ScheduleVersion> _versions = [
    _ScheduleVersion(label: 'Version 1 — Balanced', blocks: []),
    _ScheduleVersion(label: 'Version 2 — Front-loaded', blocks: []),
    _ScheduleVersion(label: 'Version 3 — Light start', blocks: []),
  ];

  @override
  void initState() {
    super.initState();
    _tabCtrl = TabController(length: _versions.length, vsync: this);
  }

  @override
  void dispose() {
    _tabCtrl.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Schedule Suggestions'),
        bottom: TabBar(
          controller: _tabCtrl,
          isScrollable: true,
          indicatorColor: AppColors.primary,
          labelColor: AppColors.primary,
          tabs: _versions
              .map((v) => Tab(text: v.label))
              .toList(),
        ),
      ),
      body: TabBarView(
        controller: _tabCtrl,
        children: _versions
            .map((v) => _ScheduleVersionView(version: v))
            .toList(),
      ),
      bottomNavigationBar: Padding(
        padding: const EdgeInsets.all(16),
        child: FilledButton.icon(
          onPressed: () {
            final picked = _tabCtrl.index;
            // TODO: apply chosen version to main calendar
            Navigator.of(context).pop();
            ScaffoldMessenger.of(context).showSnackBar(
              SnackBar(
                  content:
                      Text('Applied: ${_versions[picked].label}')),
            );
          },
          icon: const Icon(Icons.check),
          label: const Text('Use This Schedule'),
        ),
      ),
    );
  }
}

class _ScheduleVersion {
  final String label;
  final List<ScheduleBlockModel> blocks;
  const _ScheduleVersion({required this.label, required this.blocks});
}

class _ScheduleVersionView extends StatelessWidget {
  final _ScheduleVersion version;
  const _ScheduleVersionView({required this.version});

  @override
  Widget build(BuildContext context) {
    if (version.blocks.isEmpty) {
      return Center(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(Icons.auto_awesome, size: 48, color: Colors.grey[300]),
            const SizedBox(height: 12),
            Text('AI schedule generation coming soon',
                style: TextStyle(color: Colors.grey[500])),
          ],
        ),
      );
    }

    return ListView.builder(
      padding: const EdgeInsets.all(16),
      itemCount: version.blocks.length,
      itemBuilder: (_, i) => Card(
        margin: const EdgeInsets.only(bottom: 8),
        child: ListTile(
          leading: Container(
            width: 4,
            height: 40,
            decoration: BoxDecoration(
              color: AppColors.flexibleBlock,
              borderRadius: BorderRadius.circular(2),
            ),
          ),
          title: Text(version.blocks[i].taskTitle),
          subtitle: Text(
            '${version.blocks[i].startTime.hour}:00 – '
            '${version.blocks[i].endTime.hour}:00',
          ),
        ),
      ),
    );
  }
}

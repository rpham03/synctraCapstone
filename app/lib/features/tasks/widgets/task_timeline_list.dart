// Scrollable task list: today and future by default; scroll up to load older work.
import 'package:flutter/material.dart';

import '../../../data/models/task_model.dart';
import '../../../shared/utils/task_timeline_utils.dart';
import 'task_list_tile.dart';

class TaskTimelineList extends StatefulWidget {
  final List<TaskModel> tasks;
  final bool loadingOlder;
  final bool hasOlderOutsideWindow;
  final VoidCallback onLoadOlder;
  final Future<void> Function(TaskModel task, bool done) onToggleDone;
  final Future<void> Function(TaskModel task) onDeleteTask;

  const TaskTimelineList({
    super.key,
    required this.tasks,
    required this.loadingOlder,
    required this.hasOlderOutsideWindow,
    required this.onLoadOlder,
    required this.onToggleDone,
    required this.onDeleteTask,
  });

  @override
  State<TaskTimelineList> createState() => _TaskTimelineListState();
}

class _TaskTimelineListState extends State<TaskTimelineList> {
  final _scrollCtrl = ScrollController();
  final _todayKey = GlobalKey();
  var _didInitialScroll = false;
  double? _scrollAnchorPixels;
  double? _scrollAnchorMaxExtent;

  @override
  void initState() {
    super.initState();
    _scrollCtrl.addListener(_onScroll);
  }

  @override
  void dispose() {
    _scrollCtrl.removeListener(_onScroll);
    _scrollCtrl.dispose();
    super.dispose();
  }

  @override
  void didUpdateWidget(TaskTimelineList oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (widget.tasks.length > oldWidget.tasks.length &&
        _scrollAnchorMaxExtent != null) {
      WidgetsBinding.instance.addPostFrameCallback((_) => _restoreScrollAnchor());
    } else if (oldWidget.tasks.length != widget.tasks.length) {
      _didInitialScroll = false;
      WidgetsBinding.instance.addPostFrameCallback((_) => _scrollToToday());
    }
  }

  void _onScroll() {
    if (!_scrollCtrl.hasClients) return;
    if (_scrollCtrl.position.pixels <= 72 &&
        widget.hasOlderOutsideWindow &&
        !widget.loadingOlder) {
      _scrollAnchorPixels = _scrollCtrl.position.pixels;
      _scrollAnchorMaxExtent = _scrollCtrl.position.maxScrollExtent;
      widget.onLoadOlder();
    }
  }

  void _restoreScrollAnchor() {
    if (!_scrollCtrl.hasClients ||
        _scrollAnchorPixels == null ||
        _scrollAnchorMaxExtent == null) {
      return;
    }
    final delta = _scrollCtrl.position.maxScrollExtent - _scrollAnchorMaxExtent!;
    _scrollCtrl.jumpTo(_scrollAnchorPixels! + delta);
    _scrollAnchorPixels = null;
    _scrollAnchorMaxExtent = null;
  }

  void _scrollToToday() {
    if (_didInitialScroll) return;
    final ctx = _todayKey.currentContext;
    if (ctx == null) return;
    _didInitialScroll = true;
    Scrollable.ensureVisible(
      ctx,
      duration: const Duration(milliseconds: 280),
      curve: Curves.easeOut,
      alignment: 0.08,
    );
  }

  @override
  Widget build(BuildContext context) {
    final sections = buildTaskTimelineSections(widget.tasks);

    if (sections.isEmpty) {
      return const SizedBox.shrink();
    }

    WidgetsBinding.instance.addPostFrameCallback((_) => _scrollToToday());

    final scheme = Theme.of(context).colorScheme;
    final theme = Theme.of(context).textTheme;

    return ListView(
      controller: _scrollCtrl,
      padding: const EdgeInsets.fromLTRB(16, 8, 16, 24),
      children: [
        if (widget.loadingOlder)
          const Padding(
            padding: EdgeInsets.symmetric(vertical: 12),
            child: Center(child: CircularProgressIndicator(strokeWidth: 2)),
          )
        else if (widget.hasOlderOutsideWindow)
          Padding(
            padding: const EdgeInsets.only(bottom: 8),
            child: Text(
              'Scroll up for older assignments',
              textAlign: TextAlign.center,
              style: theme.bodySmall?.copyWith(color: scheme.onSurfaceVariant),
            ),
          ),
        for (final section in sections) ...[
          _SectionHeader(
            key: section.kind == TaskTimelineSectionKind.today ? _todayKey : null,
            label: section.label,
            count: section.tasks.length,
          ),
          for (final task in section.tasks)
            TaskListTile(
              task: task,
              onToggle: (done) => widget.onToggleDone(task, done),
              onDelete: () => widget.onDeleteTask(task),
            ),
        ],
      ],
    );
  }
}

class _SectionHeader extends StatelessWidget {
  final String label;
  final int count;

  const _SectionHeader({
    super.key,
    required this.label,
    required this.count,
  });

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context).textTheme;
    final scheme = Theme.of(context).colorScheme;
    final isToday = label == 'Today';

    return Padding(
      padding: const EdgeInsets.fromLTRB(0, 14, 0, 8),
      child: Row(
        children: [
          if (isToday)
            Container(
              width: 4,
              height: 18,
              margin: const EdgeInsets.only(right: 8),
              decoration: BoxDecoration(
                color: scheme.primary,
                borderRadius: BorderRadius.circular(2),
              ),
            ),
          Text(
            label,
            style: theme.titleSmall?.copyWith(
              fontWeight: FontWeight.w700,
              color: isToday ? scheme.primary : scheme.onSurface,
            ),
          ),
          const SizedBox(width: 8),
          Text(
            '$count',
            style: theme.labelMedium?.copyWith(color: scheme.onSurfaceVariant),
          ),
        ],
      ),
    );
  }
}

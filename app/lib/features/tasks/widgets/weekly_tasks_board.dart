// Mon–Sun board: flat columns, whitespace, long-press drag between days, inline add.
import 'package:flutter/material.dart';
import 'package:intl/intl.dart';

import '../../../core/theme/app_theme.dart';
import '../../../core/utils/responsive.dart';
import '../../../data/models/task_model.dart';

DateTime _dateOnly(DateTime d) => DateTime(d.year, d.month, d.day);

DateTime weekMondayOf(DateTime anchor) {
  final d = _dateOnly(anchor);
  return d.subtract(Duration(days: d.weekday - DateTime.monday));
}

bool taskDueInWeek(TaskModel t, DateTime weekMonday) {
  final end = weekMonday.add(const Duration(days: 7));
  final dd = _dateOnly(t.dueDate);
  return !dd.isBefore(weekMonday) && dd.isBefore(end);
}

int _dayIndexForDueDate(DateTime due, DateTime weekMonday) {
  return _dateOnly(due).difference(weekMonday).inDays.clamp(0, 6);
}

Color _priorityDotColor(TaskModel t, ThemeData theme) {
  if (t.isCompleted) return theme.colorScheme.outlineVariant;
  final days = _dateOnly(t.dueDate).difference(_dateOnly(DateTime.now())).inDays;
  if (days < 0) return AppColors.deadline;
  if (days <= 1) return const Color(0xFFE11D48);
  if (days <= 3) return const Color(0xFFF59E0B);
  return theme.colorScheme.outlineVariant;
}

class WeeklyTasksBoard extends StatefulWidget {
  final DateTime weekMonday;
  final List<TaskModel> tasks;
  final void Function(TaskModel task, DateTime newDue) onTaskDueChanged;
  final void Function(String title, DateTime dueEndOfDay) onQuickAdd;
  final void Function(TaskModel task, bool done) onToggleDone;
  final void Function(TaskModel task) onDeleteTask;

  const WeeklyTasksBoard({
    super.key,
    required this.weekMonday,
    required this.tasks,
    required this.onTaskDueChanged,
    required this.onQuickAdd,
    required this.onToggleDone,
    required this.onDeleteTask,
  });

  @override
  State<WeeklyTasksBoard> createState() => _WeeklyTasksBoardState();
}

class _WeeklyTasksBoardState extends State<WeeklyTasksBoard> {
  int? _addOpenDay;
  final _quickTitle = TextEditingController();

  @override
  void dispose() {
    _quickTitle.dispose();
    super.dispose();
  }

  void _openAdd(int day) {
    setState(() {
      _addOpenDay = day;
      _quickTitle.clear();
    });
  }

  void _closeAdd() {
    setState(() {
      _addOpenDay = null;
      _quickTitle.clear();
    });
  }

  void _submitAdd(int dayIndex) {
    final title = _quickTitle.text.trim();
    if (title.isEmpty) return;
    final day = widget.weekMonday.add(Duration(days: dayIndex));
    final due = DateTime(day.year, day.month, day.day, 23, 59);
    widget.onQuickAdd(title, due);
    _closeAdd();
  }

  List<TaskModel> _tasksForDay(int dayIndex) {
    return widget.tasks
        .where((t) => taskDueInWeek(t, widget.weekMonday) && _dayIndexForDueDate(t.dueDate, widget.weekMonday) == dayIndex)
        .toList()
      ..sort((a, b) => a.dueDate.compareTo(b.dueDate));
  }

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    final today = _dateOnly(DateTime.now());
    final mobile = Responsive.isMobile(context);

    return LayoutBuilder(
      builder: (context, constraints) {
        final maxH = constraints.maxHeight.isFinite ? constraints.maxHeight : 440.0;
        final rowHeight = maxH.clamp(320.0, 720.0);

        Widget gutter() => SizedBox(
              width: mobile ? 10 : 12,
              child: Center(
                child: Container(
                  width: 1,
                  color: cs.outlineVariant.withValues(alpha: 0.35),
                ),
              ),
            );

        Widget dayColumn(int dayIndex) {
          final day = _dateOnly(widget.weekMonday.add(Duration(days: dayIndex)));
          final isToday = day == today;
          return _DayColumn(
            day: day,
            isToday: isToday,
            dayIndex: dayIndex,
            compact: mobile,
            tasks: _tasksForDay(dayIndex),
            addOpen: _addOpenDay == dayIndex,
            quickTitle: _quickTitle,
            onOpenAdd: () => _openAdd(dayIndex),
            onCloseAdd: _closeAdd,
            onSubmitAdd: () => _submitAdd(dayIndex),
            onTaskDueChanged: widget.onTaskDueChanged,
            onToggleDone: widget.onToggleDone,
            onDeleteTask: widget.onDeleteTask,
            weekMonday: widget.weekMonday,
          );
        }

        final colW = mobile ? (constraints.maxWidth * 0.72).clamp(132.0, 168.0) : null;
        final rowChildren = <Widget>[];
        for (var i = 0; i < 7; i++) {
          if (i > 0) rowChildren.add(gutter());
          final inner = dayColumn(i);
          rowChildren.add(
            colW != null ? SizedBox(width: colW, child: inner) : Expanded(child: inner),
          );
        }

        final row = SizedBox(
          height: rowHeight,
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: rowChildren,
          ),
        );

        if (!mobile) return row;

        final minScrollW = constraints.maxWidth;
        final contentW = 7 * colW! + 6 * 10.0;
        return SingleChildScrollView(
          scrollDirection: Axis.horizontal,
          physics: const BouncingScrollPhysics(),
          child: ConstrainedBox(
            constraints: BoxConstraints(minWidth: minScrollW > contentW ? minScrollW : contentW),
            child: row,
          ),
        );
      },
    );
  }
}

/// Column top: weekday name + full calendar date.
class _DayColumnHeader extends StatelessWidget {
  final DateTime day;
  final bool isToday;
  final bool compact;
  final VoidCallback onAdd;

  const _DayColumnHeader({
    required this.day,
    required this.isToday,
    required this.compact,
    required this.onAdd,
  });

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final cs = theme.colorScheme;
    final weekday = compact ? DateFormat('EEE').format(day) : DateFormat('EEEE').format(day);
    final dateLine = DateFormat(compact ? 'MMM d' : 'MMM d, yyyy').format(day);

    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    weekday,
                    style: theme.textTheme.titleSmall?.copyWith(
                      fontWeight: FontWeight.w600,
                      color: isToday ? cs.primary : cs.onSurface,
                      letterSpacing: -0.15,
                    ),
                  ),
                  const SizedBox(height: 2),
                  Text(
                    dateLine,
                    style: theme.textTheme.bodyMedium?.copyWith(
                      fontWeight: FontWeight.w500,
                      color: cs.onSurface,
                    ),
                  ),
                  if (isToday) ...[
                    const SizedBox(height: 4),
                    Container(
                      padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
                      decoration: BoxDecoration(
                        color: cs.primary.withValues(alpha: 0.12),
                        borderRadius: BorderRadius.circular(4),
                      ),
                      child: Text(
                        'Today',
                        style: theme.textTheme.labelSmall?.copyWith(
                          color: cs.primary,
                          fontWeight: FontWeight.w600,
                          fontSize: 10,
                        ),
                      ),
                    ),
                  ],
                ],
              ),
            ),
            TextButton(
              onPressed: onAdd,
              style: TextButton.styleFrom(
                padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
                minimumSize: Size.zero,
                tapTargetSize: MaterialTapTargetSize.shrinkWrap,
              ),
              child: Text(
                '+',
                style: theme.textTheme.titleMedium?.copyWith(
                  color: cs.onSurfaceVariant,
                  fontWeight: FontWeight.w400,
                ),
              ),
            ),
          ],
        ),
        const SizedBox(height: 10),
        Divider(height: 1, color: cs.outlineVariant.withValues(alpha: 0.6)),
        const SizedBox(height: 8),
      ],
    );
  }
}

class _DayColumn extends StatelessWidget {
  final DateTime day;
  final bool isToday;
  final bool compact;
  final int dayIndex;
  final List<TaskModel> tasks;
  final bool addOpen;
  final TextEditingController quickTitle;
  final VoidCallback onOpenAdd;
  final VoidCallback onCloseAdd;
  final VoidCallback onSubmitAdd;
  final void Function(TaskModel task, DateTime newDue) onTaskDueChanged;
  final void Function(TaskModel task, bool done) onToggleDone;
  final void Function(TaskModel task) onDeleteTask;
  final DateTime weekMonday;

  const _DayColumn({
    required this.day,
    required this.isToday,
    required this.compact,
    required this.dayIndex,
    required this.tasks,
    required this.addOpen,
    required this.quickTitle,
    required this.onOpenAdd,
    required this.onCloseAdd,
    required this.onSubmitAdd,
    required this.onTaskDueChanged,
    required this.onToggleDone,
    required this.onDeleteTask,
    required this.weekMonday,
  });

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final cs = theme.colorScheme;

    final bg = isToday ? cs.primary.withValues(alpha: 0.06) : cs.surface;

    return DragTarget<TaskModel>(
      onWillAcceptWithDetails: (_) => true,
      onAcceptWithDetails: (details) {
        final t = details.data;
        final newDue = DateTime(
          day.year,
          day.month,
          day.day,
          t.dueDate.hour,
          t.dueDate.minute,
        );
        onTaskDueChanged(t, newDue);
      },
      builder: (context, candidate, rejected) {
        final over = candidate.isNotEmpty;
        return AnimatedContainer(
          duration: const Duration(milliseconds: 120),
          decoration: BoxDecoration(
            color: bg,
            borderRadius: BorderRadius.circular(12),
            border: Border.all(
              color: over
                  ? cs.primary.withValues(alpha: 0.35)
                  : (isToday ? cs.primary.withValues(alpha: 0.22) : cs.outlineVariant.withValues(alpha: 0.65)),
              width: over ? 1.5 : 1,
            ),
          ),
          child: Material(
            color: Colors.transparent,
            child: Padding(
              padding: const EdgeInsets.fromLTRB(8, 10, 8, 12),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  _DayColumnHeader(
                    day: day,
                    isToday: isToday,
                    compact: compact,
                    onAdd: onOpenAdd,
                  ),
                  if (addOpen) ...[
                    const SizedBox(height: 8),
                    TextField(
                      controller: quickTitle,
                      style: theme.textTheme.bodyMedium,
                      decoration: InputDecoration(
                        hintText: 'Task title',
                        isDense: true,
                        filled: true,
                        contentPadding: const EdgeInsets.symmetric(horizontal: 10, vertical: 10),
                        border: OutlineInputBorder(
                          borderRadius: BorderRadius.circular(8),
                          borderSide: BorderSide(color: cs.outlineVariant),
                        ),
                        enabledBorder: OutlineInputBorder(
                          borderRadius: BorderRadius.circular(8),
                          borderSide: BorderSide(color: cs.outlineVariant),
                        ),
                        focusedBorder: OutlineInputBorder(
                          borderRadius: BorderRadius.circular(8),
                          borderSide: BorderSide(color: cs.primary, width: 1.5),
                        ),
                      ),
                      textCapitalization: TextCapitalization.sentences,
                      onSubmitted: (_) => onSubmitAdd(),
                    ),
                    const SizedBox(height: 8),
                    Row(
                      mainAxisAlignment: MainAxisAlignment.end,
                      children: [
                        TextButton(onPressed: onCloseAdd, child: const Text('Cancel')),
                        const SizedBox(width: 4),
                        FilledButton(
                          onPressed: onSubmitAdd,
                          style: FilledButton.styleFrom(
                            visualDensity: VisualDensity.compact,
                            padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 8),
                          ),
                          child: const Text('Add'),
                        ),
                      ],
                    ),
                  ],
                  const SizedBox(height: 8),
                  Expanded(
                    child: tasks.isEmpty && !addOpen
                        ? Center(
                            child: Text(
                              '—',
                              style: theme.textTheme.bodySmall?.copyWith(color: cs.outline),
                            ),
                          )
                        : ListView(
                            shrinkWrap: true,
                            physics: const ClampingScrollPhysics(),
                            children: [
                              for (final t in tasks)
                                Padding(
                                  padding: const EdgeInsets.only(bottom: 6),
                                  child: _BoardTaskCard(
                                    task: t,
                                    dotColor: _priorityDotColor(t, theme),
                                    onToggleDone: onToggleDone,
                                    onDelete: () => onDeleteTask(t),
                                  ),
                                ),
                            ],
                          ),
                  ),
                ],
              ),
            ),
          ),
        );
      },
    );
  }
}

class _BoardTaskCard extends StatelessWidget {
  final TaskModel task;
  final Color dotColor;
  final void Function(TaskModel task, bool done) onToggleDone;
  final VoidCallback onDelete;

  const _BoardTaskCard({
    required this.task,
    required this.dotColor,
    required this.onToggleDone,
    required this.onDelete,
  });

  Widget _shell(BuildContext context, {required bool interactive}) {
    final theme = Theme.of(context);
    final cs = theme.colorScheme;
    final done = task.isCompleted;

    final inner = Padding(
      padding: const EdgeInsets.fromLTRB(10, 10, 10, 10),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Padding(
            padding: const EdgeInsets.only(top: 4),
            child: Container(
              width: 8,
              height: 8,
              decoration: BoxDecoration(color: dotColor, shape: BoxShape.circle),
            ),
          ),
          const SizedBox(width: 10),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  task.title,
                  maxLines: 3,
                  overflow: TextOverflow.ellipsis,
                  style: theme.textTheme.bodyMedium?.copyWith(
                    fontWeight: FontWeight.w500,
                    height: 1.25,
                    decoration: done ? TextDecoration.lineThrough : null,
                    color: done ? cs.onSurfaceVariant : cs.onSurface,
                  ),
                ),
                if (task.courseLabel != null) ...[
                  const SizedBox(height: 4),
                  Text(
                    task.courseLabel!,
                    maxLines: 2,
                    overflow: TextOverflow.ellipsis,
                    style: theme.textTheme.labelSmall?.copyWith(
                      color: cs.primary.withValues(alpha: 0.9),
                      fontWeight: FontWeight.w500,
                    ),
                  ),
                ] else if (task.source == 'canvas') ...[
                  const SizedBox(height: 4),
                  Text(
                    'Canvas',
                    style: theme.textTheme.labelSmall?.copyWith(color: cs.primary.withValues(alpha: 0.85)),
                  ),
                ],
                if (task.description.trim().isNotEmpty && !done) ...[
                  const SizedBox(height: 4),
                  Text(
                    task.description.trim(),
                    maxLines: 2,
                    overflow: TextOverflow.ellipsis,
                    style: theme.textTheme.bodySmall?.copyWith(
                      color: cs.onSurfaceVariant,
                      height: 1.3,
                    ),
                  ),
                ],
              ],
            ),
          ),
          IconButton(
            icon: Icon(Icons.close, size: 16, color: cs.onSurfaceVariant),
            tooltip: 'Remove task',
            visualDensity: VisualDensity.compact,
            padding: EdgeInsets.zero,
            constraints: const BoxConstraints(minWidth: 28, minHeight: 28),
            onPressed: onDelete,
          ),
        ],
      ),
    );

    return Material(
      color: cs.surface,
      elevation: 0,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(8),
        side: BorderSide(color: cs.outlineVariant.withValues(alpha: 0.85)),
      ),
      child: interactive
          ? InkWell(
              onTap: () => onToggleDone(task, !done),
              borderRadius: BorderRadius.circular(8),
              child: inner,
            )
          : inner,
    );
  }

  @override
  Widget build(BuildContext context) {
    final shell = _shell(context, interactive: true);
    final ghost = _shell(context, interactive: false);

    return LongPressDraggable<TaskModel>(
      data: task,
      delay: const Duration(milliseconds: 280),
      hapticFeedbackOnStart: true,
      feedback: Material(
        elevation: 12,
        borderRadius: BorderRadius.circular(8),
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 220),
          child: ghost,
        ),
      ),
      childWhenDragging: Opacity(opacity: 0.35, child: shell),
      child: shell,
    );
  }
}

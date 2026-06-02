import 'package:flutter/material.dart';
import 'package:intl/intl.dart';

import '../../../core/theme/app_theme.dart';
import '../../../shared/utils/duration_format.dart';
import '../../../shared/utils/task_schedule_utils.dart';
import '../../../shared/utils/task_timeline_utils.dart';
import '../../../data/models/task_model.dart';

class TaskListTile extends StatelessWidget {
  final TaskModel task;
  final ValueChanged<bool> onToggle;
  final VoidCallback onDelete;

  const TaskListTile({
    super.key,
    required this.task,
    required this.onToggle,
    required this.onDelete,
  });

  Color _sourceColor(BuildContext context, {required bool completed}) {
    final scheme = Theme.of(context).colorScheme;
    if (completed) return scheme.onSurfaceVariant;
    return switch (task.source) {
      'manual' => AppColors.manualTask,
      'canvas' => AppColors.canvasAssignment,
      'course' => AppColors.deadline,
      _ => scheme.onSurfaceVariant,
    };
  }

  Color _urgencyColor(BuildContext context, {required bool completed}) {
    if (!completed && task.source == 'manual') {
      return AppColors.manualTask;
    }
    final scheme = Theme.of(context).colorScheme;
    if (completed) return scheme.onSurfaceVariant;
    final daysLeft = taskDaysUntilDue(task);
    if (daysLeft <= 0) return AppColors.deadline;
    if (daysLeft <= 3) return AppColors.secondary;
    return scheme.onSurfaceVariant;
  }

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final theme = Theme.of(context).textTheme;
    final due = taskDateOnly(task.dueDate);
    final completed = task.isCompleted;
    final urgency = _urgencyColor(context, completed: completed);
    final statusLabel = taskDueStatusLabel(task, completed: completed);
    final spanDays = taskSpanCalendarDays(task.estimatedMinutes);
    final workStart = taskWorkStartDate(task.dueDate, task.estimatedMinutes);
    final estimateLabel = DurationFormat.formatEstimate(task.estimatedMinutes);
    final dueLine =
        'Due ${DateFormat('MMM d').format(due)} · $statusLabel';

    return Card(
      margin: const EdgeInsets.only(bottom: 12),
      elevation: 0,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(8),
        side: BorderSide(
          color: completed
              ? scheme.outlineVariant.withValues(alpha: 0.75)
              : _sourceColor(context, completed: completed)
                  .withValues(alpha: 0.45),
        ),
      ),
      clipBehavior: Clip.antiAlias,
      child: IntrinsicHeight(
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            if (!completed)
              Container(
                width: 4,
                color: _sourceColor(context, completed: completed),
              ),
            Expanded(
              child: Padding(
                padding: const EdgeInsets.fromLTRB(4, 6, 8, 10),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    Row(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Checkbox(
                          value: task.isCompleted,
                          onChanged: (v) => onToggle(v ?? false),
                        ),
                        Expanded(
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Text(
                                task.title,
                                style: theme.titleSmall?.copyWith(
                                  decoration: task.isCompleted
                                      ? TextDecoration.lineThrough
                                      : null,
                                  color: task.isCompleted
                                      ? scheme.onSurfaceVariant
                                      : scheme.onSurface,
                                ),
                              ),
                              if (task.courseLabel != null) ...[
                                const SizedBox(height: 4),
                                Text(
                                  task.courseLabel!,
                                  style: theme.labelMedium?.copyWith(
                                    color: scheme.primary,
                                    fontWeight: FontWeight.w500,
                                  ),
                                ),
                              ] else ...[
                                const SizedBox(height: 4),
                                Text(
                                  switch (task.source) {
                                    'canvas' => 'Canvas',
                                    'course' => 'Course import',
                                    'manual' => 'Your task',
                                    _ => 'Task',
                                  },
                                  style: theme.labelMedium?.copyWith(
                                    color: _sourceColor(
                                      context,
                                      completed: completed,
                                    ),
                                    fontWeight: FontWeight.w600,
                                  ),
                                ),
                              ],
                            ],
                          ),
                        ),
                        IconButton(
                          icon: Icon(Icons.close,
                              size: 20, color: scheme.onSurfaceVariant),
                          tooltip: 'Remove task',
                          visualDensity: VisualDensity.compact,
                          padding: EdgeInsets.zero,
                          constraints: const BoxConstraints(
                            minWidth: 28,
                            minHeight: 28,
                          ),
                          onPressed: onDelete,
                        ),
                      ],
                    ),
                    Padding(
                      padding: const EdgeInsets.only(left: 12),
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          const SizedBox(height: 2),
                          Row(
                            children: [
                              Icon(Icons.schedule,
                                  size: 14, color: scheme.onSurfaceVariant),
                              const SizedBox(width: 4),
                              Flexible(
                                child: Text(
                                  'Estimate: $estimateLabel',
                                  style: theme.bodySmall,
                                ),
                              ),
                            ],
                          ),
                          if (spanDays > 1) ...[
                            const SizedBox(height: 4),
                            Text(
                              'Work ${DateFormat('MMM d').format(workStart)} to ${DateFormat('MMM d').format(due)}',
                              style: theme.bodySmall?.copyWith(
                                color: scheme.onSurfaceVariant,
                              ),
                            ),
                          ],
                          const SizedBox(height: 6),
                          Text(
                            dueLine,
                            style: theme.labelMedium?.copyWith(
                              color: urgency,
                              fontWeight: FontWeight.w600,
                            ),
                          ),
                        ],
                      ),
                    ),
                  ],
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

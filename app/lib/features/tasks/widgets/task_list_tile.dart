import 'package:flutter/material.dart';
import 'package:intl/intl.dart';

import '../../../core/theme/app_theme.dart';
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

  Color _urgencyColor(BuildContext context, DateTime due,
      {required bool completed}) {
    final scheme = Theme.of(context).colorScheme;
    if (completed) return scheme.onSurfaceVariant;
    final daysLeft = due.difference(DateTime.now()).inDays;
    if (daysLeft <= 1) return AppColors.deadline;
    if (daysLeft <= 3) return AppColors.secondary;
    return scheme.onSurfaceVariant;
  }

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final theme = Theme.of(context).textTheme;
    final due = task.dueDate;
    final daysLeft = due.difference(DateTime.now()).inDays;
    final completed = task.isCompleted;
    final urgency = _urgencyColor(context, due, completed: completed);
    final statusLabel = completed
        ? 'Done'
        : (daysLeft == 0 ? 'Today' : '$daysLeft days');

    return Card(
      margin: const EdgeInsets.only(bottom: 12),
      elevation: 0,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(8),
        side: BorderSide(color: scheme.outlineVariant.withValues(alpha: 0.75)),
      ),
      clipBehavior: Clip.antiAlias,
      child: Padding(
        padding: const EdgeInsets.fromLTRB(4, 6, 6, 8),
        child: Row(
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
                      decoration:
                          task.isCompleted ? TextDecoration.lineThrough : null,
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
                  ] else if (task.source == 'canvas') ...[
                    const SizedBox(height: 4),
                    Text(
                      'Canvas',
                      style: theme.labelMedium?.copyWith(
                        color: scheme.primary.withValues(alpha: 0.85),
                      ),
                    ),
                  ] else if (task.source == 'course') ...[
                    const SizedBox(height: 4),
                    Text(
                      'Course import',
                      style: theme.labelMedium?.copyWith(
                        color: scheme.primary.withValues(alpha: 0.85),
                      ),
                    ),
                  ],
                  const SizedBox(height: 6),
                  Row(
                    children: [
                      Icon(Icons.schedule,
                          size: 14, color: scheme.onSurfaceVariant),
                      const SizedBox(width: 4),
                      Text(
                        '~${task.estimatedMinutes} min',
                        style: theme.bodySmall,
                      ),
                    ],
                  ),
                ],
              ),
            ),
            const SizedBox(width: 4),
            SizedBox(
              width: 52,
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.end,
                children: [
                  IconButton(
                    icon: Icon(Icons.close,
                        size: 20, color: scheme.onSurfaceVariant),
                    tooltip: 'Remove task',
                    visualDensity: VisualDensity.compact,
                    padding: EdgeInsets.zero,
                    constraints:
                        const BoxConstraints(minWidth: 28, minHeight: 28),
                    alignment: Alignment.centerRight,
                    onPressed: onDelete,
                  ),
                  Text(
                    DateFormat('MMM d').format(due),
                    maxLines: 1,
                    textAlign: TextAlign.right,
                    overflow: TextOverflow.ellipsis,
                    style: theme.labelLarge?.copyWith(
                      color: urgency,
                      fontWeight: FontWeight.w600,
                    ),
                  ),
                  Text(
                    statusLabel,
                    maxLines: 1,
                    textAlign: TextAlign.right,
                    overflow: TextOverflow.ellipsis,
                    style: theme.labelSmall?.copyWith(color: urgency),
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}

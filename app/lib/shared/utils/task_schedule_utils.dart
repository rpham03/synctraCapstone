// Work window helpers — map task estimates to calendar days (start → due).
import '../../data/models/task_model.dart';
import 'task_timeline_utils.dart';

/// Inclusive calendar days the task occupies, derived from its estimate.
int taskSpanCalendarDays(int estimatedMinutes) {
  if (estimatedMinutes <= 0) return 1;
  final hours = estimatedMinutes / 60.0;
  if (hours <= 24) return 1;
  return (hours / 24).ceil().clamp(1, 365);
}

/// First calendar day you should work on this task (due date counts as the last day).
DateTime taskWorkStartDate(DateTime dueDate, int estimatedMinutes) {
  final due = taskDateOnly(dueDate);
  final span = taskSpanCalendarDays(estimatedMinutes);
  return due.subtract(Duration(days: span - 1));
}

/// True when [day] falls inside the task's work window (inclusive).
bool taskCoversDay(TaskModel task, DateTime day) {
  if (task.isCompleted) return false;
  final d = taskDateOnly(day);
  final start = taskWorkStartDate(task.dueDate, task.estimatedMinutes);
  final due = taskDateOnly(task.dueDate);
  return !d.isBefore(start) && !d.isAfter(due);
}

/// True when any part of the task window overlaps Mon–Sun [weekMonday].
bool taskOverlapsWeek(TaskModel task, DateTime weekMonday) {
  if (task.isCompleted) return false;
  final weekStart = taskDateOnly(weekMonday);
  final weekEnd = weekStart.add(const Duration(days: 7));
  final start = taskWorkStartDate(task.dueDate, task.estimatedMinutes);
  final due = taskDateOnly(task.dueDate);
  return due.isAfter(weekStart.subtract(const Duration(days: 1))) &&
      start.isBefore(weekEnd);
}

/// Calendar days from today until the due date (0 = due today).
int taskDaysUntilDue(TaskModel task, [DateTime? now]) {
  final today = taskDateOnly(now ?? DateTime.now());
  return taskDateOnly(task.dueDate).difference(today).inDays;
}

bool taskIsDueDay(TaskModel task, DateTime day) =>
    taskDateOnly(task.dueDate) == taskDateOnly(day);

String taskDueStatusLabel(TaskModel task, {required bool completed}) {
  if (completed) return 'Done';
  final left = taskDaysUntilDue(task);
  if (left == 0) return 'Due today';
  if (left == 1) return 'Due tomorrow';
  if (left < 0) {
    final overdue = -left;
    return overdue == 1 ? '1 day overdue' : '$overdue days overdue';
  }
  return left == 1 ? '1 day left' : '$left days left';
}

/// End-of-day due timestamp for a calendar column drop.
DateTime taskDueEndOfDay(DateTime day) =>
    DateTime(day.year, day.month, day.day, 23, 59);

bool eventCoversDay(DateTime rangeStart, DateTime rangeEnd, DateTime day) {
  final d = taskDateOnly(day);
  final start = taskDateOnly(rangeStart);
  final end = taskDateOnly(rangeEnd);
  return !d.isBefore(start) && !d.isAfter(end);
}

String manualTaskDayLabel({
  required DateTime viewDay,
  required DateTime rangeStart,
  required DateTime rangeEnd,
}) {
  final view = taskDateOnly(viewDay);
  final start = taskDateOnly(rangeStart);
  final due = taskDateOnly(rangeEnd);
  final today = taskDateOnly(DateTime.now());

  if (view == due) {
    if (view == today) return 'Due today';
    return 'Due ${ _shortDate(due) }';
  }
  if (view == start) {
    if (view == today) return 'Starts today';
    return 'Starts ${_shortDate(start)}';
  }
  return 'In progress, due ${_shortDate(due)}';
}

String _shortDate(DateTime d) {
  const months = [
    'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
    'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec',
  ];
  return '${months[d.month - 1]} ${d.day}';
}

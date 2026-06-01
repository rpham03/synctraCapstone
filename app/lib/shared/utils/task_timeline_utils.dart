// Merge and order Canvas / course-import / manual tasks for the Tasks timeline list.
import '../../data/models/task_model.dart';

DateTime taskDateOnly(DateTime d) => DateTime(d.year, d.month, d.day);

/// Due today or later (local calendar day). Overdue / past-due items are excluded.
bool isTaskDueTodayOrLater(TaskModel task, [DateTime? now]) {
  final today = taskDateOnly(now ?? DateTime.now());
  return !taskDateOnly(task.dueDate).isBefore(today);
}

String taskDedupeKey(TaskModel t) {
  final course = (t.courseLabel ?? t.courseId ?? '').trim().toLowerCase();
  final title = t.title
      .toLowerCase()
      .replaceAll(RegExp(r'[^a-z0-9]+'), ' ')
      .trim();
  final day = taskDateOnly(t.dueDate).toIso8601String();
  return '$course|$title|$day';
}

/// One row per assignment when Canvas and course import describe the same due item.
List<TaskModel> mergeCanvasAndCourseTasks(
  Iterable<TaskModel> canvas,
  Iterable<TaskModel> course,
) {
  final byKey = <String, TaskModel>{};

  void put(TaskModel task, {required bool prefer}) {
    final key = taskDedupeKey(task);
    final existing = byKey[key];
    if (existing == null || prefer) {
      byKey[key] = task;
    }
  }

  for (final t in course) {
    put(t, prefer: false);
  }
  for (final t in canvas) {
    put(t, prefer: true);
  }

  return byKey.values.toList();
}

int compareTasksTimeline(TaskModel a, TaskModel b) {
  final aDay = taskDateOnly(a.dueDate);
  final bDay = taskDateOnly(b.dueDate);
  final dayCmp = aDay.compareTo(bDay);
  if (dayCmp != 0) return dayCmp;
  final aDone = a.isCompleted ? 1 : 0;
  final bDone = b.isCompleted ? 1 : 0;
  if (aDone != bDone) return aDone.compareTo(bDone);
  return a.title.toLowerCase().compareTo(b.title.toLowerCase());
}

enum TaskTimelineSectionKind {
  earlier,
  today,
  tomorrow,
  thisWeek,
  later,
}

class TaskTimelineSection {
  final TaskTimelineSectionKind kind;
  final String label;
  final List<TaskModel> tasks;

  const TaskTimelineSection({
    required this.kind,
    required this.label,
    required this.tasks,
  });
}

TaskTimelineSectionKind sectionKindForTask(TaskModel task, DateTime today) {
  final due = taskDateOnly(task.dueDate);
  if (due.isBefore(today)) {
    return TaskTimelineSectionKind.earlier;
  }
  if (due == today) return TaskTimelineSectionKind.today;
  if (due == today.add(const Duration(days: 1))) {
    return TaskTimelineSectionKind.tomorrow;
  }
  final weekEnd = today.add(const Duration(days: 7));
  if (due.isBefore(weekEnd)) return TaskTimelineSectionKind.thisWeek;
  return TaskTimelineSectionKind.later;
}

List<TaskTimelineSection> buildTaskTimelineSections(List<TaskModel> tasks) {
  final today = taskDateOnly(DateTime.now());
  final sorted = List<TaskModel>.from(tasks)..sort(compareTasksTimeline);

  final buckets = <TaskTimelineSectionKind, List<TaskModel>>{
    for (final k in TaskTimelineSectionKind.values) k: [],
  };

  for (final t in sorted) {
    buckets[sectionKindForTask(t, today)]!.add(t);
  }

  String labelFor(TaskTimelineSectionKind kind) {
    switch (kind) {
      case TaskTimelineSectionKind.earlier:
        return 'Earlier';
      case TaskTimelineSectionKind.today:
        return 'Today';
      case TaskTimelineSectionKind.tomorrow:
        return 'Tomorrow';
      case TaskTimelineSectionKind.thisWeek:
        return 'This week';
      case TaskTimelineSectionKind.later:
        return 'Later';
    }
  }

  const order = [
    TaskTimelineSectionKind.earlier,
    TaskTimelineSectionKind.today,
    TaskTimelineSectionKind.tomorrow,
    TaskTimelineSectionKind.thisWeek,
    TaskTimelineSectionKind.later,
  ];

  return [
    for (final kind in order)
      if (buckets[kind]!.isNotEmpty)
        TaskTimelineSection(
          kind: kind,
          label: labelFor(kind),
          tasks: buckets[kind]!,
        ),
  ];
}

/// Default list: today and future only. Past completed tasks load on scroll-up.
class TimelineVisibleTasks {
  final List<TaskModel> tasks;
  final bool hasMorePast;

  const TimelineVisibleTasks({
    required this.tasks,
    required this.hasMorePast,
  });
}

TimelineVisibleTasks buildTimelineVisibleTasks(
  List<TaskModel> sortedAll, {
  required int revealedPastCount,
}) {
  final pastCompleted = <TaskModel>[];
  final todayAndFuture = <TaskModel>[];

  for (final task in sortedAll) {
    if (isTaskDueTodayOrLater(task)) {
      todayAndFuture.add(task);
    } else if (task.isCompleted) {
      pastCompleted.add(task);
    }
  }

  final hasMorePast = pastCompleted.length > revealedPastCount;
  final start = hasMorePast ? pastCompleted.length - revealedPastCount : 0;
  final revealedPast = pastCompleted.sublist(start);

  return TimelineVisibleTasks(
    tasks: [...revealedPast, ...todayAndFuture],
    hasMorePast: hasMorePast,
  );
}

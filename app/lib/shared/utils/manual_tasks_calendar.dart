// Manual tasks from the Tasks tab as calendar due-date chips (green).
import 'dart:convert';

import 'package:shared_preferences/shared_preferences.dart';

import '../../data/models/event_model.dart';
import '../../data/models/task_model.dart';
import 'duration_format.dart';
import 'task_schedule_utils.dart';

class ManualTasksCalendar {
  ManualTasksCalendar._();

  static const prefsKey = 'synctra_manual_tasks_v1';

  static DateTime _dueDay(DateTime due) =>
      DateTime(due.year, due.month, due.day);

  static String _eventDescription(TaskModel task) {
    final estimateLine =
        'Estimated time: ${DurationFormat.formatEstimate(task.estimatedMinutes)}';
    final body = task.description.trim();
    if (body.isEmpty) return estimateLine;
    if (body.contains(RegExp(r'^Estimated time:', multiLine: true))) {
      return body;
    }
    return '$estimateLine\n\n$body';
  }

  static EventModel eventFromTask(TaskModel task) {
    final dueDay = _dueDay(task.dueDate);
    final startDay = taskWorkStartDate(task.dueDate, task.estimatedMinutes);
    return EventModel(
      id: 'manual-task-${task.id}',
      title: task.title,
      startTime: startDay,
      endTime: DateTime(dueDay.year, dueDay.month, dueDay.day, 23, 59),
      source: 'manual_task',
      description: _eventDescription(task),
    );
  }

  static List<EventModel> eventsFromTasks(Iterable<TaskModel> tasks) =>
      tasks
          .where((t) =>
              t.source == 'manual' && !t.isCompleted && t.isDueTodayOrLater)
          .map(eventFromTask)
          .toList();

  static Future<List<TaskModel>> loadTasks() async {
    final prefs = await SharedPreferences.getInstance();
    final raw = prefs.getString(prefsKey);
    if (raw == null || raw.isEmpty) return [];
    try {
      final list = jsonDecode(raw) as List<dynamic>;
      return list
          .whereType<Map>()
          .map((m) => TaskModel.fromJson(Map<String, dynamic>.from(m)))
          .where((t) => t.source == 'manual')
          .toList();
    } catch (_) {
      return [];
    }
  }

  static Future<void> saveTasks(List<TaskModel> tasks) async {
    final prefs = await SharedPreferences.getInstance();
    final payload =
        tasks.where((t) => t.source == 'manual').map((t) => t.toJson()).toList();
    await prefs.setString(prefsKey, jsonEncode(payload));
  }

  static Future<List<EventModel>> loadEvents() async {
    final tasks = await loadTasks();
    return eventsFromTasks(tasks);
  }

  static Future<void> removeTaskById(String taskId) async {
    final tasks = await loadTasks();
    await saveTasks(tasks.where((t) => t.id != taskId).toList());
  }

  static Future<void> updateTaskFromEvent(
    EventModel original,
    EventModel updated,
  ) async {
    final taskId = original.id.replaceFirst('manual-task-', '');
    final tasks = await loadTasks();
    final i = tasks.indexWhere((t) => t.id == taskId);
    if (i < 0) return;
    tasks[i] = tasks[i].copyWith(
      title: updated.title,
      description: updated.description,
      dueDate: taskDueEndOfDay(
        DateTime(
          updated.endTime.year,
          updated.endTime.month,
          updated.endTime.day,
        ),
      ),
    );
    await saveTasks(tasks);
  }
}

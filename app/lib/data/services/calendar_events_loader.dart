// Loads calendar events and tasks for Chat (same rules as Calendar + Tasks tabs).
import 'dart:convert';

import 'package:dio/dio.dart';
import 'package:get_it/get_it.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../../core/constants/api_constants.dart';
import '../models/event_model.dart';
import '../models/schedule_block_model.dart';
import '../models/task_model.dart';
import 'course_import_service.dart';
import '../../shared/services/canvas_tasks_service.dart';
import '../../shared/services/suggested_schedule_store.dart';
import '../../shared/utils/calendar_display_utils.dart';
import '../../shared/utils/manual_tasks_calendar.dart';
import '../../shared/utils/local_time_format.dart';
import '../../shared/utils/task_timeline_utils.dart';

class CalendarEventsLoader {
  static const _manualEventsKey = 'synctra_manual_events_v1';
  static const _manualTasksKey = 'synctra_manual_tasks_v1';

  /// Device-local calendar date (YYYY-MM-DD) for the chat backend.
  static String clientTodayIso() =>
      CalendarDisplayUtils.localDateKey(DateTime.now());

  /// Calendar events aligned with the Calendar tab (deduped, with local_date).
  static Future<List<Map<String, dynamic>>> loadForChat() async {
    final events = <EventModel>[];
    await _loadIcalFeeds(events);
    await _loadCourseImports(events);
    await _loadManualEvents(events);
    await _loadManualTaskEvents(events);
    await _loadCanvasDueEvents(events);

    final deduped = CalendarDisplayUtils.dedupeCalendarEvents(events);
    final out = deduped.map(_eventPayload).toList();

    final store = _scheduleStoreOrNull();
    if (store != null) {
      for (final b in store.blocks) {
        out.add(_blockPayload(b));
      }
    }

    return out;
  }

  /// Incomplete Tasks-tab items. The backend filters by the requested due range.
  static Future<List<Map<String, dynamic>>> loadTasksForChat() async {
    final manual = <TaskModel>[];
    final canvas = <TaskModel>[];
    final course = <TaskModel>[];

    await _loadManualTasks(manual);
    await _loadCachedCanvasTasks(canvas);
    await _loadCourseTasks(course);

    final merged = mergeCanvasAndCourseTasks(canvas, course);
    final all = [...manual, ...merged];
    final out = <Map<String, dynamic>>[];
    for (final t in all) {
      if (t.isCompleted) continue;
      out.add(_taskPayload(t));
    }
    return out;
  }

  static SuggestedScheduleStore? _scheduleStoreOrNull() {
    try {
      final g = GetIt.instance;
      if (g.isRegistered<SuggestedScheduleStore>()) {
        return g<SuggestedScheduleStore>();
      }
    } catch (_) {}
    return null;
  }

  static Map<String, dynamic> _eventPayload(EventModel e) {
    final allDay = e.isDateOnlyCourseEvent || e.isCourseAssignment;
    return {
      'id': e.id,
      'start_time': e.startTime.toIso8601String(),
      'end_time': e.endTime.toIso8601String(),
      'local_date': CalendarDisplayUtils.localDateKey(e.startTime),
      'time_label':
          allDay ? null : LocalTimeFormat.timeRange(e.startTime, e.endTime),
      'when_label': allDay
          ? LocalTimeFormat.whenDateOnly(e.startTime)
          : LocalTimeFormat.whenTimed(e.startTime, e.endTime),
      'title': e.title,
      'source': e.source,
      'description': e.description,
      'is_all_day': allDay,
    };
  }

  static Map<String, dynamic> _blockPayload(ScheduleBlockModel b) => {
        'id': b.id,
        'start_time': b.startTime.toIso8601String(),
        'end_time': b.endTime.toIso8601String(),
        'local_date': CalendarDisplayUtils.localDateKey(b.startTime),
        'time_label': LocalTimeFormat.timeRange(b.startTime, b.endTime),
        'when_label': LocalTimeFormat.whenTimed(b.startTime, b.endTime),
        'title': b.taskTitle,
        'source': 'study_block',
        'description': b.description,
        'is_all_day': false,
        'is_ai_generated': b.isAiGenerated,
      };

  static Map<String, dynamic> _taskPayload(TaskModel t) => {
        ...t.toJson(),
        'local_due_date': CalendarDisplayUtils.localDateKey(t.dueDate),
        'due_label': LocalTimeFormat.dueLabel(t.dueDate),
      };

  static Future<void> _loadIcalFeeds(List<EventModel> out) async {
    final prefs = await SharedPreferences.getInstance();
    final raw = prefs.getStringList('ical_feeds') ?? [];
    for (final item in raw) {
      try {
        final feed = jsonDecode(item) as Map<String, dynamic>;
        final name = feed['name'] as String? ?? 'iCal';
        final url = feed['url'] as String?;
        if (url == null || url.isEmpty) continue;
        final resp = await Dio().post<Map<String, dynamic>>(
          '${ApiConstants.baseUrl}/events/ical-feeds/preview',
          data: {'url': url, 'name': name},
        );
        final events = resp.data?['events'];
        if (events is! List) continue;
        for (final e in events) {
          if (e is Map) {
            out.add(EventModel.fromJson(Map<String, dynamic>.from(e)));
          }
        }
      } catch (_) {}
    }
  }

  static Future<void> _loadCourseImports(List<EventModel> out) async {
    try {
      final service = CourseImportService();
      final imports = await service.loadImports();
      for (final rec in imports) {
        final events = await service.loadEventsForImport(rec.id);
        out.addAll(events);
      }
    } catch (_) {}
  }

  static Future<void> _loadManualTaskEvents(List<EventModel> out) async {
    try {
      out.addAll(await ManualTasksCalendar.loadEvents());
    } catch (_) {}
  }

  static Future<void> _loadManualEvents(List<EventModel> out) async {
    final prefs = await SharedPreferences.getInstance();
    final raw = prefs.getString(_manualEventsKey);
    if (raw == null || raw.isEmpty) return;
    try {
      final list = jsonDecode(raw) as List<dynamic>;
      for (final item in list) {
        if (item is! Map) continue;
        final e = EventModel.fromJson(Map<String, dynamic>.from(item));
        if (e.source == 'manual') out.add(e);
      }
    } catch (_) {}
  }

  static Future<void> _loadCanvasDueEvents(List<EventModel> out) async {
    try {
      final g = GetIt.instance;
      if (!g.isRegistered<CanvasTasksService>()) return;
      final service = g<CanvasTasksService>();
      final tasks = await service.loadCached();
      out.addAll(service.toCalendarEvents(tasks));
    } catch (_) {}
  }

  static Future<void> _loadManualTasks(List<TaskModel> out) async {
    final prefs = await SharedPreferences.getInstance();
    final raw = prefs.getString(_manualTasksKey);
    if (raw == null || raw.isEmpty) return;
    try {
      final list = jsonDecode(raw) as List<dynamic>;
      for (final item in list) {
        if (item is! Map) continue;
        out.add(TaskModel.fromJson(Map<String, dynamic>.from(item)));
      }
    } catch (_) {}
  }

  static Future<void> _loadCachedCanvasTasks(List<TaskModel> out) async {
    try {
      final g = GetIt.instance;
      if (!g.isRegistered<CanvasTasksService>()) return;
      final tasks = await g<CanvasTasksService>().loadCached();
      out.addAll(tasks);
    } catch (_) {}
  }

  static Future<void> _loadCourseTasks(List<TaskModel> out) async {
    try {
      final service = CourseImportService();
      out.addAll(await service.loadCachedTasks());
    } catch (_) {}
  }
}

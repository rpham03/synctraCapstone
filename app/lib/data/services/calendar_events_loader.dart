// Loads calendar events and tasks for Chat (same sources as Calendar + Tasks tabs).
import 'dart:convert';

import 'package:dio/dio.dart';
import 'package:get_it/get_it.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../../core/constants/api_constants.dart';
import '../models/event_model.dart';
import '../models/task_model.dart';
import 'course_import_service.dart';
import '../../shared/services/canvas_tasks_service.dart';

class CalendarEventsLoader {
  static const _manualEventsKey = 'synctra_manual_events_v1';
  static const _manualTasksKey = 'synctra_manual_tasks_v1';

  /// Calendar events to send with each chat message (schedule / busy times).
  static Future<List<Map<String, dynamic>>> loadForChat() async {
    final out = <Map<String, dynamic>>[];
    await _loadIcalFeeds(out);
    await _loadCourseImports(out);
    await _loadManualEvents(out);
    await _loadCanvasDueEvents(out);
    return out;
  }

  /// Tasks due today or later from the Tasks tab.
  static Future<List<Map<String, dynamic>>> loadTasksForChat() async {
    final out = <Map<String, dynamic>>[];
    await _loadManualTasks(out);
    await _loadCachedCanvasTasks(out);
    return out;
  }

  static void _addEvent(List<Map<String, dynamic>> out, EventModel e) {
    out.add({
      'start_time': e.startTime.toIso8601String(),
      'end_time': e.endTime.toIso8601String(),
      'title': e.title,
      'source': e.source,
    });
  }

  static Future<void> _loadIcalFeeds(List<Map<String, dynamic>> out) async {
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
            _addEvent(out, EventModel.fromJson(Map<String, dynamic>.from(e)));
          }
        }
      } catch (_) {
        // Skip feeds that fail to sync (offline, bad URL, etc.)
      }
    }
  }

  static Future<void> _loadCourseImports(List<Map<String, dynamic>> out) async {
    try {
      final service = CourseImportService();
      final imports = await service.loadImports();
      for (final rec in imports) {
        final events = await service.loadEventsForImport(rec.id);
        for (final e in events) {
          _addEvent(out, e);
        }
      }
    } catch (_) {
      // Not signed in or Supabase unavailable
    }
  }

  static Future<void> _loadManualEvents(List<Map<String, dynamic>> out) async {
    final prefs = await SharedPreferences.getInstance();
    final raw = prefs.getString(_manualEventsKey);
    if (raw == null || raw.isEmpty) return;
    try {
      final list = jsonDecode(raw) as List<dynamic>;
      for (final item in list) {
        if (item is! Map) continue;
        final m = Map<String, dynamic>.from(item);
        final e = EventModel.fromJson(m);
        if (e.source == 'manual') {
          _addEvent(out, e);
        }
      }
    } catch (_) {}
  }

  static Future<void> _loadCanvasDueEvents(List<Map<String, dynamic>> out) async {
    try {
      final g = GetIt.instance;
      if (!g.isRegistered<CanvasTasksService>()) return;
      final service = g<CanvasTasksService>();
      final tasks = await service.loadCached();
      for (final e in service.toCalendarEvents(tasks)) {
        _addEvent(out, e);
      }
    } catch (_) {}
  }

  static void _addTask(List<Map<String, dynamic>> out, TaskModel t) {
    if (!t.isDueTodayOrLater || t.isCompleted) return;
    out.add(t.toJson());
  }

  static Future<void> _loadManualTasks(List<Map<String, dynamic>> out) async {
    final prefs = await SharedPreferences.getInstance();
    final raw = prefs.getString(_manualTasksKey);
    if (raw == null || raw.isEmpty) return;
    try {
      final list = jsonDecode(raw) as List<dynamic>;
      for (final item in list) {
        if (item is! Map) continue;
        _addTask(out, TaskModel.fromJson(Map<String, dynamic>.from(item)));
      }
    } catch (_) {}
  }

  static Future<void> _loadCachedCanvasTasks(List<Map<String, dynamic>> out) async {
    try {
      final g = GetIt.instance;
      if (!g.isRegistered<CanvasTasksService>()) return;
      final tasks = await g<CanvasTasksService>().loadCached();
      for (final t in tasks) {
        _addTask(out, t);
      }
    } catch (_) {}
  }
}

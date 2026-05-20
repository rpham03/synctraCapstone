// Loads iCal + course calendar events for Chat (same sources as CalendarScreen).
import 'dart:convert';

import 'package:dio/dio.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../../core/constants/api_constants.dart';
import '../models/event_model.dart';
import 'course_import_service.dart';

class CalendarEventsLoader {
  /// Busy blocks to send with each chat message so free-time uses real schedule data.
  static Future<List<Map<String, dynamic>>> loadForChat() async {
    final out = <Map<String, dynamic>>[];
    await _loadIcalFeeds(out);
    await _loadCourseImports(out);
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
}

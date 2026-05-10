// Service for course URL imports.
// Calls the FastAPI scraper to extract events, then persists everything in
// Supabase (course_imports + events tables). CalendarScreen reads from here.

import 'package:dio/dio.dart';
import 'package:supabase_flutter/supabase_flutter.dart';

import '../../core/constants/api_constants.dart';
import '../models/event_model.dart';

class CourseImportRecord {
  final String id;
  final String courseUrl;
  final String courseName;
  final String? bestSource;
  final int eventCount;
  final DateTime lastSyncedAt;

  const CourseImportRecord({
    required this.id,
    required this.courseUrl,
    required this.courseName,
    this.bestSource,
    required this.eventCount,
    required this.lastSyncedAt,
  });

  factory CourseImportRecord.fromSupabase(Map<String, dynamic> row) =>
      CourseImportRecord(
        id: row['id'] as String,
        courseUrl: row['course_url'] as String,
        courseName: row['course_name'] as String? ?? '',
        bestSource: row['best_source'] as String?,
        eventCount: row['event_count'] as int? ?? 0,
        lastSyncedAt: DateTime.parse(row['last_synced_at'] as String),
      );
}

class CourseImportService {
  final _db = Supabase.instance.client;

  String get _userId => _db.auth.currentUser!.id;

  // ── Queries ──────────────────────────────────────────────────────────────

  Future<List<CourseImportRecord>> loadImports() async {
    final rows = await _db
        .from('course_imports')
        .select()
        .eq('user_id', _userId)
        .order('created_at');
    return rows.map(CourseImportRecord.fromSupabase).toList();
  }

  Future<List<EventModel>> loadEventsForImport(String importId) async {
    final rows = await _db
        .from('events')
        .select()
        .eq('course_import_id', importId)
        .order('start_time');
    return rows.map(EventModel.fromSupabase).toList();
  }

  // ── Mutations ─────────────────────────────────────────────────────────────

  /// Scrape [url], save everything to Supabase, return the new record.
  Future<CourseImportRecord> addImport(String url, String name) =>
      _scrapeAndSave(url: url, name: name, existingImportId: null);

  /// Re-scrape [url], replace events in Supabase, return updated record.
  Future<CourseImportRecord> syncImport({
    required String importId,
    required String url,
    required String name,
  }) =>
      _scrapeAndSave(url: url, name: name, existingImportId: importId);

  /// Delete a course import and all its events (cascade via FK).
  Future<void> removeImport(String importId) async {
    await _db.from('course_imports').delete().eq('id', importId);
  }

  // ── Internal ──────────────────────────────────────────────────────────────

  Future<CourseImportRecord> _scrapeAndSave({
    required String url,
    required String name,
    required String? existingImportId,
  }) async {
    // 1. Ask the backend to scrape the course page.
    final resp = await Dio().post(
      '${ApiConstants.baseUrl}/course-import/',
      queryParameters: {'course_url': url},
      options: Options(
        sendTimeout: const Duration(seconds: 60),
        receiveTimeout: const Duration(seconds: 60),
      ),
    );

    final data = resp.data as Map<String, dynamic>;
    final scrapedEvents = data['events'] as List<dynamic>;
    final bestSource = data['best_source'] as String?;
    final courseName = name.isNotEmpty ? name : _nameFromUrl(url);

    // 2. Upsert the course_imports row.
    final importRow = await _db
        .from('course_imports')
        .upsert(
          {
            'user_id': _userId,
            'course_url': url,
            'course_name': courseName,
            'best_source': bestSource,
            'last_synced_at': DateTime.now().toUtc().toIso8601String(),
            'event_count': scrapedEvents.length,
          },
          onConflict: 'user_id, course_url',
        )
        .select()
        .single();

    final importId = importRow['id'] as String;

    // 3. Delete stale events for this import, then re-insert fresh ones.
    await _db.from('events').delete().eq('course_import_id', importId);

    if (scrapedEvents.isNotEmpty) {
      final rows = scrapedEvents.asMap().entries.map((entry) {
        final idx = entry.key;
        final ev = entry.value as Map<String, dynamic>;
        final (start, end) = _parseTimes(ev);
        return {
          'user_id': _userId,
          'title': ev['title'] as String,
          'description': ev['description'] as String?,
          'start_time': start.toUtc().toIso8601String(),
          'end_time': end.toUtc().toIso8601String(),
          'source': 'course',
          // Stable within this import: importId + position index is fine
          // because we always delete + re-insert on sync.
          'source_event_id': '$importId:$idx',
          'course_import_id': importId,
          'is_fixed': true,
        };
      }).toList();

      await _db.from('events').insert(rows);
    }

    return CourseImportRecord.fromSupabase(importRow);
  }

  // Convert scraper's {date, time} pair into Flutter DateTimes.
  // Assignments without a specific time default to 23:59 (end-of-day deadline).
  (DateTime, DateTime) _parseTimes(Map<String, dynamic> ev) {
    final dateStr = ev['date'] as String; // "2026-04-15"
    final timeStr = ev['time'] as String?; // "23:59" or null
    final date = DateTime.parse(dateStr);

    final DateTime start;
    if (timeStr != null) {
      final parts = timeStr.split(':');
      start = DateTime(
        date.year, date.month, date.day,
        int.parse(parts[0]), int.parse(parts[1]),
      );
    } else {
      start = DateTime(date.year, date.month, date.day, 23, 59);
    }
    final end = start.add(const Duration(minutes: 30));
    return (start, end);
  }

  String _nameFromUrl(String url) {
    // Best-effort: extract last two path segments, e.g. "cse331/26sp"
    final segments = Uri.parse(url).pathSegments.where((s) => s.isNotEmpty).toList();
    if (segments.length >= 2) return segments.reversed.take(2).toList().reversed.join(' / ');
    if (segments.isNotEmpty) return segments.last;
    return url;
  }
}

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
    return rows.map((row) => EventModel.fromSupabase(row)).toList();
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
        sendTimeout: const Duration(seconds: 180),
        receiveTimeout: const Duration(seconds: 180),
      ),
    );

    final data = resp.data as Map<String, dynamic>;
    final courseName = name.isNotEmpty
        ? name
        : (data['course_name'] as String? ?? _nameFromUrl(url));
    final totalImported = data['total_imported'] as int? ?? 0;
    final classEvents = data['class_events'] as List<dynamic>? ?? [];
    final assignments = data['assignments'] as List<dynamic>? ?? [];

    // 2. Upsert the course_imports row.
    final importRow = await _db
        .from('course_imports')
        .upsert(
          {
            'user_id': _userId,
            'course_url': url,
            'course_name': courseName,
            'best_source': 'ai_parsed',
            'last_synced_at': DateTime.now().toUtc().toIso8601String(),
            'event_count': totalImported,
          },
          onConflict: 'user_id, course_url',
        )
        .select()
        .single();

    final importId = importRow['id'] as String;

    // 3. Save events from backend response.
    final rows = <Map<String, dynamic>>[
      ...classEvents.asMap().entries.map((entry) {
        final idx = entry.key;
        final ev = entry.value as Map<String, dynamic>;
        final title = ev['event_name'] as String;
        final rawStartTime = ev['start_time'] as String?;
        final hasTime = rawStartTime != null && rawStartTime.trim().isNotEmpty;
        final startTime = hasTime ? rawStartTime : '00:00';
        final endTime =
            hasTime ? ((ev['end_time'] as String?) ?? startTime) : startTime;
        final startIso = '${ev['date']}T$startTime';
        final endIso = '${ev['date']}T$endTime';

        return {
          'user_id': _userId,
          'title': title,
          'description': ev['description'] as String?,
          'location': ev['location'] as String?,
          'start_time': startIso,
          'end_time': endIso,
          'event_type': ev['event_type'] as String,
          'source': 'course',
          'source_event_id': _sourceEventId(
            importId: importId,
            kind: hasTime ? 'class' : 'class_date_only',
            index: idx,
            title: title,
            startIso: startIso,
            endIso: endIso,
          ),
          'course_import_id': importId,
          'is_fixed': true,
        };
      }),
      ...assignments.asMap().entries.map((entry) {
        final idx = entry.key;
        final assignment = entry.value as Map<String, dynamic>;
        final title = assignment['assignment_name'] as String;
        final rawDueTime = assignment['due_time'] as String?;
        final dueTime =
            rawDueTime == null || rawDueTime.trim().isEmpty ? null : rawDueTime;
        final dueIso = '${assignment['due_date']}T${dueTime ?? '00:00'}';

        return {
          'user_id': _userId,
          'title': title,
          'description': assignment['description'] as String?,
          'location': null,
          'start_time': dueIso,
          'end_time': dueIso,
          'event_type': assignment['assignment_type'] == 'exam' ? 'exam' : null,
          'source': 'course',
          'source_event_id': _sourceEventId(
            importId: importId,
            kind: dueTime == null ? 'assignment_date_only' : 'assignment',
            index: idx,
            title: title,
            startIso: dueIso,
            endIso: dueIso,
          ),
          'course_import_id': importId,
          'is_fixed': true,
        };
      }),
    ];

    // Delete old events first, then insert the current scrape.
    await _db.from('events').delete().eq('course_import_id', importId);
    if (rows.isNotEmpty) {
      await _db.from('events').insert(rows);
    }

    return CourseImportRecord.fromSupabase(importRow);
  }

  String _nameFromUrl(String url) {
    // Best-effort: extract last two path segments, e.g. "cse331/26sp"
    final segments =
        Uri.parse(url).pathSegments.where((s) => s.isNotEmpty).toList();
    if (segments.length >= 2) {
      return segments.reversed.take(2).toList().reversed.join(' / ');
    }
    if (segments.isNotEmpty) {
      return segments.last;
    }
    return url;
  }

  String _sourceEventId({
    required String importId,
    required String kind,
    required int index,
    required String title,
    required String startIso,
    required String endIso,
  }) {
    final raw = '$importId|$kind|$startIso|$endIso|$title|$index';
    return raw
        .toLowerCase()
        .replaceAll(RegExp(r'[^a-z0-9]+'), '_')
        .replaceAll(RegExp(r'_+'), '_')
        .replaceAll(RegExp(r'^_|_$'), '');
  }
}

// Service for course URL imports.
// Calls the FastAPI scraper to extract events, then persists everything in
// Supabase (course_imports + events tables). CalendarScreen reads from here.

import 'dart:convert';

import 'package:dio/dio.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:supabase_flutter/supabase_flutter.dart';

import '../../core/constants/api_constants.dart';
import '../models/event_model.dart';
import '../models/task_model.dart';

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

  static const _courseTasksKey = 'synctra_course_import_tasks_v1';

  String get _userId => _db.auth.currentUser!.id;

  List<Map<String, dynamic>> _rowsFrom(dynamic value) {
    if (value is List) {
      return value
          .whereType<Map>()
          .map((row) => Map<String, dynamic>.from(row))
          .toList();
    }
    return const [];
  }

  // ── Queries ──────────────────────────────────────────────────────────────

  Future<List<CourseImportRecord>> loadImports() async {
    final rows = await _db
        .from('course_imports')
        .select()
        .eq('user_id', _userId)
        .order('created_at');
    return _rowsFrom(rows).map(CourseImportRecord.fromSupabase).toList();
  }

  Future<List<EventModel>> loadEventsForImport(String importId) async {
    final rows = await _db
        .from('events')
        .select()
        .eq('course_import_id', importId)
        .order('start_time');
    return _rowsFrom(rows).map(EventModel.fromSupabase).toList();
  }

  Future<List<TaskModel>> loadCachedTasks() async {
    final cached = await _loadLocalCachedTasks();
    final imported = await _loadTasksFromImportedAssignmentEvents(cached);
    return _mergeCourseTasks(cached: cached, imported: imported)
        .map(_withoutImportedDescription)
        .toList();
  }

  TaskModel _withoutImportedDescription(TaskModel task) {
    if (task.source == 'manual' || task.description.isEmpty) return task;
    return task.copyWith(description: '');
  }

  Future<List<TaskModel>> _loadLocalCachedTasks() async {
    final prefs = await SharedPreferences.getInstance();
    final raw = prefs.getString(_courseTasksKey);
    if (raw == null || raw.isEmpty) return [];
    try {
      final list = jsonDecode(raw) as List<dynamic>;
      return list
          .whereType<Map>()
          .map((row) => TaskModel.fromJson(Map<String, dynamic>.from(row)))
          .where((task) => task.source == 'course')
          .toList();
    } catch (_) {
      return [];
    }
  }

  Future<void> saveCachedTasks(List<TaskModel> tasks) async {
    final prefs = await SharedPreferences.getInstance();
    final payload = tasks.where((task) => task.source == 'course').map((task) {
      return task.toJson();
    }).toList();
    await prefs.setString(_courseTasksKey, jsonEncode(payload));
  }

  Future<void> updateCachedTask(TaskModel updated) async {
    final tasks = await _loadLocalCachedTasks();
    final index = tasks.indexWhere((task) => task.id == updated.id);
    if (index >= 0) {
      tasks[index] = updated;
    } else {
      tasks.add(updated);
    }
    await saveCachedTasks(tasks);
  }

  /// Removes a course event from Supabase and drops any linked cached task row.
  Future<void> removeEventForCalendar(EventModel event) async {
    await _db.from('events').delete().eq('id', event.id);
    final sourceEventId = event.sourceEventId;
    if (sourceEventId != null && sourceEventId.contains('assignment')) {
      final taskId = _courseTaskIdFromSourceEventId(sourceEventId);
      await removeTaskForCalendar(taskId, updateCacheOnly: true);
    }
  }

  /// Updates a course calendar event in Supabase (and linked cached task when applicable).
  Future<void> updateCalendarEvent(EventModel event) async {
    await _db.from('events').update({
      'title': event.title,
      'description': event.description,
      'start_time': event.startTime.toUtc().toIso8601String(),
      'end_time': event.endTime.toUtc().toIso8601String(),
    }).eq('id', event.id);

    final sourceEventId = event.sourceEventId;
    if (sourceEventId == null || !sourceEventId.contains('assignment')) {
      return;
    }
    final taskId = _courseTaskIdFromSourceEventId(sourceEventId);
    final cached = await _loadLocalCachedTasks();
    final i = cached.indexWhere((t) => t.id == taskId);
    if (i < 0) return;
    cached[i] = cached[i].copyWith(
      title: event.title,
      dueDate: event.startTime,
      description: '',
    );
    await saveCachedTasks(cached);
  }

  /// Removes a course assignment task and any linked calendar events.
  Future<void> removeTaskForCalendar(
    String taskId, {
    bool updateCacheOnly = false,
  }) async {
    if (!updateCacheOnly) {
      final eventRows = await _db
          .from('events')
          .select('id,source_event_id')
          .eq('user_id', _userId)
          .eq('source', 'course');
      for (final row in _rowsFrom(eventRows)) {
        final sourceEventId = row['source_event_id'] as String? ?? '';
        if (_courseTaskIdFromSourceEventId(sourceEventId) != taskId) continue;
        await _db.from('events').delete().eq('id', row['id'] as String);
      }
    }
    final cached = await _loadLocalCachedTasks();
    await saveCachedTasks(cached.where((t) => t.id != taskId).toList());
  }

  Future<List<TaskModel>> _loadTasksFromImportedAssignmentEvents(
    List<TaskModel> cachedTasks,
  ) async {
    final user = _db.auth.currentUser;
    if (user == null) return const [];

    try {
      final importRows = await _db
          .from('course_imports')
          .select('id,course_name')
          .eq('user_id', user.id);
      final courseNameById = <String, String>{
        for (final row in _rowsFrom(importRows))
          row['id'] as String: row['course_name'] as String? ?? '',
      };

      final eventRows = await _db
          .from('events')
          .select(
            'id,title,description,start_time,source_event_id,course_import_id',
          )
          .eq('user_id', user.id)
          .eq('source', 'course')
          .order('start_time');

      final cachedById = {for (final task in cachedTasks) task.id: task};
      final tasks = <TaskModel>[];

      for (final row in _rowsFrom(eventRows)) {
        final sourceEventId = row['source_event_id'] as String? ?? '';
        if (!sourceEventId.contains('assignment')) continue;

        final title = row['title'] as String? ?? 'Assignment';
        final rawStartTime = row['start_time'] as String?;
        if (rawStartTime == null || rawStartTime.isEmpty) continue;

        final courseImportId = row['course_import_id'] as String?;
        final description = row['description'] as String? ?? '';
        final taskId = _courseTaskIdFromSourceEventId(
          sourceEventId.isNotEmpty ? sourceEventId : row['id'].toString(),
        );
        final existingTask = cachedById[taskId];
        final start = DateTime.parse(rawStartTime);
        final dueDate = sourceEventId.contains('assignment_date_only')
            ? DateTime(start.year, start.month, start.day, 23, 59)
            : start;

        tasks.add(
          TaskModel(
            id: taskId,
            title: title,
            dueDate: dueDate,
            estimatedMinutes: _estimatedMinutesFromDescription(description) ??
                _defaultEstimateForAssignmentTitle(title),
            courseId: courseImportId,
            courseName: courseNameById[courseImportId],
            source: 'course',
            isCompleted: existingTask?.isCompleted ?? false,
            description: '',
          ),
        );
      }

      return tasks;
    } catch (_) {
      return const [];
    }
  }

  List<TaskModel> _mergeCourseTasks({
    required List<TaskModel> cached,
    required List<TaskModel> imported,
  }) {
    final byId = <String, TaskModel>{};
    for (final task in imported) {
      byId[task.id] = task;
    }
    for (final task in cached) {
      byId[task.id] = task;
    }
    return byId.values.toList()..sort((a, b) => a.dueDate.compareTo(b.dueDate));
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
    await _removeCachedTasksForImport(importId);
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
        final startTime =
            _normalizedClassStartTime(ev['start_time'] as String?);
        final hasTime = startTime != null;
        final storedStartTime = startTime ?? '00:00';
        final endTime = hasTime
            ? _normalizedEndTime(storedStartTime, ev['end_time'] as String?)
            : storedStartTime;
        final startIso = '${ev['date']}T$storedStartTime';
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
        final dueTime = _normalizedDueTime(rawDueTime);
        final dueIso = '${assignment['due_date']}T${dueTime ?? '00:00'}';
        final estimatedMinutes =
            _normalizedEstimatedMinutes(assignment['estimated_minutes']);

        return {
          'user_id': _userId,
          'title': title,
          'description': _descriptionWithEstimate(
            assignment['description'] as String?,
            estimatedMinutes,
          ),
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

    final taskRows = await _courseTasksFromAssignments(
      importId: importId,
      courseName: courseName,
      assignments: assignments,
    );

    // Delete old events first, then insert the current scrape.
    await _db.from('events').delete().eq('course_import_id', importId);
    if (rows.isNotEmpty) {
      await _db.from('events').insert(rows);
    }
    await _replaceCachedTasksForImport(importId, taskRows);

    return CourseImportRecord.fromSupabase(importRow);
  }

  Future<List<TaskModel>> _courseTasksFromAssignments({
    required String importId,
    required String courseName,
    required List<dynamic> assignments,
  }) async {
    final existing = await _loadLocalCachedTasks();
    final existingById = {for (final task in existing) task.id: task};

    return assignments.asMap().entries.where((entry) {
      return entry.value is Map;
    }).map((entry) {
      final idx = entry.key;
      final assignment = Map<String, dynamic>.from(entry.value as Map);
      final title = assignment['assignment_name'] as String? ?? 'Assignment';
      final rawDueTime = assignment['due_time'] as String?;
      final dueTime = _normalizedDueTime(rawDueTime);
      final eventDueIso = '${assignment['due_date']}T${dueTime ?? '00:00'}';
      final taskDueIso = '${assignment['due_date']}T${dueTime ?? '23:59'}';
      final estimatedMinutes =
          _normalizedEstimatedMinutes(assignment['estimated_minutes']) ??
              _defaultEstimateForAssignmentType(
                assignment['assignment_type'] as String?,
              );
      final sourceEventId = _sourceEventId(
        importId: importId,
        kind: dueTime == null ? 'assignment_date_only' : 'assignment',
        index: idx,
        title: title,
        startIso: eventDueIso,
        endIso: eventDueIso,
      );
      final id = _courseTaskIdFromSourceEventId(sourceEventId);
      final existingTask = existingById[id];

      return TaskModel(
        id: id,
        title: title,
        dueDate: DateTime.parse(taskDueIso),
        estimatedMinutes: estimatedMinutes,
        courseId: importId,
        courseName: courseName,
        source: 'course',
        isCompleted: existingTask?.isCompleted ?? false,
        description: '',
      );
    }).toList();
  }

  Future<void> _replaceCachedTasksForImport(
    String importId,
    List<TaskModel> importedTasks,
  ) async {
    final existing = await _loadLocalCachedTasks();
    final retained = existing.where((task) => task.courseId != importId);
    await saveCachedTasks([...retained, ...importedTasks]);
  }

  Future<void> _removeCachedTasksForImport(String importId) async {
    final existing = await _loadLocalCachedTasks();
    await saveCachedTasks(
      existing.where((task) => task.courseId != importId).toList(),
    );
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

  String? _normalizedDueTime(String? rawDueTime) {
    final dueTime = rawDueTime?.trim();
    if (dueTime == null || dueTime.isEmpty || dueTime.startsWith('00:00')) {
      return null;
    }
    return dueTime;
  }

  int? _normalizedEstimatedMinutes(dynamic rawMinutes) {
    final minutes = rawMinutes is num
        ? rawMinutes.round()
        : int.tryParse(rawMinutes?.toString() ?? '');
    if (minutes == null || minutes <= 0) return null;
    return minutes.clamp(60, 960).toInt();
  }

  int _defaultEstimateForAssignmentType(String? rawType) {
    switch (rawType?.trim().toLowerCase()) {
      case 'project':
        return 600;
      case 'lab':
        return 240;
      case 'reading':
      case 'quiz':
        return 120;
      case 'exam':
        return 360;
      case 'homework':
      default:
        return 300;
    }
  }

  int _defaultEstimateForAssignmentTitle(String title) {
    final lower = title.toLowerCase();
    if (lower.contains('project')) {
      return _defaultEstimateForAssignmentType('project');
    }
    if (lower.contains('lab')) {
      return _defaultEstimateForAssignmentType('lab');
    }
    if (lower.contains('quiz')) {
      return _defaultEstimateForAssignmentType('quiz');
    }
    if (lower.contains('exam') ||
        lower.contains('midterm') ||
        lower.contains('final')) {
      return _defaultEstimateForAssignmentType('exam');
    }
    if (lower.contains('reading') || lower.contains('read ')) {
      return _defaultEstimateForAssignmentType('reading');
    }
    return _defaultEstimateForAssignmentType('homework');
  }

  int? _estimatedMinutesFromDescription(String? rawDescription) {
    final description = rawDescription?.trim();
    if (description == null || description.isEmpty) return null;

    final match = RegExp(
      r'Estimated time:\s*(?:(\d+)\s*h)?(?:\s*(\d+)\s*m)?',
      caseSensitive: false,
    ).firstMatch(description);
    if (match == null) return null;

    final hours = int.tryParse(match.group(1) ?? '') ?? 0;
    final minutes = int.tryParse(match.group(2) ?? '') ?? 0;
    final total = hours * 60 + minutes;
    if (total <= 0) return null;
    return _normalizedEstimatedMinutes(total);
  }

  String _descriptionWithEstimate(String? rawDescription, int? minutes) {
    final description = rawDescription?.trim() ?? '';
    if (minutes == null) return description;
    final estimateLine = 'Estimated time: ${_formatDuration(minutes)}';
    if (description.contains(RegExp(r'^Estimated time:', multiLine: true))) {
      return description;
    }
    if (description.isEmpty) return estimateLine;
    return '$estimateLine\n\n$description';
  }

  String _formatDuration(int minutes) {
    final hours = minutes ~/ 60;
    final mins = minutes % 60;
    if (hours == 0) return '${mins}m';
    if (mins == 0) return '${hours}h';
    return '${hours}h ${mins}m';
  }

  String? _normalizedClassStartTime(String? rawStartTime) {
    final startTime = rawStartTime?.trim();
    if (startTime == null ||
        startTime.isEmpty ||
        startTime.startsWith('00:00')) {
      return null;
    }
    return startTime;
  }

  String _normalizedEndTime(String startTime, String? rawEndTime) {
    final endTime = rawEndTime?.trim();
    final startMinutes = _minutesFromTime(startTime);
    final endMinutes = _minutesFromTime(endTime);
    if (startMinutes == null) {
      return endTime == null || endTime.isEmpty ? startTime : endTime;
    }
    if (endMinutes == null || endMinutes <= startMinutes) {
      return _timeFromMinutes(startMinutes + 50);
    }
    return endTime!;
  }

  int? _minutesFromTime(String? time) {
    if (time == null || time.trim().isEmpty) return null;
    final parts = time.trim().split(':');
    if (parts.length < 2) return null;
    final hour = int.tryParse(parts[0]);
    final minute = int.tryParse(parts[1]);
    if (hour == null || minute == null) return null;
    return hour * 60 + minute;
  }

  String _timeFromMinutes(int totalMinutes) {
    final minutesInDay = const Duration(days: 1).inMinutes;
    final normalized = totalMinutes.clamp(0, minutesInDay - 1);
    final hour = normalized ~/ 60;
    final minute = normalized % 60;
    return '${hour.toString().padLeft(2, '0')}:${minute.toString().padLeft(2, '0')}';
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

  String _courseTaskIdFromSourceEventId(String sourceEventId) {
    final raw = 'course-task|$sourceEventId';
    return raw
        .toLowerCase()
        .replaceAll(RegExp(r'[^a-z0-9]+'), '_')
        .replaceAll(RegExp(r'_+'), '_')
        .replaceAll(RegExp(r'^_|_$'), '');
  }
}

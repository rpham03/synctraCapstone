// Canvas assignments: API sync, local cache, calendar event conversion.
import 'dart:convert';

import 'package:dio/dio.dart';
import 'package:flutter/foundation.dart';
import 'package:get_it/get_it.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../../core/constants/api_constants.dart';
import '../../data/models/event_model.dart';
import '../../data/models/task_model.dart';
import '../utils/task_timeline_utils.dart';

class CanvasTasksService extends ChangeNotifier {
  static const _cacheKey = 'synctra_canvas_tasks_v1';
  static const _lastSyncKey = 'synctra_canvas_last_sync_ms';
  static const _tokenKey = 'synctra_canvas_token_v1';
  static const _maxPastRetentionDays = 120;

  DateTime? _lastSyncedAt;

  DateTime? get lastSyncedAt => _lastSyncedAt;

  /// The student's saved Canvas personal access token, or null if not set.
  Future<String?> loadToken() async {
    final prefs = await SharedPreferences.getInstance();
    final token = prefs.getString(_tokenKey)?.trim();
    return (token == null || token.isEmpty) ? null : token;
  }

  Future<bool> hasToken() async => (await loadToken()) != null;

  Future<void> saveToken(String token) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(_tokenKey, token.trim());
    notifyListeners();
  }

  Future<void> clearToken() async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.remove(_tokenKey);
    notifyListeners();
  }

  Future<void> loadLastSyncTime() async {
    final prefs = await SharedPreferences.getInstance();
    final ms = prefs.getInt(_lastSyncKey);
    if (ms == null) return;
    _lastSyncedAt = DateTime.fromMillisecondsSinceEpoch(ms);
  }

  Future<void> _recordSyncTime() async {
    _lastSyncedAt = DateTime.now();
    final prefs = await SharedPreferences.getInstance();
    await prefs.setInt(_lastSyncKey, _lastSyncedAt!.millisecondsSinceEpoch);
    notifyListeners();
  }

  Future<List<TaskModel>> loadCached() async {
    final prefs = await SharedPreferences.getInstance();
    final raw = prefs.getString(_cacheKey);
    if (raw == null || raw.isEmpty) return [];
    try {
      final list = jsonDecode(raw) as List<dynamic>;
      return list
          .whereType<Map>()
          .map((m) => TaskModel.fromJson(Map<String, dynamic>.from(m)))
          .where((t) => t.source == 'canvas')
          .toList()
        ..sort(compareTasksTimeline);
    } catch (_) {
      return [];
    }
  }

  Future<void> saveCache(List<TaskModel> tasks) async {
    final prefs = await SharedPreferences.getInstance();
    final payload = tasks
        .where((t) => t.source == 'canvas')
        .map((t) => t.toJson())
        .toList();
    await prefs.setString(_cacheKey, jsonEncode(payload));
  }

  /// Clears cached Canvas assignments so the next sync starts fresh.
  Future<void> clearCache() async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.remove(_cacheKey);
    notifyListeners();
  }

  List<TaskModel> _mergeWithCache(
    List<TaskModel> existing,
    List<TaskModel> incoming,
  ) {
    final byId = <String, TaskModel>{
      for (final t in existing) t.id: t,
    };
    for (final t in incoming) {
      byId[t.id] = t;
    }

    final today = taskDateOnly(DateTime.now());
    final pruneBefore = today.subtract(const Duration(days: _maxPastRetentionDays));

    return byId.values
        .where((t) {
          if (!t.isCompleted) return true;
          return !taskDateOnly(t.dueDate).isBefore(pruneBefore);
        })
        .toList()
      ..sort(compareTasksTimeline);
  }

  /// Fetches from backend, merges into cache (keeps older past dues), returns all cached.
  Future<List<TaskModel>> syncFromApi() async {
    final existing = await loadCached();
    final token = await loadToken();
    final response = await Dio().get<Map<String, dynamic>>(
      '${ApiConstants.baseUrl}/canvas/assignments',
      options: (token != null)
          ? Options(headers: {'X-Canvas-Token': token})
          : null,
    );
    final raw = response.data?['tasks'];
    if (raw is! List) {
      throw const FormatException('Invalid response: missing tasks list');
    }
    final incoming = raw
        .whereType<Map>()
        .map((m) => TaskModel.fromJson(Map<String, dynamic>.from(m)))
        .where((t) => t.isDueTodayOrLater)
        .toList();
    final merged = _mergeWithCache(existing, incoming);
    await saveCache(merged);
    await _recordSyncTime();
    notifyListeners();
    return merged;
  }

  Future<void> reloadFromCache() async {
    notifyListeners();
  }

  /// Due-date chips on the calendar (today+ only for the calendar row).
  List<EventModel> toCalendarEvents(Iterable<TaskModel> tasks) {
    return tasks
        .where((t) => t.isDueTodayOrLater)
        .map((t) {
      final d = DateTime(t.dueDate.year, t.dueDate.month, t.dueDate.day);
      final label = t.courseLabel;
      return EventModel(
        id: 'canvas-${t.id}',
        title: label != null ? '$label · ${t.title}' : t.title,
        startTime: d,
        endTime: d.add(const Duration(minutes: 15)),
        source: 'canvas',
        description: t.description,
      );
    }).toList();
  }
}

void registerCanvasTasksService() {
  final g = GetIt.instance;
  if (!g.isRegistered<CanvasTasksService>()) {
    g.registerSingleton(CanvasTasksService());
  }
}

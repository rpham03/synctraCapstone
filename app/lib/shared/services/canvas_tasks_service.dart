// Canvas assignments: API sync, local cache, calendar event conversion.
import 'dart:convert';

import 'package:dio/dio.dart';
import 'package:flutter/foundation.dart';
import 'package:get_it/get_it.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../../core/constants/api_constants.dart';
import '../../data/models/event_model.dart';
import '../../data/models/task_model.dart';

class CanvasTasksService extends ChangeNotifier {
  static const _cacheKey = 'synctra_canvas_tasks_v1';

  Future<List<TaskModel>> loadCached() async {
    final prefs = await SharedPreferences.getInstance();
    final raw = prefs.getString(_cacheKey);
    if (raw == null || raw.isEmpty) return [];
    try {
      final list = jsonDecode(raw) as List<dynamic>;
      return list
          .whereType<Map>()
          .map((m) => TaskModel.fromJson(Map<String, dynamic>.from(m)))
          .where((t) => t.source == 'canvas' && t.isDueTodayOrLater)
          .toList();
    } catch (_) {
      return [];
    }
  }

  Future<void> saveCache(List<TaskModel> tasks) async {
    final prefs = await SharedPreferences.getInstance();
    final payload = tasks.map((t) => t.toJson()).toList();
    await prefs.setString(_cacheKey, jsonEncode(payload));
  }

  /// Fetches from backend and updates cache. Throws on hard failure.
  Future<List<TaskModel>> syncFromApi() async {
    final response = await Dio().get<Map<String, dynamic>>(
      '${ApiConstants.baseUrl}/canvas/assignments',
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
    await saveCache(incoming);
    notifyListeners();
    return incoming;
  }

  Future<void> reloadFromCache() async {
    notifyListeners();
  }

  /// Due-date chips on the calendar (all-day row, not time grid).
  List<EventModel> toCalendarEvents(Iterable<TaskModel> tasks) {
    return tasks.map((t) {
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

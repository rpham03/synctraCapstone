import 'package:dio/dio.dart';

import '../../core/constants/api_constants.dart';
import '../../data/models/event_model.dart';
import '../../data/models/habit_model.dart';
import 'user_scope.dart';

/// HTTP client for Reclaim-style habit CRUD and scheduling.
class HabitService {
  HabitService({Dio? dio}) : _dio = dio ?? Dio();

  final Dio _dio;

  Map<String, String> get _headers => {'X-User-Id': currentUserScope()};

  Future<List<HabitModel>> listHabits() async {
    final resp = await _dio.get<Map<String, dynamic>>(
      '${ApiConstants.baseUrl}/habits',
      options: Options(headers: _headers),
    );
    final habits = resp.data?['habits'];
    if (habits is! List) return [];
    return habits
        .whereType<Map>()
        .map((m) => HabitModel.fromJson(Map<String, dynamic>.from(m)))
        .toList();
  }

  Future<HabitModel> createHabit(Map<String, dynamic> payload) async {
    final resp = await _dio.post<Map<String, dynamic>>(
      '${ApiConstants.baseUrl}/habits',
      data: payload,
      options: Options(headers: _headers),
    );
    final habit = resp.data?['habit'];
    if (habit is! Map) {
      throw StateError('Invalid create habit response');
    }
    return HabitModel.fromJson(Map<String, dynamic>.from(habit));
  }

  Future<HabitModel> updateHabit(String id, Map<String, dynamic> payload) async {
    final resp = await _dio.put<Map<String, dynamic>>(
      '${ApiConstants.baseUrl}/habits/$id',
      data: payload,
      options: Options(headers: _headers),
    );
    final habit = resp.data?['habit'];
    if (habit is! Map) {
      throw StateError('Invalid update habit response');
    }
    return HabitModel.fromJson(Map<String, dynamic>.from(habit));
  }

  Future<void> deleteHabit(String id) async {
    await _dio.delete(
      '${ApiConstants.baseUrl}/habits/$id',
      options: Options(headers: _headers),
    );
  }

  Future<List<HabitSessionModel>> scheduleWeek({
    required List<EventModel> calendarEvents,
    DateTime? weekStart,
    int lookAheadDays = 7,
  }) async {
    final resp = await _dio.post<Map<String, dynamic>>(
      '${ApiConstants.baseUrl}/habits/schedule',
      data: {
        'calendar_events': _eventsToApi(calendarEvents),
        if (weekStart != null) 'week_start': weekStart.toIso8601String(),
        'look_ahead_days': lookAheadDays,
      },
      options: Options(headers: _headers),
    );
    return _parseSessions(resp.data?['sessions']);
  }

  Future<List<HabitSessionModel>> rescheduleForNewEvent({
    required List<EventModel> calendarEvents,
    required List<HabitSessionModel> currentSessions,
    required EventModel newEvent,
    DateTime? weekStart,
    int lookAheadDays = 7,
  }) async {
    final resp = await _dio.post<Map<String, dynamic>>(
      '${ApiConstants.baseUrl}/habits/reschedule',
      data: {
        'calendar_events': _eventsToApi(calendarEvents),
        'current_sessions': [
          for (final s in currentSessions) s.toRescheduleJson(),
        ],
        'new_event': {
          'id': newEvent.id,
          'title': newEvent.title,
          'start': newEvent.startTime.toIso8601String(),
          'end': newEvent.endTime.toIso8601String(),
          'source': newEvent.source,
        },
        if (weekStart != null) 'week_start': weekStart.toIso8601String(),
        'look_ahead_days': lookAheadDays,
      },
      options: Options(headers: _headers),
    );
    return _parseSessions(resp.data?['sessions']);
  }

  static List<Map<String, dynamic>> _eventsToApi(List<EventModel> events) => [
        for (final e in events)
          {
            'id': e.id,
            'title': e.title,
            'start': e.startTime.toIso8601String(),
            'end': e.endTime.toIso8601String(),
            'source': e.source,
          },
      ];

  static List<HabitSessionModel> _parseSessions(dynamic raw) {
    if (raw is! List) return [];
    return raw
        .whereType<Map>()
        .map((m) => HabitSessionModel.fromJson(Map<String, dynamic>.from(m)))
        .toList();
  }
}

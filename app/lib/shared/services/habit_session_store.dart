import 'dart:async';
import 'dart:convert';

import 'package:flutter/foundation.dart';
import 'package:get_it/get_it.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../../data/models/event_model.dart';
import '../../data/models/habit_model.dart';
import 'habit_service.dart';
import 'user_scope.dart';

/// Persisted habit sessions for the calendar grid; calls the scheduling API.
class HabitSessionStore extends ChangeNotifier {
  static const _persistKeyBase = 'synctra_habit_sessions_v1';

  String get _persistKey => userScopedKey(_persistKeyBase);

  final HabitService _service;
  final List<HabitSessionModel> _sessions = [];
  List<EventModel> _lastCalendarEvents = [];
  DateTime? _lastWeekStart;
  bool _scheduling = false;
  int _scheduleGeneration = 0;

  HabitSessionStore({HabitService? service})
      : _service = service ?? HabitService();

  List<HabitSessionModel> get sessions => List.unmodifiable(_sessions);
  List<EventModel> get calendarEvents => List.unmodifiable(_lastCalendarEvents);
  bool get isScheduling => _scheduling;

  /// Sunday-start week anchor (matches [CalendarScreen] navigation).
  static DateTime startOfWeek(DateTime d) {
    final day = DateTime(d.year, d.month, d.day);
    return day.subtract(Duration(days: day.weekday % 7));
  }

  Future<void> refreshFromCachedEvents({DateTime? weekStart}) => refreshSchedule(
        calendarEvents: _lastCalendarEvents,
        weekStart: weekStart,
      );

  Future<void> refreshAfterHabitChange({DateTime? weekStart}) =>
      refreshSchedule(
        calendarEvents: _lastCalendarEvents,
        weekStart: weekStart ?? _lastWeekStart ?? startOfWeek(DateTime.now()),
      );

  void setCalendarEvents(Iterable<EventModel> events) {
    _lastCalendarEvents = events.toList();
  }

  List<HabitSessionModel> sessionsOnDay(DateTime day) => _sessions
      .where(
        (s) =>
            s.startTime.year == day.year &&
            s.startTime.month == day.month &&
            s.startTime.day == day.day,
      )
      .toList();

  void updateSessionTimes({
    required String id,
    required DateTime start,
    required DateTime end,
  }) {
    final i = _sessions.indexWhere((s) => s.id == id);
    if (i < 0) return;
    _sessions[i] = _sessions[i].copyWith(
      startTime: start,
      endTime: end.isAfter(start) ? end : start.add(const Duration(minutes: 30)),
    );
    unawaited(_persist());
    notifyListeners();
  }

  Future<void> loadPersisted() async {
    try {
      final prefs = await SharedPreferences.getInstance();
      final raw = prefs.getString(_persistKey);
      final decoded = (raw == null || raw.isEmpty) ? const [] : jsonDecode(raw);
      if (decoded is! List) return;
      final loaded = decoded
          .whereType<Map>()
          .map((m) => HabitSessionModel.fromJson(Map<String, dynamic>.from(m)))
          .toList();
      _sessions
        ..clear()
        ..addAll(loaded);
      notifyListeners();
    } catch (_) {}
  }

  Future<void> refreshSchedule({
    required Iterable<EventModel> calendarEvents,
    DateTime? weekStart,
  }) async {
    final generation = ++_scheduleGeneration;
    _lastCalendarEvents = calendarEvents.toList();
    if (weekStart != null) {
      _lastWeekStart = startOfWeek(weekStart);
    }
    _scheduling = true;
    notifyListeners();
    try {
      final habits = await _service.listHabits();
      if (generation != _scheduleGeneration) return;
      if (habits.where((h) => h.isActive).isEmpty) {
        _sessions.clear();
        await _persist();
        return;
      }
      final sessions = await _service.scheduleWeek(
        calendarEvents: _lastCalendarEvents,
        weekStart: weekStart,
      );
      if (generation != _scheduleGeneration) return;
      _sessions
        ..clear()
        ..addAll(sessions);
      await _persist();
    } catch (e) {
      debugPrint('Habit schedule failed: $e');
    } finally {
      if (generation == _scheduleGeneration) {
        _scheduling = false;
        notifyListeners();
      }
    }
  }

  Future<void> rescheduleForNewEvent({
    required EventModel newEvent,
    DateTime? weekStart,
  }) async {
    if (_sessions.isEmpty) {
      await refreshSchedule(
        calendarEvents: _lastCalendarEvents,
        weekStart: weekStart,
      );
      return;
    }
    final generation = ++_scheduleGeneration;
    _scheduling = true;
    notifyListeners();
    try {
      final others = _lastCalendarEvents
          .where((e) => e.id != newEvent.id)
          .toList();
      final sessions = await _service.rescheduleForNewEvent(
        calendarEvents: others,
        currentSessions: _sessions,
        newEvent: newEvent,
        weekStart: weekStart,
      );
      if (generation != _scheduleGeneration) return;
      _sessions
        ..clear()
        ..addAll(sessions);
      await _persist();
    } catch (e) {
      debugPrint('Habit reschedule failed: $e');
    } finally {
      if (generation == _scheduleGeneration) {
        _scheduling = false;
        notifyListeners();
      }
    }
  }

  Future<void> _persist() async {
    try {
      final prefs = await SharedPreferences.getInstance();
      await prefs.setString(
        _persistKey,
        jsonEncode([for (final s in _sessions) s.toJson()]),
      );
    } catch (_) {}
  }
}

void registerHabitSessionStore() {
  final g = GetIt.instance;
  if (!g.isRegistered<HabitSessionStore>()) {
    g.registerSingleton(HabitSessionStore());
  }
}

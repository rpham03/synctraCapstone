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
      final scheduleStart =
          startOfWeek(weekStart ?? _lastWeekStart ?? DateTime.now());
      _lastWeekStart = scheduleStart;
      List<HabitSessionModel> sessions;
      try {
        sessions = await _service.scheduleWeek(
          calendarEvents: _lastCalendarEvents,
          weekStart: scheduleStart,
        );
        if (sessions.isEmpty) {
          sessions = _buildLocalFallbackSchedule(
            habits: habits,
            calendarEvents: _lastCalendarEvents,
            weekStart: scheduleStart,
          );
        }
      } catch (error) {
        debugPrint(
          'Habit scheduling endpoint failed; using local placement: $error',
        );
        sessions = _buildLocalFallbackSchedule(
          habits: habits,
          calendarEvents: _lastCalendarEvents,
          weekStart: scheduleStart,
        );
      }
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

  static List<HabitSessionModel> _buildLocalFallbackSchedule({
    required Iterable<HabitModel> habits,
    required Iterable<EventModel> calendarEvents,
    required DateTime weekStart,
  }) {
    final sessions = <HabitSessionModel>[];
    final busy = <({DateTime start, DateTime end})>[
      for (final event in calendarEvents)
        if (event.endTime.isAfter(event.startTime))
          (start: event.startTime, end: event.endTime),
    ];
    final active = habits.where((habit) => habit.isActive).toList()
      ..sort((a, b) => b.priority.compareTo(a.priority));

    for (final habit in active) {
      final preferredDays = habit.preferredDays.isEmpty
          ? List<int>.generate(7, (day) => day)
          : habit.preferredDays;
      var placed = 0;
      for (final backendDay in preferredDays) {
        if (placed >= habit.frequencyPerWeek) break;
        final day = _dateForBackendWeekday(weekStart, backendDay);
        final ranges = habit.preferredTimeRanges[backendDay.toString()];
        final windows = ranges == null || ranges.isEmpty
            ? const [HabitTimeRange(start: '8:00am', end: '10:00pm')]
            : ranges;
        DateTime? selectedStart;
        for (final window in windows) {
          final rangeStart = _clockOnDay(day, window.start);
          var rangeEnd = _clockOnDay(day, window.end);
          if (!rangeEnd.isAfter(rangeStart)) {
            rangeEnd = rangeEnd.add(const Duration(days: 1));
          }
          var candidate = rangeStart;
          final duration = Duration(minutes: habit.durationMinutes);
          while (!candidate.add(duration).isAfter(rangeEnd)) {
            final candidateEnd = candidate.add(duration);
            final overlaps = busy.any(
              (entry) =>
                  candidate.isBefore(entry.end) &&
                  candidateEnd.isAfter(entry.start),
            );
            if (!overlaps) {
              selectedStart = candidate;
              break;
            }
            candidate = candidate.add(const Duration(minutes: 15));
          }
          if (selectedStart != null) break;
        }
        if (selectedStart == null) continue;
        final selectedEnd =
            selectedStart.add(Duration(minutes: habit.durationMinutes));
        busy.add((start: selectedStart, end: selectedEnd));
        sessions.add(
          HabitSessionModel(
            id: 'local-${habit.id}-${selectedStart.toIso8601String()}',
            habitId: habit.id,
            habitTitle: habit.title,
            startTime: selectedStart,
            endTime: selectedEnd,
            explanation:
                'Placed locally in an available preferred habit window.',
          ),
        );
        placed += 1;
      }
    }
    return sessions;
  }

  static DateTime _dateForBackendWeekday(DateTime weekStart, int backendDay) {
    final start = startOfWeek(weekStart);
    final sundayBasedOffset = (backendDay + 1) % 7;
    return DateTime(start.year, start.month, start.day)
        .add(Duration(days: sundayBasedOffset));
  }

  static DateTime _clockOnDay(DateTime day, String value) {
    final text = value.trim().toLowerCase().replaceAll('.', '');
    final match =
        RegExp(r'^(\d{1,2})(?::(\d{1,2}))?\s*(am|pm)?$').firstMatch(text);
    if (match == null) return DateTime(day.year, day.month, day.day, 8);
    var hour = int.tryParse(match.group(1) ?? '') ?? 8;
    final minute = int.tryParse(match.group(2) ?? '') ?? 0;
    final meridiem = match.group(3);
    if (meridiem == 'pm' && hour != 12) hour += 12;
    if (meridiem == 'am' && hour == 12) hour = 0;
    return DateTime(
      day.year,
      day.month,
      day.day,
      hour.clamp(0, 23).toInt(),
      minute.clamp(0, 59).toInt(),
    );
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

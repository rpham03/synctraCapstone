import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:synctra/data/models/event_model.dart';
import 'package:synctra/data/models/habit_model.dart';
import 'package:synctra/shared/services/habit_service.dart';
import 'package:synctra/shared/services/habit_session_store.dart';
import 'package:synctra/theme.dart';

class _UnavailableScheduleService extends HabitService {
  _UnavailableScheduleService(this.habits);

  final List<HabitModel> habits;

  @override
  Future<List<HabitModel>> listHabits() async => habits;

  @override
  Future<List<HabitSessionModel>> scheduleWeek({
    required List<EventModel> calendarEvents,
    DateTime? weekStart,
    int lookAheadDays = 7,
  }) async {
    throw StateError('schedule endpoint unavailable');
  }
}

class _EmptyScheduleService extends _UnavailableScheduleService {
  _EmptyScheduleService(super.habits);

  @override
  Future<List<HabitSessionModel>> scheduleWeek({
    required List<EventModel> calendarEvents,
    DateTime? weekStart,
    int lookAheadDays = 7,
  }) async =>
      [];
}

HabitModel _weekdayGym() => const HabitModel(
      id: 'gym',
      userId: 'user',
      title: 'Gym',
      durationMinutes: 30,
      frequencyPerWeek: 5,
      preferredDays: [0, 1, 2, 3, 4],
      preferredTimeRanges: {
        '0': [HabitTimeRange(start: '6:00pm', end: '8:00pm')],
        '1': [HabitTimeRange(start: '6:00pm', end: '8:00pm')],
        '2': [HabitTimeRange(start: '6:00pm', end: '8:00pm')],
        '3': [HabitTimeRange(start: '6:00pm', end: '8:00pm')],
        '4': [HabitTimeRange(start: '6:00pm', end: '8:00pm')],
      },
      priority: 9,
    );

void main() {
  setUp(() {
    SharedPreferences.setMockInitialValues({});
  });

  test('habit sessions remain visible when scheduling endpoint is unavailable',
      () async {
    final store = HabitSessionStore(
      service: _UnavailableScheduleService([_weekdayGym()]),
    );

    await store.refreshSchedule(
      calendarEvents: const [],
      weekStart: DateTime(2026, 6, 7),
    );

    expect(store.sessions, hasLength(5));
    expect(store.sessions.map((session) => session.startTime.weekday), {
      DateTime.monday,
      DateTime.tuesday,
      DateTime.wednesday,
      DateTime.thursday,
      DateTime.friday,
    });
  });

  test('empty backend schedule falls back to local habit placement', () async {
    final store = HabitSessionStore(
      service: _EmptyScheduleService([_weekdayGym()]),
    );

    await store.refreshSchedule(
      calendarEvents: const [],
      weekStart: DateTime(2026, 6, 7),
    );

    expect(store.sessions, hasLength(5));
  });

  test('manual calendar events use cyan instead of default light blue', () {
    expect(AppColors.manualCalendarEvent, const Color(0xFF0891B2));
    expect(AppColors.manualCalendarEvent, isNot(AppColors.fixedEvent));
  });
}

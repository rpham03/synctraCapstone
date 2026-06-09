import 'package:flutter/material.dart';

/// Work-style preset stored in Supabase `user_settings.schedule_type`.
enum ScheduleType {
  earlyBird('early_bird'),
  nightOwl('night_owl'),
  flexible('flexible');

  const ScheduleType(this.dbValue);
  final String dbValue;

  static ScheduleType fromDb(String? raw) {
    return ScheduleType.values.firstWhere(
      (t) => t.dbValue == raw,
      orElse: () => ScheduleType.flexible,
    );
  }

  String get label => switch (this) {
        ScheduleType.earlyBird => 'Early Bird',
        ScheduleType.nightOwl => 'Night Owl',
        ScheduleType.flexible => 'Flexible',
      };

  String get emoji => switch (this) {
        ScheduleType.earlyBird => '🌅',
        ScheduleType.nightOwl => '🦉',
        ScheduleType.flexible => '⚡',
      };

  String get subtitle => switch (this) {
        ScheduleType.earlyBird => 'Best before noon',
        ScheduleType.nightOwl => 'Hits stride after dark',
        ScheduleType.flexible => 'No strong preference',
      };
}

/// Preset working hours when the user picks a schedule type.
class SchedulePresets {
  static TimeOfDay workStart(ScheduleType type) => switch (type) {
        ScheduleType.earlyBird => const TimeOfDay(hour: 7, minute: 0),
        ScheduleType.nightOwl => const TimeOfDay(hour: 11, minute: 0),
        ScheduleType.flexible => const TimeOfDay(hour: 9, minute: 0),
      };

  static TimeOfDay workEnd(ScheduleType type) => switch (type) {
        ScheduleType.earlyBird => const TimeOfDay(hour: 20, minute: 0),
        ScheduleType.nightOwl => const TimeOfDay(hour: 2, minute: 0),
        ScheduleType.flexible => const TimeOfDay(hour: 22, minute: 0),
      };
}

/// Mirrors Supabase `user_settings` row.
class UserSettings {
  final String? id;
  final String userId;
  final ScheduleType scheduleType;
  final TimeOfDay workStartTime;
  final TimeOfDay workEndTime;
  final int preferredSessionMinutes;
  final int breakMinutes;
  final List<String> icalLinks;
  final List<String> courseUrls;
  final bool onboardingComplete;

  const UserSettings({
    this.id,
    required this.userId,
    this.scheduleType = ScheduleType.flexible,
    this.workStartTime = const TimeOfDay(hour: 9, minute: 0),
    this.workEndTime = const TimeOfDay(hour: 22, minute: 0),
    this.preferredSessionMinutes = 60,
    this.breakMinutes = 10,
    this.icalLinks = const [],
    this.courseUrls = const [],
    this.onboardingComplete = false,
  });

  factory UserSettings.defaults(String userId) => UserSettings(userId: userId);

  factory UserSettings.fromSupabase(Map<String, dynamic> row) {
    return UserSettings(
      id: row['id'] as String?,
      userId: row['user_id'] as String,
      scheduleType: ScheduleType.fromDb(row['schedule_type'] as String?),
      workStartTime: _parseTime(row['work_start_time']),
      workEndTime: _parseTime(row['work_end_time']),
      preferredSessionMinutes:
          (row['preferred_session_minutes'] as num?)?.toInt() ?? 60,
      breakMinutes: (row['break_minutes'] as num?)?.toInt() ?? 10,
      icalLinks: _stringList(row['ical_links']),
      courseUrls: _stringList(row['course_urls']),
      onboardingComplete: row['onboarding_complete'] as bool? ?? false,
    );
  }

  Map<String, dynamic> toSupabaseMap() => {
        if (id != null) 'id': id,
        'user_id': userId,
        'schedule_type': scheduleType.dbValue,
        'work_start_time': _formatTime(workStartTime),
        'work_end_time': _formatTime(workEndTime),
        'preferred_session_minutes': preferredSessionMinutes,
        'break_minutes': breakMinutes,
        'ical_links': icalLinks,
        'course_urls': courseUrls,
        'onboarding_complete': onboardingComplete,
      };

  UserSettings copyWith({
    String? id,
    String? userId,
    ScheduleType? scheduleType,
    TimeOfDay? workStartTime,
    TimeOfDay? workEndTime,
    int? preferredSessionMinutes,
    int? breakMinutes,
    List<String>? icalLinks,
    List<String>? courseUrls,
    bool? onboardingComplete,
  }) {
    return UserSettings(
      id: id ?? this.id,
      userId: userId ?? this.userId,
      scheduleType: scheduleType ?? this.scheduleType,
      workStartTime: workStartTime ?? this.workStartTime,
      workEndTime: workEndTime ?? this.workEndTime,
      preferredSessionMinutes:
          preferredSessionMinutes ?? this.preferredSessionMinutes,
      breakMinutes: breakMinutes ?? this.breakMinutes,
      icalLinks: icalLinks ?? this.icalLinks,
      courseUrls: courseUrls ?? this.courseUrls,
      onboardingComplete: onboardingComplete ?? this.onboardingComplete,
    );
  }

  /// Converts to scheduling algorithm input.
  UserWorkPreferences get workPreferences => UserWorkPreferences(
        scheduleType: scheduleType,
        workStartMinutes: _minutes(workStartTime),
        workEndMinutes: _minutes(workEndTime),
        preferredSessionMinutes: preferredSessionMinutes,
        breakMinutes: breakMinutes,
      );

  static List<String> _stringList(dynamic raw) {
    if (raw is List) {
      return raw.map((e) => e.toString()).where((s) => s.isNotEmpty).toList();
    }
    return const [];
  }

  static TimeOfDay _parseTime(dynamic raw) {
    if (raw is String) {
      final parts = raw.split(':');
      if (parts.length >= 2) {
        final h = int.tryParse(parts[0]) ?? 9;
        final m = int.tryParse(parts[1]) ?? 0;
        return TimeOfDay(hour: h, minute: m);
      }
    }
    return const TimeOfDay(hour: 9, minute: 0);
  }

  static String _formatTime(TimeOfDay t) =>
      '${t.hour.toString().padLeft(2, '0')}:${t.minute.toString().padLeft(2, '0')}';

  static int _minutes(TimeOfDay t) => t.hour * 60 + t.minute;

  bool get crossesMidnight => _minutes(workEndTime) <= _minutes(workStartTime);

  bool isValidWorkRange() {
    if (crossesMidnight) return true;
    return _minutes(workStartTime) < _minutes(workEndTime);
  }
}

/// Scheduling algorithm contract — read from [UserSettings].
class UserWorkPreferences {
  final ScheduleType scheduleType;
  final int workStartMinutes;
  final int workEndMinutes;
  final int preferredSessionMinutes;
  final int breakMinutes;

  const UserWorkPreferences({
    required this.scheduleType,
    required this.workStartMinutes,
    required this.workEndMinutes,
    this.preferredSessionMinutes = 60,
    this.breakMinutes = 10,
  });

  bool get crossesMidnight => workEndMinutes <= workStartMinutes;

  bool isMinuteWithinWorkWindow(int minuteOfDay) {
    if (crossesMidnight) {
      return minuteOfDay >= workStartMinutes || minuteOfDay <= workEndMinutes;
    }
    return minuteOfDay >= workStartMinutes && minuteOfDay <= workEndMinutes;
  }

  int minuteOfDay(DateTime dt) => dt.hour * 60 + dt.minute;

  /// Latest [DateTime] work may end on the calendar day of [day].
  DateTime workEndCapOnDay(DateTime day) {
    final d = DateTime(day.year, day.month, day.day);
    if (crossesMidnight) {
      if (workEndMinutes <= workStartMinutes) {
        return d.add(Duration(minutes: workEndMinutes));
      }
    }
    return d.add(Duration(minutes: workEndMinutes));
  }

  /// Earliest [DateTime] work may start on the calendar day of [day].
  DateTime workStartFloorOnDay(DateTime day) {
    final d = DateTime(day.year, day.month, day.day);
    return d.add(Duration(minutes: workStartMinutes));
  }
}

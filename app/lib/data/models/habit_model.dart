/// Reclaim-style habit definitions and scheduled sessions.
class HabitTimeRange {
  final String start;
  final String end;

  const HabitTimeRange({required this.start, required this.end});

  Map<String, dynamic> toJson() => {'start': start, 'end': end};

  factory HabitTimeRange.fromJson(Map<String, dynamic> json) => HabitTimeRange(
        start: json['start'] as String? ?? '9:00am',
        end: json['end'] as String? ?? '5:00pm',
      );

  HabitTimeRange copyWith({String? start, String? end}) => HabitTimeRange(
        start: start ?? this.start,
        end: end ?? this.end,
      );
}

class HabitModel {
  final String id;
  final String userId;
  final String title;
  final int durationMinutes;
  final int durationMaxMinutes;
  final int frequencyPerWeek;
  final List<int> preferredDays;
  final Map<String, List<HabitTimeRange>> preferredTimeRanges;
  final int priority;
  final bool isActive;

  const HabitModel({
    required this.id,
    required this.userId,
    required this.title,
    required this.durationMinutes,
    this.durationMaxMinutes = 0,
    required this.frequencyPerWeek,
    required this.preferredDays,
    required this.preferredTimeRanges,
    required this.priority,
    this.isActive = true,
  });

  /// Backend uses 0=Monday … 6=Sunday (Python weekday).
  static int dartWeekdayToBackend(int dartWeekday) => dartWeekday - 1;

  static int backendWeekdayToDart(int backendDay) => backendDay + 1;

  static const dayLabels = ['Mo', 'Tu', 'We', 'Th', 'Fr', 'Sa', 'Su'];

  static String dayLabel(int backendDay) {
    final dart = backendWeekdayToDart(backendDay);
    if (dart < 1 || dart > 7) return '?';
    return dayLabels[dart - 1];
  }

  HabitModel copyWith({
    String? id,
    String? userId,
    String? title,
    int? durationMinutes,
    int? durationMaxMinutes,
    int? frequencyPerWeek,
    List<int>? preferredDays,
    Map<String, List<HabitTimeRange>>? preferredTimeRanges,
    int? priority,
    bool? isActive,
  }) =>
      HabitModel(
        id: id ?? this.id,
        userId: userId ?? this.userId,
        title: title ?? this.title,
        durationMinutes: durationMinutes ?? this.durationMinutes,
        durationMaxMinutes: durationMaxMinutes ?? this.durationMaxMinutes,
        frequencyPerWeek: frequencyPerWeek ?? this.frequencyPerWeek,
        preferredDays: preferredDays ?? this.preferredDays,
        preferredTimeRanges:
            preferredTimeRanges ?? this.preferredTimeRanges,
        priority: priority ?? this.priority,
        isActive: isActive ?? this.isActive,
      );

  Map<String, dynamic> toCreateJson() => {
        'title': title,
        'duration_minutes': durationMinutes,
        'duration_max_minutes': durationMaxMinutes >= durationMinutes
            ? durationMaxMinutes
            : durationMinutes,
        'frequency_per_week': frequencyPerWeek,
        'preferred_days': preferredDays,
        'preferred_time_ranges': {
          for (final entry in preferredTimeRanges.entries)
            entry.key: [for (final r in entry.value) r.toJson()],
        },
        'priority': priority,
        'is_active': isActive,
      };

  factory HabitModel.fromJson(Map<String, dynamic> json) {
    final rangesRaw = json['preferred_time_ranges'];
    final ranges = <String, List<HabitTimeRange>>{};
    if (rangesRaw is Map) {
      for (final entry in rangesRaw.entries) {
        final list = entry.value;
        if (list is List) {
          ranges[entry.key.toString()] = list
              .whereType<Map>()
              .map((m) => HabitTimeRange.fromJson(Map<String, dynamic>.from(m)))
              .toList();
        }
      }
    }
    final dur = json['duration_minutes'] as int? ?? 30;
    final durMax = json['duration_max_minutes'] as int? ?? dur;
    return HabitModel(
      id: json['id'] as String? ?? '',
      userId: json['user_id'] as String? ?? '',
      title: json['title'] as String? ?? 'Habit',
      durationMinutes: dur,
      durationMaxMinutes: durMax >= dur ? durMax : dur,
      frequencyPerWeek: json['frequency_per_week'] as int? ?? 1,
      preferredDays: (json['preferred_days'] as List<dynamic>? ?? [])
          .map((d) => d as int)
          .toList(),
      preferredTimeRanges: ranges,
      priority: json['priority'] as int? ?? 5,
      isActive: json['is_active'] as bool? ?? true,
    );
  }
}

class HabitSessionModel {
  final String id;
  final String habitId;
  final String habitTitle;
  final DateTime startTime;
  final DateTime endTime;
  final String explanation;
  final double score;

  const HabitSessionModel({
    required this.id,
    required this.habitId,
    required this.habitTitle,
    required this.startTime,
    required this.endTime,
    this.explanation = '',
    this.score = 0,
  });

  HabitSessionModel copyWith({
    String? id,
    String? habitId,
    String? habitTitle,
    DateTime? startTime,
    DateTime? endTime,
    String? explanation,
    double? score,
  }) =>
      HabitSessionModel(
        id: id ?? this.id,
        habitId: habitId ?? this.habitId,
        habitTitle: habitTitle ?? this.habitTitle,
        startTime: startTime ?? this.startTime,
        endTime: endTime ?? this.endTime,
        explanation: explanation ?? this.explanation,
        score: score ?? this.score,
      );

  Map<String, dynamic> toJson() => {
        'id': id,
        'habit_id': habitId,
        'habit_title': habitTitle,
        'start_time': startTime.toIso8601String(),
        'end_time': endTime.toIso8601String(),
        'explanation': explanation,
        'score': score,
      };

  Map<String, dynamic> toRescheduleJson() => {
        'id': id,
        'habit_id': habitId,
        'habit_title': habitTitle,
        'start_time': startTime.toIso8601String(),
        'end_time': endTime.toIso8601String(),
        'explanation': explanation,
      };

  factory HabitSessionModel.fromJson(Map<String, dynamic> json) =>
      HabitSessionModel(
        id: json['id'] as String? ?? '',
        habitId: json['habit_id'] as String? ?? '',
        habitTitle: json['habit_title'] as String? ?? 'Habit',
        startTime: DateTime.parse(json['start_time'] as String),
        endTime: DateTime.parse(json['end_time'] as String),
        explanation: json['explanation'] as String? ?? '',
        score: (json['score'] as num?)?.toDouble() ?? 0,
      );
}

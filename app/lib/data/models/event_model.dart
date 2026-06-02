// Represents a fixed calendar event (class, meeting, exam, or course assignment).
class EventModel {
  final String id;
  final String title;
  final DateTime startTime;
  final DateTime endTime;
  // 'google_calendar' | 'canvas' | 'manual' | 'ical' | 'course'
  final String source;
  final bool isFixed;
  final String? sourceEventId;

  /// Optional notes (manual entry, or cached from feed).
  final String description;

  const EventModel({
    required this.id,
    required this.title,
    required this.startTime,
    required this.endTime,
    required this.source,
    this.isFixed = true,
    this.sourceEventId,
    this.description = '',
  });

  static String _normalizeTitle(String title) =>
      title.replaceAll(RegExp(r'(?:\s+[—–\-]){2,}\s+'), ' — ').trim();

  bool get isDateOnlyCourseEvent =>
      source == 'course' &&
      ((sourceEventId?.contains('assignment_date_only') ?? false) ||
          (_startsAtMidnight &&
              (sourceEventId?.contains('class_date_only') ?? false)) ||
          (_startsAtMidnight && !endTime.isAfter(startTime)) ||
          _isShortMidnightClassEvent);

  bool get isCourseAssignment =>
      source == 'course' && (sourceEventId?.contains('assignment') ?? false);

  bool get isManualTask => source == 'manual_task';

  /// Due-date chip on the calendar (not a timed block).
  bool get isDueDateChip =>
      isManualTask || isCourseAssignment || source == 'canvas';

  int? get estimatedMinutes {
    final match = RegExp(r'^Estimated time:\s*([^\n]+)', multiLine: true)
        .firstMatch(description);
    if (match == null) return null;
    final raw = match.group(1)?.toLowerCase().trim() ?? '';
    var total = 0;
    final hours = RegExp(r'(\d+)\s*h').firstMatch(raw);
    final minutes = RegExp(r'(\d+)\s*m').firstMatch(raw);
    if (hours != null) total += (int.tryParse(hours.group(1) ?? '') ?? 0) * 60;
    if (minutes != null) total += int.tryParse(minutes.group(1) ?? '') ?? 0;
    if (total == 0) total = int.tryParse(raw) ?? 0;
    if (total <= 0) return null;
    return total.clamp(1, 9999).toInt();
  }

  bool get _startsAtMidnight => startTime.hour == 0 && startTime.minute == 0;

  bool get _isShortMidnightClassEvent {
    if (!_startsAtMidnight) return false;
    final durationMinutes = endTime.difference(startTime).inMinutes;
    if (durationMinutes < 0 || durationMinutes > 60) return false;
    return RegExp(
      r'^(lecture|section|lab|discussion)\b',
      caseSensitive: false,
    ).hasMatch(title.trim());
  }

  // From backend scraper JSON response
  factory EventModel.fromJson(Map<String, dynamic> json) => EventModel(
        id: json['id'] as String? ?? '',
        title: _normalizeTitle(json['title'] as String? ?? ''),
        startTime: DateTime.parse(json['start_time'] as String),
        endTime: DateTime.parse(json['end_time'] as String),
        source: json['source'] as String? ?? 'manual',
        isFixed: json['is_fixed'] as bool? ?? true,
        sourceEventId: json['source_event_id'] as String?,
        description: json['description'] as String? ?? '',
      );

  factory EventModel.fromSupabase(Map<String, dynamic> row) => EventModel(
        id: row['id'] as String,
        title: _normalizeTitle(row['title'] as String? ?? ''),
        startTime: DateTime.parse(row['start_time'] as String),
        endTime: DateTime.parse(row['end_time'] as String),
        source: row['source'] as String? ?? 'course',
        isFixed: row['is_fixed'] as bool? ?? true,
        sourceEventId: row['source_event_id'] as String?,
        description: row['description'] as String? ?? '',
      );

  EventModel copyWith({
    String? id,
    String? title,
    DateTime? startTime,
    DateTime? endTime,
    String? source,
    bool? isFixed,
    String? sourceEventId,
    String? description,
  }) =>
      EventModel(
        id: id ?? this.id,
        title: title ?? this.title,
        startTime: startTime ?? this.startTime,
        endTime: endTime ?? this.endTime,
        source: source ?? this.source,
        isFixed: isFixed ?? this.isFixed,
        sourceEventId: sourceEventId ?? this.sourceEventId,
        description: description ?? this.description,
      );

  // For upserting into Supabase events table
  Map<String, dynamic> toSupabaseMap({
    required String userId,
    required String importId,
    required String sourceEventId,
  }) =>
      {
        'user_id': userId,
        'title': title,
        'description': description,
        'start_time': startTime.toUtc().toIso8601String(),
        'end_time': endTime.toUtc().toIso8601String(),
        'source': 'course',
        'source_event_id': sourceEventId,
        'course_import_id': importId,
        'is_fixed': true,
      };
}

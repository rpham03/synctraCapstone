// Represents a fixed calendar event (class, meeting, exam, or course assignment).
class EventModel {
  final String id;
  final String title;
  final DateTime startTime;
  final DateTime endTime;
  // 'google_calendar' | 'canvas' | 'manual' | 'ical' | 'course'
  final String source;
  final bool isFixed;
  /// Optional notes (manual entry, or cached from feed).
  final String description;

  const EventModel({
    required this.id,
    required this.title,
    required this.startTime,
    required this.endTime,
    required this.source,
    this.isFixed = true,
    this.description = '',
  });

  bool get isDateOnlyCourseEvent =>
      source == 'course' && (sourceEventId?.contains('_date_only_') ?? false);

  // From backend scraper JSON response
  factory EventModel.fromJson(Map<String, dynamic> json) => EventModel(
        id: json['id'],
        title: json['title'],
        startTime: DateTime.parse(json['start_time']),
        endTime: DateTime.parse(json['end_time']),
        source: json['source'],
        isFixed: json['is_fixed'] ?? true,
        description: json['description'] as String? ?? '',
      );

  EventModel copyWith({
    String? id,
    String? title,
    DateTime? startTime,
    DateTime? endTime,
    String? source,
    bool? isFixed,
    String? description,
  }) =>
      EventModel(
        id: id ?? this.id,
        title: title ?? this.title,
        startTime: startTime ?? this.startTime,
        endTime: endTime ?? this.endTime,
        source: source ?? this.source,
        isFixed: isFixed ?? this.isFixed,
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

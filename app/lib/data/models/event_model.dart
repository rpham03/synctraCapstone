// Represents a fixed calendar event (class, meeting, exam, or course assignment).
class EventModel {
  final String id;
  final String title;
  final DateTime startTime;
  final DateTime endTime;
  final String source; // 'google_calendar' | 'canvas' | 'manual' | 'ical' | 'course'
  final bool isFixed;
  final String? description;

  const EventModel({
    required this.id,
    required this.title,
    required this.startTime,
    required this.endTime,
    required this.source,
    this.isFixed = true,
    this.description,
  });

  // From backend scraper JSON response
  factory EventModel.fromJson(Map<String, dynamic> json) => EventModel(
        id: json['id'] as String? ?? '',
        title: json['title'] as String,
        startTime: DateTime.parse(json['start_time'] as String),
        endTime: DateTime.parse(json['end_time'] as String),
        source: json['source'] as String? ?? 'manual',
        isFixed: json['is_fixed'] as bool? ?? true,
        description: json['description'] as String?,
      );

  // From Supabase row
  factory EventModel.fromSupabase(Map<String, dynamic> row) => EventModel(
        id: row['id'] as String,
        title: row['title'] as String,
        startTime: DateTime.parse(row['start_time'] as String),
        endTime: DateTime.parse(row['end_time'] as String),
        source: row['source'] as String,
        isFixed: row['is_fixed'] as bool? ?? true,
        description: row['description'] as String?,
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

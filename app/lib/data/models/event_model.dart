// Represents a fixed calendar event (class, meeting, exam)
class EventModel {
  final String id;
  final String title;
  final DateTime startTime;
  final DateTime endTime;
  final String source; // 'google_calendar' | 'canvas' | 'manual'
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
}

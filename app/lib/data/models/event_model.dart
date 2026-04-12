// Represents a fixed calendar event (class, meeting, exam)
class EventModel {
  final String id;
  final String title;
  final DateTime startTime;
  final DateTime endTime;
  final String source; // 'google_calendar' | 'canvas' | 'manual'
  final bool isFixed;

  const EventModel({
    required this.id,
    required this.title,
    required this.startTime,
    required this.endTime,
    required this.source,
    this.isFixed = true,
  });

  factory EventModel.fromJson(Map<String, dynamic> json) => EventModel(
        id: json['id'],
        title: json['title'],
        startTime: DateTime.parse(json['start_time']),
        endTime: DateTime.parse(json['end_time']),
        source: json['source'],
        isFixed: json['is_fixed'] ?? true,
      );
}

// Represents a flexible task (homework, studying, project work)
class TaskModel {
  final String id;
  final String title;
  final DateTime dueDate;
  final int estimatedMinutes;
  final String? courseId;
  final String source; // 'canvas' | 'manual'
  final bool isCompleted;

  const TaskModel({
    required this.id,
    required this.title,
    required this.dueDate,
    required this.estimatedMinutes,
    this.courseId,
    required this.source,
    this.isCompleted = false,
  });

  factory TaskModel.fromJson(Map<String, dynamic> json) => TaskModel(
        id: json['id'],
        title: json['title'],
        dueDate: DateTime.parse(json['due_date']),
        estimatedMinutes: json['estimated_minutes'],
        courseId: json['course_id'],
        source: json['source'],
        isCompleted: json['is_completed'] ?? false,
      );
}

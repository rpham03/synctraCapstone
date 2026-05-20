// Represents a flexible task (homework, studying, project work)
class TaskModel {
  final String id;
  final String title;
  final DateTime dueDate;
  final int estimatedMinutes;
  final String? courseId;
  final String source; // 'canvas' | 'manual'
  final bool isCompleted;
  final String description;

  const TaskModel({
    required this.id,
    required this.title,
    required this.dueDate,
    required this.estimatedMinutes,
    this.courseId,
    required this.source,
    this.isCompleted = false,
    this.description = '',
  });

  factory TaskModel.fromJson(Map<String, dynamic> json) => TaskModel(
        id: json['id'],
        title: json['title'],
        dueDate: DateTime.parse(json['due_date']),
        estimatedMinutes: json['estimated_minutes'],
        courseId: json['course_id'],
        source: json['source'],
        isCompleted: json['is_completed'] ?? false,
        description: json['description'] as String? ?? '',
      );

  Map<String, dynamic> toJson() => {
        'id': id,
        'title': title,
        'due_date': dueDate.toIso8601String(),
        'estimated_minutes': estimatedMinutes,
        'course_id': courseId,
        'source': source,
        'is_completed': isCompleted,
        'description': description,
      };

  TaskModel copyWith({
    String? id,
    String? title,
    DateTime? dueDate,
    int? estimatedMinutes,
    String? courseId,
    String? source,
    bool? isCompleted,
    String? description,
  }) =>
      TaskModel(
        id: id ?? this.id,
        title: title ?? this.title,
        dueDate: dueDate ?? this.dueDate,
        estimatedMinutes: estimatedMinutes ?? this.estimatedMinutes,
        courseId: courseId ?? this.courseId,
        source: source ?? this.source,
        isCompleted: isCompleted ?? this.isCompleted,
        description: description ?? this.description,
      );
}

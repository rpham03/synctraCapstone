// Represents a flexible task (homework, studying, project work)
class TaskModel {
  final String id;
  final String title;
  final DateTime dueDate;
  final int estimatedMinutes;
  final String? courseId;
  final String? courseName;
  final String source; // 'canvas' | 'manual' | 'course'
  final bool isCompleted;
  final String description;

  /// Canvas course label (e.g. CSE 331), when known.
  String? get courseLabel {
    final n = courseName?.trim();
    return (n != null && n.isNotEmpty) ? n : null;
  }

  /// True when the due date is today or later (local calendar day).
  bool get isDueTodayOrLater {
    final now = DateTime.now();
    final today = DateTime(now.year, now.month, now.day);
    final due = DateTime(dueDate.year, dueDate.month, dueDate.day);
    return !due.isBefore(today);
  }

  const TaskModel({
    required this.id,
    required this.title,
    required this.dueDate,
    required this.estimatedMinutes,
    this.courseId,
    this.courseName,
    required this.source,
    this.isCompleted = false,
    this.description = '',
  });

  factory TaskModel.fromJson(Map<String, dynamic> json) => TaskModel(
        id: json['id'],
        title: json['title'],
        dueDate: DateTime.parse(json['due_date']),
        estimatedMinutes: json['estimated_minutes'] ?? 180,
        courseId: json['course_id'],
        courseName: json['course_name'] as String?,
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
        if (courseName != null) 'course_name': courseName,
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
    String? courseName,
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
        courseName: courseName ?? this.courseName,
        source: source ?? this.source,
        isCompleted: isCompleted ?? this.isCompleted,
        description: description ?? this.description,
      );
}

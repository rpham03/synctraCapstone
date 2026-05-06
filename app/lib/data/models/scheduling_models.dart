// Structured types for Synctra scheduling ↔ LLM boundary (JSON-serializable where noted).
// Algorithm consumes these; LLM never mutates calendar structures directly.

/// Fixed calendar event (class, meeting, exam). Cannot be moved by the packer.
class FixedEvent {
  final String id;
  final String title;
  final DateTime startTime;
  final DateTime endTime;
  final bool isRecurring;

  const FixedEvent({
    required this.id,
    required this.title,
    required this.startTime,
    required this.endTime,
    this.isRecurring = false,
  });

  Map<String, dynamic> toJson() => {
        'id': id,
        'title': title,
        'startTime': startTime.toIso8601String(),
        'endTime': endTime.toIso8601String(),
        'isRecurring': isRecurring,
      };
}

/// LLM-suggested session slice (duration only; algorithm places it).
class TaskSession {
  final Duration duration;

  const TaskSession({required this.duration});

  Map<String, dynamic> toJson() => {'durationMinutes': duration.inMinutes};

  factory TaskSession.fromJson(Map<String, dynamic> json) {
    final m = json['durationMinutes'] ?? json['duration'];
    final minutes = m is int ? m : (m as num?)?.toInt() ?? 60;
    return TaskSession(duration: Duration(minutes: minutes.clamp(1, 24 * 60)));
  }
}

/// Flexible work the algorithm packs around fixed events.
class FlexibleTask {
  final String id;
  final String title;
  final DateTime dueDate;
  final Duration estimatedDuration;
  final int priority;
  final bool urgencyFlag;

  /// When non-empty, each entry is scheduled as its own unit (same due date).
  /// When empty, [estimatedDuration] is used as a single unit.
  final List<TaskSession> sessions;

  /// When true, free windows before noon are tried first (soft preference).
  final bool preferMorning;

  const FlexibleTask({
    required this.id,
    required this.title,
    required this.dueDate,
    required this.estimatedDuration,
    this.priority = 0,
    this.urgencyFlag = false,
    this.sessions = const [],
    this.preferMorning = false,
  });

  /// Sort key: sooner due, then higher priority, then urgency.
  int compareToOthers(FlexibleTask o) {
    final c = dueDate.compareTo(o.dueDate);
    if (c != 0) return c;
    final p = o.priority.compareTo(priority);
    if (p != 0) return p;
    return (o.urgencyFlag ? 1 : 0).compareTo(urgencyFlag ? 1 : 0);
  }

  Map<String, dynamic> toJson() => {
        'id': id,
        'title': title,
        'dueDate': dueDate.toIso8601String(),
        'estimatedDurationMinutes': estimatedDuration.inMinutes,
        'priority': priority,
        'urgencyFlag': urgencyFlag,
        'sessions': sessions.map((s) => s.toJson()).toList(),
        'preferMorning': preferMorning,
      };
}

/// One placed work interval for a flexible task.
class ScheduledBlock {
  final String taskId;
  final DateTime startTime;
  final DateTime endTime;

  const ScheduledBlock({
    required this.taskId,
    required this.startTime,
    required this.endTime,
  });

  Duration get duration => endTime.difference(startTime);

  Map<String, dynamic> toJson() => {
        'taskId': taskId,
        'startTime': startTime.toIso8601String(),
        'endTime': endTime.toIso8601String(),
      };
}

/// Parsed chat intent (Job 4). Algorithm validates and executes.
class SchedulingIntent {
  final String action;
  final String? taskName;
  final String? targetDay;
  final String? timePreference;
  final double? durationHours;

  const SchedulingIntent({
    required this.action,
    this.taskName,
    this.targetDay,
    this.timePreference,
    this.durationHours,
  });

  Map<String, dynamic> toJson() => {
        'action': action,
        'taskName': taskName,
        'targetDay': targetDay,
        'timePreference': timePreference,
        'durationHours': durationHours,
      };

  factory SchedulingIntent.fromJson(Map<String, dynamic> json) {
    return SchedulingIntent(
      action: json['action'] as String? ?? 'query',
      taskName: json['taskName'] as String? ?? json['task'] as String?,
      targetDay: json['targetDay'] as String? ?? json['target_day'] as String?,
      timePreference:
          json['timePreference'] as String? ?? json['time_preference'] as String?,
      durationHours: (json['durationHours'] ?? json['duration_hours']) is num
          ? ((json['durationHours'] ?? json['duration_hours']) as num).toDouble()
          : null,
    );
  }
}

/// Result of an algorithm-side change or query (fed back to LLM for Job 5).
class SchedulingResult {
  final bool success;
  final ScheduledBlock? block;
  final ScheduledBlock? alternativeBlock;
  final String? reason;
  final List<ScheduledBlock>? weekBlocks;

  const SchedulingResult({
    required this.success,
    this.block,
    this.alternativeBlock,
    this.reason,
    this.weekBlocks,
  });

  Map<String, dynamic> toJson() => {
        'success': success,
        'block': block?.toJson(),
        'alternativeBlock': alternativeBlock?.toJson(),
        'reason': reason,
        'weekBlocks': weekBlocks?.map((b) => b.toJson()).toList(),
      };
}

/// Soft constraint from LLM (Job 4 → algorithm).
class UserConstraint {
  final String constraintType;
  final String time;
  final String scope;

  const UserConstraint({
    required this.constraintType,
    required this.time,
    required this.scope,
  });

  Map<String, dynamic> toJson() => {
        'constraintType': constraintType,
        'time': time,
        'scope': scope,
      };

  factory UserConstraint.fromJson(Map<String, dynamic> json) => UserConstraint(
        constraintType: json['constraintType'] as String? ??
            json['constraint_type'] as String? ??
            'avoid_after',
        time: json['time'] as String? ?? '21:00',
        scope: json['scope'] as String? ?? 'today',
      );
}

/// LLM enrichment for one task (Jobs 1–3). Must pass [SchedulingService.validateEnrichedTask].
class LLMEnrichedTask {
  final String taskId;
  final double estimatedDurationHours;
  final String priority;
  final bool urgencyFlag;
  final List<TaskSession> sessions;

  const LLMEnrichedTask({
    required this.taskId,
    required this.estimatedDurationHours,
    this.priority = 'medium',
    this.urgencyFlag = false,
    this.sessions = const [],
  });

  Map<String, dynamic> toJson() => {
        'taskId': taskId,
        'estimatedDuration': estimatedDurationHours,
        'priority': priority,
        'urgencyFlag': urgencyFlag,
        'sessions': sessions.map((s) => s.toJson()).toList(),
      };

  factory LLMEnrichedTask.fromJson(Map<String, dynamic> json) {
    final raw = json['estimatedDuration'] ?? json['estimated_duration'];
    final hours = raw is num ? raw.toDouble() : double.tryParse('$raw') ?? 1.0;
    final sess = (json['sessions'] as List?) ?? const [];
    return LLMEnrichedTask(
      taskId: json['taskId'] as String? ?? json['task_id'] as String? ?? '',
      estimatedDurationHours: hours,
      priority: json['priority'] as String? ?? 'medium',
      urgencyFlag: json['urgencyFlag'] as bool? ?? json['urgency_flag'] as bool? ?? false,
      sessions: sess
          .map((e) => TaskSession.fromJson(e as Map<String, dynamic>))
          .toList(),
    );
  }
}

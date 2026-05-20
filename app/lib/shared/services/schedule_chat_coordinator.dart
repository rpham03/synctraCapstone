// Facade: user message → LLM parse → [SchedulingService] → LLM natural reply.
// Does not let the LLM write calendar models directly.

import 'package:get_it/get_it.dart';

import '../../data/models/schedule_block_model.dart';
import 'llm_service.dart';
import 'scheduling_service.dart';
import 'suggested_schedule_store.dart';

/// Monday 00:00 local of the ISO week containing [d].
DateTime _startOfIsoWeek(DateTime d) {
  final local = DateTime(d.year, d.month, d.day);
  return local.subtract(Duration(days: local.weekday - DateTime.monday));
}

class ScheduleChatCoordinator {
  ScheduleChatCoordinator({
    required LlmService llm,
    required SchedulingService scheduling,
    required SuggestedScheduleStore store,
  })  : _llm = llm,
        _scheduling = scheduling,
        _store = store;

  final LlmService _llm;
  final SchedulingService _scheduling;
  final SuggestedScheduleStore _store;

  factory ScheduleChatCoordinator.fromGetIt() {
    final g = GetIt.instance;
    return ScheduleChatCoordinator(
      llm: g<LlmService>(),
      scheduling: const SchedulingService(),
      store: g<SuggestedScheduleStore>(),
    );
  }

  /// End-to-end chat turn: deterministic scheduling + stub LLM reply.
  Future<String> handleUserMessage(String userMessage) async {
    final intent = _llm.parseSchedulingIntent(userMessage);
    final now = DateTime.now();
    final weekStart = _startOfIsoWeek(now);
    final weekEnd = weekStart.add(const Duration(days: 7));

    final fixed = _store.fixedEventsForScheduling();

    final constraints = <UserConstraint>[];
    final t = userMessage.toLowerCase();
    if (t.contains('after 9') || t.contains('after nine') || t.contains('before 9')) {
      constraints.add(const UserConstraint(
        constraintType: 'avoid_after',
        time: '21:00',
        scope: 'weekdays',
      ));
    }

    switch (intent.action) {
      case 'query':
        final result = _runQuery(intent, weekStart, weekEnd, fixed);
        return _llm.generateSchedulingReply(
          userMessage: userMessage,
          intent: intent,
          result: result,
        );
      case 'add':
      case 'move':
      default:
        return _handleScheduleChange(
          userMessage: userMessage,
          intent: intent,
          weekStart: weekStart,
          weekEnd: weekEnd,
          fixed: fixed,
          constraints: constraints,
          now: now,
        );
    }
  }

  /// Pack study time before a Canvas due (or similar) using the same engine as chat.
  String scheduleStudyForDueItem({
    required String taskId,
    required String title,
    required DateTime dueDate,
    double hours = 1.5,
    bool preferMorning = false,
  }) {
    final now = DateTime.now();
    final weekStart = _startOfIsoWeek(now);
    final weekEnd = weekStart.add(const Duration(days: 7));
    final fixed = _store.fixedEventsForScheduling();
    const constraints = <UserConstraint>[];

    final enriched = _llm.enrichTaskStub(
      taskId: taskId,
      title: title,
      hours: hours,
      priority: 'medium',
      urgency: false,
    );
    final err = SchedulingService.validateEnrichedTask(enriched);
    if (err != null) {
      return 'Could not schedule: $err';
    }

    final task = SchedulingService.flexibleFromLlm(
      enriched,
      title: title,
      dueDate: dueDate,
      preferMorning: preferMorning,
    );

    final byId = <String, List<ScheduleBlockModel>>{};
    for (final b in _store.blocks) {
      byId.putIfAbsent(b.taskId, () => []).add(b);
    }
    final existingFlexible = <FlexibleTask>[
      for (final e in byId.entries)
        FlexibleTask(
          id: e.key,
          title: e.value.first.taskTitle,
          dueDate: weekEnd.subtract(const Duration(seconds: 1)),
          estimatedDuration: e.value.fold<Duration>(
            Duration.zero,
            (s, b) => s + b.endTime.difference(b.startTime),
          ),
          priority: 0,
        ),
    ];

    final allTasks = [...existingFlexible, task];
    const config = SchedulingConfig(
      bufferAroundFixedEvents: Duration(minutes: 15),
      minimumBlockSize: Duration(minutes: 30),
    );

    final result = _scheduling.scheduleWithNearestAlternative(
      weekStart: weekStart,
      weekEnd: weekEnd,
      fixedEvents: fixed,
      flexibleTasks: allTasks,
      task: task,
      config: config,
      userConstraints: constraints,
      constraintClock: now,
    );

    final newBlocks = result.weekBlocks ?? const [];
    if (newBlocks.isNotEmpty) {
      final titles = <String, String>{
        for (final b in _store.blocks) b.taskId: b.taskTitle,
        task.id: title,
      };
      for (final s in newBlocks) {
        titles.putIfAbsent(s.taskId, () => s.taskId);
      }
      _store.applySynctraPreview(
        scheduled: [...newBlocks],
        taskTitles: titles,
        fixed: fixed,
      );
    }

    final intent = SchedulingIntent(
      action: 'add',
      taskName: title,
      durationHours: hours,
    );
    return _llm.generateSchedulingReply(
      userMessage: 'Schedule study for $title',
      intent: intent,
      result: result,
    );
  }

  SchedulingResult _runQuery(
    SchedulingIntent intent,
    DateTime weekStart,
    DateTime weekEnd,
    List<FixedEvent> fixed,
  ) {
    final blocks = _store.blocks;
    if (blocks.isEmpty && fixed.isEmpty) {
      return const SchedulingResult(
        success: true,
        reason: 'No preview blocks yet. Open Suggest Schedule to build a week, or add tasks there.',
      );
    }
    final relevant = <ScheduleBlockModel>[];
    for (final b in blocks) {
      if (!b.startTime.isBefore(weekEnd) || !b.endTime.isAfter(weekStart)) continue;
      if (intent.targetDay == 'tomorrow') {
        final tomorrow = DateTime.now().add(const Duration(days: 1));
        final d0 = DateTime(tomorrow.year, tomorrow.month, tomorrow.day);
        final d1 = d0.add(const Duration(days: 1));
        if (b.startTime.isBefore(d1) && b.endTime.isAfter(d0)) relevant.add(b);
      } else {
        relevant.add(b);
      }
    }
    final weekBlocks = [
      for (final b in relevant)
        ScheduledBlock(
          taskId: b.taskId,
          startTime: b.startTime,
          endTime: b.endTime,
        ),
    ];
    return SchedulingResult(
      success: true,
      weekBlocks: weekBlocks,
      reason: weekBlocks.isEmpty
          ? 'Nothing on the calendar for that window yet.'
          : 'Here are the Synctra blocks in that range.',
    );
  }

  String _handleScheduleChange({
    required String userMessage,
    required SchedulingIntent intent,
    required DateTime weekStart,
    required DateTime weekEnd,
    required List<FixedEvent> fixed,
    required List<UserConstraint> constraints,
    required DateTime now,
  }) {
    final title = intent.taskName ?? 'Study block';
    final due = _dueForTarget(intent.targetDay, weekStart, weekEnd, now);
    final hours = intent.durationHours ?? 1.5;
    final preferMorning = (intent.timePreference ?? '').toLowerCase() == 'morning';

    final enriched = _llm.enrichTaskStub(
      taskId: 'chat-${now.millisecondsSinceEpoch}',
      title: title,
      hours: hours,
      priority: 'medium',
      urgency: false,
    );
    final err = SchedulingService.validateEnrichedTask(enriched);
    if (err != null) {
      return 'I could not use those numbers ($err). Try a duration between 0 and 200 hours.';
    }

    final task = SchedulingService.flexibleFromLlm(
      enriched,
      title: title,
      dueDate: due,
      preferMorning: preferMorning,
    );

    final byId = <String, List<ScheduleBlockModel>>{};
    for (final b in _store.blocks) {
      byId.putIfAbsent(b.taskId, () => []).add(b);
    }
    final existingFlexible = <FlexibleTask>[
      for (final e in byId.entries)
        FlexibleTask(
          id: e.key,
          title: e.value.first.taskTitle,
          dueDate: weekEnd.subtract(const Duration(seconds: 1)),
          estimatedDuration: e.value.fold<Duration>(
            Duration.zero,
            (s, b) => s + b.endTime.difference(b.startTime),
          ),
          priority: 0,
        ),
    ];

    final allTasks = [...existingFlexible, task];
    const config = SchedulingConfig(
      bufferAroundFixedEvents: Duration(minutes: 15),
      minimumBlockSize: Duration(minutes: 30),
    );

    final result = _scheduling.scheduleWithNearestAlternative(
      weekStart: weekStart,
      weekEnd: weekEnd,
      fixedEvents: fixed,
      flexibleTasks: allTasks,
      task: task,
      config: config,
      userConstraints: constraints,
      constraintClock: now,
    );

    final newBlocks = result.weekBlocks ?? const [];
    if (newBlocks.isNotEmpty) {
      final titles = <String, String>{
        for (final b in _store.blocks) b.taskId: b.taskTitle,
        task.id: title,
      };
      for (final s in newBlocks) {
        titles.putIfAbsent(s.taskId, () => s.taskId);
      }
      _store.applySynctraPreview(
        scheduled: [...newBlocks],
        taskTitles: titles,
        fixed: fixed,
      );
    }

    return _llm.generateSchedulingReply(
      userMessage: userMessage,
      intent: intent,
      result: result,
    );
  }

  static DateTime _dueForTarget(
    String? targetDay,
    DateTime weekStart,
    DateTime weekEnd,
    DateTime now,
  ) {
    switch (targetDay) {
      case 'tomorrow':
        final t = now.add(const Duration(days: 1));
        return DateTime(t.year, t.month, t.day, 23, 59);
      case 'this_week':
        return weekEnd.subtract(const Duration(seconds: 1));
      default:
        return weekEnd.subtract(const Duration(seconds: 1));
    }
  }
}

void registerLlmService() {
  final g = GetIt.instance;
  if (!g.isRegistered<LlmService>()) {
    g.registerLazySingleton(LlmService.new);
  }
}

void registerScheduleChatCoordinator() {
  final g = GetIt.instance;
  if (!g.isRegistered<ScheduleChatCoordinator>()) {
    g.registerLazySingleton(ScheduleChatCoordinator.fromGetIt);
  }
}

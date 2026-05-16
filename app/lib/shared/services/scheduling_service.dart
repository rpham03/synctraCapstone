import 'dart:math' as math;

import '../../data/models/scheduling_models.dart';

// -----------------------------------------------------------------------------
// Synctra scheduling — deterministic gap-packing (not machine learning).
//
// Pipeline: expand [FlexibleTask.sessions] → optional [UserConstraint] caps per day
// → fixed events buffered → merge busy → complement = free windows → sort tasks
// (due, priority, urgency) → greedy assign with end ≤ min(due, local midnight, avoid_after).
//
// LLM stays outside: parse intent / enrich estimates / natural language reply only.
// -----------------------------------------------------------------------------

export '../../data/models/scheduling_models.dart';

/// Tunables for [SchedulingService.scheduleWeek].
class SchedulingConfig {
  /// Non-work padding applied before each fixed event start and after each end.
  final Duration bufferAroundFixedEvents;

  /// Smallest slice of work that may be scheduled. Smaller gaps are ignored.
  final Duration minimumBlockSize;

  const SchedulingConfig({
    this.bufferAroundFixedEvents = const Duration(minutes: 15),
    this.minimumBlockSize = const Duration(minutes: 30),
  });
}

class _Window {
  final DateTime start;
  final DateTime end;

  _Window(this.start, this.end);

  Duration get duration => end.difference(start);
}

/// Computes free gaps between fixed events and packs flexible tasks into them.
class SchedulingService {
  const SchedulingService();

  /// Validates LLM enrichment before building a [FlexibleTask]. Returns null if OK.
  static String? validateEnrichedTask(LLMEnrichedTask e) {
    if (e.taskId.trim().isEmpty) return 'taskId must be non-empty';
    if (e.estimatedDurationHours <= 0 || e.estimatedDurationHours > 200) {
      return 'estimatedDuration must be in (0, 200] hours';
    }
    final p = e.priority.toLowerCase();
    if (p != 'high' && p != 'medium' && p != 'low') {
      return 'priority must be high|medium|low';
    }
    for (final s in e.sessions) {
      final m = s.duration.inMinutes;
      if (m < 1 || m > 24 * 60) return 'session duration out of range';
    }
    return null;
  }

  /// Builds a [FlexibleTask] from a validated [LLMEnrichedTask].
  static FlexibleTask flexibleFromLlm(
    LLMEnrichedTask e, {
    required String title,
    required DateTime dueDate,
    bool preferMorning = false,
  }) {
    final err = validateEnrichedTask(e);
    if (err != null) throw ArgumentError(err);
    final pri = switch (e.priority.toLowerCase()) {
      'high' => 10,
      'medium' => 5,
      'low' => 2,
      _ => 5,
    };
    final minutes = (e.estimatedDurationHours * 60).round().clamp(1, 200 * 60);
    final baseDur = Duration(minutes: minutes);
    return FlexibleTask(
      id: e.taskId.trim(),
      title: title,
      dueDate: dueDate,
      estimatedDuration: e.sessions.isEmpty ? baseDur : Duration.zero,
      priority: pri,
      urgencyFlag: e.urgencyFlag,
      sessions: List<TaskSession>.from(e.sessions),
      preferMorning: preferMorning,
    );
  }

  /// One flexible row per session slice, or one row using [estimatedDuration] if no sessions.
  static List<FlexibleTask> expandTaskSessions(List<FlexibleTask> tasks) {
    final out = <FlexibleTask>[];
    for (final t in tasks) {
      if (t.sessions.isEmpty) {
        if (t.estimatedDuration > Duration.zero) out.add(t);
        continue;
      }
      for (var i = 0; i < t.sessions.length; i++) {
        final dur = t.sessions[i].duration;
        if (dur <= Duration.zero) continue;
        out.add(FlexibleTask(
          id: '${t.id}__s$i',
          title: t.sessions.length > 1 ? '${t.title} (${i + 1}/${t.sessions.length})' : t.title,
          dueDate: t.dueDate,
          estimatedDuration: dur,
          priority: t.priority,
          urgencyFlag: t.urgencyFlag,
          sessions: const [],
          preferMorning: t.preferMorning,
        ));
      }
    }
    return out;
  }

  /// Plans flexible tasks into the half-open window `[weekStart, weekEnd)`.
  List<ScheduledBlock> scheduleWeek({
    required DateTime weekStart,
    required DateTime weekEnd,
    required List<FixedEvent> fixedEvents,
    required List<FlexibleTask> flexibleTasks,
    SchedulingConfig config = const SchedulingConfig(),
    List<UserConstraint> userConstraints = const [],
    DateTime? constraintClock,
  }) {
    if (!weekStart.isBefore(weekEnd)) return [];

    final clock = constraintClock ?? DateTime.now();
    final expanded = expandTaskSessions(flexibleTasks);
    final busy = _busyWindows(fixedEvents, config.bufferAroundFixedEvents, weekStart, weekEnd);
    final mergedBusy = _mergeWindows(busy);
    var free = _complement(mergedBusy, weekStart, weekEnd);
    free = free
        .where((w) => !w.duration.isNegative && w.duration >= config.minimumBlockSize)
        .toList();

    final tasks = List<FlexibleTask>.from(expanded)..sort((a, b) => a.compareToOthers(b));

    final blocks = <ScheduledBlock>[];

    for (final task in tasks) {
      if (task.estimatedDuration <= Duration.zero) continue;
      if (!task.dueDate.isAfter(weekStart)) continue;

      var remaining = task.estimatedDuration;

      while (remaining >= config.minimumBlockSize) {
        _sortWindowsForTask(free, task);
        var placed = false;

        for (var i = 0; i < free.length; i++) {
          final slot = free[i];
          if (!slot.start.isBefore(slot.end)) continue;

          final cappedEnd = _cappedSlotEnd(
            slot: slot,
            task: task,
            userConstraints: userConstraints,
            clock: clock,
          );
          if (!cappedEnd.isAfter(slot.start)) continue;

          var usable = cappedEnd.difference(slot.start);
          if (usable < config.minimumBlockSize) continue;

          var takeMicro = math.min(remaining.inMicroseconds, usable.inMicroseconds).toInt();
          var takeDur = Duration(microseconds: takeMicro);
          if (takeDur < config.minimumBlockSize) continue;

          var blockEnd = slot.start.add(takeDur);
          final dayEnd = _startOfNextLocalDay(slot.start);
          if (blockEnd.isAfter(dayEnd)) {
            takeDur = dayEnd.difference(slot.start);
            if (takeDur < config.minimumBlockSize) continue;
            takeMicro = takeDur.inMicroseconds;
            blockEnd = slot.start.add(takeDur);
          }

          blocks.add(ScheduledBlock(
            taskId: task.id,
            startTime: slot.start,
            endTime: blockEnd,
          ));

          remaining -= takeDur;
          _consumeWindow(free, i, takeDur, config.minimumBlockSize);
          placed = true;
          break;
        }

        if (!placed) break;
      }
    }

    blocks.sort((a, b) => a.startTime.compareTo(b.startTime));
    return blocks;
  }

  /// Runs [scheduleWeek], then if the greedy plan leaves part of [task] unscheduled,
  /// searches for the earliest other gap that fits at least [config.minimumBlockSize].
  SchedulingResult scheduleWithNearestAlternative({
    required DateTime weekStart,
    required DateTime weekEnd,
    required List<FixedEvent> fixedEvents,
    required List<FlexibleTask> flexibleTasks,
    required FlexibleTask task,
    SchedulingConfig config = const SchedulingConfig(),
    List<UserConstraint> userConstraints = const [],
    DateTime? constraintClock,
  }) {
    final clock = constraintClock ?? DateTime.now();
    final blocks = scheduleWeek(
      weekStart: weekStart,
      weekEnd: weekEnd,
      fixedEvents: fixedEvents,
      flexibleTasks: flexibleTasks,
      config: config,
      userConstraints: userConstraints,
      constraintClock: clock,
    );

    final expanded = expandTaskSessions([task]);
    if (expanded.isEmpty) {
      return SchedulingResult(success: true, weekBlocks: blocks, reason: 'Nothing to schedule');
    }

    final expandedIds = expanded.map((e) => e.id).toSet();
    final needMinutes =
        expanded.fold<int>(0, (s, u) => s + u.estimatedDuration.inMinutes);
    final gotMinutes = blocks
        .where((b) => expandedIds.contains(b.taskId))
        .fold<int>(0, (s, b) => s + b.duration.inMinutes);

    if (gotMinutes >= needMinutes) {
      ScheduledBlock? first;
      for (final b in blocks) {
        if (expandedIds.contains(b.taskId)) {
          first = b;
          break;
        }
      }
      return SchedulingResult(success: true, block: first, weekBlocks: blocks);
    }

    FlexibleTask? unit;
    for (final u in expanded) {
      final uGot = blocks
          .where((b) => b.taskId == u.id)
          .fold<int>(0, (s, b) => s + b.duration.inMinutes);
      if (uGot < u.estimatedDuration.inMinutes) {
        unit = u;
        break;
      }
    }
    final resolvedUnit = unit ?? expanded.first;

    final scheduledForUnit = blocks.where((b) => b.taskId == resolvedUnit.id).toList();
    final remaining = resolvedUnit.estimatedDuration -
        scheduledForUnit.fold<Duration>(Duration.zero, (s, b) => s + b.duration);
    if (remaining < config.minimumBlockSize) {
      return SchedulingResult(
        success: scheduledForUnit.isNotEmpty,
        block: scheduledForUnit.isNotEmpty ? scheduledForUnit.first : null,
        weekBlocks: blocks,
        reason: 'Remaining slice is below minimum block size.',
      );
    }

    final placedBusy = [
      ...fixedEvents,
      for (final b in blocks)
        FixedEvent(
          id: 'synctra-placed-${b.startTime.millisecondsSinceEpoch}',
          title: '_',
          startTime: b.startTime,
          endTime: b.endTime,
        ),
    ];
    final busy = _busyWindows(placedBusy, config.bufferAroundFixedEvents, weekStart, weekEnd);
    final mergedBusy = _mergeWindows(busy);
    var free = _complement(mergedBusy, weekStart, weekEnd);
    free = free
        .where((w) => !w.duration.isNegative && w.duration >= config.minimumBlockSize)
        .toList();
    _sortWindowsForTask(free, resolvedUnit);

    ScheduledBlock? alt;
    for (final slot in free) {
      final cappedEnd = _cappedSlotEnd(
        slot: slot,
        task: resolvedUnit,
        userConstraints: userConstraints,
        clock: clock,
      );
      if (!cappedEnd.isAfter(slot.start)) continue;
      var usable = cappedEnd.difference(slot.start);
      final dayEnd = _startOfNextLocalDay(slot.start);
      final dayCap = dayEnd.difference(slot.start);
      if (usable > dayCap) usable = dayCap;
      if (usable < remaining) continue;
      var end = slot.start.add(remaining);
      if (end.isAfter(dayEnd)) end = dayEnd;
      if (end.difference(slot.start) < config.minimumBlockSize) continue;
      alt = ScheduledBlock(taskId: resolvedUnit.id, startTime: slot.start, endTime: end);
      break;
    }

    return SchedulingResult(
      success: scheduledForUnit.isNotEmpty,
      block: scheduledForUnit.isNotEmpty ? scheduledForUnit.first : null,
      alternativeBlock: alt,
      reason: scheduledForUnit.isEmpty
          ? 'No gap matched your due time and constraints.'
          : 'Primary plan is partial; see alternative if shown.',
      weekBlocks: blocks,
    );
  }

  static DateTime _startOfNextLocalDay(DateTime d) =>
      DateTime(d.year, d.month, d.day).add(const Duration(days: 1));

  static DateTime _cappedSlotEnd({
    required _Window slot,
    required FlexibleTask task,
    required List<UserConstraint> userConstraints,
    required DateTime clock,
  }) {
    var end = _minDateTime(slot.end, task.dueDate);
    final cap = _userConstraintEndOnDay(
      slot.start,
      userConstraints,
      clock,
    );
    if (cap != null && cap.isBefore(end)) end = cap;
    return end;
  }

  /// Latest instant work may end on [slotDate] due to avoid_after (inclusive cap as DateTime).
  static DateTime? _userConstraintEndOnDay(
    DateTime slotStart,
    List<UserConstraint> constraints,
    DateTime clock,
  ) {
    DateTime? strictest;
    final day = DateTime(slotStart.year, slotStart.month, slotStart.day);
    for (final c in constraints) {
      final t = c.constraintType.toLowerCase();
      if (t != 'avoid_after' && t != 'avoidafter') continue;
      if (!_scopeApplies(c.scope, day, clock)) continue;
      final hm = _parseHm(c.time);
      if (hm == null) continue;
      final cap = DateTime(day.year, day.month, day.day, hm.$1, hm.$2);
      if (strictest == null || cap.isBefore(strictest)) strictest = cap;
    }
    return strictest;
  }

  static (int, int)? _parseHm(String s) {
    final parts = s.trim().split(':');
    if (parts.isEmpty) return null;
    final h = int.tryParse(parts[0]);
    if (h == null) return null;
    final m = parts.length > 1 ? int.tryParse(parts[1]) ?? 0 : 0;
    if (h < 0 || h > 23 || m < 0 || m > 59) return null;
    return (h, m);
  }

  static bool _scopeApplies(String scope, DateTime slotDay, DateTime clock) {
    final s = scope.toLowerCase();
    final today = DateTime(clock.year, clock.month, clock.day);
    final d = DateTime(slotDay.year, slotDay.month, slotDay.day);
    if (s == 'today') return d == today;
    if (s == 'weekdays' || s == 'weekday') {
      return slotDay.weekday >= DateTime.monday && slotDay.weekday <= DateTime.friday;
    }
    if (s == 'weekend') {
      return slotDay.weekday == DateTime.saturday || slotDay.weekday == DateTime.sunday;
    }
    return true;
  }

  static List<_Window> _busyWindows(
    List<FixedEvent> events,
    Duration buffer,
    DateTime weekStart,
    DateTime weekEnd,
  ) {
    final out = <_Window>[];
    for (final e in events) {
      if (!e.startTime.isBefore(e.endTime)) continue;
      var s = e.startTime.subtract(buffer);
      var t = e.endTime.add(buffer);
      if (!t.isAfter(weekStart) || !s.isBefore(weekEnd)) continue;
      if (s.isBefore(weekStart)) s = weekStart;
      if (t.isAfter(weekEnd)) t = weekEnd;
      if (s.isBefore(t)) out.add(_Window(s, t));
    }
    return out;
  }

  static List<_Window> _mergeWindows(List<_Window> windows) {
    if (windows.isEmpty) return [];
    final sorted = List<_Window>.from(windows)..sort((a, b) => a.start.compareTo(b.start));
    final merged = <_Window>[sorted.first];
    for (var i = 1; i < sorted.length; i++) {
      final cur = sorted[i];
      final last = merged.last;
      if (cur.start.isAfter(last.end)) {
        merged.add(cur);
      } else {
        final end = cur.end.isAfter(last.end) ? cur.end : last.end;
        merged[merged.length - 1] = _Window(last.start, end);
      }
    }
    return merged;
  }

  static List<_Window> _complement(List<_Window> busy, DateTime weekStart, DateTime weekEnd) {
    if (busy.isEmpty) return [_Window(weekStart, weekEnd)];
    final free = <_Window>[];
    var cursor = weekStart;
    for (final b in busy) {
      if (b.start.isAfter(cursor)) {
        free.add(_Window(cursor, b.start));
      }
      if (b.end.isAfter(cursor)) cursor = b.end;
    }
    if (cursor.isBefore(weekEnd)) free.add(_Window(cursor, weekEnd));
    return free;
  }

  static void _sortWindowsForTask(List<_Window> windows, FlexibleTask task) {
    if (!task.preferMorning) {
      windows.sort((a, b) => a.start.compareTo(b.start));
      return;
    }
    final morning = <_Window>[];
    final rest = <_Window>[];
    for (final w in windows) {
      if (w.start.hour < 12) {
        morning.add(w);
      } else {
        rest.add(w);
      }
    }
    morning.sort((a, b) => a.start.compareTo(b.start));
    rest.sort((a, b) => a.start.compareTo(b.start));
    windows
      ..clear()
      ..addAll(morning)
      ..addAll(rest);
  }

  static void _consumeWindow(
    List<_Window> windows,
    int index,
    Duration used,
    Duration minRemainder,
  ) {
    final w = windows[index];
    final newStart = w.start.add(used);
    if (!newStart.isBefore(w.end)) {
      windows.removeAt(index);
      return;
    }
    final remainder = w.end.difference(newStart);
    if (remainder < minRemainder) {
      windows.removeAt(index);
    } else {
      windows[index] = _Window(newStart, w.end);
    }
  }

  static DateTime _minDateTime(DateTime a, DateTime b) => a.isBefore(b) ? a : b;
}

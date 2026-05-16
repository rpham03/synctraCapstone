// On-device LLM integration point (Phi / Gemma via MLC or similar).
// Today: deterministic stubs — no cloud calls. Swap [parseSchedulingIntent] / [_replyBody]
// for a local model that emits JSON only.

import '../../data/models/scheduling_models.dart';

/// Five logical jobs: (1) duration (2) sessions (3) priority/urgency (4) intent (5) reply.
/// Implemented here as small JSON-shaped stubs until a local runtime is wired.
class LlmService {
  LlmService();

  /// Job 4 — map user text to [SchedulingIntent]. Must stay JSON-serializable at the boundary.
  SchedulingIntent parseSchedulingIntent(String userMessage) {
    final t = userMessage.toLowerCase().trim();
    if (t.contains('tomorrow') || t.contains('next day')) {
      if (t.contains('move') || t.contains('reschedule')) {
        return SchedulingIntent(
          action: 'move',
          taskName: _extractQuoted(t) ?? _guessTaskName(t),
          targetDay: 'tomorrow',
          timePreference: _extractTimePreference(t),
        );
      }
      if (t.contains('add') || t.contains('block') || t.contains('schedule')) {
        return SchedulingIntent(
          action: 'add',
          taskName: _extractQuoted(t) ?? 'Study block',
          targetDay: 'tomorrow',
          durationHours: _extractHours(t) ?? 2,
          timePreference: _extractTimePreference(t),
        );
      }
      return const SchedulingIntent(action: 'query', targetDay: 'tomorrow');
    }
    if (t.contains('week') || t.contains('due')) {
      return const SchedulingIntent(action: 'query', targetDay: 'this_week');
    }
    if (t.contains('add') || t.contains('block')) {
      return SchedulingIntent(
        action: 'add',
        taskName: _extractQuoted(t) ?? 'Study block',
        durationHours: _extractHours(t) ?? 1,
      );
    }
    return SchedulingIntent(action: 'query', taskName: _extractQuoted(t));
  }

  /// Job 1–3 stub: enrich a named task for the packer (caller supplies ids/titles from Canvas later).
  LLMEnrichedTask enrichTaskStub({
    required String taskId,
    required String title,
    double hours = 1.5,
    String priority = 'medium',
    bool urgency = false,
  }) {
    return LLMEnrichedTask(
      taskId: taskId,
      estimatedDurationHours: hours,
      priority: priority,
      urgencyFlag: urgency,
      sessions: const [],
    );
  }

  /// Job 5 — natural language from algorithm [SchedulingResult] (no direct calendar mutation).
  String generateSchedulingReply({
    required String userMessage,
    required SchedulingIntent intent,
    required SchedulingResult result,
  }) {
    final buf = StringBuffer();
    buf.writeln(_replyBody(intent, result));
    if (result.weekBlocks != null && result.weekBlocks!.isNotEmpty) {
      buf.writeln();
      buf.writeln(
        'I placed ${result.weekBlocks!.length} work block(s) this week using the built-in scheduler '
        '(deterministic — not an on-device model yet).',
      );
    }
    return buf.toString().trim();
  }

  String _replyBody(SchedulingIntent intent, SchedulingResult result) {
    if (!result.success && result.block == null && result.alternativeBlock == null) {
      return result.reason ??
          "I couldn't find a slot that fits your due date and the current busy times. "
              'Try shortening the block or moving a fixed event in Calendar preview.';
    }
    if (result.alternativeBlock != null && result.reason != null) {
      final a = result.alternativeBlock!;
      return '${result.reason} One option: ${_fmt(a.startTime)}–${_fmt(a.endTime)} for that task.';
    }
    if (result.block != null) {
      final b = result.block!;
      return 'Done — I scheduled "${intent.taskName ?? 'your task'}" at ${_fmt(b.startTime)}–${_fmt(b.endTime)}.';
    }
    return 'Here is what I found for your question.';
  }

  static String _fmt(DateTime d) {
    final h = d.hour > 12 ? d.hour - 12 : (d.hour == 0 ? 12 : d.hour);
    final am = d.hour < 12 ? 'am' : 'pm';
    final m = d.minute.toString().padLeft(2, '0');
    return '$h:$m $am';
  }

  static String? _extractQuoted(String t) {
    final single = RegExp(r"'([^']+)'");
    final double = RegExp(r'"([^"]+)"');
    final m1 = single.firstMatch(t);
    if (m1 != null) return m1.group(1);
    final m2 = double.firstMatch(t);
    return m2?.group(1);
  }

  static String? _guessTaskName(String t) {
    final m = RegExp(r'move\s+(.+?)\s+to').firstMatch(t);
    return m?.group(1)?.trim();
  }

  static double? _extractHours(String t) {
    final m = RegExp(r'(\d+(?:\.\d+)?)\s*hours?').firstMatch(t);
    if (m != null) return double.tryParse(m.group(1)!);
    final m2 = RegExp(r'(\d+)\s*hrs?').firstMatch(t);
    return m2 != null ? double.tryParse(m2.group(1)!) : null;
  }

  static String? _extractTimePreference(String t) {
    if (t.contains('3pm') || t.contains('3 pm')) return '15:00';
    if (t.contains('morning')) return 'morning';
    if (t.contains('afternoon')) return 'afternoon';
    return null;
  }
}

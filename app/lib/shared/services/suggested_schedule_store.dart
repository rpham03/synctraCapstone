import 'package:flutter/foundation.dart';
import 'package:get_it/get_it.dart';
import 'package:uuid/uuid.dart';

import '../../data/models/event_model.dart';
import '../../data/models/schedule_block_model.dart';
import 'scheduling_service.dart';

/// In-memory Synctra preview applied to [CalendarScreen]: study blocks + copied fixed busy times.
class SuggestedScheduleStore extends ChangeNotifier {
  final List<ScheduleBlockModel> _blocks = [];
  final List<EventModel> _previewFixed = [];

  /// Live busy times from the calendar (iCal, Canvas, manual). Used by [ScheduleChatCoordinator]
  /// when non-empty so the first chat turn respects real events.
  final List<EventModel> _externalBusy = [];

  List<ScheduleBlockModel> get blocks => List.unmodifiable(_blocks);

  List<EventModel> get previewFixed => List.unmodifiable(_previewFixed);

  /// Replaces external busy sources (call from [CalendarScreen] when events change).
  void setExternalBusy(Iterable<EventModel> events) {
    _externalBusy
      ..clear()
      ..addAll(events);
    notifyListeners();
  }

  /// Busy intervals for the scheduling algorithm.
  List<FixedEvent> fixedEventsForScheduling() {
    if (_externalBusy.isNotEmpty) {
      return [
        for (final e in _externalBusy)
          FixedEvent(
            id: e.id,
            title: e.title,
            startTime: e.startTime,
            endTime: e.endTime,
          ),
      ];
    }
    return [
      for (final e in _previewFixed)
        FixedEvent(
          id: e.id,
          title: e.title,
          startTime: e.startTime,
          endTime: e.endTime,
        ),
    ];
  }

  void removeBlock(String id) {
    _blocks.removeWhere((b) => b.id == id);
    notifyListeners();
  }

  void updateBlockTimes({
    required String id,
    required DateTime start,
    required DateTime end,
  }) {
    final i = _blocks.indexWhere((b) => b.id == id);
    if (i < 0) return;
    final b = _blocks[i];
    _blocks[i] = b.copyWith(
      startTime: start,
      endTime: end.isAfter(start) ? end : start.add(const Duration(minutes: 30)),
    );
    notifyListeners();
  }

  void updateBlockDescription(String id, String description) {
    final i = _blocks.indexWhere((b) => b.id == id);
    if (i < 0) return;
    _blocks[i] = _blocks[i].copyWith(description: description);
    notifyListeners();
  }

  bool get hasAny =>
      _blocks.isNotEmpty || _previewFixed.isNotEmpty;

  /// Replaces previous apply: flexible [ScheduledBlock]s plus [FixedEvent]s from the preview.
  void applySynctraPreview({
    required List<ScheduledBlock> scheduled,
    required Map<String, String> taskTitles,
    required List<FixedEvent> fixed,
  }) {
    // Merge by task id so chat / suggest can add blocks without wiping the week.
    final touched = scheduled.map((s) => s.taskId).toSet();
    _blocks.removeWhere((b) => touched.contains(b.taskId));
    _blocks.addAll([
      for (final s in scheduled)
        ScheduleBlockModel(
          id: const Uuid().v4(),
          taskId: s.taskId,
          taskTitle: taskTitles[s.taskId] ?? s.taskId,
          startTime: s.startTime,
          endTime: s.endTime,
          isAiGenerated: true,
          description: '',
        ),
    ]);
    _previewFixed
      ..clear()
      ..addAll([
        for (final f in fixed)
          EventModel(
            id: 'synctra-fixed-${f.id}',
            title: f.title,
            startTime: f.startTime,
            endTime: f.endTime,
            source: 'synctra_preview',
            isFixed: true,
            description: '',
          ),
      ]);
    notifyListeners();
  }

  void clear() {
    _blocks.clear();
    _previewFixed.clear();
    notifyListeners();
  }

  /// Study blocks proposed by Sync It chat (Calendar + Chat tab).
  void addStudyBlocks(List<ScheduleBlockModel> blocks) {
    if (blocks.isEmpty) return;
    _blocks.addAll(blocks);
    notifyListeners();
  }
}

void registerSuggestedScheduleStore() {
  final g = GetIt.instance;
  if (!g.isRegistered<SuggestedScheduleStore>()) {
    g.registerSingleton(SuggestedScheduleStore());
  }
}

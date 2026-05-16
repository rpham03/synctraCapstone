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

  List<ScheduleBlockModel> get blocks => List.unmodifiable(_blocks);

  List<EventModel> get previewFixed => List.unmodifiable(_previewFixed);

  bool get hasAny =>
      _blocks.isNotEmpty || _previewFixed.isNotEmpty;

  /// Replaces previous apply: flexible [ScheduledBlock]s plus [FixedEvent]s from the preview.
  void applySynctraPreview({
    required List<ScheduledBlock> scheduled,
    required Map<String, String> taskTitles,
    required List<FixedEvent> fixed,
  }) {
    _blocks
      ..clear()
      ..addAll([
        for (final s in scheduled)
          ScheduleBlockModel(
            id: const Uuid().v4(),
            taskId: s.taskId,
            taskTitle: taskTitles[s.taskId] ?? s.taskId,
            startTime: s.startTime,
            endTime: s.endTime,
            isAiGenerated: true,
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
          ),
      ]);
    notifyListeners();
  }

  void clear() {
    _blocks.clear();
    _previewFixed.clear();
    notifyListeners();
  }
}

void registerSuggestedScheduleStore() {
  final g = GetIt.instance;
  if (!g.isRegistered<SuggestedScheduleStore>()) {
    g.registerSingleton(SuggestedScheduleStore());
  }
}

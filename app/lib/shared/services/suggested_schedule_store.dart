import 'dart:async';
import 'dart:convert';

import 'package:flutter/foundation.dart';
import 'package:get_it/get_it.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:uuid/uuid.dart';

import '../../data/models/event_model.dart';
import '../../data/models/schedule_block_model.dart';
import '../../data/services/remote_event_sync.dart';
import 'scheduling_service.dart';
import 'user_scope.dart';

/// Synctra study blocks applied to [CalendarScreen]: chat-created blocks
/// (persisted per user so they survive a relaunch/login) + copied fixed busy
/// times.
class SuggestedScheduleStore extends ChangeNotifier {
  /// Base SharedPreferences key; the actual key is scoped to the current user.
  static const _persistKeyBase = 'synctra_study_blocks_v1';

  String get _persistKey => userScopedKey(_persistKeyBase);

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
    unawaited(_persist());
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
    unawaited(_persist());
    notifyListeners();
  }

  void updateBlockDescription(String id, String description) {
    final i = _blocks.indexWhere((b) => b.id == id);
    if (i < 0) return;
    _blocks[i] = _blocks[i].copyWith(description: description);
    unawaited(_persist());
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
    unawaited(_persist());
    notifyListeners();
  }

  void clear() {
    _blocks.clear();
    _previewFixed.clear();
    unawaited(_persist());
    notifyListeners();
  }

  /// Study blocks proposed by Sync It chat (Calendar + Chat tab).
  void addStudyBlocks(List<ScheduleBlockModel> blocks) {
    if (blocks.isEmpty) return;
    _blocks.addAll(blocks);
    unawaited(_persist());
    notifyListeners();
  }

  /// Load the current user's saved study blocks, replacing what's in memory.
  ///
  /// Call after Supabase is ready and on every sign-in/sign-out so each account
  /// sees only its own blocks (and signing out clears the previous user's).
  /// Loads the local cache first (fast), then reconciles with Supabase so chat
  /// blocks created on any device reappear — and local-only blocks migrate up
  /// the first time. Preview busy times are not persisted.
  Future<void> loadPersisted() async {
    final local = await _loadLocal();
    _blocks
      ..clear()
      ..addAll(local);
    notifyListeners();

    // Reconcile with Supabase: server rows win; otherwise migrate local up.
    final remote = await RemoteEventSync.pullStudyBlocks();
    if (remote == null) return; // signed out / offline — keep local
    if (remote.isNotEmpty) {
      _blocks
        ..clear()
        ..addAll(remote);
      await _persistLocal();
      notifyListeners();
    } else if (local.isNotEmpty) {
      await RemoteEventSync.replaceStudyBlocks(local);
    }
  }

  Future<List<ScheduleBlockModel>> _loadLocal() async {
    try {
      final prefs = await SharedPreferences.getInstance();
      final raw = prefs.getString(_persistKey);
      final decoded = (raw == null || raw.isEmpty) ? const [] : jsonDecode(raw);
      if (decoded is! List) return const [];
      return decoded
          .whereType<Map>()
          .map((m) => ScheduleBlockModel.fromJson(Map<String, dynamic>.from(m)))
          .toList();
    } catch (_) {
      // Corrupt read — treat as empty rather than crashing.
      return const [];
    }
  }

  Future<void> _persistLocal() async {
    try {
      final prefs = await SharedPreferences.getInstance();
      await prefs.setString(
        _persistKey,
        jsonEncode([for (final b in _blocks) b.toJson()]),
      );
    } catch (_) {
      // Persistence is best-effort; never crash the UI on a write failure.
    }
  }

  Future<void> _persist() async {
    await _persistLocal();
    // Mirror to Supabase so chat-created blocks survive logout/login and reach
    // other devices. Best effort: a failure leaves the local cache intact.
    await RemoteEventSync.replaceStudyBlocks(_blocks.toList());
  }
}

void registerSuggestedScheduleStore() {
  final g = GetIt.instance;
  if (!g.isRegistered<SuggestedScheduleStore>()) {
    g.registerSingleton(SuggestedScheduleStore());
  }
  // Saved blocks are loaded per user once Supabase auth is ready (see main.dart),
  // not here at startup where the signed-in user isn't known yet.
}

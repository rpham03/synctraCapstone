// Unified Sync It chat — same backend, calendar context, and study blocks everywhere.
import 'package:dio/dio.dart';
import 'package:get_it/get_it.dart';
import 'package:supabase_flutter/supabase_flutter.dart';
import 'package:uuid/uuid.dart';

import '../../core/constants/api_constants.dart';
import '../../data/models/schedule_block_model.dart';
import '../../data/models/user_settings.dart';
import '../../data/services/calendar_events_loader.dart';
import 'manual_events_store.dart';
import 'suggested_schedule_store.dart';
import 'user_settings_service.dart';

class SynctraChatResult {
  final String reply;
  final int blocksAdded;

  const SynctraChatResult({
    required this.reply,
    this.blocksAdded = 0,
  });
}

class SynctraChatService {
  SynctraChatService({SuggestedScheduleStore? store})
      : _store = store ?? GetIt.instance<SuggestedScheduleStore>();

  final SuggestedScheduleStore _store;

  /// Inverse operations for the most recently applied change, newest last.
  /// Lets the user say "undo" / "put it back" to reverse a move, delete, or add
  /// without a round-trip to the backend. One level deep (the last change only).
  final List<Future<void> Function()> _undo = [];

  static final RegExp _undoPattern = RegExp(
    r'^(?:please\s+)?(?:can you\s+|could you\s+)?'
    r'(?:undo|revert|put (?:it|that|them) back)'
    r'(?:\s+(?:that|it|the last(?:\s+change)?))?\s*[.!]*$',
    caseSensitive: false,
  );

  factory SynctraChatService.fromGetIt() =>
      SynctraChatService(store: GetIt.instance<SuggestedScheduleStore>());

  Future<SynctraChatResult> sendMessage(String userText) async {
    final text = userText.trim();
    if (text.isEmpty) {
      return const SynctraChatResult(
        reply: 'Send me a message about your schedule or tasks.',
      );
    }

    // "undo" / "put it back" reverses the last change locally — never sent to
    // the backend, so a delete is always recoverable.
    if (_isUndoRequest(text)) {
      final restored = await _undoLast();
      return SynctraChatResult(
        reply: restored > 0
            ? 'Done — I undid the last change.'
            : "There's nothing for me to undo.",
      );
    }

    try {
      final calendarEvents = await CalendarEventsLoader.loadForChat();
      final tasks = await CalendarEventsLoader.loadTasksForChat();
      final uid = Supabase.instance.client.auth.currentUser?.id ?? 'app-user';
      final response = await Dio().post<Map<String, dynamic>>(
        '${ApiConstants.baseUrl}/chat/message',
        data: {
          'message': text,
          'user_id': uid,
          'client_today': CalendarEventsLoader.clientTodayIso(),
          'timezone_offset_minutes': DateTime.now().timeZoneOffset.inMinutes,
          'timezone_name': DateTime.now().timeZoneName,
          'calendar_events': calendarEvents,
          'tasks': tasks,
          // Always send the latest Settings study window/session/break so chat
          // scheduling matches the Settings screen without an app restart.
          ...await _studyPreferencesPayload(),
        },
      );

      final reply = response.data?['reply']?.toString() ??
          'Sorry, I did not get a reply from the server.';
      final proposals = _readProposals(response.data?['schedule_proposals']);
      final hadDelete = proposals.any(
        (p) => (p['delete_block_id']?.toString() ?? '').isNotEmpty,
      );
      final added = await _applyScheduleProposals(proposals);

      // Make recovery discoverable right after a delete actually happened.
      final finalReply = (hadDelete && added > 0)
          ? '$reply\n\n(Say "undo" to put it back.)'
          : reply;
      return SynctraChatResult(reply: finalReply, blocksAdded: added);
    } on DioException catch (e) {
      final data = e.response?.data;
      if (data is Map && data['detail'] != null) {
        return SynctraChatResult(reply: data['detail'].toString());
      }
      if (e.type == DioExceptionType.connectionError ||
          e.error?.toString().contains('Connection refused') == true) {
        return SynctraChatResult(
          reply: 'Cannot reach the Synctra backend at ${ApiConstants.baseUrl}. '
              'If you are using Colab, keep the backend uvicorn cell and the '
              'Cloudflare tunnel cell running, then restart Flutter with the '
              'latest API_BASE_URL. For local backend:\n'
              'cd backend && python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000',
        );
      }
      return SynctraChatResult(
          reply: e.message ?? 'Could not reach the chat API');
    } catch (e) {
      return SynctraChatResult(reply: '$e');
    }
  }

  /// Same engine as chat — used from calendar event detail "Schedule study time".
  Future<SynctraChatResult> scheduleStudyForDueItem({
    required String title,
    required DateTime dueDate,
    int? estimatedMinutes,
    double? hours,
  }) async {
    final mins = estimatedMinutes ??
        (hours != null ? (hours * 60).round().clamp(15, 200 * 60) : 90);
    final dueDay = DateTime(dueDate.year, dueDate.month, dueDate.day);
    final dueIso =
        '${dueDay.year.toString().padLeft(4, '0')}-${dueDay.month.toString().padLeft(2, '0')}-${dueDay.day.toString().padLeft(2, '0')}';
    final hr = mins ~/ 60;
    final min = mins % 60;
    final durationLabel = min == 0 ? '$hr hours' : '$hr hours $min minutes';
    return sendMessage(
      'Propose study blocks for "$title" due on $dueIso. '
      'Use $mins estimated minutes total ($durationLabel). '
      'Avoid busy times on my calendar.',
    );
  }

  List<Map<String, dynamic>> _readProposals(Object? raw) {
    if (raw is! List) return const [];
    return raw
        .whereType<Map>()
        .map((m) => Map<String, dynamic>.from(m))
        .toList();
  }

  Future<int> _applyScheduleProposals(
      List<Map<String, dynamic>> proposals) async {
    if (proposals.isEmpty) return 0;

    final g = GetIt.instance;
    final manualStore =
        g.isRegistered<ManualEventsStore>() ? g<ManualEventsStore>() : null;

    final taskId = 'chat-${DateTime.now().millisecondsSinceEpoch}';
    final blocks = <ScheduleBlockModel>[];
    // Inverse of everything we apply this turn, so the next "undo" reverses it.
    final undoOps = <Future<void> Function()>[];
    var applied = 0;

    for (final p in proposals) {
      // A proposal carrying delete_block_id is a DELETE: remove the matching
      // study block or manual event. It has no start/end, so handle it first.
      final deleteId = p['delete_block_id']?.toString();
      if (deleteId != null && deleteId.isNotEmpty) {
        final sb = _findStudyBlock(deleteId);
        if (sb != null) {
          _store.removeBlock(deleteId);
          undoOps.add(() async => _store.addStudyBlocks([sb]));
          applied++;
        } else if (manualStore != null) {
          final removed = await manualStore.removeReturning(deleteId);
          if (removed != null) {
            undoOps.add(() async {
              await manualStore.restore(removed);
            });
            applied++;
          }
        }
        continue;
      }

      final startRaw = p['start_time']?.toString();
      final endRaw = p['end_time']?.toString();
      if (startRaw == null || endRaw == null) continue;
      try {
        final start = DateTime.parse(startRaw).toLocal();
        final end = DateTime.parse(endRaw).toLocal();
        final replaceId = p['replace_block_id']?.toString();
        // A proposal carrying replace_block_id is a MOVE: relocate the existing
        // item in place. Never fall through to adding a new one, or the move
        // would duplicate the event instead of moving it.
        if (replaceId != null && replaceId.isNotEmpty) {
          final sb = _findStudyBlock(replaceId);
          if (sb != null) {
            final oldStart = sb.startTime;
            final oldEnd = sb.endTime;
            _store.updateBlockTimes(id: replaceId, start: start, end: end);
            undoOps.add(() async => _store.updateBlockTimes(
                id: replaceId, start: oldStart, end: oldEnd));
            applied++;
          } else if (manualStore != null) {
            final old = await manualStore.findById(replaceId);
            if (old != null &&
                await manualStore.updateTimes(
                    id: replaceId, start: start, end: end)) {
              final oldStart = old.startTime;
              final oldEnd = old.endTime;
              undoOps.add(() async {
                await manualStore.updateTimes(
                    id: replaceId, start: oldStart, end: oldEnd);
              });
              applied++;
            }
          }
          continue;
        }
        blocks.add(
          ScheduleBlockModel(
            id: const Uuid().v4(),
            taskId: taskId,
            taskTitle: p['task_title']?.toString() ?? 'Study block',
            startTime: start,
            endTime: end,
            isAiGenerated: p['is_ai_generated'] as bool? ?? true,
          ),
        );
      } catch (_) {}
    }

    if (blocks.isNotEmpty) {
      _store.addStudyBlocks(blocks);
      applied += blocks.length;
      final addedIds = [for (final b in blocks) b.id];
      undoOps.add(() async {
        for (final id in addedIds) {
          _store.removeBlock(id);
        }
      });
    }

    if (undoOps.isNotEmpty) {
      _undo
        ..clear()
        ..addAll(undoOps);
    }
    return applied;
  }

  /// The user's latest Settings study window/session/break, read fresh from the
  /// shared [UserSettingsService] on every send so changing Settings takes
  /// effect on the next message (no restart). Returns an empty map when settings
  /// aren't available, letting the backend fall back to its defaults.
  Future<Map<String, dynamic>> _studyPreferencesPayload() async {
    final g = GetIt.instance;
    if (!g.isRegistered<UserSettingsService>()) return const {};
    try {
      final svc = g<UserSettingsService>();
      await svc.ensureLoaded();
      return chatStudyPreferences(svc.settings);
    } catch (_) {
      return const {};
    }
  }

  /// Maps the user's [UserSettings] to the chat request's study-preference
  /// fields. Pure + static so it can be unit-tested without the network stack.
  /// Returns an empty map when there are no settings (backend uses defaults).
  static Map<String, dynamic> chatStudyPreferences(UserSettings? s) {
    if (s == null) return const {};
    String hhmm(int hour, int minute) =>
        '${hour.toString().padLeft(2, '0')}:${minute.toString().padLeft(2, '0')}';
    return {
      'study_start_time': hhmm(s.workStartTime.hour, s.workStartTime.minute),
      'study_end_time': hhmm(s.workEndTime.hour, s.workEndTime.minute),
      'session_length_minutes': s.preferredSessionMinutes,
      'break_minutes': s.breakMinutes,
    };
  }

  ScheduleBlockModel? _findStudyBlock(String id) {
    for (final b in _store.blocks) {
      if (b.id == id) return b;
    }
    return null;
  }

  bool _isUndoRequest(String text) => _undoPattern.hasMatch(text.trim());

  /// Reverse the most recently applied change. Returns the number of inverse
  /// operations run (0 when there's nothing to undo).
  Future<int> _undoLast() async {
    if (_undo.isEmpty) return 0;
    final ops = List<Future<void> Function()>.from(_undo);
    _undo.clear();
    for (final op in ops.reversed) {
      try {
        await op();
      } catch (_) {}
    }
    return ops.length;
  }
}

void registerSynctraChatService() {
  final g = GetIt.instance;
  if (!g.isRegistered<SynctraChatService>()) {
    g.registerLazySingleton(SynctraChatService.fromGetIt);
  }
}

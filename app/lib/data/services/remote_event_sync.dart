// Syncs user-authored calendar data to Supabase so it survives logout/login and
// follows the account across devices:
//   • "+"-button manual events  -> public.events       (source = 'manual')
//   • chat/AI study blocks       -> public.schedule_blocks
//
// The local SharedPreferences stores stay as an offline cache; these helpers
// push on every change and pull on login. Every method is a safe no-op when the
// user is signed out or Supabase is unreachable, so the UI never blocks or
// crashes on a network error.

import 'package:supabase_flutter/supabase_flutter.dart';

import '../models/event_model.dart';
import '../models/schedule_block_model.dart';

class RemoteEventSync {
  RemoteEventSync._();

  static SupabaseClient get _db => Supabase.instance.client;

  static String? get _uid {
    try {
      return _db.auth.currentUser?.id;
    } catch (_) {
      return null;
    }
  }

  static List<Map<String, dynamic>> _rows(dynamic value) {
    if (value is List) {
      return value
          .whereType<Map>()
          .map((row) => Map<String, dynamic>.from(row))
          .toList();
    }
    return const [];
  }

  // ── Manual ("+") events → public.events (source = 'manual') ───────────────

  /// All of the signed-in user's manual events from Supabase, or null when
  /// signed out / unreachable (caller should then keep the local cache).
  static Future<List<EventModel>?> pullManualEvents() async {
    final uid = _uid;
    if (uid == null) return null;
    try {
      final rows = await _db
          .from('events')
          .select()
          .eq('user_id', uid)
          .eq('source', 'manual')
          .order('start_time');
      return _rows(rows).map(_manualFromRow).toList();
    } catch (_) {
      return null;
    }
  }

  /// Make Supabase match [events] exactly: upsert the current set, delete the
  /// manual rows that are no longer present.
  static Future<void> replaceManualEvents(List<EventModel> events) async {
    final uid = _uid;
    if (uid == null) return;
    try {
      if (events.isNotEmpty) {
        await _db
            .from('events')
            .upsert([for (final e in events) _manualRow(e, uid)]);
      }
      final existing = await _db
          .from('events')
          .select('id')
          .eq('user_id', uid)
          .eq('source', 'manual');
      final keep = {for (final e in events) e.id};
      for (final row in _rows(existing)) {
        final id = row['id'] as String?;
        if (id != null && !keep.contains(id)) {
          await _db.from('events').delete().eq('id', id);
        }
      }
    } catch (_) {
      // Best effort — the local cache still has the change.
    }
  }

  static Map<String, dynamic> _manualRow(EventModel e, String uid) => {
        'id': e.id,
        'user_id': uid,
        'title': e.title,
        'description': e.description,
        'start_time': e.startTime.toUtc().toIso8601String(),
        'end_time': e.endTime.toUtc().toIso8601String(),
        'source': 'manual',
        'is_fixed': e.isFixed,
      };

  static EventModel _manualFromRow(Map<String, dynamic> r) => EventModel(
        id: r['id'] as String,
        title: r['title'] as String? ?? '',
        startTime: DateTime.parse(r['start_time'] as String).toLocal(),
        endTime: DateTime.parse(r['end_time'] as String).toLocal(),
        source: 'manual',
        isFixed: r['is_fixed'] as bool? ?? true,
        description: r['description'] as String? ?? '',
      );

  // ── Chat/AI study blocks → public.schedule_blocks ─────────────────────────

  static Future<List<ScheduleBlockModel>?> pullStudyBlocks() async {
    final uid = _uid;
    if (uid == null) return null;
    try {
      final rows = await _db
          .from('schedule_blocks')
          .select()
          .eq('user_id', uid)
          .eq('is_active', true)
          .order('start_time');
      return _rows(rows).map(_blockFromRow).toList();
    } catch (_) {
      return null;
    }
  }

  static Future<void> replaceStudyBlocks(List<ScheduleBlockModel> blocks) async {
    final uid = _uid;
    if (uid == null) return;
    try {
      if (blocks.isNotEmpty) {
        await _db
            .from('schedule_blocks')
            .upsert([for (final b in blocks) _blockRow(b, uid)]);
      }
      final existing =
          await _db.from('schedule_blocks').select('id').eq('user_id', uid);
      final keep = {for (final b in blocks) b.id};
      for (final row in _rows(existing)) {
        final id = row['id'] as String?;
        if (id != null && !keep.contains(id)) {
          await _db.from('schedule_blocks').delete().eq('id', id);
        }
      }
    } catch (_) {
      // Best effort — the local cache still has the change.
    }
  }

  static Map<String, dynamic> _blockRow(ScheduleBlockModel b, String uid) => {
        'id': b.id,
        'user_id': uid,
        // schedule_blocks.task_id is an FK to public.tasks; our chat task ids
        // aren't task rows, so the title carries the label and task_id stays null.
        'task_title': b.taskTitle,
        'start_time': b.startTime.toUtc().toIso8601String(),
        'end_time': b.endTime.toUtc().toIso8601String(),
        'is_ai_generated': b.isAiGenerated,
        'is_active': true,
      };

  static ScheduleBlockModel _blockFromRow(Map<String, dynamic> r) =>
      ScheduleBlockModel(
        id: r['id'] as String,
        taskId: '',
        taskTitle: r['task_title'] as String? ?? 'Study block',
        startTime: DateTime.parse(r['start_time'] as String).toLocal(),
        endTime: DateTime.parse(r['end_time'] as String).toLocal(),
        isAiGenerated: r['is_ai_generated'] as bool? ?? true,
      );
}

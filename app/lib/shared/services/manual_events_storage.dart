import 'dart:convert';

import 'package:shared_preferences/shared_preferences.dart';

import '../../data/models/event_model.dart';
import '../../data/services/remote_event_sync.dart';
import 'user_scope.dart';

/// Single source of truth for reading/writing the user's "+"-button manual
/// calendar events, scoped per user. The calendar screen, the chat calendar
/// loader, and [ManualEventsStore] all go through here so they agree on the key
/// and format.
const _manualEventsBase = 'synctra_manual_events_v1';

/// Pre-multi-user key. Read as a fallback so events saved before per-user
/// scoping are not lost; the next save migrates them to the scoped key.
const _legacyManualEventsKey = 'synctra_manual_events_v1';

Map<String, dynamic> manualEventToJson(EventModel e) => {
      'id': e.id,
      'title': e.title,
      'start_time': e.startTime.toIso8601String(),
      'end_time': e.endTime.toIso8601String(),
      'source': e.source,
      'is_fixed': e.isFixed,
      'description': e.description,
    };

List<EventModel> _decodeManualEvents(String? raw) {
  if (raw == null || raw.isEmpty) return const [];
  try {
    final decoded = jsonDecode(raw);
    if (decoded is! List) return const [];
    return decoded
        .whereType<Map>()
        .map((m) => EventModel.fromJson(Map<String, dynamic>.from(m)))
        .where((e) => e.source == 'manual')
        .toList();
  } catch (_) {
    return const [];
  }
}

Future<List<EventModel>> loadManualEvents() async {
  final prefs = await SharedPreferences.getInstance();
  final scopedKey = userScopedKey(_manualEventsBase);
  // Once the per-user key exists we trust it — even an empty list, so deleting
  // every event doesn't make the old pre-scoping events resurface.
  if (prefs.containsKey(scopedKey)) {
    return _decodeManualEvents(prefs.getString(scopedKey));
  }
  // First run for this user: fall back to the pre-scoping key so events saved
  // before per-user scoping still show up (the next save migrates them).
  if (scopedKey != _legacyManualEventsKey) {
    return _decodeManualEvents(prefs.getString(_legacyManualEventsKey));
  }
  return const [];
}

/// Writes the manual events to the local per-user cache only (no Supabase).
Future<void> _writeManualEventsLocal(List<EventModel> events) async {
  final prefs = await SharedPreferences.getInstance();
  final data = [for (final e in events) manualEventToJson(e)];
  await prefs.setString(userScopedKey(_manualEventsBase), jsonEncode(data));
}

Future<void> saveManualEvents(List<EventModel> events) async {
  await _writeManualEventsLocal(events);
  // Mirror to Supabase so the events survive logout/login and reach other
  // devices. Best effort: a network failure leaves the local cache intact.
  await RemoteEventSync.replaceManualEvents(events);
}

/// Reconciles the local manual-event cache with Supabase at login:
///   • Supabase has rows  -> they win (the account's events on any device).
///   • Supabase is empty but local has events -> migrate the local ones up.
/// A no-op (keeps local) when signed out or Supabase is unreachable.
Future<void> syncManualEventsFromSupabase() async {
  final remote = await RemoteEventSync.pullManualEvents();
  if (remote == null) return; // signed out / offline — keep the local cache
  if (remote.isNotEmpty) {
    await _writeManualEventsLocal(remote);
    return;
  }
  final local = await loadManualEvents();
  if (local.isNotEmpty) {
    await RemoteEventSync.replaceManualEvents(local);
  }
}

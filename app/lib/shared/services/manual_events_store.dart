import 'package:flutter/foundation.dart';
import 'package:get_it/get_it.dart';

import '../../data/models/event_model.dart';
import 'manual_events_storage.dart';

/// Shared access to the user's manually-added calendar events (the "+" button),
/// persisted per user in SharedPreferences.
///
/// Both [CalendarScreen] and Sync It chat read/write through this so a
/// chat-driven move or delete updates the same stored list and the grid
/// refreshes. The store keeps no in-memory cache — every operation reads the
/// latest prefs, so it never goes stale against the calendar screen's own edits.
class ManualEventsStore extends ChangeNotifier {
  Future<List<EventModel>> load() => loadManualEvents();

  Future<void> _saveAll(List<EventModel> events) => saveManualEvents(events);

  /// Tell listeners (the calendar grid) to reload — e.g. after the user changes.
  void refresh() => notifyListeners();

  /// Relocate a manual event in place. Returns true if a matching event existed.
  Future<bool> updateTimes({
    required String id,
    required DateTime start,
    required DateTime end,
  }) async {
    final events = await load();
    final i = events.indexWhere((e) => e.id == id);
    if (i < 0) return false;
    final safeEnd =
        end.isAfter(start) ? end : start.add(const Duration(minutes: 30));
    events[i] = events[i].copyWith(startTime: start, endTime: safeEnd);
    await _saveAll(events);
    notifyListeners();
    return true;
  }

  /// Remove a manual event. Returns true if a matching event existed.
  Future<bool> remove(String id) async {
    final events = await load();
    final before = events.length;
    events.removeWhere((e) => e.id == id);
    if (events.length == before) return false;
    await _saveAll(events);
    notifyListeners();
    return true;
  }
}

void registerManualEventsStore() {
  final g = GetIt.instance;
  if (!g.isRegistered<ManualEventsStore>()) {
    g.registerSingleton(ManualEventsStore());
  }
}

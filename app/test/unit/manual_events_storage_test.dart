import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:synctra/data/models/event_model.dart';
import 'package:synctra/shared/services/manual_events_storage.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  setUp(() => SharedPreferences.setMockInitialValues({}));

  EventModel ev(String id, String title) => EventModel(
        id: id,
        title: title,
        startTime: DateTime(2026, 6, 8, 20),
        endTime: DateTime(2026, 6, 8, 21),
        source: 'manual',
      );

  group('manual events storage (local cache + graceful offline sync)', () {
    test('save then load round-trips manual events', () async {
      await saveManualEvents([ev('a', 'Dentist'), ev('b', 'Gym')]);

      final loaded = await loadManualEvents();
      expect(loaded.map((e) => e.id), containsAll(['a', 'b']));
      expect(loaded.firstWhere((e) => e.id == 'a').title, 'Dentist');
    });

    test('saving an empty list clears the stored events', () async {
      await saveManualEvents([ev('a', 'Dentist')]);
      await saveManualEvents([]);
      expect(await loadManualEvents(), isEmpty);
    });

    test('saveManualEvents still persists locally when Supabase is unavailable',
        () async {
      // Supabase isn't initialized in unit tests, so the remote mirror is a
      // safe no-op — the local write must still succeed (never throws).
      await saveManualEvents([ev('a', 'Dentist')]);
      expect((await loadManualEvents()).single.title, 'Dentist');
    });

    test('syncManualEventsFromSupabase keeps the local cache when signed out',
        () async {
      await saveManualEvents([ev('a', 'Dentist')]);
      // Signed out / offline: pull returns null, so local data is preserved.
      await syncManualEventsFromSupabase();
      expect((await loadManualEvents()).single.id, 'a');
    });
  });
}

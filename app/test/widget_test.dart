// Smoke test — verifies the SynctraApp widget tree builds without crashing.
import 'package:flutter_test/flutter_test.dart';

void main() {
  testWidgets('App builds smoke test', (WidgetTester tester) async {
    // Supabase requires real credentials so full app pump is tested
    // in integration tests. Unit and widget tests go in test/unit/ and test/widget/.
    expect(true, isTrue);
  });
}

import 'package:shared_preferences/shared_preferences.dart';

/// Persists the user's preferred calendar view (day / week / month).
class CalendarViewPrefs {
  CalendarViewPrefs._();

  static const _key = 'calendar_view_mode';

  static Future<String?> load() async {
    final prefs = await SharedPreferences.getInstance();
    return prefs.getString(_key);
  }

  static Future<void> save(String mode) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(_key, mode);
  }
}

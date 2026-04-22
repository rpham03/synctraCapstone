// App-wide constant values shared across the Flutter application.
class AppConstants {
  static const String appName = 'Synctra';

  // Default scheduling preferences
  static const int defaultStudyBlockMinutes = 50;
  static const int defaultBreakMinutes = 10;
  static const int minTaskBlockMinutes = 15;

  // How many days ahead the AI looks when building a schedule
  static const int scheduleLookAheadDays = 14;

  // Bottom nav tab indices
  static const int tabCalendar = 0;
  static const int tabTasks    = 1;
  static const int tabChat     = 2;
  static const int tabCollab   = 3;
}

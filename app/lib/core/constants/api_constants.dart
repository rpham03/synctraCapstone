// Base URLs for the Syntra backend API and Canvas LMS (UW instance).
class ApiConstants {
  static const String baseUrl = 'http://localhost:8000/api/v1';

  /// Canvas web UI — dashboard, courses, assignments (browser / WebView).
  /// UW: [https://canvas.uw.edu](https://canvas.uw.edu)
  static const String canvasWebBaseUrl = 'https://canvas.uw.edu';

  /// Canvas REST API v1 for this host (Bearer token). Paths like `/users/self/profile`.
  static const String canvasBaseUrl = '$canvasWebBaseUrl/api/v1';

  /// Canvas dashboard (home).
  static String get canvasDashboardUrl => '$canvasWebBaseUrl/';

  /// A single course shell (Syllabus, Modules, etc.).
  static String canvasCourseUrl(String courseId) =>
      '$canvasWebBaseUrl/courses/$courseId';

  /// Assignments index for a course.
  static String canvasCourseAssignmentsUrl(String courseId) =>
      '$canvasWebBaseUrl/courses/$courseId/assignments';

  /// Course calendar (month/week views in Canvas).
  static String canvasCourseCalendarUrl(String courseId) =>
      '$canvasWebBaseUrl/courses/$courseId/calendar_events';
}

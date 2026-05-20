// Base URLs for the Syntra backend API and Canvas LMS (UW instance).
import 'dart:io' show Platform;

import 'package:flutter/foundation.dart' show kIsWeb;

class ApiConstants {
  /// Backend API — `localhost` on web/desktop; Android emulator uses `10.0.2.2`.
  static String get baseUrl {
    if (kIsWeb) return 'http://localhost:8000/api/v1';
    try {
      if (Platform.isAndroid) return 'http://10.0.2.2:8000/api/v1';
    } catch (_) {}
    return 'http://localhost:8000/api/v1';
  }

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

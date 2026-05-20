// Breakpoint helpers — use these everywhere instead of hardcoding pixel values.
import 'package:flutter/material.dart';

class Breakpoints {
  static const double mobile  = 600;
  static const double tablet  = 900;
  static const double desktop = 1200;
}

class Responsive {
  /// True when there is room for the Notion-style sidebar + calendar mini panel + grid.
  static bool isDesktop(BuildContext context) =>
      MediaQuery.sizeOf(context).width >= 1000;

  static bool isMobile(BuildContext context) =>
      MediaQuery.sizeOf(context).width < Breakpoints.mobile;

  /// Returns different values based on current screen width.
  static T value<T>(
    BuildContext context, {
    required T mobile,
    T? tablet,
    required T desktop,
  }) {
    final w = MediaQuery.sizeOf(context).width;
    if (w >= Breakpoints.tablet) return desktop;
    if (w >= Breakpoints.mobile) return tablet ?? desktop;
    return mobile;
  }
}

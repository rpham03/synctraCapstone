import 'package:flutter/material.dart';

import '../../core/theme/app_tokens.dart';

/// Calendar layout breakpoints — use instead of raw MediaQuery in feature UI.
enum CalendarLayoutSize {
  compact,
  medium,
  expanded,
}

class CalendarLayoutInfo {
  const CalendarLayoutInfo({required this.width});

  final double width;

  CalendarLayoutSize get size {
    if (width >= AppTokens.breakpointExpanded) return CalendarLayoutSize.expanded;
    if (width >= AppTokens.breakpointCompact) return CalendarLayoutSize.medium;
    return CalendarLayoutSize.compact;
  }

  bool get showCalendarSidebar => size == CalendarLayoutSize.expanded;
  /// Expanded layout can dock the planner sidebar inline (toggle in top bar).
  bool get canDockCalendarSidebar => size == CalendarLayoutSize.expanded;
  bool get showRightPanelDocked => size != CalendarLayoutSize.compact;
  bool get isCompact => size == CalendarLayoutSize.compact;
}

/// Wraps [LayoutBuilder] and exposes [CalendarLayoutInfo] to descendants.
class ResponsiveLayout extends StatelessWidget {
  const ResponsiveLayout({
    super.key,
    required this.builder,
  });

  final Widget Function(BuildContext context, CalendarLayoutInfo info) builder;

  @override
  Widget build(BuildContext context) {
    return LayoutBuilder(
      builder: (context, constraints) {
        return builder(
          context,
          CalendarLayoutInfo(width: constraints.maxWidth),
        );
      },
    );
  }
}

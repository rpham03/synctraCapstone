import 'package:flutter/material.dart';

import '../../theme.dart';

/// Layout, spacing, and sizing tokens — use instead of magic numbers in UI code.
abstract final class AppTokens {
  // Spacing (4dp grid)
  static const double space4 = 4;
  static const double space8 = 8;
  static const double space12 = 12;
  static const double space16 = 16;
  static const double space20 = 20;
  static const double space24 = 24;
  static const double space32 = 32;

  static const EdgeInsets screenPadding =
      EdgeInsets.symmetric(horizontal: space24, vertical: space16);
  static const EdgeInsets screenPaddingH =
      EdgeInsets.symmetric(horizontal: space24);

  // Shape
  static const double radiusSm = 6;
  static const double radiusMd = 8;
  static const double radiusLg = 12;

  static BorderRadius get borderRadiusMd => BorderRadius.circular(radiusMd);
  static BorderRadius get borderRadiusLg => BorderRadius.circular(radiusLg);

  // Icons
  static const double iconInline = 20;
  static const double iconStandard = 24;

  // Interaction
  static const double minTapTarget = 48;
  static const double buttonHeight = 44;

  // Onboarding / settings content width feel
  static const double sectionGap = space24;

  // ── Calendar (Reclaim-style layout) ─────────────────────────────────────
  static const double calendarTopBarHeight = 56;
  static const double pageTopBarHeight = 56;
  static const double pageContentMaxWidth = 680;
  static const double calendarSidebarWidth = 240;
  static const double calendarRightPanelWidth = 320;
  static const double calendarTimeGutterWidth = 48;
  static const double calendarHourHeight = 56;
  static const double calendarEventRadius = 8;
  static const double calendarDividerThickness = 1;
  static const double calendarDividerOpacity = 0.42;
  static const double calendarHalfHourOpacity = 0.22;
  static const double calendarTodayColumnTint = 0.1;

  static const Duration calendarPanelAnimation = Duration(milliseconds: 250);
  static const Duration calendarWeekSlideAnimation = Duration(milliseconds: 200);
  static const Duration calendarViewCrossfade = Duration(milliseconds: 150);

  static const Curve calendarPanelCurve = Curves.easeInOutCubic;
  static const Curve calendarWeekSlideCurve = Curves.easeOut;

  /// Responsive breakpoints for calendar chrome.
  static const double breakpointCompact = 768;
  static const double breakpointExpanded = 1280;

  /// Hairline divider color from theme border token.
  static Color calendarDivider(BuildContext context) {
    final isDark = Theme.of(context).brightness == Brightness.dark;
    final base = isDark ? AppColorsDark.border : AppColors.border;
    return base.withValues(alpha: calendarDividerOpacity);
  }

  static Color calendarHalfHourLine(BuildContext context) {
    return calendarDivider(context).withValues(
      alpha: calendarHalfHourOpacity / calendarDividerOpacity,
    );
  }

  /// Grid canvas — flat, no card chrome.
  static Color calendarGridSurface(BuildContext context) {
    return Theme.of(context).colorScheme.surface;
  }

  /// Subtle wash behind today's column header + body.
  static Color calendarTodayWash(BuildContext context) {
    return AppColors.primary.withValues(alpha: calendarTodayColumnTint);
  }

  /// Sidebar surface — one step above scaffold.
  static Color calendarSidebarSurface(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return scheme.surfaceContainerLow;
  }
}

/// Semantic text helpers — always prefer [Theme.of(context).textTheme] first.
extension SynctraTextTheme on BuildContext {
  TextTheme get synctraText => Theme.of(this).textTheme;
  ColorScheme get synctraColors => Theme.of(this).colorScheme;

  /// Section headers in settings (muted, smaller than row labels).
  TextStyle? get sectionHeaderStyle => synctraText.labelLarge?.copyWith(
        color: AppColors.textSecondary,
        fontWeight: FontWeight.w600,
        letterSpacing: 0.4,
        height: 1.3,
      );

  /// Onboarding step counter below progress bar.
  TextStyle? get stepLabelStyle => synctraText.labelLarge?.copyWith(
        color: AppColors.textSecondary,
        fontWeight: FontWeight.w500,
        height: 1.3,
      );

  /// Inline helper / caption (min 12sp per accessibility guidelines).
  TextStyle? get captionStyle => synctraText.bodySmall?.copyWith(
        color: AppColors.textSecondary,
        height: 1.45,
      );
}

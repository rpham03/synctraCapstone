import 'package:flutter/material.dart';

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
}

/// Semantic text helpers — always prefer [Theme.of(context).textTheme] first.
extension SynctraTextTheme on BuildContext {
  TextTheme get synctraText => Theme.of(this).textTheme;
  ColorScheme get synctraColors => Theme.of(this).colorScheme;

  /// Section headers in settings (muted, smaller than row labels).
  TextStyle? get sectionHeaderStyle => synctraText.labelLarge?.copyWith(
        color: synctraColors.onSurfaceVariant,
        fontWeight: FontWeight.w600,
        letterSpacing: 0.4,
        height: 1.3,
      );

  /// Onboarding step counter below progress bar.
  TextStyle? get stepLabelStyle => synctraText.labelLarge?.copyWith(
        color: synctraColors.onSurfaceVariant,
        fontWeight: FontWeight.w500,
        height: 1.3,
      );

  /// Inline helper / caption (min 12sp per accessibility guidelines).
  TextStyle? get captionStyle => synctraText.bodySmall?.copyWith(
        color: synctraColors.onSurfaceVariant,
        height: 1.45,
      );
}

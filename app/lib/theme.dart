// Synctra design system — Notion-inspired surfaces, Inter typography, quiet chrome.
// All chroma lives here; screens should use Theme.of(context) or [AppColors] for semantics.
import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';

// ── Core palette (light) ───────────────────────────────────────────────────

/// Brand + calendar semantics. Neutrals follow Notion-like ink on paper.
abstract final class AppColors {
  /// Primary UI / links — readable blue on warm white.
  static const Color primary = Color(0xFF1B6CB5);

  /// Secondary — Canvas / warm highlights.
  static const Color secondary = Color(0xFFF9AB00);

  static const Color surface = Color(0xFFFFFFFF);
  static const Color background = Color(0xFFF5F4F1);

  static const Color error = Color(0xFFDC4F45);
  static const Color success = Color(0xFF0D6B5E);

  /// Notion ink.
  static const Color textPrimary = Color(0xFF2F2E2B);
  static const Color textSecondary = Color(0xFF6F6E69);

  static const Color border = Color(0xFFDCDAD6);

  // ── Neutrals ───────────────────────────────────────────────────────────────
  static const Color grey100 = Color(0xFFEEEDEA);
  static const Color grey300 = Color(0xFFDCDAD6);
  static const Color grey600 = Color(0xFF6F6E69);
  static const Color grey800 = Color(0xFF2F2E2B);

  // ── Calendar / schedule semantics ────────────────────────────────────────
  static const Color calendarGridLine = border;
  static const Color currentTimeLine = Color(0xFFEB5757);

  static const Color canvasAssignment = secondary;
  static const Color canvasAssignmentContainer = Color(0xFFFFF6E8);

  /// Tasks added manually on the Tasks tab (calendar due chips + list accent).
  static const Color manualTask = Color(0xFF16A34A);
  static const Color manualTaskContainer = Color(0xFFE8F5EC);

  static const Color fixedEvent = primary;
  static const Color aiStudyBlock = success;
  static const Color confirmedStudyBlock = success;

  static const Color aiSuggestedFill = Color(0x331B6CB5);
  static const Color aiSuggestedBorder = primary;

  static const Color icalAccent = Color(0xFF9065B0);
  static const Color flexibleBlock = aiStudyBlock;
  static const Color collabEvent = secondary;
  static const Color deadline = error;

  static const Color surfaceLight = surface;
  static const Color surfaceDimLight = background;
  static const Color outlineVariantLight = border;
}

/// Dark-mode companions (Notion-dark inspired).
abstract final class AppColorsDark {
  static const Color surface = Color(0xFF252525);
  static const Color background = Color(0xFF191919);
  static const Color textPrimary = Color(0xFFE6E6E4);
  static const Color textSecondary = Color(0xFF9B9B99);
  static const Color border = Color(0xFF3D3D3A);

  static const Color canvasAssignmentContainer = Color(0xFF3E2E14);
  static const Color aiSuggestedFill = Color(0x331B6CB5);
}

/// Custom page transition: fade + slight upward slide (Linear-style polish).
final class SynctraFadeUpTransitionsBuilder extends PageTransitionsBuilder {
  const SynctraFadeUpTransitionsBuilder();

  @override
  Widget buildTransitions<T>(
    PageRoute<T> route,
    BuildContext context,
    Animation<double> animation,
    Animation<double> secondaryAnimation,
    Widget child,
  ) {
    final curved = CurvedAnimation(
      parent: animation,
      curve: Curves.easeOutCubic,
      reverseCurve: Curves.easeInCubic,
    );
    return FadeTransition(
      opacity: curved,
      child: SlideTransition(
        position: Tween<Offset>(
          begin: const Offset(0, 0.024),
          end: Offset.zero,
        ).animate(curved),
        child: child,
      ),
    );
  }
}

/// Material 3 themes — Notion-like surfaces, Inter typography, quiet chrome.
abstract final class AppTheme {
  static ThemeData get light => _build(brightness: Brightness.light);

  static ThemeData get dark => _build(brightness: Brightness.dark);

  static ColorScheme _scheme(Brightness brightness) {
    final isLight = brightness == Brightness.light;
    final base = ColorScheme.fromSeed(
      seedColor: AppColors.primary,
      brightness: brightness,
    );

    if (isLight) {
      return base.copyWith(
        surface: AppColors.surface,
        onSurface: AppColors.textPrimary,
        onSurfaceVariant: AppColors.textSecondary,
        outline: AppColors.textPrimary.withValues(alpha: 0.12),
        outlineVariant: AppColors.border,
        surfaceContainerLowest: AppColors.background,
        surfaceContainerLow: const Color(0xFFEEEDEA),
        surfaceContainer: const Color(0xFFE6E5E1),
        surfaceContainerHigh: const Color(0xFFDCDAD6),
        surfaceContainerHighest: const Color(0xFFD3D1CC),
        primary: AppColors.primary,
        onPrimary: Colors.white,
        secondary: AppColors.secondary,
        onSecondary: AppColors.textPrimary,
        error: AppColors.error,
        tertiary: AppColors.icalAccent,
        onTertiary: Colors.white,
      );
    }

    return base.copyWith(
      surface: AppColorsDark.surface,
      onSurface: AppColorsDark.textPrimary,
      onSurfaceVariant: AppColorsDark.textSecondary,
      outline: AppColorsDark.textPrimary.withValues(alpha: 0.14),
      outlineVariant: AppColorsDark.border,
      surfaceContainerLowest: AppColorsDark.background,
      surfaceContainerLow: const Color(0xFF2A2A2A),
      surfaceContainer: const Color(0xFF323232),
      surfaceContainerHigh: const Color(0xFF383838),
      surfaceContainerHighest: const Color(0xFF3D3D3A),
      primary: AppColors.primary,
      onPrimary: Colors.white,
      secondary: AppColors.secondary,
      onSecondary: AppColorsDark.textPrimary,
      error: AppColors.error,
      tertiary: AppColors.icalAccent,
      onTertiary: Colors.white,
    );
  }

  static TextTheme _textTheme(ColorScheme scheme, Brightness brightness) {
    final seed = ThemeData(brightness: brightness, useMaterial3: true).textTheme;
    final inter = GoogleFonts.interTextTheme(seed).apply(
      bodyColor: scheme.onSurface,
      displayColor: scheme.onSurface,
    );
    return inter.copyWith(
      displayLarge: GoogleFonts.inter(textStyle: inter.displayLarge, fontWeight: FontWeight.w600, letterSpacing: -0.5),
      displayMedium: GoogleFonts.inter(textStyle: inter.displayMedium, fontWeight: FontWeight.w600),
      displaySmall: GoogleFonts.inter(textStyle: inter.displaySmall, fontWeight: FontWeight.w600),
      headlineLarge: GoogleFonts.inter(textStyle: inter.headlineLarge, fontWeight: FontWeight.w600, letterSpacing: -0.35),
      headlineMedium: GoogleFonts.inter(textStyle: inter.headlineMedium, fontWeight: FontWeight.w600, letterSpacing: -0.25),
      headlineSmall: GoogleFonts.inter(textStyle: inter.headlineSmall, fontWeight: FontWeight.w600, letterSpacing: -0.2),
      titleLarge: GoogleFonts.inter(
        textStyle: inter.titleLarge,
        fontSize: 17,
        fontWeight: FontWeight.w600,
        letterSpacing: -0.28,
        height: 1.25,
      ),
      titleMedium: GoogleFonts.inter(textStyle: inter.titleMedium, fontSize: 15, fontWeight: FontWeight.w500, letterSpacing: -0.15),
      titleSmall: GoogleFonts.inter(textStyle: inter.titleSmall, fontSize: 14, fontWeight: FontWeight.w500, letterSpacing: -0.1),
      bodyLarge: GoogleFonts.inter(textStyle: inter.bodyLarge, fontSize: 16, height: 1.5, letterSpacing: -0.1),
      bodyMedium: GoogleFonts.inter(textStyle: inter.bodyMedium, fontSize: 14, height: 1.45, letterSpacing: -0.05),
      bodySmall: GoogleFonts.inter(textStyle: inter.bodySmall, fontSize: 12, height: 1.35, color: scheme.onSurfaceVariant),
      labelLarge: GoogleFonts.inter(textStyle: inter.labelLarge, fontWeight: FontWeight.w500, letterSpacing: -0.05),
      labelMedium: GoogleFonts.inter(textStyle: inter.labelMedium, fontWeight: FontWeight.w500, letterSpacing: 0.02),
      labelSmall: GoogleFonts.inter(
        textStyle: inter.labelSmall,
        fontSize: 12,
        fontWeight: FontWeight.w500,
        letterSpacing: 0.2,
        height: 1.35,
        color: scheme.onSurfaceVariant,
      ),
    );
  }

  static ThemeData _build({required Brightness brightness}) {
    final isLight = brightness == Brightness.light;
    final scheme = _scheme(brightness);
    final textTheme = _textTheme(scheme, brightness);
    const transition = SynctraFadeUpTransitionsBuilder();

    final fillInput = isLight ? const Color(0xFFF7F7F4) : AppColorsDark.surface;

    return ThemeData(
      useMaterial3: true,
      brightness: brightness,
      colorScheme: scheme,
      scaffoldBackgroundColor: isLight ? AppColors.surface : AppColorsDark.background,
      fontFamily: GoogleFonts.inter().fontFamily,
      textTheme: textTheme,
      pageTransitionsTheme: const PageTransitionsTheme(
        builders: {
          TargetPlatform.android: transition,
          TargetPlatform.iOS: transition,
          TargetPlatform.linux: transition,
          TargetPlatform.macOS: transition,
          TargetPlatform.windows: transition,
          TargetPlatform.fuchsia: transition,
        },
      ),
      appBarTheme: AppBarTheme(
        elevation: 0,
        scrolledUnderElevation: 0,
        backgroundColor: scheme.surface,
        foregroundColor: scheme.onSurface,
        surfaceTintColor: Colors.transparent,
        centerTitle: false,
        toolbarHeight: 48,
        titleSpacing: 16,
        titleTextStyle: GoogleFonts.inter(
          fontSize: 15,
          fontWeight: FontWeight.w500,
          letterSpacing: -0.2,
          color: scheme.onSurface,
        ),
      ),
      navigationBarTheme: NavigationBarThemeData(
        elevation: 0,
        height: 60,
        backgroundColor: scheme.surface,
        surfaceTintColor: Colors.transparent,
        indicatorColor: scheme.surfaceContainerHighest.withValues(alpha: isLight ? 0.9 : 0.65),
        labelBehavior: NavigationDestinationLabelBehavior.alwaysShow,
        labelTextStyle: WidgetStateProperty.resolveWith((states) {
          final selected = states.contains(WidgetState.selected);
          return GoogleFonts.inter(
            fontSize: 12,
            fontWeight: selected ? FontWeight.w600 : FontWeight.w500,
            letterSpacing: 0,
            height: 1.3,
            color: selected ? scheme.onSurface : scheme.onSurfaceVariant,
          );
        }),
        iconTheme: WidgetStateProperty.resolveWith((states) {
          final selected = states.contains(WidgetState.selected);
          return IconThemeData(
            size: 24,
            color: selected ? scheme.onSurface : scheme.onSurfaceVariant,
          );
        }),
      ),
      cardTheme: CardThemeData(
        elevation: 0,
        color: scheme.surface,
        surfaceTintColor: Colors.transparent,
        margin: EdgeInsets.zero,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(8),
          side: BorderSide(color: scheme.outlineVariant),
        ),
      ),
      dividerTheme: DividerThemeData(color: scheme.outlineVariant, thickness: 1),
      dialogTheme: DialogThemeData(
        backgroundColor: scheme.surface,
        surfaceTintColor: Colors.transparent,
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(8)),
        elevation: 16,
        shadowColor: Colors.black.withValues(alpha: 0.1),
        titleTextStyle: GoogleFonts.inter(
          fontSize: 16,
          fontWeight: FontWeight.w600,
          letterSpacing: -0.2,
          color: scheme.onSurface,
        ),
        contentTextStyle: GoogleFonts.inter(
          fontSize: 14,
          height: 1.45,
          color: scheme.onSurfaceVariant,
        ),
      ),
      bottomSheetTheme: BottomSheetThemeData(
        backgroundColor: scheme.surface,
        surfaceTintColor: Colors.transparent,
        shape: const RoundedRectangleBorder(
          borderRadius: BorderRadius.vertical(top: Radius.circular(12)),
        ),
        dragHandleColor: scheme.onSurfaceVariant.withValues(alpha: 0.35),
        showDragHandle: true,
      ),
      snackBarTheme: SnackBarThemeData(
        behavior: SnackBarBehavior.floating,
        elevation: 8,
        backgroundColor: isLight ? scheme.surface : const Color(0xFF2E2E2E),
        actionTextColor: scheme.primary,
        contentTextStyle: GoogleFonts.inter(
          color: isLight ? scheme.onSurface : const Color(0xFFECEBE8),
          fontSize: 14,
          fontWeight: FontWeight.w500,
          height: 1.35,
        ),
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(8),
          side: BorderSide(
            color: isLight ? scheme.outlineVariant : scheme.outline.withValues(alpha: 0.35),
          ),
        ),
      ),
      tooltipTheme: TooltipThemeData(
        waitDuration: const Duration(milliseconds: 450),
        showDuration: const Duration(seconds: 4),
        decoration: BoxDecoration(
          color: isLight ? scheme.surface : const Color(0xFF2E2E2E),
          borderRadius: BorderRadius.circular(6),
          border: Border.all(
            color: isLight ? scheme.outlineVariant : scheme.outline.withValues(alpha: 0.4),
          ),
          boxShadow: [
            BoxShadow(
              color: Colors.black.withValues(alpha: isLight ? 0.06 : 0.35),
              blurRadius: 12,
              offset: const Offset(0, 4),
            ),
          ],
        ),
        textStyle: GoogleFonts.inter(
          color: isLight ? scheme.onSurface : const Color(0xFFECEBE8),
          fontSize: 12,
          fontWeight: FontWeight.w500,
          height: 1.25,
        ),
      ),
      popupMenuTheme: PopupMenuThemeData(
        color: scheme.surface,
        surfaceTintColor: Colors.transparent,
        elevation: 12,
        shadowColor: Colors.black.withValues(alpha: 0.1),
        textStyle: GoogleFonts.inter(color: scheme.onSurface, fontSize: 14, fontWeight: FontWeight.w400),
      ),
      floatingActionButtonTheme: FloatingActionButtonThemeData(
        backgroundColor: scheme.primary,
        foregroundColor: scheme.onPrimary,
        elevation: 1,
        highlightElevation: 2,
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(8)),
      ),
      segmentedButtonTheme: SegmentedButtonThemeData(
        style: ButtonStyle(
          visualDensity: VisualDensity.compact,
          padding: WidgetStateProperty.all(const EdgeInsets.symmetric(horizontal: 12, vertical: 8)),
          side: WidgetStateProperty.all(BorderSide(color: scheme.outlineVariant)),
          shape: WidgetStateProperty.all(RoundedRectangleBorder(borderRadius: BorderRadius.circular(6))),
        ),
      ),
      inputDecorationTheme: InputDecorationTheme(
        filled: true,
        fillColor: fillInput,
        border: OutlineInputBorder(borderRadius: BorderRadius.circular(8)),
        enabledBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(8),
          borderSide: BorderSide(color: scheme.outlineVariant),
        ),
        focusedBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(8),
          borderSide: BorderSide(color: scheme.primary, width: 2),
        ),
        errorBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(8),
          borderSide: BorderSide(color: scheme.error),
        ),
        focusedErrorBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(8),
          borderSide: BorderSide(color: scheme.error, width: 2),
        ),
        contentPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 14),
        hintStyle: TextStyle(color: scheme.onSurfaceVariant.withValues(alpha: 0.8), fontSize: 14, height: 1.4),
        helperStyle: TextStyle(color: scheme.onSurfaceVariant, fontSize: 12, height: 1.4),
        errorStyle: TextStyle(color: scheme.error, fontSize: 12, height: 1.35),
      ),
      filledButtonTheme: FilledButtonThemeData(
        style: FilledButton.styleFrom(
          minimumSize: const Size(64, 44),
          elevation: 0,
          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(8)),
          textStyle: GoogleFonts.inter(fontSize: 14, fontWeight: FontWeight.w600, letterSpacing: -0.02, height: 1.2),
        ).copyWith(
          overlayColor: WidgetStateProperty.resolveWith((states) {
            if (states.contains(WidgetState.pressed)) {
              return scheme.onPrimary.withValues(alpha: 0.12);
            }
            if (states.contains(WidgetState.hovered)) {
              return scheme.onPrimary.withValues(alpha: 0.08);
            }
            return null;
          }),
        ),
      ),
      outlinedButtonTheme: OutlinedButtonThemeData(
        style: OutlinedButton.styleFrom(
          minimumSize: const Size(64, 44),
          side: BorderSide(color: scheme.outlineVariant),
          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(8)),
          textStyle: GoogleFonts.inter(fontSize: 14, fontWeight: FontWeight.w500, height: 1.2),
        ),
      ),
      textButtonTheme: TextButtonThemeData(
        style: TextButton.styleFrom(
          minimumSize: const Size(48, 44),
          textStyle: GoogleFonts.inter(fontSize: 14, fontWeight: FontWeight.w500, height: 1.2),
          foregroundColor: scheme.primary,
        ),
      ),
      chipTheme: ChipThemeData(
        labelStyle: GoogleFonts.inter(textStyle: textTheme.labelMedium),
        side: BorderSide(color: scheme.outlineVariant),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(4)),
        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 0),
      ),
      listTileTheme: ListTileThemeData(
        titleTextStyle: textTheme.titleMedium,
        subtitleTextStyle: textTheme.bodySmall,
        iconColor: scheme.onSurfaceVariant,
        contentPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 4),
        minVerticalPadding: 12,
        minLeadingWidth: 24,
      ),
      progressIndicatorTheme: ProgressIndicatorThemeData(
        color: scheme.primary,
        circularTrackColor: scheme.outlineVariant.withValues(alpha: 0.35),
      ),
    );
  }
}

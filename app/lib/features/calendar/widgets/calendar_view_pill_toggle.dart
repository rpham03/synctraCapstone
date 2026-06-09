import 'package:flutter/material.dart';

import '../../../core/theme/app_tokens.dart';
import '../../../theme.dart';

/// Reclaim-style Day / Week / Month segmented control.
class CalendarViewPillToggle<T extends Object> extends StatelessWidget {
  const CalendarViewPillToggle({
    super.key,
    required this.segments,
    required this.selected,
    required this.onChanged,
    required this.labelBuilder,
  });

  final List<T> segments;
  final T selected;
  final ValueChanged<T> onChanged;
  final String Function(T value) labelBuilder;

  @override
  Widget build(BuildContext context) {
    final brightness = Theme.of(context).brightness;
    final isDark = brightness == Brightness.dark;
    final track = isDark
        ? AppColorsDark.border.withValues(alpha: 0.55)
        : AppColors.grey100;

    return Container(
      padding: const EdgeInsets.all(3),
      decoration: BoxDecoration(
        color: track,
        borderRadius: BorderRadius.circular(AppTokens.radiusLg),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          for (var i = 0; i < segments.length; i++)
            _PillSegment(
              label: labelBuilder(segments[i]),
              selected: segments[i] == selected,
              onTap: () => onChanged(segments[i]),
              brightness: brightness,
            ),
        ],
      ),
    );
  }
}

class _PillSegment extends StatelessWidget {
  const _PillSegment({
    required this.label,
    required this.selected,
    required this.onTap,
    required this.brightness,
  });

  final String label;
  final bool selected;
  final VoidCallback onTap;
  final Brightness brightness;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final isDark = brightness == Brightness.dark;

    return AnimatedContainer(
      duration: AppTokens.calendarViewCrossfade,
      curve: AppTokens.calendarPanelCurve,
      decoration: BoxDecoration(
        color: selected
            ? (isDark ? scheme.surfaceContainerHighest : scheme.surface)
            : Colors.transparent,
        borderRadius: BorderRadius.circular(AppTokens.radiusMd),
        boxShadow: selected && !isDark
            ? [
                BoxShadow(
                  color: Colors.black.withValues(alpha: 0.05),
                  blurRadius: 2,
                  offset: const Offset(0, 1),
                ),
              ]
            : null,
      ),
      child: Material(
        color: Colors.transparent,
        child: InkWell(
          onTap: onTap,
          borderRadius: BorderRadius.circular(AppTokens.radiusMd),
          child: Padding(
            padding: const EdgeInsets.symmetric(
              horizontal: AppTokens.space16,
              vertical: AppTokens.space8,
            ),
            child: Text(
              label,
              style: CalendarTextStyles.upcomingRow(brightness).copyWith(
                fontSize: 13,
                fontWeight: selected ? FontWeight.w600 : FontWeight.w500,
                color: selected
                    ? (isDark ? scheme.onSurface : AppColors.textPrimary)
                    : AppColors.textSecondary,
              ),
            ),
          ),
        ),
      ),
    );
  }
}

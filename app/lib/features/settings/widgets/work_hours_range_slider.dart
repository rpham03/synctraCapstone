import 'package:flutter/material.dart';
import 'package:intl/intl.dart';

import '../../../core/theme/app_tokens.dart';
import '../../../theme.dart';

/// 30-minute slots from midnight: 0 = 12:00 AM, 48 = 12:00 AM (next day).
class WorkHoursSlots {
  WorkHoursSlots._();

  static const int min = 0;
  static const int max = 48;
  static const int defaultStart = 18; // 9:00 AM
  static const int defaultEnd = 44; // 10:00 PM

  static TimeOfDay slotToTime(int slot) {
    final clamped = slot.clamp(min, max);
    final totalMinutes = clamped * 30;
    return TimeOfDay(hour: (totalMinutes ~/ 60) % 24, minute: totalMinutes % 60);
  }

  static int timeToSlot(TimeOfDay time) {
    return (time.hour * 2 + time.minute ~/ 30).clamp(min, max);
  }

  static String formatSlot(int slot) {
    final dt = DateTime(2026, 1, 1).add(Duration(minutes: slot * 30));
    return DateFormat.jm().format(dt);
  }

  static String storageFormat(TimeOfDay time) =>
      '${time.hour.toString().padLeft(2, '0')}:${time.minute.toString().padLeft(2, '0')}';

  static RangeValues defaultRange() =>
      RangeValues(defaultStart.toDouble(), defaultEnd.toDouble());

  static RangeValues fromTimes(TimeOfDay start, TimeOfDay end) {
    return RangeValues(
      timeToSlot(start).toDouble(),
      timeToSlot(end).toDouble(),
    );
  }
}

/// Horizontal 24-hour range picker for [work_start_time] / [work_end_time].
class WorkHoursRangeSlider extends StatelessWidget {
  final RangeValues range;
  final ValueChanged<RangeValues> onChanged;
  final bool showHeader;
  final String? headline;
  final String? subtitle;
  final String? purposeLine;
  final bool showSessionSliders;
  final int sessionMinutes;
  final int breakMinutes;
  final ValueChanged<int>? onSessionChanged;
  final ValueChanged<int>? onBreakChanged;

  const WorkHoursRangeSlider({
    super.key,
    required this.range,
    required this.onChanged,
    this.showHeader = true,
    this.headline,
    this.subtitle,
    this.purposeLine,
    this.showSessionSliders = false,
    this.sessionMinutes = 60,
    this.breakMinutes = 10,
    this.onSessionChanged,
    this.onBreakChanged,
  });

  @override
  Widget build(BuildContext context) {
    final brightness = Theme.of(context).brightness;
    final scheme = Theme.of(context).colorScheme;
    final onSurface = scheme.onSurface;
    final startSlot = range.start.round();
    final endSlot = range.end.round();
    final startLabel = WorkHoursSlots.formatSlot(startSlot);
    final endLabel = WorkHoursSlots.formatSlot(endSlot);

    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        if (showHeader) ...[
          Text(
            headline ?? 'When do you do your best work?',
            style: CalendarTextStyles.topBarDate(brightness).copyWith(
              fontSize: 20,
              fontWeight: FontWeight.w600,
            ),
          ),
          const SizedBox(height: AppTokens.space8),
          Text(
            subtitle ?? 'Drag to set your typical study window.',
            style: CalendarTextStyles.upcomingRow(brightness).copyWith(height: 1.5),
          ),
          if (purposeLine != null) ...[
            const SizedBox(height: AppTokens.space8),
            Text(
              purposeLine!,
              style: CalendarTextStyles.hourLabel(brightness).copyWith(
                fontSize: 12,
                height: 1.45,
              ),
            ),
          ],
          const SizedBox(height: AppTokens.space24),
        ],
        Text(
          'STUDY WINDOW',
          style: CalendarTextStyles.sidebarSectionHeader(brightness),
        ),
        const SizedBox(height: AppTokens.space12),
        Row(
          mainAxisAlignment: MainAxisAlignment.spaceBetween,
          children: [
            _TimeChip(label: 'Start', time: startLabel),
            _TimeChip(label: 'End', time: endLabel),
          ],
        ),
        const SizedBox(height: AppTokens.space8),
        SliderTheme(
          data: SliderTheme.of(context).copyWith(
            trackHeight: 4,
            activeTrackColor: AppColors.primary,
            inactiveTrackColor: AppTokens.calendarDivider(context).withValues(alpha: 0.5),
            rangeThumbShape: const RoundRangeSliderThumbShape(enabledThumbRadius: 10),
            overlayShape: const RoundSliderOverlayShape(overlayRadius: 18),
          ),
          child: RangeSlider(
            values: range,
            min: WorkHoursSlots.min.toDouble(),
            max: WorkHoursSlots.max.toDouble(),
            divisions: WorkHoursSlots.max,
            labels: RangeLabels(startLabel, endLabel),
            onChanged: (next) {
              if (next.end - next.start < 1) return;
              onChanged(next);
            },
          ),
        ),
        Row(
          mainAxisAlignment: MainAxisAlignment.spaceBetween,
          children: [
            for (final label in ['12 AM', '6 AM', '12 PM', '6 PM', '12 AM'])
              Text(
                label,
                style: CalendarTextStyles.hourLabel(brightness),
              ),
          ],
        ),
        const SizedBox(height: AppTokens.space20),
        Text(
          "You'll get study blocks from $startLabel to $endLabel",
          style: CalendarTextStyles.upcomingRow(brightness).copyWith(
            color: onSurface.withValues(alpha: 0.85),
          ),
        ),
        if (showSessionSliders) ...[
          const SizedBox(height: AppTokens.space32),
          Text(
            'SESSION LENGTH',
            style: CalendarTextStyles.sidebarSectionHeader(brightness),
          ),
          const SizedBox(height: AppTokens.space4),
          Text(
            'How long each focus block should last before you take a break.',
            style: CalendarTextStyles.hourLabel(brightness).copyWith(
              fontSize: 12,
              height: 1.4,
            ),
          ),
          const SizedBox(height: AppTokens.space8),
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              Text(
                '$sessionMinutes min',
                style: CalendarTextStyles.upcomingRow(brightness).copyWith(
                  fontWeight: FontWeight.w600,
                ),
              ),
              Text(
                '15–120 min',
                style: CalendarTextStyles.hourLabel(brightness),
              ),
            ],
          ),
          Slider(
            value: sessionMinutes.toDouble(),
            min: 15,
            max: 120,
            divisions: 7,
            activeColor: AppColors.primary,
            label: '$sessionMinutes min',
            onChanged: onSessionChanged == null ? null : (v) => onSessionChanged!(v.round()),
          ),
          const SizedBox(height: AppTokens.space20),
          Text(
            'BREAK BETWEEN BLOCKS',
            style: CalendarTextStyles.sidebarSectionHeader(brightness),
          ),
          const SizedBox(height: AppTokens.space4),
          Text(
            'A short pause Synctra leaves between study sessions.',
            style: CalendarTextStyles.hourLabel(brightness).copyWith(
              fontSize: 12,
              height: 1.4,
            ),
          ),
          const SizedBox(height: AppTokens.space8),
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              Text(
                '$breakMinutes min',
                style: CalendarTextStyles.upcomingRow(brightness).copyWith(
                  fontWeight: FontWeight.w600,
                ),
              ),
              Text(
                '5–30 min',
                style: CalendarTextStyles.hourLabel(brightness),
              ),
            ],
          ),
          Slider(
            value: breakMinutes.toDouble(),
            min: 5,
            max: 30,
            divisions: 5,
            activeColor: AppColors.primary,
            label: '$breakMinutes min',
            onChanged: onBreakChanged == null ? null : (v) => onBreakChanged!(v.round()),
          ),
        ],
      ],
    );
  }
}

class _TimeChip extends StatelessWidget {
  final String label;
  final String time;

  const _TimeChip({
    required this.label,
    required this.time,
  });

  @override
  Widget build(BuildContext context) {
    final brightness = Theme.of(context).brightness;
    final divider = AppTokens.calendarDivider(context);
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
      decoration: BoxDecoration(
        color: AppTokens.calendarGridSurface(context),
        borderRadius: BorderRadius.circular(AppTokens.radiusMd),
        border: Border.all(
          color: divider,
          width: AppTokens.calendarDividerThickness,
        ),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(label, style: CalendarTextStyles.hourLabel(brightness)),
          Text(
            time,
            style: CalendarTextStyles.upcomingRow(brightness).copyWith(
              fontWeight: FontWeight.w600,
              color: AppColors.primary,
            ),
          ),
        ],
      ),
    );
  }
}

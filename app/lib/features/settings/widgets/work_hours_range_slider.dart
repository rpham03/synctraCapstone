import 'package:flutter/material.dart';
import 'package:intl/intl.dart';

import '../../../core/theme/app_tokens.dart';

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
    final scheme = Theme.of(context).colorScheme;
    final onSurface = scheme.onSurface;
    final startSlot = range.start.round();
    final endSlot = range.end.round();
    final startLabel = WorkHoursSlots.formatSlot(startSlot);
    final endLabel = WorkHoursSlots.formatSlot(endSlot);
    final bodySmall = Theme.of(context).textTheme.bodySmall;

    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        if (showHeader) ...[
          Text(
            headline ?? 'When do you do your best work?',
            style: Theme.of(context).textTheme.headlineSmall?.copyWith(
                  fontWeight: FontWeight.w600,
                  color: onSurface,
                ),
          ),
          const SizedBox(height: 8),
          Text(
            subtitle ?? 'Drag to set your typical study window.',
            style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                  color: scheme.onSurfaceVariant,
                  height: 1.45,
                ),
          ),
          if (purposeLine != null) ...[
            const SizedBox(height: 6),
            Text(
              purposeLine!,
              style: bodySmall?.copyWith(
                color: scheme.onSurfaceVariant.withValues(alpha: 0.9),
                height: 1.4,
              ),
            ),
          ],
          const SizedBox(height: AppTokens.space24),
        ],
        Text(
          'Study window',
          style: Theme.of(context).textTheme.titleSmall?.copyWith(color: onSurface),
        ),
        const SizedBox(height: AppTokens.space12),
        Row(
          mainAxisAlignment: MainAxisAlignment.spaceBetween,
          children: [
            _TimeChip(label: 'Start', time: startLabel, color: scheme.primary),
            _TimeChip(label: 'End', time: endLabel, color: scheme.primary),
          ],
        ),
        const SizedBox(height: AppTokens.space8),
        SliderTheme(
          data: SliderTheme.of(context).copyWith(
            trackHeight: 4,
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
            Text('12 AM', style: Theme.of(context).textTheme.labelSmall?.copyWith(color: scheme.onSurfaceVariant)),
            Text('6 AM', style: Theme.of(context).textTheme.labelSmall?.copyWith(color: scheme.onSurfaceVariant)),
            Text('12 PM', style: Theme.of(context).textTheme.labelSmall?.copyWith(color: scheme.onSurfaceVariant)),
            Text('6 PM', style: Theme.of(context).textTheme.labelSmall?.copyWith(color: scheme.onSurfaceVariant)),
            Text('12 AM', style: Theme.of(context).textTheme.labelSmall?.copyWith(color: scheme.onSurfaceVariant)),
          ],
        ),
        const SizedBox(height: 20),
        Text(
          "You'll get study blocks from $startLabel to $endLabel",
          style: TextStyle(color: onSurface.withValues(alpha: 0.85), height: 1.4),
        ),
        if (showSessionSliders) ...[
          const SizedBox(height: AppTokens.space32),
          Text(
            'Study session length',
            style: Theme.of(context).textTheme.titleSmall?.copyWith(color: onSurface),
          ),
          const SizedBox(height: 4),
          Text(
            'How long each focus block should last before you take a break.',
            style: bodySmall?.copyWith(color: scheme.onSurfaceVariant, height: 1.4),
          ),
          const SizedBox(height: 8),
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              Text('$sessionMinutes min', style: TextStyle(fontWeight: FontWeight.w600, color: onSurface)),
              Text('15–120 min', style: bodySmall?.copyWith(color: scheme.onSurfaceVariant)),
            ],
          ),
          Slider(
            value: sessionMinutes.toDouble(),
            min: 15,
            max: 120,
            divisions: 7,
            label: '$sessionMinutes min',
            onChanged: onSessionChanged == null ? null : (v) => onSessionChanged!(v.round()),
          ),
          const SizedBox(height: 20),
          Text(
            'Break between blocks',
            style: Theme.of(context).textTheme.titleSmall?.copyWith(color: onSurface),
          ),
          const SizedBox(height: 4),
          Text(
            'A short pause Synctra leaves between study sessions.',
            style: bodySmall?.copyWith(color: scheme.onSurfaceVariant, height: 1.4),
          ),
          const SizedBox(height: 8),
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              Text('$breakMinutes min', style: TextStyle(fontWeight: FontWeight.w600, color: onSurface)),
              Text('5–30 min', style: bodySmall?.copyWith(color: scheme.onSurfaceVariant)),
            ],
          ),
          Slider(
            value: breakMinutes.toDouble(),
            min: 5,
            max: 30,
            divisions: 5,
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
  final Color color;

  const _TimeChip({
    required this.label,
    required this.time,
    required this.color,
  });

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
      decoration: BoxDecoration(
        color: scheme.surfaceContainerHighest.withValues(alpha: 0.5),
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: scheme.outlineVariant),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(label, style: Theme.of(context).textTheme.labelSmall?.copyWith(color: scheme.onSurfaceVariant)),
          Text(time, style: TextStyle(fontWeight: FontWeight.w600, color: color)),
        ],
      ),
    );
  }
}

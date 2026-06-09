import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';
import 'package:table_calendar/table_calendar.dart';

import '../../../core/theme/app_tokens.dart';
import '../../../theme.dart';

/// Upcoming row shown in the calendar left sidebar.
class CalendarUpcomingItem {
  const CalendarUpcomingItem({
    required this.title,
    required this.timeLabel,
    required this.color,
    required this.targetDay,
  });

  final String title;
  final String timeLabel;
  final Color color;
  final DateTime targetDay;
}

/// Feed chip for toggling iCal source visibility on the main grid.
class CalendarFeedChipData {
  const CalendarFeedChipData({
    required this.id,
    required this.name,
    required this.color,
    required this.visible,
  });

  final String id;
  final String name;
  final Color color;
  final bool visible;
}

/// Reclaim-style planner sidebar — mini month, upcoming, source filters.
class CalendarLeftSidebar extends StatelessWidget {
  const CalendarLeftSidebar({
    super.key,
    required this.focusedDay,
    required this.selectedDay,
    required this.onDaySelected,
    required this.onPageChanged,
    required this.upcoming,
    required this.feedChips,
    required this.onUpcomingTap,
    required this.onFeedToggle,
  });

  final DateTime focusedDay;
  final DateTime selectedDay;
  final void Function(DateTime selected, DateTime focused) onDaySelected;
  final ValueChanged<DateTime> onPageChanged;
  final List<CalendarUpcomingItem> upcoming;
  final List<CalendarFeedChipData> feedChips;
  final ValueChanged<DateTime> onUpcomingTap;
  final ValueChanged<String> onFeedToggle;

  @override
  Widget build(BuildContext context) {
    final brightness = Theme.of(context).brightness;
    final divider = AppTokens.calendarDivider(context);
    final isDark = brightness == Brightness.dark;

    return DecoratedBox(
      decoration: BoxDecoration(
        color: AppTokens.calendarSidebarSurface(context),
        border: Border(
          right: BorderSide(
            color: divider,
            width: AppTokens.calendarDividerThickness,
          ),
        ),
      ),
      child: SizedBox(
        width: AppTokens.calendarSidebarWidth,
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Padding(
              padding: const EdgeInsets.fromLTRB(
                AppTokens.space8,
                AppTokens.space16,
                AppTokens.space8,
                AppTokens.space4,
              ),
              child: TableCalendar<void>(
                firstDay: DateTime.utc(2020, 1, 1),
                lastDay: DateTime.utc(2035, 12, 31),
                focusedDay: focusedDay,
                selectedDayPredicate: (day) => isSameDay(day, selectedDay),
                calendarFormat: CalendarFormat.month,
                rowHeight: 36,
                daysOfWeekHeight: 24,
                availableGestures: AvailableGestures.horizontalSwipe,
                headerStyle: HeaderStyle(
                  formatButtonVisible: false,
                  titleCentered: true,
                  headerPadding: const EdgeInsets.only(bottom: AppTokens.space8),
                  titleTextStyle: CalendarTextStyles.topBarDate(brightness).copyWith(
                    fontSize: 14,
                    fontWeight: FontWeight.w600,
                  ),
                  leftChevronIcon: Icon(
                    Icons.chevron_left,
                    size: 18,
                    color: AppColors.textSecondary,
                  ),
                  rightChevronIcon: Icon(
                    Icons.chevron_right,
                    size: 18,
                    color: AppColors.textSecondary,
                  ),
                ),
                daysOfWeekStyle: DaysOfWeekStyle(
                  weekdayStyle: CalendarTextStyles.hourLabel(brightness),
                  weekendStyle: CalendarTextStyles.hourLabel(brightness),
                ),
                calendarStyle: CalendarStyle(
                  outsideDaysVisible: false,
                  cellMargin: const EdgeInsets.all(2),
                  defaultTextStyle: CalendarTextStyles.upcomingRow(brightness).copyWith(
                    fontSize: 12,
                  ),
                  weekendTextStyle: CalendarTextStyles.upcomingRow(brightness).copyWith(
                    fontSize: 12,
                    color: AppColors.textSecondary,
                  ),
                  selectedDecoration: const BoxDecoration(
                    color: AppColors.primary,
                    shape: BoxShape.circle,
                  ),
                  selectedTextStyle: GoogleFonts.inter(
                    fontSize: 12,
                    fontWeight: FontWeight.w600,
                    color: Colors.white,
                  ),
                  todayDecoration: BoxDecoration(
                    shape: BoxShape.circle,
                    color: isDark
                        ? AppColors.primary.withValues(alpha: 0.2)
                        : AppColors.primary.withValues(alpha: 0.12),
                    border: Border.all(color: AppColors.primary, width: 1),
                  ),
                  todayTextStyle: CalendarTextStyles.todayDateInCircle(brightness),
                ),
                onDaySelected: onDaySelected,
                onPageChanged: onPageChanged,
              ),
            ),
            Divider(height: 1, thickness: AppTokens.calendarDividerThickness, color: divider),
            _SectionLabel(title: 'UPCOMING', brightness: brightness),
            Expanded(
              child: upcoming.isEmpty
                  ? Padding(
                      padding: const EdgeInsets.symmetric(
                        horizontal: AppTokens.space16,
                        vertical: AppTokens.space8,
                      ),
                      child: Text(
                        'Nothing scheduled soon',
                        style: CalendarTextStyles.hourLabel(brightness),
                      ),
                    )
                  : ListView.separated(
                      padding: const EdgeInsets.fromLTRB(
                        AppTokens.space12,
                        AppTokens.space4,
                        AppTokens.space12,
                        AppTokens.space12,
                      ),
                      itemCount: upcoming.length,
                      separatorBuilder: (_, __) => const SizedBox(height: AppTokens.space4),
                      itemBuilder: (context, index) {
                        final item = upcoming[index];
                        return _UpcomingRow(
                          item: item,
                          brightness: brightness,
                          onTap: () => onUpcomingTap(item.targetDay),
                        );
                      },
                    ),
            ),
            if (feedChips.isNotEmpty) ...[
              Divider(height: 1, thickness: AppTokens.calendarDividerThickness, color: divider),
              _SectionLabel(title: 'SOURCES', brightness: brightness),
              Padding(
                padding: const EdgeInsets.fromLTRB(
                  AppTokens.space12,
                  0,
                  AppTokens.space12,
                  AppTokens.space16,
                ),
                child: Wrap(
                  spacing: AppTokens.space8,
                  runSpacing: AppTokens.space8,
                  children: [
                    for (final chip in feedChips)
                      _SourceChip(
                        label: chip.name,
                        color: chip.color,
                        selected: chip.visible,
                        brightness: brightness,
                        onTap: () => onFeedToggle(chip.id),
                      ),
                  ],
                ),
              ),
            ],
          ],
        ),
      ),
    );
  }
}

class _SectionLabel extends StatelessWidget {
  const _SectionLabel({required this.title, required this.brightness});

  final String title;
  final Brightness brightness;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.fromLTRB(
        AppTokens.space16,
        AppTokens.space16,
        AppTokens.space16,
        AppTokens.space8,
      ),
      child: Text(
        title,
        style: CalendarTextStyles.sidebarSectionHeader(brightness),
      ),
    );
  }
}

class _UpcomingRow extends StatelessWidget {
  const _UpcomingRow({
    required this.item,
    required this.brightness,
    required this.onTap,
  });

  final CalendarUpcomingItem item;
  final Brightness brightness;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final isDark = brightness == Brightness.dark;

    return Material(
      color: Colors.transparent,
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(AppTokens.radiusMd),
        hoverColor: isDark
            ? Colors.white.withValues(alpha: 0.04)
            : AppColors.grey100.withValues(alpha: 0.8),
        child: Padding(
          padding: const EdgeInsets.symmetric(
            horizontal: AppTokens.space8,
            vertical: AppTokens.space8,
          ),
          child: Row(
            children: [
              Container(
                width: 7,
                height: 7,
                decoration: BoxDecoration(
                  color: item.color,
                  shape: BoxShape.circle,
                ),
              ),
              const SizedBox(width: AppTokens.space8),
              Expanded(
                child: Text(
                  item.title,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: CalendarTextStyles.upcomingRow(brightness).copyWith(
                    fontSize: 13,
                  ),
                ),
              ),
              const SizedBox(width: AppTokens.space8),
              Text(
                item.timeLabel,
                style: CalendarTextStyles.hourLabel(brightness),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _SourceChip extends StatelessWidget {
  const _SourceChip({
    required this.label,
    required this.color,
    required this.selected,
    required this.brightness,
    required this.onTap,
  });

  final String label;
  final Color color;
  final bool selected;
  final Brightness brightness;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final divider = AppTokens.calendarDivider(context);

    return Material(
      color: selected ? color.withValues(alpha: 0.12) : Colors.transparent,
      borderRadius: BorderRadius.circular(AppTokens.radiusMd),
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(AppTokens.radiusMd),
        child: Container(
          padding: const EdgeInsets.symmetric(
            horizontal: AppTokens.space8,
            vertical: AppTokens.space4,
          ),
          decoration: BoxDecoration(
            borderRadius: BorderRadius.circular(AppTokens.radiusMd),
            border: Border.all(
              color: selected ? color.withValues(alpha: 0.5) : divider,
            ),
          ),
          child: Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              Container(
                width: 8,
                height: 8,
                decoration: BoxDecoration(color: color, shape: BoxShape.circle),
              ),
              const SizedBox(width: AppTokens.space4),
              Text(
                label,
                style: CalendarTextStyles.upcomingRow(brightness).copyWith(
                  fontSize: 12,
                  color: selected ? AppColors.textPrimary : AppColors.textSecondary,
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

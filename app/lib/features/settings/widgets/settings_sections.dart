import 'package:flutter/material.dart';
import 'package:intl/intl.dart';

import '../../../core/theme/app_theme.dart';
import '../../../data/models/ical_feed.dart';
import '../../../shared/widgets/synctra_page_scaffold.dart';
import '../../../theme.dart';
import 'work_hours_range_slider.dart';

/// Muted section label — smaller/lighter than row titles (settings hierarchy).
class SettingsSectionHeader extends StatelessWidget {
  final String title;
  final String? description;

  const SettingsSectionHeader(this.title, {super.key, this.description});

  @override
  Widget build(BuildContext context) {
    final brightness = Theme.of(context).brightness;
    return Padding(
      padding: const EdgeInsets.only(
        top: AppTokens.space24,
        bottom: AppTokens.space8,
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            title.toUpperCase(),
            style: CalendarTextStyles.sidebarSectionHeader(brightness),
          ),
          if (description != null) ...[
            const SizedBox(height: AppTokens.space4),
            Text(
              description!,
              style: CalendarTextStyles.hourLabel(brightness).copyWith(
                fontSize: 12,
                height: 1.45,
              ),
            ),
          ],
        ],
      ),
    );
  }
}

/// Settings row with ≥48dp tap target, label + optional description.
class SettingsActionRow extends StatelessWidget {
  final IconData? icon;
  final String label;
  final String? description;
  final Widget? trailing;
  final VoidCallback? onTap;
  final Color? foregroundColor;

  const SettingsActionRow({
    super.key,
    this.icon,
    required this.label,
    this.description,
    this.trailing,
    this.onTap,
    this.foregroundColor,
  });

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final brightness = Theme.of(context).brightness;
    final color = foregroundColor ?? scheme.onSurface;

    return Material(
      color: Colors.transparent,
      child: InkWell(
        onTap: onTap,
        borderRadius: AppTokens.borderRadiusMd,
        child: ConstrainedBox(
          constraints: const BoxConstraints(minHeight: AppTokens.minTapTarget),
          child: Padding(
            padding: const EdgeInsets.symmetric(
              horizontal: AppTokens.space16,
              vertical: AppTokens.space12,
            ),
            child: Row(
              children: [
                if (icon != null) ...[
                  Icon(icon, size: AppTokens.iconStandard, color: color),
                  const SizedBox(width: AppTokens.space16),
                ],
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    mainAxisAlignment: MainAxisAlignment.center,
                    children: [
                      Text(
                        label,
                        style: CalendarTextStyles.upcomingRow(brightness).copyWith(
                          fontWeight: FontWeight.w600,
                          color: color,
                        ),
                      ),
                      if (description != null) ...[
                        const SizedBox(height: AppTokens.space4),
                        Text(
                          description!,
                          style: CalendarTextStyles.hourLabel(brightness).copyWith(
                            height: 1.45,
                          ),
                        ),
                      ],
                    ],
                  ),
                ),
                if (trailing != null) trailing!,
              ],
            ),
          ),
        ),
      ),
    );
  }
}

class SettingsInsetCard extends StatelessWidget {
  final Widget child;
  final EdgeInsetsGeometry? padding;

  const SettingsInsetCard({super.key, required this.child, this.padding});

  @override
  Widget build(BuildContext context) {
    final divider = AppTokens.calendarDivider(context);
    final surface = AppTokens.calendarGridSurface(context);

    return Container(
      decoration: BoxDecoration(
        color: surface,
        borderRadius: AppTokens.borderRadiusLg,
        border: Border.all(
          color: divider,
          width: AppTokens.calendarDividerThickness,
        ),
      ),
      clipBehavior: Clip.antiAlias,
      child: Padding(
        padding: padding ?? const EdgeInsets.all(AppTokens.space16),
        child: child,
      ),
    );
  }
}

/// Shared work-preference controls for settings.
class WorkPreferencesForm extends StatelessWidget {
  final TimeOfDay workStart;
  final TimeOfDay workEnd;
  final int sessionMinutes;
  final int breakMinutes;
  final ValueChanged<RangeValues> onWorkRangeChanged;
  final ValueChanged<int> onSessionChanged;
  final ValueChanged<int> onBreakChanged;

  const WorkPreferencesForm({
    super.key,
    required this.workStart,
    required this.workEnd,
    required this.sessionMinutes,
    required this.breakMinutes,
    required this.onWorkRangeChanged,
    required this.onSessionChanged,
    required this.onBreakChanged,
  });

  @override
  Widget build(BuildContext context) {
    return WorkHoursRangeSlider(
      range: WorkHoursSlots.fromTimes(workStart, workEnd),
      showHeader: false,
      showSessionSliders: true,
      sessionMinutes: sessionMinutes,
      breakMinutes: breakMinutes,
      onChanged: onWorkRangeChanged,
      onSessionChanged: onSessionChanged,
      onBreakChanged: onBreakChanged,
    );
  }
}

class IcalFeedEditor extends StatelessWidget {
  final TextEditingController controller;
  final bool loading;
  final String? statusMessage;
  final bool isError;
  final VoidCallback onAdd;
  final String hintText;
  final String? helperText;

  const IcalFeedEditor({
    super.key,
    required this.controller,
    required this.loading,
    this.statusMessage,
    this.isError = false,
    required this.onAdd,
    this.hintText = 'Paste iCal URL…',
    this.helperText,
  });

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Expanded(
              child: TextField(
                controller: controller,
                decoration: InputDecoration(
                  hintText: hintText,
                  helperText: isError ? null : helperText,
                  errorText: isError ? statusMessage : null,
                ),
              ),
            ),
            const SizedBox(width: AppTokens.space8),
            Padding(
              padding: const EdgeInsets.only(top: AppTokens.space4),
              child: loading
                  ? SizedBox(
                      width: 72,
                      height: AppTokens.buttonHeight,
                      child: Center(
                        child: SizedBox(
                          width: 18,
                          height: 18,
                          child: CircularProgressIndicator(
                            strokeWidth: 2,
                            color: scheme.primary,
                          ),
                        ),
                      ),
                    )
                  : SynctraPrimaryButton(onPressed: onAdd, label: 'Add'),
            ),
          ],
        ),
        if (!isError && statusMessage != null)
          Padding(
            padding: const EdgeInsets.only(top: AppTokens.space8),
            child: Text(
              statusMessage!,
              style: TextStyle(color: scheme.primary, fontSize: 14, height: 1.4),
            ),
          ),
      ],
    );
  }
}

class IcalFeedListTile extends StatelessWidget {
  final IcalFeed feed;
  final VoidCallback? onDelete;
  final VoidCallback? onRefresh;

  const IcalFeedListTile({
    super.key,
    required this.feed,
    this.onDelete,
    this.onRefresh,
  });

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final brightness = Theme.of(context).brightness;
    final synced = feed.lastSyncedAt != null
        ? 'Synced ${DateFormat.MMMd().add_jm().format(feed.lastSyncedAt!.toLocal())}'
        : 'Not synced yet';
    return SettingsInsetCard(
      padding: EdgeInsets.zero,
      child: ListTile(
        minVerticalPadding: 12,
        leading: Icon(Icons.check_circle_outline, color: AppColors.success, size: AppTokens.iconStandard),
        title: Text(
          feed.displayLabel,
          maxLines: 1,
          overflow: TextOverflow.ellipsis,
          style: CalendarTextStyles.upcomingRow(brightness).copyWith(
            fontWeight: FontWeight.w500,
          ),
        ),
        subtitle: Text(
          '$synced\n${feed.url}',
          maxLines: 2,
          overflow: TextOverflow.ellipsis,
          style: CalendarTextStyles.hourLabel(brightness).copyWith(height: 1.4),
        ),
        isThreeLine: true,
        trailing: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            if (onRefresh != null)
              IconButton(
                icon: const Icon(Icons.refresh, size: AppTokens.iconStandard),
                tooltip: 'Refresh feed',
                onPressed: onRefresh,
              ),
            if (onDelete != null)
              IconButton(
                icon: Icon(Icons.close, size: AppTokens.iconStandard, color: scheme.onSurfaceVariant),
                tooltip: 'Remove feed',
                onPressed: onDelete,
              ),
          ],
        ),
      ),
    );
  }
}

class CourseImportListTile extends StatelessWidget {
  final String name;
  final String url;
  final int totalImported;
  final VoidCallback? onDelete;
  final VoidCallback? onReimport;

  const CourseImportListTile({
    super.key,
    required this.name,
    required this.url,
    required this.totalImported,
    this.onDelete,
    this.onReimport,
  });

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final brightness = Theme.of(context).brightness;
    return SettingsInsetCard(
      padding: EdgeInsets.zero,
      child: ListTile(
        minVerticalPadding: 12,
        leading: const Icon(Icons.school_outlined, size: AppTokens.iconStandard),
        title: Text(
          name,
          style: CalendarTextStyles.upcomingRow(brightness).copyWith(
            fontWeight: FontWeight.w500,
          ),
        ),
        subtitle: Text(
          '$totalImported events · $url',
          maxLines: 2,
          overflow: TextOverflow.ellipsis,
          style: CalendarTextStyles.hourLabel(brightness).copyWith(height: 1.4),
        ),
        isThreeLine: true,
        trailing: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            if (onReimport != null)
              IconButton(
                icon: const Icon(Icons.refresh, size: AppTokens.iconStandard),
                tooltip: 'Re-import course',
                onPressed: onReimport,
              ),
            if (onDelete != null)
              IconButton(
                icon: Icon(Icons.close, size: AppTokens.iconStandard, color: scheme.onSurfaceVariant),
                tooltip: 'Remove course',
                onPressed: onDelete,
              ),
          ],
        ),
      ),
    );
  }
}

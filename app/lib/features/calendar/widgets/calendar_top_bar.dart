import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

import '../../../core/theme/app_tokens.dart';
import '../../../shared/widgets/sync_it_chrome.dart';
import '../../../theme.dart';
import 'calendar_view_pill_toggle.dart';

enum _TopBarOverflowAction { schedule, ical, course, settings }

/// Reclaim-style calendar toolbar — quiet chrome, grouped controls.
class CalendarTopBar<T extends Object> extends StatelessWidget {
  const CalendarTopBar({
    super.key,
    required this.dateRangeLabel,
    required this.viewMode,
    required this.viewSegments,
    required this.viewLabelBuilder,
    required this.onViewModeChanged,
    required this.onPrev,
    required this.onNext,
    required this.onToday,
    required this.onNew,
    required this.aiChatOpen,
    required this.onToggleAiChat,
    this.showMenuButton = false,
    this.onOpenMenu,
    this.calendarSidebarOpen = false,
    this.onToggleCalendarSidebar,
    this.onSuggestSchedule,
    this.onOpenIcal,
    this.onOpenCourseImport,
    this.pageTitle = 'Planner',
  });

  final String dateRangeLabel;
  final T viewMode;
  final List<T> viewSegments;
  final String Function(T mode) viewLabelBuilder;
  final ValueChanged<T> onViewModeChanged;
  final VoidCallback onPrev;
  final VoidCallback onNext;
  final VoidCallback onToday;
  final VoidCallback onNew;
  final bool aiChatOpen;
  final VoidCallback onToggleAiChat;
  final bool showMenuButton;
  final VoidCallback? onOpenMenu;
  final bool calendarSidebarOpen;
  final VoidCallback? onToggleCalendarSidebar;
  final VoidCallback? onSuggestSchedule;
  final VoidCallback? onOpenIcal;
  final VoidCallback? onOpenCourseImport;
  final String pageTitle;

  static const _wideBreakpoint = 900.0;

  @override
  Widget build(BuildContext context) {
    final brightness = Theme.of(context).brightness;
    final scheme = Theme.of(context).colorScheme;
    final divider = AppTokens.calendarDivider(context);
    final isDark = brightness == Brightness.dark;
    final controlBg = isDark
        ? scheme.surfaceContainerHigh.withValues(alpha: 0.65)
        : AppColors.grey100.withValues(alpha: 0.85);

    return Material(
      color: AppTokens.calendarGridSurface(context),
      elevation: 0,
      child: Container(
        height: AppTokens.calendarTopBarHeight,
        padding: const EdgeInsets.symmetric(horizontal: AppTokens.space16),
        decoration: BoxDecoration(
          color: AppTokens.calendarGridSurface(context),
          border: Border(
            bottom: BorderSide(
              color: divider,
              width: AppTokens.calendarDividerThickness,
            ),
          ),
        ),
        child: LayoutBuilder(
          builder: (context, constraints) {
            final wide = constraints.maxWidth >= _wideBreakpoint;

            return Row(
              children: [
                if (showMenuButton && onOpenMenu != null)
                  _GhostIconButton(
                    tooltip: 'Open planner sidebar',
                    icon: Icons.menu,
                    onPressed: onOpenMenu!,
                  ),
                if (onToggleCalendarSidebar != null)
                  _GhostIconButton(
                    tooltip: calendarSidebarOpen
                        ? 'Hide planner sidebar'
                        : 'Show planner sidebar',
                    icon: calendarSidebarOpen
                        ? Icons.view_sidebar
                        : Icons.view_sidebar_outlined,
                    onPressed: onToggleCalendarSidebar,
                    highlighted: calendarSidebarOpen,
                  ),
                if (pageTitle.isNotEmpty) ...[
                  Text(
                    pageTitle,
                    style: CalendarTextStyles.topBarDate(brightness).copyWith(
                      fontSize: 17,
                      fontWeight: FontWeight.w600,
                      letterSpacing: -0.3,
                    ),
                  ),
                  const SizedBox(width: AppTokens.space20),
                ],
                _NavCluster(
                  background: controlBg,
                  divider: divider,
                  onToday: onToday,
                  onPrev: onPrev,
                  onNext: onNext,
                  brightness: brightness,
                ),
                const SizedBox(width: AppTokens.space16),
                Expanded(
                  child: Text(
                    dateRangeLabel,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: CalendarTextStyles.topBarDate(brightness).copyWith(
                      fontSize: 15,
                      fontWeight: FontWeight.w600,
                      letterSpacing: -0.2,
                    ),
                  ),
                ),
                if (wide) ...[
                  CalendarViewPillToggle<T>(
                    segments: viewSegments,
                    selected: viewMode,
                    onChanged: onViewModeChanged,
                    labelBuilder: viewLabelBuilder,
                  ),
                  const SizedBox(width: AppTokens.space12),
                ] else
                  _CompactViewMenu<T>(
                    viewMode: viewMode,
                    viewSegments: viewSegments,
                    viewLabelBuilder: viewLabelBuilder,
                    onViewModeChanged: onViewModeChanged,
                  ),
                if (wide && onSuggestSchedule != null) ...[
                  const SizedBox(width: AppTokens.space8),
                  _AutoScheduleButton(onPressed: onSuggestSchedule!),
                ],
                if (wide)
                  PopupMenuButton<_TopBarOverflowAction>(
                    tooltip: 'More',
                    icon: Icon(Icons.more_horiz,
                        size: AppTokens.iconInline,
                        color: AppColors.textSecondary),
                    onSelected: (action) {
                      switch (action) {
                        case _TopBarOverflowAction.schedule:
                          onSuggestSchedule?.call();
                        case _TopBarOverflowAction.ical:
                          onOpenIcal?.call();
                        case _TopBarOverflowAction.course:
                          onOpenCourseImport?.call();
                        case _TopBarOverflowAction.settings:
                          context.push('/settings');
                      }
                    },
                    itemBuilder: (context) => [
                      if (onOpenIcal != null)
                        const PopupMenuItem(
                          value: _TopBarOverflowAction.ical,
                          child: Text('iCal feeds'),
                        ),
                      if (onOpenCourseImport != null)
                        const PopupMenuItem(
                          value: _TopBarOverflowAction.course,
                          child: Text('Course import'),
                        ),
                      const PopupMenuItem(
                        value: _TopBarOverflowAction.settings,
                        child: Text('Settings'),
                      ),
                    ],
                  )
                else
                  _TopBarOverflowMenu(
                    onSuggestSchedule: onSuggestSchedule,
                    onOpenIcal: onOpenIcal,
                    onOpenCourseImport: onOpenCourseImport,
                  ),
                const SizedBox(width: AppTokens.space8),
                SyncItLaunchButton(
                  isOpen: aiChatOpen,
                  onPressed: onToggleAiChat,
                  compact: true,
                  minimal: true,
                ),
                const SizedBox(width: AppTokens.space8),
                OutlinedButton.icon(
                  onPressed: onNew,
                  icon: const Icon(Icons.add, size: 16),
                  label: Text(wide ? 'New Task' : ''),
                  style: OutlinedButton.styleFrom(
                    visualDensity: VisualDensity.compact,
                    minimumSize: Size(wide ? 108 : 36, 34),
                    padding: EdgeInsets.symmetric(
                      horizontal: wide ? AppTokens.space16 : AppTokens.space8,
                    ),
                    backgroundColor: AppColors.surface,
                    foregroundColor: AppColors.textPrimary,
                    side: const BorderSide(color: AppColors.border),
                    elevation: 0,
                    shape: RoundedRectangleBorder(
                      borderRadius: BorderRadius.circular(AppTokens.radiusMd),
                    ),
                  ),
                ),
              ],
            );
          },
        ),
      ),
    );
  }
}

/// One-click week fill — distinct from Sync It chat.
class _AutoScheduleButton extends StatelessWidget {
  const _AutoScheduleButton({required this.onPressed});

  final VoidCallback onPressed;

  @override
  Widget build(BuildContext context) {
    final brightness = Theme.of(context).brightness;

    return Tooltip(
      message:
          'Auto-fill study blocks around your classes and events this week',
      child: TextButton.icon(
        onPressed: onPressed,
        icon: Icon(
          Icons.view_timeline_outlined,
          size: 16,
          color: AppColors.textSecondary,
        ),
        label: Text(
          'Auto-schedule',
          style: CalendarTextStyles.upcomingRow(brightness).copyWith(
            fontSize: 13,
            fontWeight: FontWeight.w500,
            color: AppColors.textSecondary,
          ),
        ),
        style: TextButton.styleFrom(
          visualDensity: VisualDensity.compact,
          minimumSize: const Size(0, 34),
          padding: const EdgeInsets.symmetric(horizontal: AppTokens.space8),
        ),
      ),
    );
  }
}

class _NavCluster extends StatelessWidget {
  const _NavCluster({
    required this.background,
    required this.divider,
    required this.onToday,
    required this.onPrev,
    required this.onNext,
    required this.brightness,
  });

  final Color background;
  final Color divider;
  final VoidCallback onToday;
  final VoidCallback onPrev;
  final VoidCallback onNext;
  final Brightness brightness;

  @override
  Widget build(BuildContext context) {
    return Container(
      height: 34,
      decoration: BoxDecoration(
        color: background,
        borderRadius: BorderRadius.circular(AppTokens.radiusMd),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          TextButton(
            onPressed: onToday,
            style: TextButton.styleFrom(
              visualDensity: VisualDensity.compact,
              minimumSize: const Size(0, 34),
              padding: const EdgeInsets.symmetric(horizontal: AppTokens.space12),
              foregroundColor: AppColors.textSecondary,
              textStyle: CalendarTextStyles.upcomingRow(brightness).copyWith(
                fontSize: 13,
                fontWeight: FontWeight.w500,
              ),
            ),
            child: const Text('Today'),
          ),
          Container(width: AppTokens.calendarDividerThickness, color: divider),
          _GhostIconButton(
            tooltip: 'Previous',
            icon: Icons.chevron_left,
            onPressed: onPrev,
            dense: true,
          ),
          _GhostIconButton(
            tooltip: 'Next',
            icon: Icons.chevron_right,
            onPressed: onNext,
            dense: true,
          ),
        ],
      ),
    );
  }
}

class _GhostIconButton extends StatelessWidget {
  const _GhostIconButton({
    required this.tooltip,
    required this.icon,
    required this.onPressed,
    this.dense = false,
    this.highlighted = false,
  });

  final String tooltip;
  final IconData icon;
  final VoidCallback? onPressed;
  final bool dense;
  final bool highlighted;

  @override
  Widget build(BuildContext context) {
    return IconButton(
      tooltip: tooltip,
      onPressed: onPressed,
      visualDensity: VisualDensity.compact,
      padding: EdgeInsets.all(dense ? AppTokens.space4 : AppTokens.space8),
      constraints: BoxConstraints(
        minWidth: dense ? 28 : 36,
        minHeight: dense ? 28 : 36,
      ),
      icon: Icon(icon, size: dense ? 18 : AppTokens.iconInline),
      color: highlighted ? AppColors.primary : AppColors.textSecondary,
    );
  }
}

class _CompactViewMenu<T extends Object> extends StatelessWidget {
  const _CompactViewMenu({
    required this.viewMode,
    required this.viewSegments,
    required this.viewLabelBuilder,
    required this.onViewModeChanged,
  });

  final T viewMode;
  final List<T> viewSegments;
  final String Function(T mode) viewLabelBuilder;
  final ValueChanged<T> onViewModeChanged;

  @override
  Widget build(BuildContext context) {
    return PopupMenuButton<T>(
      tooltip: 'Change view',
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: AppTokens.space8),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            Text(
              viewLabelBuilder(viewMode),
              style: CalendarTextStyles.topBarDate(
                Theme.of(context).brightness,
              ).copyWith(fontSize: 13, fontWeight: FontWeight.w600),
            ),
            Icon(Icons.expand_more, size: 18, color: AppColors.textSecondary),
          ],
        ),
      ),
      onSelected: onViewModeChanged,
      itemBuilder: (context) => [
        for (final mode in viewSegments)
          PopupMenuItem(
            value: mode,
            child: Text(viewLabelBuilder(mode)),
          ),
      ],
    );
  }
}

class _TopBarOverflowMenu extends StatelessWidget {
  const _TopBarOverflowMenu({
    this.onSuggestSchedule,
    this.onOpenIcal,
    this.onOpenCourseImport,
  });

  final VoidCallback? onSuggestSchedule;
  final VoidCallback? onOpenIcal;
  final VoidCallback? onOpenCourseImport;

  @override
  Widget build(BuildContext context) {
    return PopupMenuButton<_TopBarOverflowAction>(
      tooltip: 'More actions',
      icon: Icon(Icons.more_horiz,
          size: AppTokens.iconInline, color: AppColors.textSecondary),
      onSelected: (action) {
        switch (action) {
          case _TopBarOverflowAction.schedule:
            onSuggestSchedule?.call();
          case _TopBarOverflowAction.ical:
            onOpenIcal?.call();
          case _TopBarOverflowAction.course:
            onOpenCourseImport?.call();
          case _TopBarOverflowAction.settings:
            context.push('/settings');
        }
      },
      itemBuilder: (context) => [
        if (onSuggestSchedule != null)
          const PopupMenuItem(
            value: _TopBarOverflowAction.schedule,
            child: ListTile(
              dense: true,
              leading: Icon(Icons.view_timeline_outlined),
              title: Text('Auto-schedule week'),
              subtitle: Text('Fill study blocks automatically'),
              contentPadding: EdgeInsets.zero,
            ),
          ),
        if (onOpenIcal != null)
          const PopupMenuItem(
            value: _TopBarOverflowAction.ical,
            child: Text('iCal feeds'),
          ),
        if (onOpenCourseImport != null)
          const PopupMenuItem(
            value: _TopBarOverflowAction.course,
            child: Text('Course import'),
          ),
        const PopupMenuItem(
          value: _TopBarOverflowAction.settings,
          child: Text('Settings'),
        ),
      ],
    );
  }
}

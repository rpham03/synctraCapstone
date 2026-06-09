// Consistent tab page chrome — Reclaim-style top bar matching calendar.
import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

import '../../core/theme/app_tokens.dart';
import '../../theme.dart';
import '../state/calendar_shell_bridge.dart';
import '../state/shell_sidebar_controller.dart';

class SynctraPageHeader extends StatelessWidget implements PreferredSizeWidget {
  final String title;
  final String? subtitle;
  final List<Widget>? actions;
  final bool showSettings;
  final bool showSidebarToggle;

  const SynctraPageHeader({
    super.key,
    required this.title,
    this.subtitle,
    this.actions,
    this.showSettings = true,
    this.showSidebarToggle = true,
  });

  @override
  Size get preferredSize => Size.fromHeight(subtitle != null ? 64 : AppTokens.pageTopBarHeight);

  @override
  Widget build(BuildContext context) {
    final brightness = Theme.of(context).brightness;
    final divider = AppTokens.calendarDivider(context);
    final surface = AppTokens.calendarGridSurface(context);
    final isDesktop =
        MediaQuery.sizeOf(context).width >= ShellSidebarController.desktopBreakpoint;

    final trailing = <Widget>[
      ...?actions,
      if (showSettings)
        IconButton(
          tooltip: 'Settings',
          icon: Icon(
            Icons.settings_outlined,
            color: AppColors.textSecondary,
            size: AppTokens.iconStandard,
          ),
          onPressed: () => context.push('/settings'),
        ),
    ];

    return Material(
      color: surface,
      elevation: 0,
      child: SafeArea(
        bottom: false,
        child: Container(
          height: preferredSize.height,
          padding: const EdgeInsets.symmetric(horizontal: AppTokens.space12),
          decoration: BoxDecoration(
            color: surface,
            border: Border(
              bottom: BorderSide(
                color: divider,
                width: AppTokens.calendarDividerThickness,
              ),
            ),
          ),
          child: Row(
            children: [
              if (showSidebarToggle && !isDesktop)
                IconButton(
                  tooltip: 'Navigation menu',
                  icon: Icon(Icons.menu, color: AppColors.textSecondary, size: AppTokens.iconStandard),
                  onPressed: () => CalendarShellBridge.instance.openDrawer?.call(),
                ),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  mainAxisAlignment: MainAxisAlignment.center,
                  children: [
                    Text(
                      title,
                      style: CalendarTextStyles.topBarDate(brightness).copyWith(
                        fontSize: 16,
                        fontWeight: FontWeight.w600,
                      ),
                    ),
                    if (subtitle != null) ...[
                      const SizedBox(height: 2),
                      Text(
                        subtitle!,
                        style: CalendarTextStyles.hourLabel(brightness).copyWith(
                          fontSize: 12,
                          height: 1.35,
                        ),
                      ),
                    ],
                  ],
                ),
              ),
              ...trailing,
            ],
          ),
        ),
      ),
    );
  }
}

// Navigation drawer / sidebar — tabs, calendar import actions, account.
import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

import '../../core/theme/app_tokens.dart';
import '../../theme.dart';
import '../state/calendar_shell_bridge.dart';
import 'notion_sidebar_row.dart';
import 'synctra_page_scaffold.dart';

class SynctraCombinedSidebar extends StatelessWidget {
  final StatefulNavigationShell navigationShell;
  final int selectedIndex;
  final VoidCallback? onSettings;
  final VoidCallback? onSignOut;

  const SynctraCombinedSidebar({
    super.key,
    required this.navigationShell,
    required this.selectedIndex,
    this.onSettings,
    this.onSignOut,
  });

  static const _tabs = [
    _Tab(icon: Icons.calendar_month_outlined, active: Icons.calendar_month, label: 'Calendar'),
    _Tab(icon: Icons.checklist_outlined, active: Icons.checklist, label: 'Tasks'),
    _Tab(icon: Icons.chat_bubble_outline, active: Icons.chat_bubble, label: 'Chat'),
    _Tab(icon: Icons.group_outlined, active: Icons.group, label: 'Collab'),
  ];

  void _runAndCloseDrawer(BuildContext context, VoidCallback? action) {
    if (action == null) return;
    Navigator.maybePop(context);
    action();
  }

  @override
  Widget build(BuildContext context) {
    final brightness = Theme.of(context).brightness;
    final surface = AppTokens.calendarGridSurface(context);
    final onCalendar = selectedIndex == 0;
    final bridge = CalendarShellBridge.instance;

    return ColoredBox(
      color: surface,
      child: SafeArea(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Expanded(
              child: SingleChildScrollView(
                padding: const EdgeInsets.only(bottom: 8),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    Padding(
                      padding: const EdgeInsets.fromLTRB(18, 16, 18, 8),
                      child: Text(
                        'Synctra',
                        style: CalendarTextStyles.topBarDate(brightness).copyWith(
                          fontSize: 18,
                          fontWeight: FontWeight.w600,
                        ),
                      ),
                    ),
                    Padding(
                      padding: const EdgeInsets.fromLTRB(18, 8, 18, 6),
                      child: Text(
                        'WORKSPACE',
                        style: CalendarTextStyles.sidebarSectionHeader(brightness),
                      ),
                    ),
                    for (int i = 0; i < _tabs.length; i++)
                      NotionSidebarRow(
                        icon: _tabs[i].icon,
                        selectedIcon: _tabs[i].active,
                        label: _tabs[i].label,
                        selected: i == selectedIndex,
                        onTap: () {
                          navigationShell.goBranch(i);
                          Navigator.maybePop(context);
                        },
                      ),
                    if (onCalendar) ...[
                      const SizedBox(height: 12),
                      Padding(
                        padding: const EdgeInsets.symmetric(horizontal: 14),
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.stretch,
                          children: [
                            SynctraPrimaryButton(
                              onPressed: bridge.onOpenCourseImport == null
                                  ? null
                                  : () => _runAndCloseDrawer(
                                        context,
                                        bridge.onOpenCourseImport,
                                      ),
                              icon: Icons.school_outlined,
                              label: 'Course import',
                              expand: true,
                            ),
                            const SizedBox(height: 8),
                            SynctraGhostButton(
                              onPressed: bridge.onOpenIcal == null
                                  ? null
                                  : () => _runAndCloseDrawer(context, bridge.onOpenIcal),
                              icon: Icons.link,
                              label: 'iCal feeds',
                            ),
                          ],
                        ),
                      ),
                    ],
                  ],
                ),
              ),
            ),
            Padding(
              padding: const EdgeInsets.fromLTRB(18, 8, 18, 6),
              child: Text(
                'ACCOUNT',
                style: CalendarTextStyles.sidebarSectionHeader(brightness),
              ),
            ),
            NotionSidebarRow(
              icon: Icons.settings_outlined,
              selectedIcon: Icons.settings,
              label: 'Settings',
              selected: false,
              onTap: onSettings ?? () => context.push('/settings'),
            ),
            NotionSidebarRow(
              icon: Icons.logout_rounded,
              selectedIcon: Icons.logout_rounded,
              label: 'Sign out',
              selected: false,
              onTap: onSignOut ?? () {},
            ),
            const SizedBox(height: 8),
          ],
        ),
      ),
    );
  }
}

class _Tab {
  final IconData icon;
  final IconData active;
  final String label;
  const _Tab({required this.icon, required this.active, required this.label});
}

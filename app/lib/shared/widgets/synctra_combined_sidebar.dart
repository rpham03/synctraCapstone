// One column: app navigation + calendar planner (month + upcoming) when on Calendar.
import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

import '../state/calendar_shell_bridge.dart';
import 'notion_sidebar_row.dart';

class SynctraCombinedSidebar extends StatefulWidget {
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

  @override
  State<SynctraCombinedSidebar> createState() => _SynctraCombinedSidebarState();
}

class _SynctraCombinedSidebarState extends State<SynctraCombinedSidebar> {
  @override
  void initState() {
    super.initState();
    CalendarShellBridge.instance.addListener(_onBridge);
    // Sidebar builds before CalendarScreen in the shell Row — refresh after calendar mounts.
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (mounted) setState(() {});
    });
  }

  @override
  void dispose() {
    CalendarShellBridge.instance.removeListener(_onBridge);
    super.dispose();
  }

  void _onBridge() {
    if (mounted) setState(() {});
  }

  static const _tabs = [
    _Tab(icon: Icons.calendar_month_outlined, active: Icons.calendar_month, label: 'Calendar'),
    _Tab(icon: Icons.checklist_outlined, active: Icons.checklist, label: 'Tasks'),
    _Tab(icon: Icons.chat_bubble_outline, active: Icons.chat_bubble, label: 'Chat'),
    _Tab(icon: Icons.group_outlined, active: Icons.group, label: 'Collab'),
  ];

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final onCalendar = widget.selectedIndex == 0;
    final planner = onCalendar ? CalendarShellBridge.instance.buildPlanner() : null;

    return ColoredBox(
      color: scheme.surfaceContainerLowest,
      child: SafeArea(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Padding(
              padding: const EdgeInsets.fromLTRB(14, 12, 14, 6),
              child: Row(
                children: [
                  Container(
                    width: 22,
                    height: 22,
                    alignment: Alignment.center,
                    decoration: BoxDecoration(
                      color: scheme.surfaceContainerHigh,
                      borderRadius: BorderRadius.circular(4),
                      border: Border.all(color: scheme.outlineVariant.withValues(alpha: 0.8)),
                    ),
                    child: Icon(Icons.grid_view_rounded, size: 13, color: scheme.onSurfaceVariant),
                  ),
                  const SizedBox(width: 10),
                  Expanded(
                    child: Text(
                      'Synctra',
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: Theme.of(context).textTheme.titleSmall?.copyWith(
                            fontWeight: FontWeight.w500,
                            letterSpacing: -0.2,
                          ),
                    ),
                  ),
                ],
              ),
            ),
            Padding(
              padding: const EdgeInsets.fromLTRB(18, 10, 18, 6),
              child: Text(
                'PRIVATE',
                style: Theme.of(context).textTheme.labelSmall?.copyWith(
                      letterSpacing: 0.85,
                      fontWeight: FontWeight.w600,
                      color: scheme.onSurfaceVariant,
                      fontSize: 11,
                    ),
              ),
            ),
            for (int i = 0; i < _tabs.length; i++)
              NotionSidebarRow(
                icon: _tabs[i].icon,
                selectedIcon: _tabs[i].active,
                label: _tabs[i].label,
                selected: i == widget.selectedIndex,
                onTap: () {
                  widget.navigationShell.goBranch(i);
                  Navigator.maybePop(context);
                },
              ),
            if (onCalendar) ...[
              Divider(height: 1, color: scheme.outlineVariant.withValues(alpha: 0.65)),
              Expanded(
                child: planner ?? const _PlannerLoadingPlaceholder(),
              ),
            ] else
              const Spacer(),
            Padding(
              padding: const EdgeInsets.fromLTRB(18, 8, 18, 6),
              child: Text(
                'ACCOUNT',
                style: Theme.of(context).textTheme.labelSmall?.copyWith(
                      letterSpacing: 0.85,
                      fontWeight: FontWeight.w600,
                      color: scheme.onSurfaceVariant,
                      fontSize: 11,
                    ),
              ),
            ),
            NotionSidebarRow(
              icon: Icons.settings_outlined,
              selectedIcon: Icons.settings,
              label: 'Settings',
              selected: false,
              onTap: widget.onSettings ?? () => context.push('/settings'),
            ),
            NotionSidebarRow(
              icon: Icons.logout_rounded,
              selectedIcon: Icons.logout_rounded,
              label: 'Sign out',
              selected: false,
              onTap: widget.onSignOut ?? () {},
            ),
            const SizedBox(height: 8),
          ],
        ),
      ),
    );
  }
}

class _PlannerLoadingPlaceholder extends StatelessWidget {
  const _PlannerLoadingPlaceholder();

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(20),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            SizedBox(
              width: 22,
              height: 22,
              child: CircularProgressIndicator(strokeWidth: 2, color: scheme.primary),
            ),
            const SizedBox(height: 12),
            Text(
              'Loading month view…',
              textAlign: TextAlign.center,
              style: Theme.of(context).textTheme.bodySmall?.copyWith(
                    color: scheme.onSurfaceVariant,
                  ),
            ),
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

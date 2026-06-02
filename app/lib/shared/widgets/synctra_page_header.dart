// Consistent tab page chrome: title, optional subtitle, trailing actions.
import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

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
  Size get preferredSize => Size.fromHeight(subtitle != null ? 72 : 56);

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final scheme = theme.colorScheme;
    final isDesktop =
        MediaQuery.sizeOf(context).width >= ShellSidebarController.desktopBreakpoint;
    final trailing = <Widget>[
      ...?actions,
      if (showSettings)
        IconButton(
          tooltip: 'Settings',
          icon: Icon(Icons.settings_outlined, color: scheme.onSurfaceVariant, size: 22),
          onPressed: () => context.push('/settings'),
        ),
    ];

    return AppBar(
      elevation: 0,
      scrolledUnderElevation: 0,
      backgroundColor: scheme.surface,
      surfaceTintColor: Colors.transparent,
      automaticallyImplyLeading: false,
      leading: showSidebarToggle && isDesktop
          ? ListenableBuilder(
              listenable: ShellSidebarController.instance,
              builder: (context, _) {
                final open = ShellSidebarController.instance.visible;
                return IconButton(
                  tooltip: open ? 'Hide navigation' : 'Show navigation',
                  icon: Icon(Icons.menu,
                      color: scheme.onSurfaceVariant, size: 22),
                  onPressed: () =>
                      CalendarShellBridge.instance.openDrawer?.call(),
                );
              },
            )
          : null,
      titleSpacing: showSidebarToggle && isDesktop ? 0 : 20,
      toolbarHeight: preferredSize.height,
      title: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          Text(
            title,
            style: theme.textTheme.titleLarge?.copyWith(
              fontWeight: FontWeight.w600,
              letterSpacing: -0.3,
            ),
          ),
          if (subtitle != null) ...[
            const SizedBox(height: 2),
            Text(
              subtitle!,
              style: theme.textTheme.bodySmall?.copyWith(
                color: scheme.onSurfaceVariant,
              ),
            ),
          ],
        ],
      ),
      actions: trailing,
      bottom: PreferredSize(
        preferredSize: const Size.fromHeight(1),
        child: Divider(height: 1, color: scheme.outlineVariant.withValues(alpha: 0.65)),
      ),
    );
  }
}

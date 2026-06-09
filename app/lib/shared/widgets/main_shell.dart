// Main app shell — Reclaim-style labeled sidebar on desktop, drawer on phone.
import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import 'package:supabase_flutter/supabase_flutter.dart';

import '../../core/theme/app_tokens.dart';
import '../../theme.dart';
import '../services/auth_service.dart';
import '../state/calendar_shell_bridge.dart';
import '../state/shell_sidebar_controller.dart';
import 'synctra_app_sidebar.dart';

class MainShell extends StatelessWidget {
  final StatefulNavigationShell navigationShell;
  const MainShell({super.key, required this.navigationShell});

  static const desktopBreakpoint = ShellSidebarController.desktopBreakpoint;

  @override
  Widget build(BuildContext context) {
    final selectedIndex = navigationShell.currentIndex;
    return LayoutBuilder(
      builder: (context, constraints) {
        final useSidebarLayout = constraints.maxWidth >= desktopBreakpoint;
        return useSidebarLayout
            ? _SidebarLayoutShell(
                navigationShell: navigationShell,
                selectedIndex: selectedIndex,
              )
            : _DrawerLayoutShell(
                navigationShell: navigationShell,
                selectedIndex: selectedIndex,
              );
      },
    );
  }
}

class _SidebarLayoutShell extends StatelessWidget {
  final StatefulNavigationShell navigationShell;
  final int selectedIndex;

  const _SidebarLayoutShell({
    required this.navigationShell,
    required this.selectedIndex,
  });

  @override
  Widget build(BuildContext context) {
    final divider = AppTokens.calendarDivider(context);
    final surface = AppTokens.calendarGridSurface(context);

    return Scaffold(
      backgroundColor: surface,
      body: Row(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          SynctraAppSidebar(
            selectedIndex: selectedIndex,
            onDestinationSelected: navigationShell.goBranch,
            onSignOut: () => _signOut(context),
          ),
          Expanded(
            child: DecoratedBox(
              decoration: BoxDecoration(
                color: surface,
                border: Border(
                  left: BorderSide(
                    color: divider,
                    width: AppTokens.calendarDividerThickness,
                  ),
                ),
              ),
              child: ClipRect(child: navigationShell),
            ),
          ),
        ],
      ),
    );
  }
}

class _DrawerLayoutShell extends StatefulWidget {
  final StatefulNavigationShell navigationShell;
  final int selectedIndex;

  const _DrawerLayoutShell({
    required this.navigationShell,
    required this.selectedIndex,
  });

  @override
  State<_DrawerLayoutShell> createState() => _DrawerLayoutShellState();
}

class _DrawerLayoutShellState extends State<_DrawerLayoutShell> {
  final _scaffoldKey = GlobalKey<ScaffoldState>();

  @override
  void initState() {
    super.initState();
    CalendarShellBridge.instance.registerOpenDrawer(_openDrawer);
  }

  @override
  void dispose() {
    CalendarShellBridge.instance.registerOpenDrawer(null);
    super.dispose();
  }

  void _openDrawer() => _scaffoldKey.currentState?.openDrawer();

  @override
  Widget build(BuildContext context) {
    final divider = AppTokens.calendarDivider(context);
    final surface = AppTokens.calendarGridSurface(context);

    return Scaffold(
      key: _scaffoldKey,
      backgroundColor: surface,
      drawer: Drawer(
        width: SynctraAppSidebar.width,
        backgroundColor: AppColors.navSidebarBackground,
        child: SynctraAppSidebar(
          selectedIndex: widget.selectedIndex,
          onDestinationSelected: widget.navigationShell.goBranch,
          onSignOut: () => _signOut(context),
          onNavigate: () => Navigator.maybePop(context),
        ),
      ),
      body: widget.navigationShell,
      bottomNavigationBar: DecoratedBox(
        decoration: BoxDecoration(
          color: surface,
          border: Border(
            top: BorderSide(
              color: divider,
              width: AppTokens.calendarDividerThickness,
            ),
          ),
        ),
        child: NavigationBar(
          elevation: 0,
          backgroundColor: surface,
          surfaceTintColor: Colors.transparent,
          indicatorColor: AppColors.primary.withValues(alpha: 0.14),
          selectedIndex: widget.selectedIndex,
          onDestinationSelected: widget.navigationShell.goBranch,
          destinations: const [
            NavigationDestination(
              icon: Icon(Icons.calendar_month_outlined),
              selectedIcon: Icon(Icons.calendar_month),
              label: 'Planner',
            ),
            NavigationDestination(
              icon: Icon(Icons.repeat),
              selectedIcon: Icon(Icons.repeat_on),
              label: 'Habits',
            ),
            NavigationDestination(
              icon: Icon(Icons.checklist_outlined),
              selectedIcon: Icon(Icons.checklist),
              label: 'Tasks',
            ),
            NavigationDestination(
              icon: Icon(Icons.chat_bubble_outline),
              selectedIcon: Icon(Icons.chat_bubble),
              label: 'Chat',
            ),
            NavigationDestination(
              icon: Icon(Icons.group_outlined),
              selectedIcon: Icon(Icons.group),
              label: 'Collab',
            ),
          ],
        ),
      ),
    );
  }
}

Future<void> _signOut(BuildContext context) async {
  final session = Supabase.instance.client.auth.currentSession;
  if (session == null) {
    if (context.mounted) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('You are not signed in.')),
      );
    }
    return;
  }
  final ok = await showDialog<bool>(
    context: context,
    builder: (ctx) => AlertDialog(
      title: const Text('Sign out?'),
      actions: [
        TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Cancel')),
        FilledButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('Sign out')),
      ],
    ),
  );
  if (ok != true || !context.mounted) return;
  await AuthService().signOut();
  if (context.mounted) context.go('/login');
}

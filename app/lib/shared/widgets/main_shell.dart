// Main app shell — combined sidebar (nav + calendar planner) / bottom nav on phone.
import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import 'package:supabase_flutter/supabase_flutter.dart';

import '../services/auth_service.dart';
import '../state/calendar_shell_bridge.dart';
import '../state/shell_sidebar_controller.dart';
import 'synctra_combined_sidebar.dart';

class MainShell extends StatelessWidget {
  final StatefulNavigationShell navigationShell;
  const MainShell({super.key, required this.navigationShell});

  static const sidebarWidth = 300.0;
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

/// Wide screens: optional fixed nav column; main content expands when hidden.
class _SidebarLayoutShell extends StatefulWidget {
  final StatefulNavigationShell navigationShell;
  final int selectedIndex;

  const _SidebarLayoutShell({
    required this.navigationShell,
    required this.selectedIndex,
  });

  @override
  State<_SidebarLayoutShell> createState() => _SidebarLayoutShellState();
}

class _SidebarLayoutShellState extends State<_SidebarLayoutShell> {
  final _sidebar = ShellSidebarController.instance;

  @override
  void initState() {
    super.initState();
    _sidebar.addListener(_onSidebarChanged);
    CalendarShellBridge.instance.registerOpenDrawer(_toggleSidebar);
  }

  @override
  void dispose() {
    _sidebar.removeListener(_onSidebarChanged);
    CalendarShellBridge.instance.registerOpenDrawer(null);
    super.dispose();
  }

  void _onSidebarChanged() {
    if (mounted) setState(() {});
  }

  void _toggleSidebar() => _sidebar.toggle();

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final sidebarOpen = _sidebar.visible;

    return Scaffold(
      backgroundColor: scheme.surfaceContainerLowest,
      body: Row(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          AnimatedSize(
            duration: const Duration(milliseconds: 220),
            curve: Curves.easeInOut,
            alignment: Alignment.centerLeft,
            clipBehavior: Clip.hardEdge,
            child: sidebarOpen
                ? SizedBox(
                    width: MainShell.sidebarWidth,
                    child: SynctraCombinedSidebar(
                      navigationShell: widget.navigationShell,
                      selectedIndex: widget.selectedIndex,
                      onSignOut: () => _signOut(context),
                    ),
                  )
                : const SizedBox.shrink(),
          ),
          Expanded(
            child: DecoratedBox(
              decoration: BoxDecoration(
                color: scheme.surface,
                border: sidebarOpen
                    ? Border(
                        left: BorderSide(
                          color: scheme.outlineVariant.withValues(alpha: 0.75),
                        ),
                      )
                    : null,
              ),
              child: ClipRect(child: widget.navigationShell),
            ),
          ),
        ],
      ),
    );
  }
}

/// Narrow screens: same combined column in a drawer; bottom nav for quick switching.
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
    final scheme = Theme.of(context).colorScheme;

    return Scaffold(
      key: _scaffoldKey,
      backgroundColor: scheme.surface,
      drawer: Drawer(
        width: MainShell.sidebarWidth,
        child: SynctraCombinedSidebar(
          navigationShell: widget.navigationShell,
          selectedIndex: widget.selectedIndex,
          onSignOut: () => _signOut(context),
        ),
      ),
      body: widget.navigationShell,
      bottomNavigationBar: NavigationBar(
        selectedIndex: widget.selectedIndex,
        onDestinationSelected: widget.navigationShell.goBranch,
        destinations: const [
          NavigationDestination(
            icon: Icon(Icons.calendar_month_outlined),
            selectedIcon: Icon(Icons.calendar_month),
            label: 'Calendar',
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

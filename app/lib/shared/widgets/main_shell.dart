// Main app shell — combined sidebar (nav + calendar planner) / bottom nav on phone.
import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import 'package:supabase_flutter/supabase_flutter.dart';

import '../state/calendar_shell_bridge.dart';
import '../services/auth_service.dart';
import 'synctra_combined_sidebar.dart';

class MainShell extends StatelessWidget {
  final StatefulNavigationShell navigationShell;
  const MainShell({super.key, required this.navigationShell});

  static const _sidebarWidth = 300.0;
  static const _desktopBreakpoint = 1000.0;

  @override
  Widget build(BuildContext context) {
    final selectedIndex = navigationShell.currentIndex;
    return LayoutBuilder(
      builder: (context, constraints) {
        final useSidebarLayout = constraints.maxWidth >= _desktopBreakpoint;
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

/// Wide screens: one fixed column (nav + planner) beside the active tab.
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
  @override
  void initState() {
    super.initState();
    // Rebuild sidebar after CalendarScreen registers its planner (build order fix).
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (mounted) setState(() {});
    });
  }

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;

    return Scaffold(
      backgroundColor: scheme.surfaceContainerLowest,
      body: Row(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          SizedBox(
            width: MainShell._sidebarWidth,
            child: SynctraCombinedSidebar(
              navigationShell: widget.navigationShell,
              selectedIndex: widget.selectedIndex,
              onSignOut: () => _signOut(context),
            ),
          ),
          Expanded(
            child: DecoratedBox(
              decoration: BoxDecoration(
                color: scheme.surface,
                border: Border(
                  left: BorderSide(color: scheme.outlineVariant.withValues(alpha: 0.75)),
                ),
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
        width: MainShell._sidebarWidth,
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

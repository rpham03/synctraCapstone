// Main app shell — sidebar nav on desktop/web, bottom nav on mobile.
import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

import '../../core/theme/app_theme.dart';
import '../../core/utils/responsive.dart';

// Navigation items shared by both layouts
const _tabs = [
  _TabItem(icon: Icons.calendar_month_outlined, activeIcon: Icons.calendar_month, label: 'Calendar', path: '/calendar'),
  _TabItem(icon: Icons.checklist_outlined,       activeIcon: Icons.checklist,       label: 'Tasks',    path: '/tasks'),
  _TabItem(icon: Icons.chat_bubble_outline,      activeIcon: Icons.chat_bubble,     label: 'Chat',     path: '/chat'),
  _TabItem(icon: Icons.group_outlined,           activeIcon: Icons.group,           label: 'Collab',   path: '/collab'),
];

class MainShell extends StatelessWidget {
  final Widget child;
  const MainShell({super.key, required this.child});

  int _selectedIndex(BuildContext context) {
    final location = GoRouterState.of(context).matchedLocation;
    final idx = _tabs.indexWhere((t) => location.startsWith(t.path));
    return idx < 0 ? 0 : idx;
  }

  @override
  Widget build(BuildContext context) {
    return Responsive.isDesktop(context)
        ? _DesktopShell(child: child, selectedIndex: _selectedIndex(context))
        : _MobileShell(child: child, selectedIndex: _selectedIndex(context));
  }
}

// ── Desktop layout — left sidebar ─────────────────────────────────────────────

class _DesktopShell extends StatelessWidget {
  final Widget child;
  final int selectedIndex;
  const _DesktopShell({required this.child, required this.selectedIndex});

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: Row(
        children: [
          // Sidebar
          Container(
            width: 240,
            color: Colors.white,
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                // Logo
                Padding(
                  padding: const EdgeInsets.fromLTRB(20, 32, 20, 8),
                  child: Row(children: [
                    Icon(Icons.calendar_month_rounded,
                        color: AppColors.primary, size: 28),
                    const SizedBox(width: 10),
                    Text(
                      'Synctra',
                      style: TextStyle(
                        fontSize: 20,
                        fontWeight: FontWeight.bold,
                        color: AppColors.primary,
                      ),
                    ),
                  ]),
                ),
                const SizedBox(height: 8),
                const Divider(indent: 16, endIndent: 16),
                const SizedBox(height: 8),

                // Nav items
                for (int i = 0; i < _tabs.length; i++)
                  _SidebarItem(
                    tab: _tabs[i],
                    selected: i == selectedIndex,
                    onTap: () => context.go(_tabs[i].path),
                  ),

                const Spacer(),

                // Bottom actions
                const Divider(indent: 16, endIndent: 16),
                _SidebarItem(
                  tab: const _TabItem(
                    icon: Icons.settings_outlined,
                    activeIcon: Icons.settings,
                    label: 'Settings',
                    path: '/settings',
                  ),
                  selected: false,
                  onTap: () {/* TODO: settings */},
                ),
                _SidebarItem(
                  tab: const _TabItem(
                    icon: Icons.logout,
                    activeIcon: Icons.logout,
                    label: 'Sign Out',
                    path: '',
                  ),
                  selected: false,
                  onTap: () {/* TODO: sign out */},
                ),
                const SizedBox(height: 20),
              ],
            ),
          ),

          // Vertical divider
          const VerticalDivider(width: 1),

          // Main content
          Expanded(child: child),
        ],
      ),
    );
  }
}

class _SidebarItem extends StatelessWidget {
  final _TabItem tab;
  final bool selected;
  final VoidCallback onTap;
  const _SidebarItem({
    required this.tab,
    required this.selected,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 2),
      child: Material(
        color: selected ? AppColors.primary.withAlpha(20) : Colors.transparent,
        borderRadius: BorderRadius.circular(10),
        child: InkWell(
          borderRadius: BorderRadius.circular(10),
          onTap: onTap,
          child: Padding(
            padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
            child: Row(children: [
              Icon(
                selected ? tab.activeIcon : tab.icon,
                color: selected ? AppColors.primary : Colors.grey[600],
                size: 20,
              ),
              const SizedBox(width: 12),
              Text(
                tab.label,
                style: TextStyle(
                  fontWeight: selected ? FontWeight.w600 : FontWeight.normal,
                  color: selected ? AppColors.primary : Colors.grey[800],
                  fontSize: 14,
                ),
              ),
            ]),
          ),
        ),
      ),
    );
  }
}

// ── Mobile layout — bottom nav bar ────────────────────────────────────────────

class _MobileShell extends StatelessWidget {
  final Widget child;
  final int selectedIndex;
  const _MobileShell({required this.child, required this.selectedIndex});

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: child,
      bottomNavigationBar: NavigationBar(
        selectedIndex: selectedIndex,
        onDestinationSelected: (i) => context.go(_tabs[i].path),
        backgroundColor: Colors.white,
        indicatorColor: AppColors.primary.withAlpha(30),
        destinations: _tabs
            .map((t) => NavigationDestination(
                  icon: Icon(t.icon),
                  selectedIcon: Icon(t.activeIcon, color: AppColors.primary),
                  label: t.label,
                ))
            .toList(),
      ),
    );
  }
}

// ── Shared data class ─────────────────────────────────────────────────────────

class _TabItem {
  final IconData icon;
  final IconData activeIcon;
  final String label;
  final String path;
  const _TabItem({
    required this.icon,
    required this.activeIcon,
    required this.label,
    required this.path,
  });
}

// Main app shell — sidebar nav on desktop/web, bottom nav on mobile.
import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

import '../../core/theme/app_theme.dart';
import '../../core/utils/responsive.dart';

// Navigation items shared by both layouts (order must match StatefulShellRoute branches).
const _tabs = [
  _TabItem(icon: Icons.calendar_month_outlined, activeIcon: Icons.calendar_month, label: 'Calendar', path: '/calendar'),
  _TabItem(icon: Icons.checklist_outlined,       activeIcon: Icons.checklist,       label: 'Tasks',    path: '/tasks'),
  _TabItem(icon: Icons.chat_bubble_outline,      activeIcon: Icons.chat_bubble,     label: 'Chat',     path: '/chat'),
  _TabItem(icon: Icons.group_outlined,           activeIcon: Icons.group,           label: 'Collab',   path: '/collab'),
];

class MainShell extends StatelessWidget {
  final StatefulNavigationShell navigationShell;
  const MainShell({super.key, required this.navigationShell});

  @override
  Widget build(BuildContext context) {
    final selectedIndex = navigationShell.currentIndex;
    return Responsive.isDesktop(context)
        ? _DesktopShell(
            navigationShell: navigationShell,
            selectedIndex: selectedIndex,
          )
        : _MobileShell(
            navigationShell: navigationShell,
            selectedIndex: selectedIndex,
          );
  }
}

// ── Desktop layout — left sidebar ─────────────────────────────────────────

class _DesktopShell extends StatelessWidget {
  final StatefulNavigationShell navigationShell;
  final int selectedIndex;
  const _DesktopShell({
    required this.navigationShell,
    required this.selectedIndex,
  });

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: Row(
        children: [
          Container(
            width: 240,
            color: Colors.white,
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
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
                for (int i = 0; i < _tabs.length; i++)
                  _SidebarItem(
                    tab: _tabs[i],
                    selected: i == selectedIndex,
                    onTap: () => navigationShell.goBranch(i),
                  ),
                const Spacer(),
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
          const VerticalDivider(width: 1),
          Expanded(child: navigationShell),
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

// ── Mobile layout — bottom nav bar ───────────────────────────────────────────

class _MobileShell extends StatelessWidget {
  final StatefulNavigationShell navigationShell;
  final int selectedIndex;
  const _MobileShell({
    required this.navigationShell,
    required this.selectedIndex,
  });

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: navigationShell,
      bottomNavigationBar: NavigationBar(
        selectedIndex: selectedIndex,
        onDestinationSelected: navigationShell.goBranch,
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
import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import 'package:google_fonts/google_fonts.dart';

import '../../core/theme/app_tokens.dart';
import '../../theme.dart';

/// Reclaim-style labeled sidebar — navy background, icon + text nav rows.
class SynctraAppSidebar extends StatelessWidget {
  const SynctraAppSidebar({
    super.key,
    required this.selectedIndex,
    required this.onDestinationSelected,
    this.onSettings,
    this.onSignOut,
    this.onNavigate,
  });

  final int selectedIndex;
  final ValueChanged<int> onDestinationSelected;
  final VoidCallback? onSettings;
  final VoidCallback? onSignOut;
  final VoidCallback? onNavigate;

  static const double width = 220;

  static const _destinations = [
    _SidebarItem(Icons.calendar_month_outlined, Icons.calendar_month, 'Planner'),
    _SidebarItem(Icons.repeat, Icons.repeat_on, 'Habits'),
    _SidebarItem(Icons.checklist_outlined, Icons.checklist, 'Tasks'),
    _SidebarItem(Icons.chat_bubble_outline, Icons.chat_bubble, 'Chat'),
    _SidebarItem(Icons.group_outlined, Icons.group, 'Collab'),
  ];

  void _select(BuildContext context, int index) {
    onNavigate?.call();
    onDestinationSelected(index);
  }

  @override
  Widget build(BuildContext context) {
    return Material(
      color: AppColors.navSidebarBackground,
      child: SafeArea(
        right: false,
        child: SizedBox(
          width: width,
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Padding(
                padding: const EdgeInsets.fromLTRB(20, 20, 16, 24),
                child: Text(
                  'synctra',
                  style: GoogleFonts.inter(
                    fontSize: 18,
                    fontWeight: FontWeight.w600,
                    letterSpacing: -0.4,
                    color: AppColors.navSidebarTextActive,
                  ),
                ),
              ),
              for (var i = 0; i < _destinations.length; i++)
                _SidebarNavRow(
                  item: _destinations[i],
                  selected: i == selectedIndex,
                  onTap: () => _select(context, i),
                ),
              const Spacer(),
              _SidebarNavRow(
                item: const _SidebarItem(Icons.settings_outlined, Icons.settings, 'Settings'),
                selected: false,
                onTap: () {
                  onNavigate?.call();
                  (onSettings ?? () => context.push('/settings'))();
                },
              ),
              _SidebarNavRow(
                item: const _SidebarItem(Icons.help_outline, Icons.help_outline, 'Help'),
                selected: false,
                onTap: () => onNavigate?.call(),
              ),
              _SidebarNavRow(
                item: const _SidebarItem(Icons.logout_rounded, Icons.logout_rounded, 'Sign out'),
                selected: false,
                onTap: () {
                  onNavigate?.call();
                  onSignOut?.call();
                },
              ),
              const SizedBox(height: AppTokens.space12),
            ],
          ),
        ),
      ),
    );
  }
}

class _SidebarNavRow extends StatefulWidget {
  const _SidebarNavRow({
    required this.item,
    required this.selected,
    required this.onTap,
  });

  final _SidebarItem item;
  final bool selected;
  final VoidCallback? onTap;

  @override
  State<_SidebarNavRow> createState() => _SidebarNavRowState();
}

class _SidebarNavRowState extends State<_SidebarNavRow> {
  bool _hover = false;

  @override
  Widget build(BuildContext context) {
    final selected = widget.selected;
    final bg = selected
        ? AppColors.primary.withValues(alpha: 0.18)
        : _hover
            ? Colors.white.withValues(alpha: 0.06)
            : Colors.transparent;

    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 1),
      child: MouseRegion(
        onEnter: (_) => setState(() => _hover = true),
        onExit: (_) => setState(() => _hover = false),
        child: Material(
          color: bg,
          borderRadius: BorderRadius.circular(AppTokens.radiusMd),
          child: InkWell(
            onTap: widget.onTap,
            borderRadius: BorderRadius.circular(AppTokens.radiusMd),
            hoverColor: Colors.transparent,
            child: Padding(
              padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
              child: Row(
                children: [
                  Icon(
                    selected ? widget.item.activeIcon : widget.item.icon,
                    size: 20,
                    color: selected
                        ? AppColors.navSidebarTextActive
                        : AppColors.navSidebarText,
                  ),
                  const SizedBox(width: 12),
                  Expanded(
                    child: Text(
                      widget.item.label,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: GoogleFonts.inter(
                        fontSize: 14,
                        fontWeight: selected ? FontWeight.w600 : FontWeight.w500,
                        color: selected
                            ? AppColors.navSidebarTextActive
                            : AppColors.navSidebarText,
                        height: 1.2,
                      ),
                    ),
                  ),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}

class _SidebarItem {
  final IconData icon;
  final IconData activeIcon;
  final String label;

  const _SidebarItem(this.icon, this.activeIcon, this.label);
}

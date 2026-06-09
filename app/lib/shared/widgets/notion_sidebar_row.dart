// Notion-style sidebar row: muted icons, gray selection (no loud primary fill).
import 'package:flutter/material.dart';

import '../../core/theme/app_tokens.dart';
import '../../theme.dart';

class NotionSidebarRow extends StatefulWidget {
  final IconData icon;
  final IconData selectedIcon;
  final String label;
  final bool selected;
  final VoidCallback onTap;

  const NotionSidebarRow({
    super.key,
    required this.icon,
    required this.selectedIcon,
    required this.label,
    required this.selected,
    required this.onTap,
  });

  @override
  State<NotionSidebarRow> createState() => _NotionSidebarRowState();
}

class _NotionSidebarRowState extends State<NotionSidebarRow> {
  bool _hover = false;

  @override
  Widget build(BuildContext context) {
    final brightness = Theme.of(context).brightness;
    final ink = AppColors.textPrimary;
    final muted = AppColors.textSecondary;

    Color bg;
    if (widget.selected) {
      bg = AppColors.primary.withValues(alpha: 0.1);
    } else if (_hover) {
      bg = AppColors.grey100.withValues(alpha: 0.85);
    } else {
      bg = Colors.transparent;
    }

    return MouseRegion(
      onEnter: (_) => setState(() => _hover = true),
      onExit: (_) => setState(() => _hover = false),
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 1),
        child: Material(
          color: bg,
          borderRadius: BorderRadius.circular(AppTokens.radiusSm),
          child: InkWell(
            borderRadius: BorderRadius.circular(AppTokens.radiusSm),
            onTap: widget.onTap,
            child: Padding(
              padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 8),
              child: Row(
                children: [
                  Icon(
                    widget.selected ? widget.selectedIcon : widget.icon,
                    size: AppTokens.iconStandard,
                    color: widget.selected ? AppColors.primary : muted,
                  ),
                  const SizedBox(width: 10),
                  Expanded(
                    child: Text(
                      widget.label,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: CalendarTextStyles.upcomingRow(brightness).copyWith(
                        fontWeight: widget.selected ? FontWeight.w600 : FontWeight.w400,
                        color: widget.selected ? ink : ink.withValues(alpha: 0.88),
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

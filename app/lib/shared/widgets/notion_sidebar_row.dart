// Notion-style sidebar row: muted icons, gray selection (no loud primary fill).
import 'package:flutter/material.dart';

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
    final scheme = Theme.of(context).colorScheme;
    final ink = scheme.onSurface;
    final muted = scheme.onSurfaceVariant;

    Color bg;
    if (widget.selected) {
      bg = scheme.surfaceContainerHighest.withValues(alpha: 0.85);
    } else if (_hover) {
      bg = scheme.surfaceContainerLow;
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
          borderRadius: BorderRadius.circular(4),
          child: InkWell(
            borderRadius: BorderRadius.circular(4),
            splashColor: scheme.onSurface.withValues(alpha: 0.06),
            hoverColor: widget.selected ? Colors.transparent : scheme.onSurface.withValues(alpha: 0.04),
            onTap: widget.onTap,
            child: Padding(
              padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 8),
              child: Row(
                children: [
                  Icon(
                    widget.selected ? widget.selectedIcon : widget.icon,
                    size: 18,
                    color: widget.selected ? ink : muted,
                  ),
                  const SizedBox(width: 10),
                  Expanded(
                    child: Text(
                      widget.label,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                            fontWeight: widget.selected ? FontWeight.w500 : FontWeight.w400,
                            fontSize: 14,
                            height: 1.2,
                            color: ink,
                            letterSpacing: -0.1,
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

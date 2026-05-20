// “Sync It” — branded AI assistant chrome (toolbar launch + panel frame).
import 'package:flutter/material.dart';

import '../../core/theme/app_theme.dart';

/// Product name for the scheduling assistant (plays on Synctra + “sync your week”).
abstract final class SyncItBranding {
  static const String name = 'Sync It';
  static const String tagline = 'Talk to your calendar';
  static const String panelSubtitle = 'Changes show up on your grid instantly';
  static const String tooltipOpen = 'Open Sync It — talk to your calendar';
}

/// Toolbar control — blue outline box so Sync It is easy to spot.
class SyncItLaunchButton extends StatelessWidget {
  final bool isOpen;
  final VoidCallback onPressed;

  const SyncItLaunchButton({
    super.key,
    required this.isOpen,
    required this.onPressed,
  });

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context).textTheme;
    const blue = AppColors.primary;

    return Tooltip(
      message: isOpen ? 'Close Sync It' : SyncItBranding.tooltipOpen,
      child: Material(
        color: Colors.transparent,
        child: InkWell(
          onTap: onPressed,
          borderRadius: BorderRadius.circular(10),
          child: AnimatedContainer(
            duration: const Duration(milliseconds: 180),
            padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 9),
            decoration: BoxDecoration(
              color: isOpen ? blue.withValues(alpha: 0.14) : blue.withValues(alpha: 0.08),
              borderRadius: BorderRadius.circular(10),
              border: Border.all(
                color: isOpen ? blue : blue.withValues(alpha: 0.85),
                width: isOpen ? 2 : 1.5,
              ),
              boxShadow: [
                BoxShadow(
                  color: blue.withValues(alpha: isOpen ? 0.22 : 0.12),
                  blurRadius: isOpen ? 10 : 6,
                  offset: const Offset(0, 1),
                ),
              ],
            ),
            child: Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                Icon(
                  isOpen ? Icons.close_rounded : Icons.auto_awesome,
                  size: 18,
                  color: blue,
                ),
                const SizedBox(width: 7),
                Text(
                  isOpen ? 'Close' : SyncItBranding.name,
                  style: theme.labelLarge?.copyWith(
                    fontWeight: FontWeight.w700,
                    color: blue,
                    letterSpacing: -0.2,
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

/// Side panel wrapper — blue frame + branded header.
class SyncItPanelFrame extends StatelessWidget {
  final VoidCallback onClose;
  final Widget child;

  const SyncItPanelFrame({
    super.key,
    required this.onClose,
    required this.child,
  });

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final theme = Theme.of(context).textTheme;
    final blue = AppColors.primary;

    return DecoratedBox(
      decoration: BoxDecoration(
        color: scheme.surfaceContainerLowest,
        border: Border(
          left: const BorderSide(color: AppColors.primary, width: 3),
          top: BorderSide(color: blue.withValues(alpha: 0.5)),
          right: BorderSide(color: blue.withValues(alpha: 0.5)),
          bottom: BorderSide(color: blue.withValues(alpha: 0.5)),
        ),
        boxShadow: [
          BoxShadow(
            color: blue.withValues(alpha: 0.14),
            blurRadius: 20,
            offset: const Offset(-6, 0),
          ),
        ],
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          DecoratedBox(
            decoration: BoxDecoration(
              color: blue.withValues(alpha: 0.1),
              border: Border(bottom: BorderSide(color: blue.withValues(alpha: 0.35))),
            ),
            child: Padding(
              padding: const EdgeInsets.fromLTRB(14, 12, 4, 12),
              child: Row(
                children: [
                  Container(
                    width: 36,
                    height: 36,
                    alignment: Alignment.center,
                    decoration: BoxDecoration(
                      color: blue.withValues(alpha: 0.16),
                      borderRadius: BorderRadius.circular(8),
                      border: Border.all(color: blue.withValues(alpha: 0.45)),
                    ),
                    child: const Icon(Icons.auto_awesome, size: 20, color: AppColors.primary),
                  ),
                  const SizedBox(width: 10),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          SyncItBranding.name,
                          style: theme.titleMedium?.copyWith(
                            fontWeight: FontWeight.w700,
                            color: blue,
                            letterSpacing: -0.3,
                          ),
                        ),
                        Text(
                          SyncItBranding.panelSubtitle,
                          style: theme.labelSmall?.copyWith(
                            color: scheme.onSurfaceVariant,
                            height: 1.25,
                          ),
                        ),
                      ],
                    ),
                  ),
                  IconButton(
                    tooltip: 'Close Sync It',
                    icon: Icon(Icons.close, size: 20, color: scheme.onSurfaceVariant),
                    onPressed: onClose,
                  ),
                ],
              ),
            ),
          ),
          Expanded(child: child),
        ],
      ),
    );
  }
}

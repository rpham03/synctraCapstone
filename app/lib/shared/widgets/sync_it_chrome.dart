// “Sync It” — branded AI assistant chrome (toolbar launch + panel frame).
import 'package:flutter/material.dart';

import '../../core/theme/app_theme.dart';
import '../../core/theme/app_tokens.dart';

/// Product name for the scheduling assistant (plays on Synctra + “sync your week”).
abstract final class SyncItBranding {
  static const String name = 'Sync It';
  static const String tagline = 'Talk to your calendar';
  static const String panelSubtitle = 'Ask to plan, move, or add study blocks';
  static const String tooltipOpen = 'Chat with your calendar — plan, move, or add blocks';
}

/// Toolbar control — minimal ghost (Reclaim) or branded outline (legacy).
class SyncItLaunchButton extends StatelessWidget {
  final bool isOpen;
  final VoidCallback onPressed;
  final bool compact;
  final bool minimal;

  const SyncItLaunchButton({
    super.key,
    required this.isOpen,
    required this.onPressed,
    this.compact = false,
    this.minimal = false,
  });

  @override
  Widget build(BuildContext context) {
    if (minimal) {
      return _MinimalSyncItButton(isOpen: isOpen, onPressed: onPressed);
    }

    final theme = Theme.of(context).textTheme;
    const blue = AppColors.primary;

    return Tooltip(
      message: isOpen ? 'Close Sync It' : SyncItBranding.tooltipOpen,
      child: Material(
        color: Colors.transparent,
        child: InkWell(
          onTap: onPressed,
          borderRadius: BorderRadius.circular(AppTokens.radiusMd),
          child: AnimatedContainer(
            duration: AppTokens.calendarViewCrossfade,
            padding: EdgeInsets.symmetric(
              horizontal: compact ? AppTokens.space8 : AppTokens.space12,
              vertical: AppTokens.space8,
            ),
            decoration: BoxDecoration(
              color: isOpen
                  ? blue.withValues(alpha: 0.12)
                  : blue.withValues(alpha: 0.06),
              borderRadius: BorderRadius.circular(AppTokens.radiusMd),
              border: Border.all(
                color: blue.withValues(alpha: isOpen ? 0.55 : 0.35),
              ),
            ),
            child: Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                Icon(
                  isOpen ? Icons.close_rounded : Icons.auto_awesome,
                  size: compact ? 18 : 16,
                  color: blue,
                ),
                if (!compact) ...[
                  const SizedBox(width: AppTokens.space8),
                  Text(
                    isOpen ? 'Close' : SyncItBranding.name,
                    style: theme.labelLarge?.copyWith(
                      fontWeight: FontWeight.w600,
                      color: blue,
                    ),
                  ),
                ],
              ],
            ),
          ),
        ),
      ),
    );
  }
}

class _MinimalSyncItButton extends StatelessWidget {
  const _MinimalSyncItButton({
    required this.isOpen,
    required this.onPressed,
  });

  final bool isOpen;
  final VoidCallback onPressed;

  @override
  Widget build(BuildContext context) {
    final brightness = Theme.of(context).brightness;

    return Tooltip(
      message: isOpen ? 'Close Sync It chat' : SyncItBranding.tooltipOpen,
      child: TextButton.icon(
        onPressed: onPressed,
        icon: Icon(
          isOpen ? Icons.close_rounded : Icons.chat_bubble_outline,
          size: 16,
          color: isOpen ? AppColors.primary : AppColors.primary,
        ),
        label: Text(
          isOpen ? 'Close' : SyncItBranding.name,
          style: CalendarTextStyles.upcomingRow(brightness).copyWith(
            fontSize: 13,
            fontWeight: FontWeight.w600,
            color: isOpen ? AppColors.primary : AppColors.primary,
          ),
        ),
        style: TextButton.styleFrom(
          visualDensity: VisualDensity.compact,
          minimumSize: const Size(0, 34),
          padding: const EdgeInsets.symmetric(horizontal: AppTokens.space8),
          backgroundColor: isOpen
              ? AppColors.primary.withValues(alpha: 0.1)
              : AppColors.primary.withValues(alpha: 0.06),
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(AppTokens.radiusMd),
            side: BorderSide(
              color: AppColors.primary.withValues(alpha: isOpen ? 0.45 : 0.28),
            ),
          ),
        ),
      ),
    );
  }
}

/// Side panel wrapper — quiet Reclaim-style header.
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
    final brightness = Theme.of(context).brightness;
    final divider = AppTokens.calendarDivider(context);

    return ColoredBox(
      color: scheme.surface,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Container(
            height: AppTokens.calendarTopBarHeight,
            padding: const EdgeInsets.symmetric(horizontal: AppTokens.space16),
            decoration: BoxDecoration(
              border: Border(
                bottom: BorderSide(
                  color: divider,
                  width: AppTokens.calendarDividerThickness,
                ),
              ),
            ),
            child: Row(
              children: [
                Icon(
                  Icons.chat_bubble_outline,
                  size: 18,
                  color: AppColors.primary,
                ),
                const SizedBox(width: AppTokens.space8),
                Expanded(
                  child: Column(
                    mainAxisAlignment: MainAxisAlignment.center,
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        'Synctra AI',
                        style: CalendarTextStyles.topBarDate(brightness).copyWith(
                          fontSize: 14,
                          fontWeight: FontWeight.w600,
                        ),
                      ),
                      Text(
                        SyncItBranding.panelSubtitle,
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: CalendarTextStyles.hourLabel(brightness),
                      ),
                    ],
                  ),
                ),
                IconButton(
                  tooltip: 'Close',
                  onPressed: onClose,
                  visualDensity: VisualDensity.compact,
                  icon: Icon(Icons.close, size: 18, color: AppColors.textSecondary),
                ),
              ],
            ),
          ),
          Expanded(child: child),
        ],
      ),
    );
  }
}

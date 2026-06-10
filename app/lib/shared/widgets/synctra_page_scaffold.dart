import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

import '../../core/theme/app_tokens.dart';
import '../../theme.dart';
import '../state/calendar_shell_bridge.dart';
import '../state/shell_sidebar_controller.dart';

/// Reclaim-style page shell — matches calendar top bar and surface chrome.
class SynctraPageScaffold extends StatelessWidget {
  const SynctraPageScaffold({
    super.key,
    required this.title,
    required this.body,
    this.bottomBar,
    this.leading,
    this.actions,
    this.showSidebarToggle = true,
    this.showSettings = false,
  });

  final String title;
  final Widget body;
  final Widget? bottomBar;
  final Widget? leading;
  final List<Widget>? actions;
  final bool showSidebarToggle;
  final bool showSettings;

  @override
  Widget build(BuildContext context) {
    final divider = AppTokens.calendarDivider(context);
    final surface = AppTokens.calendarGridSurface(context);
    final isDesktop =
        MediaQuery.sizeOf(context).width >= ShellSidebarController.desktopBreakpoint;
    final showMenu = showSidebarToggle && !isDesktop && leading == null;
    final trailing = <Widget>[
      ...?actions,
      if (showSettings)
        IconButton(
          tooltip: 'Settings',
          icon: Icon(
            Icons.settings_outlined,
            color: AppColors.textSecondary,
            size: AppTokens.iconStandard,
          ),
          onPressed: () => context.push('/settings'),
        ),
    ];

    return Scaffold(
      backgroundColor: surface,
      body: SafeArea(
        bottom: false,
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Material(
              color: surface,
              elevation: 0,
              child: Container(
                height: AppTokens.pageTopBarHeight,
                padding: const EdgeInsets.symmetric(
                  horizontal: AppTokens.space8,
                ),
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
                    if (leading != null)
                      leading!
                    else if (showMenu)
                      IconButton(
                        tooltip: 'Navigation menu',
                        icon: Icon(
                          Icons.menu,
                          color: AppColors.textSecondary,
                          size: AppTokens.iconStandard,
                        ),
                        onPressed: () =>
                            CalendarShellBridge.instance.openDrawer?.call(),
                      ),
                    Expanded(
                      child: Text(
                        title,
                        style: CalendarTextStyles.topBarDate(
                          Theme.of(context).brightness,
                        ).copyWith(
                          fontSize: 16,
                          fontWeight: FontWeight.w600,
                        ),
                      ),
                    ),
                    ...trailing,
                  ],
                ),
              ),
            ),
            Expanded(child: body),
          ],
        ),
      ),
      bottomNavigationBar: bottomBar == null
          ? null
          : DecoratedBox(
              decoration: BoxDecoration(
                color: surface,
                border: Border(
                  top: BorderSide(
                    color: divider,
                    width: AppTokens.calendarDividerThickness,
                  ),
                ),
              ),
              child: SafeArea(child: bottomBar!),
            ),
    );
  }
}

/// Centers page content with a Reclaim-style max width.
class SynctraPageContent extends StatelessWidget {
  const SynctraPageContent({
    super.key,
    required this.child,
    this.maxWidth = AppTokens.pageContentMaxWidth,
    this.padding = const EdgeInsets.fromLTRB(
      AppTokens.space24,
      AppTokens.space16,
      AppTokens.space24,
      AppTokens.space32,
    ),
  });

  final Widget child;
  final double maxWidth;
  final EdgeInsetsGeometry padding;

  @override
  Widget build(BuildContext context) {
    return Align(
      alignment: Alignment.topCenter,
      child: ConstrainedBox(
        constraints: BoxConstraints(maxWidth: maxWidth),
        child: Padding(
          padding: padding,
          child: child,
        ),
      ),
    );
  }
}

/// Thin step progress strip for onboarding.
class SynctraStepProgress extends StatelessWidget {
  const SynctraStepProgress({
    super.key,
    required this.step,
    required this.totalSteps,
    required this.label,
  });

  final int step;
  final int totalSteps;
  final String label;

  @override
  Widget build(BuildContext context) {
    final brightness = Theme.of(context).brightness;
    final divider = AppTokens.calendarDivider(context);
    final progress = (step + 1) / totalSteps;

    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        SizedBox(
          height: 3,
          child: ColoredBox(
            color: divider.withValues(alpha: 0.35),
            child: Align(
              alignment: Alignment.centerLeft,
              child: FractionallySizedBox(
                widthFactor: progress.clamp(0.0, 1.0),
                child: ColoredBox(color: AppColors.primary),
              ),
            ),
          ),
        ),
        Padding(
          padding: const EdgeInsets.fromLTRB(
            AppTokens.space24,
            AppTokens.space12,
            AppTokens.space24,
            AppTokens.space4,
          ),
          child: Text(
            label,
            style: CalendarTextStyles.hourLabel(brightness).copyWith(
              fontSize: 12,
              fontWeight: FontWeight.w500,
              letterSpacing: 0.2,
            ),
          ),
        ),
      ],
    );
  }
}

/// Ghost text button — secondary actions in settings and onboarding.
class SynctraGhostButton extends StatelessWidget {
  const SynctraGhostButton({
    super.key,
    required this.onPressed,
    required this.label,
    this.icon,
  });

  final VoidCallback? onPressed;
  final String label;
  final IconData? icon;

  @override
  Widget build(BuildContext context) {
    final style = TextButton.styleFrom(
      foregroundColor: AppColors.textSecondary,
      visualDensity: VisualDensity.compact,
      padding: const EdgeInsets.symmetric(
        horizontal: AppTokens.space12,
        vertical: AppTokens.space8,
      ),
      textStyle: CalendarTextStyles.upcomingRow(Theme.of(context).brightness)
          .copyWith(fontWeight: FontWeight.w500),
    );

    if (icon != null) {
      return TextButton.icon(
        style: style,
        onPressed: onPressed,
        icon: Icon(icon, size: AppTokens.iconInline),
        label: Text(label),
      );
    }
    return TextButton(
      style: style,
      onPressed: onPressed,
      child: Text(label),
    );
  }
}

/// Primary action button — matches calendar "+ New" styling.
class SynctraPrimaryButton extends StatelessWidget {
  const SynctraPrimaryButton({
    super.key,
    required this.onPressed,
    required this.label,
    this.icon,
    this.expand = false,
  });

  final VoidCallback? onPressed;
  final String label;
  final IconData? icon;
  final bool expand;

  @override
  Widget build(BuildContext context) {
    final style = FilledButton.styleFrom(
      visualDensity: VisualDensity.compact,
      minimumSize: Size(expand ? double.infinity : 88, AppTokens.buttonHeight),
      padding: const EdgeInsets.symmetric(horizontal: AppTokens.space20),
      backgroundColor: AppColors.primary,
      elevation: 0,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(24),
      ),
    );

    if (icon != null) {
      return FilledButton.icon(
        style: style,
        onPressed: onPressed,
        icon: Icon(icon, size: AppTokens.iconInline),
        label: Text(label),
      );
    }
    return FilledButton(
      style: style,
      onPressed: onPressed,
      child: Text(label),
    );
  }
}

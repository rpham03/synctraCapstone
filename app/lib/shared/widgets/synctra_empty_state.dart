import 'package:flutter/material.dart';

import '../../core/theme/app_tokens.dart';
import '../../theme.dart';

class SynctraEmptyState extends StatelessWidget {
  final IconData icon;
  final String title;
  final String? message;
  final Widget? action;

  const SynctraEmptyState({
    super.key,
    required this.icon,
    required this.title,
    this.message,
    this.action,
  });

  @override
  Widget build(BuildContext context) {
    final brightness = Theme.of(context).brightness;
    return Center(
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 32, vertical: 24),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(icon, size: 48, color: AppColors.textTertiary),
            const SizedBox(height: AppTokens.space16),
            Text(
              title,
              textAlign: TextAlign.center,
              style: CalendarTextStyles.upcomingRow(brightness).copyWith(
                fontWeight: FontWeight.w600,
                fontSize: 15,
              ),
            ),
            if (message != null) ...[
              const SizedBox(height: AppTokens.space8),
              Text(
                message!,
                textAlign: TextAlign.center,
                style: CalendarTextStyles.hourLabel(brightness).copyWith(
                  fontSize: 13,
                  height: 1.45,
                ),
              ),
            ],
            if (action != null) ...[
              const SizedBox(height: AppTokens.space20),
              action!,
            ],
          ],
        ),
      ),
    );
  }
}

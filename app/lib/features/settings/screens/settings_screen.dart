// Account, sign-out, and links — full-screen outside the main tab shell.
import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import 'package:supabase_flutter/supabase_flutter.dart';

import '../../../core/constants/api_constants.dart';
import '../../../core/theme/app_theme.dart';
import '../../../shared/services/auth_service.dart';
import '../../../shared/services/theme_mode_notifier.dart';

class SettingsScreen extends StatelessWidget {
  const SettingsScreen({super.key});

  @override
  Widget build(BuildContext context) {
    final user = Supabase.instance.client.auth.currentUser;
    final email = user?.email ?? 'Not signed in';
    final scheme = Theme.of(context).colorScheme;

    return Scaffold(
      appBar: AppBar(
        leading: IconButton(
          icon: const Icon(Icons.arrow_back),
          onPressed: () => context.canPop() ? context.pop() : context.go('/calendar'),
        ),
        title: const Text('Settings'),
      ),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          ListTile(
            leading: CircleAvatar(
              backgroundColor: AppColors.primary.withAlpha(40),
              child: const Icon(Icons.person_outline, color: AppColors.primary),
            ),
            title: const Text('Account'),
            subtitle: Text(email),
          ),
          const Divider(),
          ListenableBuilder(
            listenable: ThemeModeNotifier.instance,
            builder: (context, _) {
              final mode = ThemeModeNotifier.instance.themeMode;
              return Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  ListTile(
                    leading: const Icon(Icons.brightness_6_outlined),
                    title: const Text('Appearance'),
                    subtitle: const Text('Light, dark, or match your device'),
                  ),
                  Padding(
                    padding: const EdgeInsets.fromLTRB(16, 0, 16, 8),
                    child: SegmentedButton<ThemeMode>(
                      segments: const [
                        ButtonSegment(
                          value: ThemeMode.light,
                          icon: Icon(Icons.light_mode_outlined, size: 18),
                          label: Text('Light'),
                        ),
                        ButtonSegment(
                          value: ThemeMode.dark,
                          icon: Icon(Icons.dark_mode_outlined, size: 18),
                          label: Text('Dark'),
                        ),
                        ButtonSegment(
                          value: ThemeMode.system,
                          icon: Icon(Icons.settings_brightness_outlined, size: 18),
                          label: Text('System'),
                        ),
                      ],
                      selected: {mode},
                      onSelectionChanged: (selection) {
                        ThemeModeNotifier.instance.setThemeMode(selection.first);
                      },
                    ),
                  ),
                ],
              );
            },
          ),
          const Divider(),
          ListTile(
            leading: const Icon(Icons.school_outlined),
            title: const Text('Canvas'),
            subtitle: Text(ApiConstants.canvasWebBaseUrl),
            onTap: () {
              ScaffoldMessenger.of(context).showSnackBar(
                const SnackBar(
                  content: Text('Open Canvas in your browser to link courses and sync assignments.'),
                ),
              );
            },
          ),
          ListTile(
            leading: const Icon(Icons.link_outlined),
            title: const Text('Calendar feeds'),
            subtitle: const Text('Add iCal URLs from the Calendar tab'),
            onTap: () => context.go('/calendar'),
          ),
          const Divider(),
          ListTile(
            leading: Icon(Icons.logout, color: scheme.error),
            title: Text('Sign out', style: TextStyle(color: scheme.error)),
            enabled: user != null,
            onTap: user == null
                ? null
                : () async {
                    final ok = await showDialog<bool>(
                      context: context,
                      builder: (ctx) => AlertDialog(
                        title: const Text('Sign out?'),
                        content: const Text('You will need to sign in again to sync your data.'),
                        actions: [
                          TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Cancel')),
                          FilledButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('Sign out')),
                        ],
                      ),
                    );
                    if (ok != true || !context.mounted) return;
                    await AuthService().signOut();
                    if (context.mounted) context.go('/login');
                  },
          ),
        ],
      ),
    );
  }
}

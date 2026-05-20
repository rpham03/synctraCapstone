// Declarative app router — redirects unauthenticated users to login.
import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import 'package:supabase_flutter/supabase_flutter.dart';

import '../../features/auth/screens/login_screen.dart';
import '../../features/auth/screens/signup_screen.dart';
import '../../features/calendar/screens/calendar_screen.dart';
import '../../features/tasks/screens/tasks_screen.dart';
import '../../features/chat/screens/chat_screen.dart';
import '../../features/collab/screens/collab_screen.dart';
import '../../features/settings/screens/settings_screen.dart';
import '../../shared/widgets/main_shell.dart';

/// UI preview without Supabase login. Run with:
/// `flutter run --dart-define=PREVIEW_NO_AUTH=true`
/// (same flag for web, e.g. `flutter run -d chrome --dart-define=PREVIEW_NO_AUTH=true`.)
const bool _previewNoAuth =
    bool.fromEnvironment('PREVIEW_NO_AUTH', defaultValue: false);

class AppRouter {
  static final _rootNavigatorKey = GlobalKey<NavigatorState>();

  static final GoRouter router = GoRouter(
        navigatorKey: _rootNavigatorKey,
        initialLocation: '/calendar',
        // Redirect to login if user is not authenticated
        redirect: (context, state) {
          if (_previewNoAuth) return null;

          final session = Supabase.instance.client.auth.currentSession;
          final isAuth = session != null;
          final isOnAuth =
              state.matchedLocation == '/login' ||
              state.matchedLocation == '/signup';

          if (!isAuth && !isOnAuth) return '/login';
          if (isAuth && isOnAuth) return '/calendar';
          return null;
        },
        routes: [
          // Auth routes — outside the shell (no bottom nav)
          GoRoute(
            path: '/login',
            builder: (_, __) => const LoginScreen(),
          ),
          GoRoute(
            path: '/signup',
            builder: (_, __) => const SignupScreen(),
          ),

          // Main shell — IndexedStack keeps each tab’s state while switching.
          StatefulShellRoute.indexedStack(
            builder: (context, state, navigationShell) {
              return MainShell(navigationShell: navigationShell);
            },
            branches: [
              StatefulShellBranch(
                routes: [
                  GoRoute(
                    path: '/calendar',
                    builder: (_, __) => const CalendarScreen(),
                  ),
                ],
              ),
              StatefulShellBranch(
                routes: [
                  GoRoute(
                    path: '/tasks',
                    builder: (_, __) => const TasksScreen(),
                  ),
                ],
              ),
              StatefulShellBranch(
                routes: [
                  GoRoute(
                    path: '/chat',
                    builder: (_, __) => const ChatScreen(),
                  ),
                ],
              ),
              StatefulShellBranch(
                routes: [
                  GoRoute(
                    path: '/collab',
                    builder: (_, __) => const CollabScreen(),
                  ),
                ],
              ),
            ],
          ),

          GoRoute(
            path: '/settings',
            parentNavigatorKey: _rootNavigatorKey,
            builder: (_, __) => const SettingsScreen(),
          ),

          // Full-screen routes (no shell / no nav bar)
          GoRoute(
            path: '/schedule/suggest',
            parentNavigatorKey: _rootNavigatorKey,
            builder: (_, __) => const _ScheduleSuggestScreen(),
          ),
        ],
      );
}

class _ScheduleSuggestScreen extends StatelessWidget {
  const _ScheduleSuggestScreen();

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        leading: IconButton(
          icon: const Icon(Icons.close),
          onPressed: () => context.canPop() ? context.pop() : context.go('/calendar'),
        ),
        title: const Text('Suggested schedule'),
      ),
      body: Padding(
        padding: const EdgeInsets.all(24),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            const Text(
              'Synctra packs study blocks around your classes and iCal busy times. '
              'Use the sparkles button on Calendar to generate a week, or ask the AI chat.',
              style: TextStyle(height: 1.4),
            ),
            const SizedBox(height: 24),
            FilledButton.icon(
              onPressed: () => context.go('/calendar'),
              icon: const Icon(Icons.calendar_month_outlined),
              label: const Text('Open calendar'),
            ),
            const SizedBox(height: 12),
            OutlinedButton.icon(
              onPressed: () => context.go('/chat'),
              icon: const Icon(Icons.chat_bubble_outline),
              label: const Text('Open AI chat'),
            ),
          ],
        ),
      ),
    );
  }
}

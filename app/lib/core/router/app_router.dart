// Declarative app router — redirects unauthenticated users to login.

import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

import 'package:supabase_flutter/supabase_flutter.dart';



import '../../core/constants/preview_flags.dart';
import '../../features/auth/screens/login_screen.dart';

import '../../features/auth/screens/signup_screen.dart';

import '../../features/calendar/screens/calendar_screen.dart';

import '../../features/chat/screens/chat_screen.dart';

import '../../features/collab/screens/collab_screen.dart';

import '../../features/onboarding/screens/onboarding_wizard.dart';

import '../../features/settings/screens/settings_screen.dart';

import '../../features/tasks/screens/tasks_screen.dart';

import '../../shared/services/user_settings_service.dart';

import '../../shared/widgets/main_shell.dart';



/// UI preview without Supabase login. Run with:
/// `flutter run --dart-define=PREVIEW_NO_AUTH=true`
///
/// Force onboarding every launch (demo):
/// `flutter run --dart-define=PREVIEW_NO_AUTH=true --dart-define=PREVIEW_FORCE_ONBOARDING=true`
///
/// Hot reload does NOT apply dart-defines — stop and run again.



class AppRouter {

  static final _rootNavigatorKey = GlobalKey<NavigatorState>();



  static GoRouter createRouter(UserSettingsService settingsService) {
    final startOnboarding = !settingsService.isLoaded ||
        !settingsService.onboardingComplete ||
        (PreviewFlags.noAuth && PreviewFlags.forceOnboarding);

    return GoRouter(
        navigatorKey: _rootNavigatorKey,
        initialLocation: startOnboarding ? '/onboarding' : '/calendar',
        refreshListenable: settingsService,
        redirect: (context, state) {
          final loc = state.matchedLocation;
          final isOnboarding = loc == '/onboarding';

          if (PreviewFlags.noAuth) {
            if (!settingsService.isLoaded) {
              return isOnboarding ? null : '/onboarding';
            }
            if (!settingsService.onboardingComplete && !isOnboarding) {
              return '/onboarding';
            }
            if (settingsService.onboardingComplete && isOnboarding) {
              return '/calendar';
            }
            return null;
          }

          final session = Supabase.instance.client.auth.currentSession;
          final isAuth = session != null;
          final isOnAuth = loc == '/login' || loc == '/signup';

          // Allow /onboarding without login (preview / local-only setup).
          if (!isAuth && !isOnAuth && !isOnboarding) return '/login';

          if (isAuth && isOnAuth) {

            return settingsService.onboardingComplete ? '/calendar' : '/onboarding';

          }



          if (isAuth && settingsService.isLoaded) {

            if (!settingsService.onboardingComplete && !isOnboarding) {

              return '/onboarding';

            }

            if (settingsService.onboardingComplete && isOnboarding) {

              return '/calendar';

            }

          }



          return null;

        },

        routes: [

          GoRoute(

            path: '/login',

            builder: (_, __) => const LoginScreen(),

          ),

          GoRoute(

            path: '/signup',

            builder: (_, __) => const SignupScreen(),

          ),

          GoRoute(

            path: '/onboarding',

            builder: (_, __) => const OnboardingWizard(),

          ),

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

          GoRoute(

            path: '/schedule/suggest',

            parentNavigatorKey: _rootNavigatorKey,

            builder: (_, __) => const _ScheduleSuggestScreen(),

          ),

        ],

      );
  }
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


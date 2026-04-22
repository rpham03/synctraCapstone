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
import '../../shared/widgets/main_shell.dart';

class AppRouter {
  static final _rootNavigatorKey = GlobalKey<NavigatorState>();
  static final _shellNavigatorKey = GlobalKey<NavigatorState>();

  static GoRouter get router => GoRouter(
        navigatorKey: _rootNavigatorKey,
        initialLocation: '/calendar',
        // Redirect to login if user is not authenticated
        redirect: (context, state) {
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

          // Main app shell — bottom nav wraps these four tabs
          ShellRoute(
            navigatorKey: _shellNavigatorKey,
            builder: (_, __, child) => MainShell(child: child),
            routes: [
              GoRoute(
                path: '/calendar',
                builder: (_, __) => const CalendarScreen(),
              ),
              GoRoute(
                path: '/tasks',
                builder: (_, __) => const TasksScreen(),
              ),
              GoRoute(
                path: '/chat',
                builder: (_, __) => const ChatScreen(),
              ),
              GoRoute(
                path: '/collab',
                builder: (_, __) => const CollabScreen(),
              ),
            ],
          ),

          // Full-screen routes (no shell / no nav bar)
          GoRoute(
            path: '/schedule/suggest',
            parentNavigatorKey: _rootNavigatorKey,
            builder: (_, __) => const Scaffold(
              body: Center(child: Text('Schedule suggestions — coming soon')),
            ),
          ),
        ],
      );
}

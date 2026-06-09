// App entry point — initializes Supabase then runs the Synctra widget tree.
import 'dart:async';

import 'package:flutter/material.dart';
import 'package:get_it/get_it.dart';
import 'package:supabase_flutter/supabase_flutter.dart';

import 'core/router/app_router.dart';
import 'shared/services/canvas_tasks_service.dart';
import 'shared/services/manual_events_store.dart';
import 'shared/services/synctra_chat_service.dart';
import 'shared/services/synctra_chat_store.dart';
import 'shared/services/schedule_chat_coordinator.dart';
import 'shared/services/habit_session_store.dart';
import 'shared/services/suggested_schedule_store.dart';
import 'shared/services/theme_mode_notifier.dart';
import 'shared/services/user_settings_service.dart';
import 'theme.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();

  registerSuggestedScheduleStore();
  registerHabitSessionStore();
  registerManualEventsStore();
  registerCanvasTasksService();
  registerSynctraChatStore();
  registerSynctraChatService();
  registerUserSettingsService();
  registerLlmService();
  registerScheduleChatCoordinator();
  await ThemeModeNotifier.load();

  await Supabase.initialize(
    url: 'https://wewuafrajfsqhaajofju.supabase.co',
    anonKey: 'sb_publishable_nLRlBikbHmLFz3uM762vXg_FNvH6GPa',
  );

  _loadUserScopedData();

  final settings = GetIt.instance<UserSettingsService>();
  attachUserSettingsAuthListener(settings);
  await settings.load();

  runApp(SynctraApp(settingsService: settings));
}

/// Load the signed-in user's saved study blocks now, and reload whenever the
/// account changes, so chat-created events reappear for that user on relaunch
/// and never leak between accounts on a shared device.
void _loadUserScopedData() {
  final store = GetIt.instance<SuggestedScheduleStore>();
  final habitStore = GetIt.instance<HabitSessionStore>();
  final manual = GetIt.instance<ManualEventsStore>();
  // loadPersisted/syncFromRemote reconcile the local cache with Supabase, so
  // chat blocks and "+" events saved on any device reappear after login.
  unawaited(store.loadPersisted());
  unawaited(habitStore.loadPersisted());
  unawaited(manual.syncFromRemote());
  Supabase.instance.client.auth.onAuthStateChange.listen((data) {
    switch (data.event) {
      case AuthChangeEvent.initialSession:
      case AuthChangeEvent.signedIn:
      case AuthChangeEvent.signedOut:
        unawaited(store.loadPersisted());
        unawaited(habitStore.loadPersisted());
        unawaited(manual.syncFromRemote());
      default:
        break;
    }
  });
}

class SynctraApp extends StatefulWidget {
  final UserSettingsService settingsService;
  const SynctraApp({super.key, required this.settingsService});

  @override
  State<SynctraApp> createState() => _SynctraAppState();
}

class _SynctraAppState extends State<SynctraApp> {
  late final _router = AppRouter.createRouter(widget.settingsService);

  @override
  Widget build(BuildContext context) {
    return ListenableBuilder(
      listenable: ThemeModeNotifier.instance,
      builder: (context, _) {
        return MaterialApp.router(
          title: 'Synctra',
          theme: AppTheme.light,
          darkTheme: AppTheme.dark,
          themeMode: ThemeModeNotifier.instance.themeMode,
          routerConfig: _router,
          debugShowCheckedModeBanner: false,
        );
      },
    );
  }
}

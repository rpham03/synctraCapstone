// App entry point — initializes Supabase then runs the Synctra widget tree.
import 'package:flutter/material.dart';
import 'package:supabase_flutter/supabase_flutter.dart';

import 'core/router/app_router.dart';
import 'shared/services/canvas_tasks_service.dart';
import 'shared/services/synctra_chat_service.dart';
import 'shared/services/synctra_chat_store.dart';
import 'shared/services/suggested_schedule_store.dart';
import 'shared/services/theme_mode_notifier.dart';
import 'theme.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();

  registerSuggestedScheduleStore();
  registerCanvasTasksService();
  registerSynctraChatStore();
  registerSynctraChatService();
  await ThemeModeNotifier.load();

  // Initialize Supabase — replace the placeholders with your project values
  // from https://supabase.com/dashboard → Settings → API
  await Supabase.initialize(
    url: 'https://wewuafrajfsqhaajofju.supabase.co',
    anonKey: 'sb_publishable_nLRlBikbHmLFz3uM762vXg_FNvH6GPa',
  );

  runApp(const SynctraApp());
}

class SynctraApp extends StatelessWidget {
  const SynctraApp({super.key});

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
          routerConfig: AppRouter.router,
          debugShowCheckedModeBanner: false,
        );
      },
    );
  }
}

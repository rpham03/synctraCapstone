// App entry point — initializes Supabase then runs the Synctra widget tree.
import 'package:flutter/material.dart';
import 'package:supabase_flutter/supabase_flutter.dart';

import 'core/router/app_router.dart';
import 'core/theme/app_theme.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();

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
    return MaterialApp.router(
      title: 'Synctra',
      theme: AppTheme.light,
      darkTheme: AppTheme.dark,
      themeMode: ThemeMode.system,
      routerConfig: AppRouter.router,
      debugShowCheckedModeBanner: false,
    );
  }
}

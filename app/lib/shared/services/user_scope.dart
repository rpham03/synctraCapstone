import 'package:supabase_flutter/supabase_flutter.dart';

/// The current Supabase user id, or 'app-user' when signed out.
///
/// Locally-persisted, user-authored data (chat study blocks, "+" manual events)
/// is keyed by this so each account only sees its own events when it signs back
/// in on this device — the same idea as imported Canvas/course data being tied
/// to the user, just stored locally rather than synced to the server.
String currentUserScope() {
  try {
    return Supabase.instance.client.auth.currentUser?.id ?? 'app-user';
  } catch (_) {
    return 'app-user';
  }
}

/// A SharedPreferences key scoped to the current user (e.g. "base_<userId>").
String userScopedKey(String base) => '${base}_${currentUserScope()}';

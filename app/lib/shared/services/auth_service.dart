// Wraps Supabase auth — sign in, sign up, Google OAuth, and sign out.
import 'package:supabase_flutter/supabase_flutter.dart';

class AuthService {
  final _client = Supabase.instance.client;

  // Current signed-in user, null if logged out.
  User? get currentUser => _client.auth.currentUser;

  // Stream that fires whenever auth state changes (login / logout).
  Stream<AuthState> get authStateChanges => _client.auth.onAuthStateChange;

  // --- Email / Password ---

  Future<AuthResponse> signUpWithEmail({
    required String email,
    required String password,
    required String fullName,
  }) {
    return _client.auth.signUp(
      email: email,
      password: password,
      data: {'full_name': fullName},
    );
  }

  Future<AuthResponse> signInWithEmail({
    required String email,
    required String password,
  }) {
    return _client.auth.signInWithPassword(
      email: email,
      password: password,
    );
  }

  // --- Google OAuth ---

  Future<bool> signInWithGoogle() async {
    return _client.auth.signInWithOAuth(
      OAuthProvider.google,
      redirectTo: 'io.synctra.app://login-callback',
      scopes: 'email profile https://www.googleapis.com/auth/calendar',
    );
  }

  // --- Sign out ---

  Future<void> signOut() => _client.auth.signOut();
}

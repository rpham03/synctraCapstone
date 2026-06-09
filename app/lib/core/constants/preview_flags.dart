/// Compile-time flags for local demo / UI preview runs.
class PreviewFlags {
  PreviewFlags._();

  /// Skip login redirect. Settings use local `preview` user, not Supabase session.
  static const bool noAuth =
      bool.fromEnvironment('PREVIEW_NO_AUTH', defaultValue: false);

  /// Always open onboarding (ignores saved onboarding_complete). For demos.
  static const bool forceOnboarding =
      bool.fromEnvironment('PREVIEW_FORCE_ONBOARDING', defaultValue: false);
}

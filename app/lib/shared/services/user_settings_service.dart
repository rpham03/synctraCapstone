import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:get_it/get_it.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:supabase_flutter/supabase_flutter.dart';

import '../../core/constants/preview_flags.dart';
import '../../data/models/user_settings.dart';

/// CRUD for `user_settings` with local cache fallback when Supabase is unavailable.
class UserSettingsService extends ChangeNotifier {
  UserSettingsService();

  static const _cacheKey = 'synctra_user_settings_v1';
  static const _draftKey = 'synctra_onboarding_draft_v1';

  UserSettings? _settings;
  bool _loaded = false;
  Timer? _saveDebounce;

  UserSettings? get settings => _settings;
  bool get isLoaded => _loaded;
  bool get onboardingComplete => _settings?.onboardingComplete ?? false;

  UserWorkPreferences get workPreferences =>
      _settings?.workPreferences ??
      UserSettings.defaults('').workPreferences;

  Future<void> load() async {
    // Preview mode always uses local preview user — ignore stale Supabase sessions.
    if (PreviewFlags.noAuth) {
      final cached = await _loadLocalCache('preview');
      _settings = cached ?? UserSettings.defaults('preview');
      if (PreviewFlags.forceOnboarding) {
        _settings = _settings!.copyWith(onboardingComplete: false);
      }
      _loaded = true;
      notifyListeners();
      return;
    }

    final user = Supabase.instance.client.auth.currentUser;
    if (user == null) {
      _settings = UserSettings.defaults('preview');
      _loaded = true;
      notifyListeners();
      return;
    }

    try {
      final row = await Supabase.instance.client
          .from('user_settings')
          .select()
          .eq('user_id', user.id)
          .maybeSingle();

      if (row != null) {
        _settings = UserSettings.fromSupabase(Map<String, dynamic>.from(row));
      } else {
        _settings = UserSettings.defaults(user.id);
        final cached = await _loadLocalCache(user.id);
        if (cached != null) _settings = cached;
      }
      await _persistLocalCache();
    } catch (e) {
      debugPrint('UserSettingsService.load fallback: $e');
      final cached = await _loadLocalCache(user.id);
      _settings = cached ?? UserSettings.defaults(user.id);
    }

    _loaded = true;
    notifyListeners();
  }

  Future<void> ensureLoaded() async {
    if (!_loaded) await load();
  }

  Future<UserSettings> getOrCreate() async {
    await ensureLoaded();
    return _settings!;
  }

  Future<void> update(UserSettings next, {bool immediate = false}) async {
    _settings = next;
    notifyListeners();
    if (immediate) {
      await _saveToSupabase();
    } else {
      _saveDebounce?.cancel();
      _saveDebounce = Timer(const Duration(milliseconds: 400), () {
        _saveToSupabase();
      });
    }
  }

  Future<void> updateField({
    ScheduleType? scheduleType,
    TimeOfDay? workStartTime,
    TimeOfDay? workEndTime,
    int? preferredSessionMinutes,
    int? breakMinutes,
    List<String>? icalLinks,
    List<String>? courseUrls,
    bool? onboardingComplete,
    bool immediate = false,
  }) async {
    final current = await getOrCreate();
    await update(
      current.copyWith(
        scheduleType: scheduleType,
        workStartTime: workStartTime,
        workEndTime: workEndTime,
        preferredSessionMinutes: preferredSessionMinutes,
        breakMinutes: breakMinutes,
        icalLinks: icalLinks,
        courseUrls: courseUrls,
        onboardingComplete: onboardingComplete,
      ),
      immediate: immediate,
    );
  }

  Future<void> applyScheduleType(ScheduleType type, {bool promptHours = false}) async {
    if (promptHours) return;
    await updateField(
      scheduleType: type,
      workStartTime: SchedulePresets.workStart(type),
      workEndTime: SchedulePresets.workEnd(type),
      immediate: true,
    );
  }

  Future<void> appendIcalLink(String url) async {
    final current = await getOrCreate();
    if (current.icalLinks.contains(url)) return;
    await updateField(icalLinks: [...current.icalLinks, url], immediate: true);
  }

  Future<void> removeIcalLink(String url) async {
    final current = await getOrCreate();
    await updateField(
      icalLinks: current.icalLinks.where((u) => u != url).toList(),
      immediate: true,
    );
  }

  Future<void> appendCourseUrl(String url) async {
    final current = await getOrCreate();
    if (current.courseUrls.contains(url)) return;
    await updateField(courseUrls: [...current.courseUrls, url], immediate: true);
  }

  Future<void> removeCourseUrl(String url) async {
    final current = await getOrCreate();
    await updateField(
      courseUrls: current.courseUrls.where((u) => u != url).toList(),
      immediate: true,
    );
  }

  Future<void> completeOnboarding(UserSettings draft) async {
    await update(
      draft.copyWith(onboardingComplete: true),
      immediate: true,
    );
    await clearOnboardingDraft();
  }

  // ── Onboarding draft (resume mid-flow) ───────────────────────────────────

  Future<void> saveOnboardingDraft(Map<String, dynamic> draft) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(_draftKey, jsonEncode(draft));
  }

  Future<Map<String, dynamic>?> loadOnboardingDraft() async {
    final prefs = await SharedPreferences.getInstance();
    final raw = prefs.getString(_draftKey);
    if (raw == null || raw.isEmpty) return null;
    try {
      return Map<String, dynamic>.from(jsonDecode(raw) as Map);
    } catch (_) {
      return null;
    }
  }

  Future<void> clearOnboardingDraft() async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.remove(_draftKey);
  }

  /// Clears saved preview onboarding so the wizard shows again.
  Future<void> resetPreviewOnboarding() async {
    if (!PreviewFlags.noAuth) return;
    final prefs = await SharedPreferences.getInstance();
    await prefs.remove(_cacheKey);
    await prefs.remove(_draftKey);
    _settings = UserSettings.defaults('preview');
    _loaded = true;
    notifyListeners();
  }

  Future<void> _saveToSupabase() async {
    if (_settings == null) return;
    await _persistLocalCache();

    final user = Supabase.instance.client.auth.currentUser;
    if (user == null || user.id != _settings!.userId) return;

    try {
      final payload = _settings!.toSupabaseMap()..remove('id');
      await Supabase.instance.client.from('user_settings').upsert(
            payload,
            onConflict: 'user_id',
          );
    } catch (e) {
      debugPrint('UserSettingsService save failed: $e');
    }
  }

  Future<void> _persistLocalCache() async {
    if (_settings == null) return;
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(_cacheKey, jsonEncode(_settings!.toSupabaseMap()));
  }

  Future<UserSettings?> _loadLocalCache(String userId) async {
    final prefs = await SharedPreferences.getInstance();
    final raw = prefs.getString(_cacheKey);
    if (raw == null) return null;
    try {
      final map = Map<String, dynamic>.from(jsonDecode(raw) as Map);
      if (map['user_id'] != userId) return null;
      return UserSettings.fromSupabase(map);
    } catch (_) {
      return null;
    }
  }
}

void registerUserSettingsService() {
  final g = GetIt.instance;
  if (!g.isRegistered<UserSettingsService>()) {
    g.registerSingleton(UserSettingsService());
  }
}

void attachUserSettingsAuthListener(UserSettingsService svc) {
  Supabase.instance.client.auth.onAuthStateChange.listen((data) {
    if (data.session != null) {
      svc.load();
    }
  });
}

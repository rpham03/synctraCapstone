// Account, work preferences, iCal feeds, course imports, sign-out.
import 'package:flutter/material.dart';
import 'package:get_it/get_it.dart';
import 'package:go_router/go_router.dart';
import 'package:supabase_flutter/supabase_flutter.dart';

import '../../../core/constants/preview_flags.dart';
import '../../../core/constants/api_constants.dart';
import '../../../core/theme/app_theme.dart';
import '../../../data/models/ical_feed.dart';
import '../../../data/models/user_settings.dart';
import '../../../data/services/course_import_service.dart';
import '../../../features/calendar/widgets/calendar_view_pill_toggle.dart';
import '../../../shared/services/auth_service.dart';
import '../../../shared/services/ical_feed_service.dart';
import '../../../shared/services/theme_mode_notifier.dart';
import '../../../shared/services/user_settings_service.dart';
import '../../../shared/widgets/synctra_page_scaffold.dart';
import '../../../theme.dart';
import '../widgets/settings_sections.dart';
import '../widgets/work_hours_range_slider.dart';

class SettingsScreen extends StatefulWidget {
  const SettingsScreen({super.key});

  @override
  State<SettingsScreen> createState() => _SettingsScreenState();
}

class _SettingsScreenState extends State<SettingsScreen> {
  late final UserSettingsService _settingsSvc;
  late final IcalFeedService _icalSvc;
  late final CourseImportService _courseSvc;

  List<IcalFeed> _feeds = [];
  List<CourseImportRecord> _courses = [];
  bool _loading = true;

  final _icalCtrl = TextEditingController();
  final _courseCtrl = TextEditingController();
  bool _icalBusy = false;
  bool _courseBusy = false;
  String? _icalStatus;
  bool _icalIsError = false;
  String? _courseError;

  @override
  void initState() {
    super.initState();
    _settingsSvc = GetIt.instance<UserSettingsService>();
    _icalSvc = IcalFeedService(settings: _settingsSvc);
    _courseSvc = CourseImportService();
    _settingsSvc.addListener(_onSettingsChanged);
    _load();
  }

  @override
  void dispose() {
    _settingsSvc.removeListener(_onSettingsChanged);
    _icalCtrl.dispose();
    _courseCtrl.dispose();
    super.dispose();
  }

  void _onSettingsChanged() {
    if (mounted) setState(() {});
  }

  Future<void> _load() async {
    await _settingsSvc.ensureLoaded();
    try {
      final feeds = await _icalSvc.loadFeeds();
      final courses = await _courseSvc.loadImports();
      if (!mounted) return;
      setState(() {
        _feeds = feeds;
        _courses = courses;
        _loading = false;
      });
    } catch (_) {
      if (mounted) setState(() => _loading = false);
    }
  }

  void _toast(String msg) {
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(content: Text(msg), duration: const Duration(seconds: 2)),
    );
  }

  Future<void> _saveSettings(UserSettings next) async {
    await _settingsSvc.update(next, immediate: true);
    _toast('Preferences saved');
  }

  Future<void> _addIcalFeed() async {
    final url = _icalCtrl.text.trim();
    if (url.isEmpty) {
      setState(() {
        _icalIsError = true;
        _icalStatus = 'Enter a calendar feed URL';
      });
      return;
    }
    setState(() {
      _icalBusy = true;
      _icalIsError = false;
      _icalStatus = null;
    });
    try {
      final feed = await _icalSvc.addFeed(url);
      if (feed == null) throw StateError('Sign in required to save calendar feeds');
      _icalCtrl.clear();
      await _load();
      setState(() => _icalStatus = 'Feed connected');
      _toast('Feed connected');
    } catch (e) {
      setState(() {
        _icalIsError = true;
        _icalStatus = e.toString();
      });
    } finally {
      if (mounted) setState(() => _icalBusy = false);
    }
  }

  Future<void> _refreshAllFeeds() async {
    setState(() => _icalBusy = true);
    try {
      await _icalSvc.syncAllFeeds();
      await _load();
      _toast('Feeds refreshed');
    } catch (e) {
      _toast('Refresh failed: $e');
    } finally {
      if (mounted) setState(() => _icalBusy = false);
    }
  }

  Future<void> _addCourse() async {
    final url = _courseCtrl.text.trim();
    if (url.isEmpty) {
      setState(() => _courseError = 'Enter a course page URL');
      return;
    }
    setState(() {
      _courseBusy = true;
      _courseError = null;
    });
    try {
      await _courseSvc.addImport(url, '');
      await _settingsSvc.appendCourseUrl(url);
      _courseCtrl.clear();
      await _load();
      _toast('Course imported');
    } catch (e) {
      setState(() => _courseError = "Couldn't import this course — check the URL");
    } finally {
      if (mounted) setState(() => _courseBusy = false);
    }
  }

  Future<void> _reimportAllCourses() async {
    setState(() => _courseBusy = true);
    try {
      for (final c in _courses) {
        await _courseSvc.syncImport(
          importId: c.id,
          url: c.courseUrl,
          name: c.courseName,
        );
      }
      await _load();
      _toast('Courses re-imported');
    } catch (e) {
      _toast('Re-import failed');
    } finally {
      if (mounted) setState(() => _courseBusy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final user = Supabase.instance.client.auth.currentUser;
    final email = user?.email ?? 'Not signed in';
    final scheme = Theme.of(context).colorScheme;
    final settings = _settingsSvc.settings;

    return SynctraPageScaffold(
      title: 'Settings',
      leading: IconButton(
        icon: const Icon(Icons.arrow_back, size: AppTokens.iconStandard),
        color: AppColors.textSecondary,
        onPressed: () => context.canPop() ? context.pop() : context.go('/calendar'),
      ),
      body: _loading || settings == null
          ? const Center(child: CircularProgressIndicator())
          : SingleChildScrollView(
              child: SynctraPageContent(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    const SettingsSectionHeader(
                      'Account',
                      description: 'Your signed-in profile for syncing data.',
                    ),
                    SettingsInsetCard(
                      child: Row(
                        children: [
                          CircleAvatar(
                            radius: 24,
                            backgroundColor: AppColors.primary.withValues(alpha: 0.12),
                            child: const Icon(
                              Icons.person_outline,
                              color: AppColors.primary,
                              size: AppTokens.iconStandard,
                            ),
                          ),
                          const SizedBox(width: AppTokens.space16),
                          Expanded(
                            child: Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                Text(
                                  'Signed in as',
                                  style: CalendarTextStyles.hourLabel(
                                    Theme.of(context).brightness,
                                  ),
                                ),
                                const SizedBox(height: AppTokens.space4),
                                Text(
                                  email,
                                  style: CalendarTextStyles.upcomingRow(
                                    Theme.of(context).brightness,
                                  ).copyWith(fontWeight: FontWeight.w600),
                                ),
                              ],
                            ),
                          ),
                        ],
                      ),
                    ),
                    const SettingsSectionHeader(
                      'Appearance',
                      description: 'Light, dark, or match your device.',
                    ),
                    SettingsInsetCard(
                      child: ListenableBuilder(
                        listenable: ThemeModeNotifier.instance,
                        builder: (context, _) {
                          final mode = ThemeModeNotifier.instance.themeMode;
                          return CalendarViewPillToggle<ThemeMode>(
                            segments: const [
                              ThemeMode.light,
                              ThemeMode.dark,
                              ThemeMode.system,
                            ],
                            selected: mode,
                            onChanged: ThemeModeNotifier.instance.setThemeMode,
                            labelBuilder: (value) => switch (value) {
                              ThemeMode.light => 'Light',
                              ThemeMode.dark => 'Dark',
                              ThemeMode.system => 'System',
                            },
                          );
                        },
                      ),
                    ),
                    const SettingsSectionHeader(
                      'Study preferences',
                      description: 'When and how Synctra schedules focus blocks.',
                    ),
                    SettingsInsetCard(
                      child: WorkPreferencesForm(
                        workStart: settings.workStartTime,
                        workEnd: settings.workEndTime,
                        sessionMinutes: settings.preferredSessionMinutes,
                        breakMinutes: settings.breakMinutes,
                        onWorkRangeChanged: (range) => _saveSettings(settings.copyWith(
                          workStartTime: WorkHoursSlots.slotToTime(range.start.round()),
                          workEndTime: WorkHoursSlots.slotToTime(range.end.round()),
                        )),
                        onSessionChanged: (v) =>
                            _saveSettings(settings.copyWith(preferredSessionMinutes: v)),
                        onBreakChanged: (v) => _saveSettings(settings.copyWith(breakMinutes: v)),
                      ),
                    ),
                    const SettingsSectionHeader(
                      'Calendar feeds',
                      description: 'iCal links from Google Calendar or Canvas export.',
                    ),
                    SettingsInsetCard(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.stretch,
                        children: [
                          IcalFeedEditor(
                            controller: _icalCtrl,
                            loading: _icalBusy,
                            statusMessage: _icalStatus,
                            isError: _icalIsError,
                            hintText: 'https://calendar.google.com/calendar/ical/…',
                            helperText: 'Paste a secret iCal address — not your normal calendar URL.',
                            onAdd: _addIcalFeed,
                          ),
                          const SizedBox(height: AppTokens.space12),
                          Align(
                            alignment: Alignment.centerLeft,
                            child: SynctraGhostButton(
                              onPressed: _icalBusy ? null : _refreshAllFeeds,
                              icon: Icons.refresh,
                              label: 'Refresh all feeds',
                            ),
                          ),
                          if (_feeds.isEmpty)
                            Padding(
                              padding: const EdgeInsets.only(top: AppTokens.space12),
                              child: Text(
                                'No feeds connected yet.',
                                style: CalendarTextStyles.hourLabel(Theme.of(context).brightness),
                              ),
                            ),
                          ..._feeds.map(
                            (f) => Padding(
                              padding: const EdgeInsets.only(top: AppTokens.space8),
                              child: IcalFeedListTile(
                                feed: f,
                                onRefresh: () async {
                                  await _icalSvc.syncFeed(f);
                                  await _load();
                                  _toast('Feed refreshed');
                                },
                                onDelete: () async {
                                  await _icalSvc.removeFeed(f);
                                  await _load();
                                  _toast('Feed removed');
                                },
                              ),
                            ),
                          ),
                        ],
                      ),
                    ),
                    const SettingsSectionHeader(
                      'Course websites',
                      description: 'Public UW course pages for lectures and due dates.',
                    ),
                    SettingsInsetCard(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.stretch,
                        children: [
                          Row(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Expanded(
                                child: TextField(
                                  controller: _courseCtrl,
                                  decoration: InputDecoration(
                                    hintText: 'https://courses.cs.washington.edu/courses/…',
                                    helperText: _courseError == null
                                        ? 'We import events from the course schedule page.'
                                        : null,
                                    errorText: _courseError,
                                  ),
                                ),
                              ),
                              const SizedBox(width: AppTokens.space8),
                              Padding(
                                padding: const EdgeInsets.only(top: AppTokens.space4),
                                child: _courseBusy
                                    ? SizedBox(
                                        width: 88,
                                        height: AppTokens.buttonHeight,
                                        child: Center(
                                          child: SizedBox(
                                            width: 18,
                                            height: 18,
                                            child: CircularProgressIndicator(
                                              strokeWidth: 2,
                                              color: scheme.primary,
                                            ),
                                          ),
                                        ),
                                      )
                                    : SynctraPrimaryButton(
                                        onPressed: _addCourse,
                                        label: 'Import',
                                      ),
                              ),
                            ],
                          ),
                          const SizedBox(height: AppTokens.space12),
                          Align(
                            alignment: Alignment.centerLeft,
                            child: SynctraGhostButton(
                              onPressed: _courseBusy || _courses.isEmpty ? null : _reimportAllCourses,
                              icon: Icons.refresh,
                              label: 'Re-import all courses',
                            ),
                          ),
                          if (_courses.isEmpty)
                            Padding(
                              padding: const EdgeInsets.only(top: AppTokens.space12),
                              child: Text(
                                'No courses imported yet.',
                                style: CalendarTextStyles.hourLabel(Theme.of(context).brightness),
                              ),
                            ),
                          ..._courses.map(
                            (c) => Padding(
                              padding: const EdgeInsets.only(top: AppTokens.space8),
                              child: CourseImportListTile(
                                name: c.courseName,
                                url: c.courseUrl,
                                totalImported: c.eventCount,
                                onReimport: () async {
                                  await _courseSvc.syncImport(
                                    importId: c.id,
                                    url: c.courseUrl,
                                    name: c.courseName,
                                  );
                                  await _load();
                                  _toast('Course re-imported');
                                },
                                onDelete: () async {
                                  final removeEvents = await showDialog<bool>(
                                    context: context,
                                    builder: (ctx) => AlertDialog(
                                      title: const Text('Remove course?'),
                                      content: const Text('Also remove associated calendar events?'),
                                      actions: [
                                        TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Keep events')),
                                        FilledButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('Remove all')),
                                      ],
                                    ),
                                  );
                                  await _courseSvc.removeImport(c.id);
                                  await _settingsSvc.removeCourseUrl(c.courseUrl);
                                  await _load();
                                  if (removeEvents == true) _toast('Course and events removed');
                                },
                              ),
                            ),
                          ),
                        ],
                      ),
                    ),
                    const SettingsSectionHeader(
                      'Integrations',
                      description: 'External services Synctra can connect to.',
                    ),
                    SettingsInsetCard(
                      padding: EdgeInsets.zero,
                      child: SettingsActionRow(
                        icon: Icons.school_outlined,
                        label: 'Canvas LMS',
                        description: ApiConstants.canvasWebBaseUrl,
                      ),
                    ),
                    if (PreviewFlags.noAuth) ...[
                      const SettingsSectionHeader('Preview'),
                      SettingsInsetCard(
                        padding: EdgeInsets.zero,
                        child: SettingsActionRow(
                          icon: Icons.replay_outlined,
                          label: 'Replay onboarding',
                          description: 'Reset local setup and open the wizard again',
                          trailing: const Icon(Icons.chevron_right, size: AppTokens.iconStandard),
                          onTap: () async {
                            await _settingsSvc.resetPreviewOnboarding();
                            if (!context.mounted) return;
                            context.go('/onboarding');
                          },
                        ),
                      ),
                    ],
                    const SettingsSectionHeader(
                      'Session',
                      description: 'Sign out of this device.',
                    ),
                    SettingsInsetCard(
                      padding: EdgeInsets.zero,
                      child: SettingsActionRow(
                        icon: Icons.logout,
                        label: 'Sign out',
                        description: user == null ? 'Not signed in' : 'You will need to sign in again to sync',
                        foregroundColor: scheme.error,
                        onTap: user == null
                            ? null
                            : () async {
                                final ok = await showDialog<bool>(
                                  context: context,
                                  builder: (ctx) => AlertDialog(
                                    title: const Text('Sign out?'),
                                    content: const Text('You will need to sign in again to sync your data.'),
                                    actions: [
                                      TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Cancel')),
                                      FilledButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('Sign out')),
                                    ],
                                  ),
                                );
                                if (ok != true || !context.mounted) return;
                                await AuthService().signOut();
                                if (context.mounted) context.go('/login');
                              },
                      ),
                    ),
                  ],
                ),
              ),
            ),
    );
  }
}

import 'package:flutter/material.dart';
import 'package:get_it/get_it.dart';
import 'package:go_router/go_router.dart';
import 'package:intl/intl.dart';
import 'package:supabase_flutter/supabase_flutter.dart';

import '../../../core/constants/preview_flags.dart';
import '../../../core/theme/app_tokens.dart';
import '../../../data/models/ical_feed.dart';
import '../../../data/models/user_settings.dart';
import '../../../data/services/course_import_service.dart';
import '../../settings/widgets/settings_sections.dart';
import '../../settings/widgets/work_hours_range_slider.dart';
import '../../../shared/services/ical_feed_service.dart';
import '../../../shared/services/user_settings_service.dart';
import '../../../shared/widgets/synctra_page_scaffold.dart';
import '../../../theme.dart';

/// Onboarding: welcome → work hours → iCal → courses → review (5 steps).
class OnboardingWizard extends StatefulWidget {
  const OnboardingWizard({super.key});

  static const int stepCount = 5;

  static const _steps = <_OnboardingStepInfo>[
    _OnboardingStepInfo(
      shortLabel: 'Welcome',
      headline: 'Your schedule, tasks, and study time in one place',
      subtitle: 'Synctra brings your calendar, assignments, and focus blocks together.',
      purpose: 'This setup takes about 2 minutes.',
    ),
    _OnboardingStepInfo(
      shortLabel: 'Work hours',
      headline: 'Set your study hours',
      subtitle: 'Drag the slider to mark when you usually focus.',
      purpose: 'Synctra only places blocks inside this window.',
    ),
    _OnboardingStepInfo(
      shortLabel: 'Calendars',
      headline: 'Add your calendars',
      subtitle: 'Paste an iCal link so we know when you\'re busy.',
      purpose: 'Google Calendar and Canvas export links work here.',
    ),
    _OnboardingStepInfo(
      shortLabel: 'Courses',
      headline: 'Import your courses',
      subtitle: 'Add a UW course page for lectures and due dates.',
      purpose: 'Optional — skip if you want to add these later.',
    ),
    _OnboardingStepInfo(
      shortLabel: 'Review',
      headline: 'Review your setup',
      subtitle: 'Confirm everything looks right before you start.',
      purpose: 'You can change any of this in Settings.',
    ),
  ];

  @override
  State<OnboardingWizard> createState() => _OnboardingWizardState();
}

class _OnboardingStepInfo {
  final String shortLabel;
  final String headline;
  final String subtitle;
  final String purpose;

  const _OnboardingStepInfo({
    required this.shortLabel,
    required this.headline,
    required this.subtitle,
    required this.purpose,
  });
}

class _OnboardingWizardState extends State<OnboardingWizard> {
  int _step = 0;

  RangeValues _workRange = WorkHoursSlots.defaultRange();
  int _sessionMinutes = 60;
  int _breakMinutes = 10;

  final List<IcalFeed> _icalFeeds = [];
  final List<_ImportedCourse> _courses = [];

  late final UserSettingsService _settingsSvc;
  late final IcalFeedService _icalSvc;
  late final CourseImportService _courseSvc;

  String? _initError;

  TimeOfDay get _workStart =>
      WorkHoursSlots.slotToTime(_workRange.start.round());
  TimeOfDay get _workEnd => WorkHoursSlots.slotToTime(_workRange.end.round());

  @override
  void initState() {
    super.initState();
    try {
      _settingsSvc = GetIt.instance<UserSettingsService>();
      _icalSvc = IcalFeedService(settings: _settingsSvc);
      _courseSvc = CourseImportService();
      _restoreDraft();
    } catch (e, st) {
      debugPrint('onboarding initState error: $e\n$st');
      _initError = e.toString();
    }
  }

  Future<void> _restoreDraft() async {
    try {
      final draft = await _settingsSvc.loadOnboardingDraft();
      if (draft == null || !mounted) {
        await _hydrateListsFromSettings();
        return;
      }
      setState(() {
        _step = ((draft['step'] as int?) ?? 0).clamp(0, OnboardingWizard.stepCount - 1);
        _workStartFromDraft(draft);
        _sessionMinutes = draft['session_minutes'] as int? ?? 60;
        _breakMinutes = draft['break_minutes'] as int? ?? 10;
        _icalFeeds
          ..clear()
          ..addAll(_icalFeedsFromDraft(draft));
        _courses
          ..clear()
          ..addAll(_coursesFromDraft(draft));
      });
      if (_icalFeeds.isEmpty && _courses.isEmpty) {
        await _hydrateListsFromSettings();
      }
    } catch (e, st) {
      debugPrint('restoreDraft error: $e\n$st');
    }
  }

  Future<void> _hydrateListsFromSettings() async {
    if (!mounted) return;
    try {
      await _settingsSvc.ensureLoaded();
      final settings = _settingsSvc.settings;
      if (settings == null) return;

      final feeds = await _icalSvc.loadFeeds();
      if (!mounted) return;
      setState(() {
        if (_icalFeeds.isEmpty && feeds.isNotEmpty) {
          _icalFeeds.addAll(feeds);
        } else if (_icalFeeds.isEmpty) {
          for (final url in settings.icalLinks) {
            _icalFeeds.add(IcalFeed(
              id: url.hashCode.toString(),
              userId: settings.userId,
              url: url,
            ));
          }
        }
        if (_courses.isEmpty) {
          for (final url in settings.courseUrls) {
            _courses.add(_ImportedCourse(
              id: url.hashCode.toString(),
              url: url,
              name: url,
              eventCount: 0,
            ));
          }
        }
      });
    } catch (e, st) {
      debugPrint('hydrateListsFromSettings error: $e\n$st');
    }
  }

  List<IcalFeed> _icalFeedsFromDraft(Map<String, dynamic> draft) {
    final raw = draft['ical_feeds'];
    if (raw is! List) return const [];
    final uid = Supabase.instance.client.auth.currentUser?.id ?? 'preview';
    return raw.whereType<Map>().map((m) {
      final map = Map<String, dynamic>.from(m);
      return IcalFeed(
        id: map['id'] as String? ?? '${map['url']}'.hashCode.toString(),
        userId: uid,
        url: map['url'] as String,
        label: map['label'] as String?,
      );
    }).where((f) => f.url.isNotEmpty).toList();
  }

  List<_ImportedCourse> _coursesFromDraft(Map<String, dynamic> draft) {
    final raw = draft['courses'];
    if (raw is! List) return const [];
    return raw.whereType<Map>().map((m) {
      final map = Map<String, dynamic>.from(m);
      return _ImportedCourse(
        id: map['id'] as String? ?? '${map['url']}'.hashCode.toString(),
        url: map['url'] as String,
        name: map['name'] as String? ?? map['url'] as String,
        eventCount: (map['event_count'] as num?)?.toInt() ?? 0,
      );
    }).where((c) => c.url.isNotEmpty).toList();
  }

  void _workStartFromDraft(Map<String, dynamic> draft) {
    final start = _timeFromDraft(draft['work_start'] as String?);
    final end = _timeFromDraft(draft['work_end'] as String?);
    if (start != null && end != null) {
      _workRange = WorkHoursSlots.fromTimes(start, end);
    }
  }

  TimeOfDay? _timeFromDraft(String? raw) {
    if (raw == null) return null;
    final parts = raw.split(':');
    if (parts.length < 2) return null;
    return TimeOfDay(
      hour: int.tryParse(parts[0]) ?? 0,
      minute: int.tryParse(parts[1]) ?? 0,
    );
  }

  Future<void> _persistDraft() async {
    await _settingsSvc.saveOnboardingDraft({
      'step': _step,
      'work_start': WorkHoursSlots.storageFormat(_workStart),
      'work_end': WorkHoursSlots.storageFormat(_workEnd),
      'session_minutes': _sessionMinutes,
      'break_minutes': _breakMinutes,
      'ical_feeds': _icalFeeds
          .map((f) => {'id': f.id, 'url': f.url, 'label': f.label})
          .toList(),
      'courses': _courses
          .map((c) => {
                'id': c.id,
                'url': c.url,
                'name': c.name,
                'event_count': c.eventCount,
              })
          .toList(),
    });
  }

  Future<void> _onIcalAdded(IcalFeed feed) async {
    setState(() => _icalFeeds.add(feed));
    await _persistDraft();
  }

  Future<void> _onIcalRemoved(IcalFeed feed) async {
    await _icalSvc.removeFeed(feed);
    setState(() => _icalFeeds.remove(feed));
    await _persistDraft();
  }

  Future<void> _onCourseImported(_ImportedCourse course) async {
    setState(() => _courses.add(course));
    await _persistDraft();
  }

  Future<void> _onCourseRemoved(_ImportedCourse course) async {
    try {
      await _courseSvc.removeImport(course.id);
    } catch (e, st) {
      debugPrint('removeImport error: $e\n$st');
    }
    await _settingsSvc.removeCourseUrl(course.url);
    setState(() => _courses.remove(course));
    await _persistDraft();
  }

  UserSettings _buildDraftSettings() {
    final uid = Supabase.instance.client.auth.currentUser?.id ?? 'preview';
    return UserSettings(
      userId: uid,
      workStartTime: _workStart,
      workEndTime: _workEnd,
      preferredSessionMinutes: _sessionMinutes,
      breakMinutes: _breakMinutes,
      icalLinks: _icalFeeds.map((f) => f.url).toList(),
      courseUrls: _courses.map((c) => c.url).toList(),
    );
  }

  void _next() {
    if (_step < OnboardingWizard.stepCount - 1) {
      setState(() => _step++);
      _persistDraft();
    }
  }

  void _back() {
    if (_step > 0) setState(() => _step--);
  }

  Future<void> _finish() async {
    await _settingsSvc.completeOnboarding(_buildDraftSettings());
    if (!mounted) return;
    context.go('/calendar');
  }

  @override
  Widget build(BuildContext context) {
    if (_initError != null) {
      return SynctraPageScaffold(
        title: 'Set up Synctra',
        body: Center(
          child: Padding(
            padding: const EdgeInsets.all(24),
            child: Text(
              'Init error: $_initError',
              style: const TextStyle(color: Colors.red),
            ),
          ),
        ),
      );
    }

    final scheme = Theme.of(context).colorScheme;
    final lastStep = _step == OnboardingWizard.stepCount - 1;
    final stepInfo = OnboardingWizard._steps[_step];

    return SynctraPageScaffold(
      title: 'Set up Synctra',
      leading: _step > 0
          ? IconButton(
              icon: const Icon(Icons.arrow_back, size: AppTokens.iconStandard),
              color: AppColors.textSecondary,
              onPressed: _back,
            )
          : null,
      body: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          SynctraStepProgress(
            step: _step,
            totalSteps: OnboardingWizard.stepCount,
            label: 'Step ${_step + 1} of ${OnboardingWizard.stepCount} · ${stepInfo.shortLabel}',
          ),
          Expanded(
            child: Builder(
              builder: (ctx) {
                try {
                  return _buildStepContent(ctx);
                } catch (e, st) {
                  return Center(
                    child: SingleChildScrollView(
                      padding: const EdgeInsets.all(24),
                      child: Text(
                        'Step error: $e\n$st',
                        style: const TextStyle(color: Colors.red),
                      ),
                    ),
                  );
                }
              },
            ),
          ),
        ],
      ),
      bottomBar: Padding(
        padding: const EdgeInsets.fromLTRB(
          AppTokens.space24,
          AppTokens.space12,
          AppTokens.space24,
          AppTokens.space16,
        ),
        child: lastStep
            ? Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  Icon(Icons.celebration_outlined, color: scheme.primary, size: 32),
                  const SizedBox(height: AppTokens.space12),
                  SynctraPrimaryButton(
                    expand: true,
                    onPressed: _finish,
                    icon: Icons.check,
                    label: 'Get started',
                  ),
                ],
              )
            : Row(
                children: [
                  if (_step == 2 || _step == 3)
                    SynctraGhostButton(
                      onPressed: _next,
                      label: 'Skip for now',
                    ),
                  const Spacer(),
                  SynctraPrimaryButton(
                    onPressed: _next,
                    label: 'Continue',
                  ),
                ],
              ),
      ),
    );
  }

  Widget _buildStepContent(BuildContext context) {
    final stepInfo = OnboardingWizard._steps[_step];
    switch (_step) {
      case 0:
        return _WelcomeStep(stepInfo: stepInfo);
      case 1:
        return SingleChildScrollView(
          child: SynctraPageContent(
            child: SettingsInsetCard(
              child: Builder(
                builder: (ctx) {
                  try {
                    return WorkHoursRangeSlider(
                      range: _workRange,
                      headline: stepInfo.headline,
                      subtitle: stepInfo.subtitle,
                      purposeLine: stepInfo.purpose,
                      showSessionSliders: true,
                      sessionMinutes: _sessionMinutes,
                      breakMinutes: _breakMinutes,
                      onChanged: (next) {
                        setState(() => _workRange = next);
                        _persistDraft();
                      },
                      onSessionChanged: (v) {
                        setState(() => _sessionMinutes = v);
                        _persistDraft();
                      },
                      onBreakChanged: (v) {
                        setState(() => _breakMinutes = v);
                        _persistDraft();
                      },
                    );
                  } catch (e, st) {
                    return Text(
                      'Slider error: $e\n$st',
                      style: const TextStyle(color: Colors.red),
                    );
                  }
                },
              ),
            ),
          ),
        );
      case 2:
        return _IcalLinksStep(
          stepInfo: stepInfo,
          feeds: _icalFeeds,
          icalService: _icalSvc,
          onAdded: _onIcalAdded,
          onRemoved: _onIcalRemoved,
        );
      case 3:
        return _CourseWebsitesStep(
          stepInfo: stepInfo,
          courses: _courses,
          courseService: _courseSvc,
          settingsService: _settingsSvc,
          onImported: _onCourseImported,
          onRemoved: _onCourseRemoved,
        );
      default:
        return _ReviewStep(
          stepInfo: stepInfo,
          workStart: _workStart,
          workEnd: _workEnd,
          sessionMinutes: _sessionMinutes,
          feedCount: _icalFeeds.length,
          courseCount: _courses.length,
          eventTotal: _courses.fold<int>(0, (s, c) => s + c.eventCount),
          onEditStep: (i) => setState(() => _step = i),
        );
    }
  }
}

class _OnboardingStepHeader extends StatelessWidget {
  final _OnboardingStepInfo info;

  const _OnboardingStepHeader({required this.info});

  @override
  Widget build(BuildContext context) {
    final brightness = Theme.of(context).brightness;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          info.headline,
          style: CalendarTextStyles.topBarDate(brightness).copyWith(
            fontSize: 20,
            fontWeight: FontWeight.w600,
          ),
        ),
        const SizedBox(height: AppTokens.space8),
        Text(
          info.subtitle,
          style: CalendarTextStyles.upcomingRow(brightness).copyWith(height: 1.5),
        ),
        const SizedBox(height: AppTokens.space8),
        Text(
          info.purpose,
          style: CalendarTextStyles.hourLabel(brightness).copyWith(
            fontSize: 12,
            height: 1.45,
          ),
        ),
      ],
    );
  }
}

class _WelcomeStep extends StatelessWidget {
  final _OnboardingStepInfo stepInfo;

  const _WelcomeStep({required this.stepInfo});

  static const _features = [
    (
      Icons.calendar_month_outlined,
      'One calendar for everything',
      'Classes, assignments, and personal events in a single week view.',
    ),
    (
      Icons.checklist_outlined,
      'Tasks from Canvas and course pages',
      'Pull due dates from Canvas and UW course schedules automatically.',
    ),
    (
      Icons.auto_awesome_outlined,
      'AI-suggested focus blocks',
      'Synctra finds open time in your study window and suggests study sessions.',
    ),
  ];

  @override
  Widget build(BuildContext context) {
    final brightness = Theme.of(context).brightness;
    return ListView(
      children: [
        SynctraPageContent(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              _OnboardingStepHeader(info: stepInfo),
              const SizedBox(height: AppTokens.space24),
              for (final feature in _features)
                Padding(
                  padding: const EdgeInsets.only(bottom: AppTokens.space12),
                  child: SettingsInsetCard(
                    child: Row(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Icon(
                          feature.$1,
                          size: AppTokens.iconStandard,
                          color: AppColors.primary,
                        ),
                        const SizedBox(width: AppTokens.space16),
                        Expanded(
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Text(
                                feature.$2,
                                style: CalendarTextStyles.upcomingRow(brightness).copyWith(
                                  fontWeight: FontWeight.w600,
                                ),
                              ),
                              const SizedBox(height: AppTokens.space4),
                              Text(
                                feature.$3,
                                style: CalendarTextStyles.hourLabel(brightness).copyWith(
                                  fontSize: 12,
                                  height: 1.45,
                                ),
                              ),
                            ],
                          ),
                        ),
                      ],
                    ),
                  ),
                ),
            ],
          ),
        ),
      ],
    );
  }
}

class _OnboardingEmptyCard extends StatelessWidget {
  final IconData icon;
  final String message;
  final String? detail;

  const _OnboardingEmptyCard({
    required this.icon,
    required this.message,
    this.detail,
  });

  @override
  Widget build(BuildContext context) {
    final brightness = Theme.of(context).brightness;
    return SettingsInsetCard(
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Icon(icon, color: AppColors.primary, size: AppTokens.iconStandard + 4),
          const SizedBox(width: AppTokens.space16),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  message,
                  style: CalendarTextStyles.upcomingRow(brightness).copyWith(
                    height: 1.5,
                  ),
                ),
                if (detail != null) ...[
                  const SizedBox(height: AppTokens.space8),
                  Text(
                    detail!,
                    style: CalendarTextStyles.hourLabel(brightness).copyWith(
                      fontSize: 12,
                      height: 1.45,
                    ),
                  ),
                ],
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class _ImportedCourse {
  final String id;
  final String url;
  final String name;
  final int eventCount;

  const _ImportedCourse({
    required this.id,
    required this.url,
    required this.name,
    required this.eventCount,
  });
}

class _IcalLinksStep extends StatefulWidget {
  final _OnboardingStepInfo stepInfo;
  final List<IcalFeed> feeds;
  final IcalFeedService icalService;
  final Future<void> Function(IcalFeed feed) onAdded;
  final Future<void> Function(IcalFeed feed) onRemoved;

  const _IcalLinksStep({
    required this.stepInfo,
    required this.feeds,
    required this.icalService,
    required this.onAdded,
    required this.onRemoved,
  });

  @override
  State<_IcalLinksStep> createState() => _IcalLinksStepState();
}

class _IcalLinksStepState extends State<_IcalLinksStep> {
  final _ctrl = TextEditingController();
  String? _status;
  bool _isError = false;
  bool _loading = false;

  Future<void> _add() async {
    final url = _ctrl.text.trim();
    if (url.isEmpty) {
      setState(() {
        _isError = true;
        _status = 'Enter a calendar feed URL';
      });
      return;
    }
    setState(() {
      _loading = true;
      _isError = false;
      _status = null;
    });
    try {
      final feed = await widget.icalService.addFeed(url);
      if (feed == null) {
        throw StateError(
          PreviewFlags.noAuth
              ? 'Could not save feed locally'
              : 'Sign in required to save calendar feeds',
        );
      }
      await widget.onAdded(feed);
      _ctrl.clear();
      setState(() => _status = 'Feed connected');
    } catch (e) {
      setState(() {
        _isError = true;
        _status = e.toString();
      });
    } finally {
      setState(() => _loading = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final isEmpty = widget.feeds.isEmpty;
    final brightness = Theme.of(context).brightness;
    return ListView(
      children: [
        SynctraPageContent(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              _OnboardingStepHeader(info: widget.stepInfo),
              const SizedBox(height: AppTokens.space20),
              if (isEmpty) ...[
                const _OnboardingEmptyCard(
                  icon: Icons.calendar_month_outlined,
                  message: 'No calendars connected yet — paste a link below to get started.',
                  detail: 'Tip: In Google Calendar, go to Settings → your calendar → '
                      'Integrate calendar → copy the secret iCal address.',
                ),
                const SizedBox(height: AppTokens.space16),
              ],
              SettingsInsetCard(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    IcalFeedEditor(
                      controller: _ctrl,
                      loading: _loading,
                      statusMessage: _status,
                      isError: _isError,
                      onAdd: _add,
                      hintText: 'https://calendar.google.com/calendar/ical/…',
                      helperText: isEmpty
                          ? 'Canvas calendar export and Google Calendar iCal links work here.'
                          : 'Add another feed — you can connect as many as you need.',
                    ),
                    ...widget.feeds.map(
                      (f) => Padding(
                        padding: const EdgeInsets.only(top: AppTokens.space8),
                        child: IcalFeedListTile(
                          feed: f,
                          onDelete: () => widget.onRemoved(f),
                        ),
                      ),
                    ),
                  ],
                ),
              ),
              const SizedBox(height: AppTokens.space12),
              Text(
                'Optional — skip and add calendars later in Settings.',
                style: CalendarTextStyles.hourLabel(brightness).copyWith(
                  fontSize: 12,
                  height: 1.45,
                ),
              ),
            ],
          ),
        ),
      ],
    );
  }
}

class _CourseWebsitesStep extends StatefulWidget {
  final _OnboardingStepInfo stepInfo;
  final List<_ImportedCourse> courses;
  final CourseImportService courseService;
  final UserSettingsService settingsService;
  final Future<void> Function(_ImportedCourse course) onImported;
  final Future<void> Function(_ImportedCourse course) onRemoved;

  const _CourseWebsitesStep({
    required this.stepInfo,
    required this.courses,
    required this.courseService,
    required this.settingsService,
    required this.onImported,
    required this.onRemoved,
  });

  @override
  State<_CourseWebsitesStep> createState() => _CourseWebsitesStepState();
}

class _CourseWebsitesStepState extends State<_CourseWebsitesStep> {
  final _ctrl = TextEditingController();
  bool _loading = false;
  String? _errorText;
  String? _status;

  Future<void> _import() async {
    final url = _ctrl.text.trim();
    if (url.isEmpty) {
      setState(() => _errorText = 'Enter a course page URL');
      return;
    }
    if (widget.courses.any((c) => c.url == url)) {
      setState(() {
        _errorText = 'This course is already imported';
        _status = null;
      });
      return;
    }
    setState(() {
      _loading = true;
      _errorText = null;
      _status = 'Importing…';
    });
    try {
      final record = await widget.courseService.addImport(url, '');
      await widget.settingsService.appendCourseUrl(url);
      await widget.onImported(_ImportedCourse(
        id: record.id,
        url: url,
        name: record.courseName,
        eventCount: record.eventCount,
      ));
      _ctrl.clear();
      setState(() {
        _status = null;
        _errorText = null;
      });
    } catch (e, st) {
      debugPrint('course import error: $e\n$st');
      setState(() {
        _errorText = "Couldn't parse this page — check the URL or try again in Settings";
        _status = null;
      });
    } finally {
      setState(() => _loading = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final brightness = Theme.of(context).brightness;
    final isEmpty = widget.courses.isEmpty;
    return ListView(
      children: [
        SynctraPageContent(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              _OnboardingStepHeader(info: widget.stepInfo),
              const SizedBox(height: AppTokens.space20),
              if (isEmpty) ...[
                const _OnboardingEmptyCard(
                  icon: Icons.school_outlined,
                  message: 'No courses yet — that\'s okay, you can add them later.',
                  detail: 'Paste a public UW course page URL below, or skip and import '
                      'from Settings whenever you\'re ready.',
                ),
                const SizedBox(height: AppTokens.space16),
              ],
              SettingsInsetCard(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    Row(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Expanded(
                          child: TextField(
                            controller: _ctrl,
                            decoration: InputDecoration(
                              hintText: 'https://courses.cs.washington.edu/courses/cse331/…',
                              helperText: _errorText == null && _status == null
                                  ? (isEmpty
                                      ? 'We pull lecture times and due dates from the page.'
                                      : 'Add another course URL')
                                  : null,
                              errorText: _errorText,
                            ),
                          ),
                        ),
                        const SizedBox(width: AppTokens.space8),
                        Padding(
                          padding: const EdgeInsets.only(top: AppTokens.space4),
                          child: _loading
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
                                  onPressed: _import,
                                  label: 'Import',
                                ),
                        ),
                      ],
                    ),
                    if (_status != null)
                      Padding(
                        padding: const EdgeInsets.only(top: AppTokens.space8),
                        child: Text(
                          _status!,
                          style: TextStyle(color: scheme.primary, fontSize: 14),
                        ),
                      ),
                    ...widget.courses.map(
                      (c) => Padding(
                        padding: const EdgeInsets.only(top: AppTokens.space8),
                        child: CourseImportListTile(
                          name: c.name,
                          url: c.url,
                          totalImported: c.eventCount,
                          onDelete: () => widget.onRemoved(c),
                        ),
                      ),
                    ),
                  ],
                ),
              ),
              const SizedBox(height: AppTokens.space12),
              Text(
                'Optional — skip and add courses later in Settings.',
                style: CalendarTextStyles.hourLabel(brightness).copyWith(
                  fontSize: 12,
                  height: 1.45,
                ),
              ),
            ],
          ),
        ),
      ],
    );
  }
}

class _ReviewStep extends StatelessWidget {
  final _OnboardingStepInfo stepInfo;
  final TimeOfDay workStart;
  final TimeOfDay workEnd;
  final int sessionMinutes;
  final int feedCount;
  final int courseCount;
  final int eventTotal;
  final ValueChanged<int> onEditStep;

  const _ReviewStep({
    required this.stepInfo,
    required this.workStart,
    required this.workEnd,
    required this.sessionMinutes,
    required this.feedCount,
    required this.courseCount,
    required this.eventTotal,
    required this.onEditStep,
  });

  bool get _skippedOptionalSteps => feedCount == 0 && courseCount == 0;

  String _fmt(TimeOfDay t) {
    final dt = DateTime(2026, 1, 1, t.hour, t.minute);
    return DateFormat.jm().format(dt);
  }

  @override
  Widget build(BuildContext context) {
    return ListView(
      children: [
        SynctraPageContent(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              _OnboardingStepHeader(info: stepInfo),
              if (_skippedOptionalSteps) ...[
                const SizedBox(height: AppTokens.space20),
                const _OnboardingEmptyCard(
                  icon: Icons.check_circle_outline,
                  message: 'You\'re all set to get started — add calendars and courses '
                      'anytime in Settings.',
                  detail: 'Synctra will use your study window to suggest focus blocks. '
                      'Connect more sources when you\'re ready for smarter scheduling.',
                ),
              ],
              const SizedBox(height: AppTokens.space20),
              _ReviewRow(
                label: 'Study window',
                value: '${_fmt(workStart)} – ${_fmt(workEnd)} · $sessionMinutes min blocks',
                onEdit: () => onEditStep(1),
              ),
              _ReviewRow(
                label: 'Calendars',
                value: feedCount == 0
                    ? 'None added — you can connect feeds in Settings'
                    : '$feedCount feed${feedCount == 1 ? '' : 's'} connected',
                onEdit: () => onEditStep(2),
              ),
              _ReviewRow(
                label: 'Courses',
                value: courseCount == 0
                    ? 'None added — import course pages in Settings'
                    : '$courseCount course${courseCount == 1 ? '' : 's'} · $eventTotal events',
                onEdit: () => onEditStep(3),
              ),
            ],
          ),
        ),
      ],
    );
  }
}

class _ReviewRow extends StatelessWidget {
  final String label;
  final String value;
  final VoidCallback onEdit;

  const _ReviewRow({
    required this.label,
    required this.value,
    required this.onEdit,
  });

  @override
  Widget build(BuildContext context) {
    final brightness = Theme.of(context).brightness;
    return Padding(
      padding: const EdgeInsets.only(bottom: AppTokens.space8),
      child: SettingsInsetCard(
        padding: EdgeInsets.zero,
        child: ListTile(
          minVerticalPadding: 12,
          title: Text(
            label,
            style: CalendarTextStyles.upcomingRow(brightness).copyWith(
              fontWeight: FontWeight.w600,
            ),
          ),
          subtitle: Text(
            value,
            style: CalendarTextStyles.hourLabel(brightness).copyWith(height: 1.45),
          ),
          trailing: SynctraGhostButton(onPressed: onEdit, label: 'Edit'),
        ),
      ),
    );
  }
}

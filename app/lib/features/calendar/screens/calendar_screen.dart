// Main calendar — Google Calendar–inspired week/day/month views, mini sidebar,
// Canvas assignment chips (all-day row), and timed events + study blocks in the grid.
// Data: same bindings as before (_fixedEvents, _feedEvents, _suggestedBlocks, iCal sync).
import 'dart:async';
import 'dart:convert';
import 'dart:math' as math;

import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:get_it/get_it.dart';
import 'package:go_router/go_router.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:table_calendar/table_calendar.dart';
import 'package:intl/intl.dart';
import 'package:uuid/uuid.dart';

import '../../../core/constants/api_constants.dart';
import '../../../core/theme/app_theme.dart';
import '../../../data/models/event_model.dart';
import '../../../data/models/schedule_block_model.dart';
import '../../../shared/services/canvas_tasks_service.dart';
import '../../../shared/services/llm_service.dart';
import '../../../shared/services/schedule_chat_coordinator.dart';
import '../../../shared/services/scheduling_service.dart';
import '../../../shared/services/suggested_schedule_store.dart';
import '../../../shared/state/calendar_shell_bridge.dart';
import '../../../shared/widgets/synctra_chat_panel.dart';
import '../../../shared/widgets/sync_it_chrome.dart';

enum _CalendarViewMode { day, week, month }

class CalendarScreen extends StatefulWidget {
  const CalendarScreen({super.key});

  @override
  State<CalendarScreen> createState() => _CalendarScreenState();
}

class _CalendarScreenState extends State<CalendarScreen> {
  DateTime _focusedDay = DateTime.now();
  DateTime _selectedDay = DateTime.now();
  CalendarFormat _monthFormat = CalendarFormat.month;
  _CalendarViewMode _viewMode = _CalendarViewMode.week;
  bool _calendarChatOpen = false;

  final List<EventModel> _fixedEvents = [];
  final List<EventModel> _canvasEvents = [];
  late final SuggestedScheduleStore _scheduleStore;
  late final CanvasTasksService _canvasTasks;
  static const _manualEventsKey = 'synctra_manual_events_v1';

  final Map<String, List<EventModel>> _feedEvents = {};
  final List<Map<String, String>> _icalFeeds = [];

  final ScrollController _timeScrollController = ScrollController();
  Timer? _nowTicker;

  static const int _firstHour = 6;
  static const int _lastHour = 23;
  static const double _hourHeight = 52;

  @override
  void initState() {
    super.initState();
    _scheduleStore = GetIt.instance<SuggestedScheduleStore>();
    _canvasTasks = GetIt.instance<CanvasTasksService>();
    _canvasTasks.addListener(_reloadCanvasEvents);
    _scheduleStore.addListener(_onScheduleStoreChanged);
    _loadSavedFeeds();
    _loadManualEvents();
    _reloadCanvasEvents();
    _nowTicker = Timer.periodic(const Duration(minutes: 1), (_) {
      if (mounted) setState(() {});
    });
    WidgetsBinding.instance.addPostFrameCallback((_) => _publishPlannerToShell());
  }

  void _publishPlannerToShell() {
    if (!mounted) return;
    CalendarShellBridge.instance.setPlannerBuilder(_buildPlannerPanel);
  }

  void _onScheduleStoreChanged() {
    if (mounted) {
      setState(() {});
      CalendarShellBridge.instance.refreshPlanner();
    }
  }

  void _pushExternalBusyToStore() {
    _scheduleStore.setExternalBusy(_allEvents());
  }

  @override
  void dispose() {
    CalendarShellBridge.instance.clearPlanner();
    _canvasTasks.removeListener(_reloadCanvasEvents);
    _scheduleStore.removeListener(_onScheduleStoreChanged);
    _nowTicker?.cancel();
    _timeScrollController.dispose();
    super.dispose();
  }

  Widget _buildPlannerPanel() {
    return _CalendarPlannerPanel(
      focusedDay: _focusedDay,
      selectedDay: _selectedDay,
      eventsForDay: _eventsForDay,
      onDaySelected: _onDaySelected,
      onPageChanged: (d) => setState(() => _focusedDay = d),
      onOpenIcal: _openIcalFeedsSheet,
    );
  }

  Iterable<EventModel> _allEvents() sync* {
    for (final e in _fixedEvents) {
      yield e;
    }
    for (final e in _canvasEvents) {
      yield e;
    }
    for (final list in _feedEvents.values) {
      for (final e in list) {
        yield e;
      }
    }
  }

  Future<void> _reloadCanvasEvents() async {
    final tasks = await _canvasTasks.loadCached();
    if (!mounted) return;
    setState(() {
      _canvasEvents
        ..clear()
        ..addAll(_canvasTasks.toCalendarEvents(tasks));
    });
    _pushExternalBusyToStore();
  }

  Future<void> _loadManualEvents() async {
    final prefs = await SharedPreferences.getInstance();
    final raw = prefs.getString(_manualEventsKey);
    if (raw == null || raw.isEmpty) return;
    try {
      final list = jsonDecode(raw) as List<dynamic>;
      final loaded = list
          .whereType<Map>()
          .map((m) => EventModel.fromJson(Map<String, dynamic>.from(m)))
          .where((e) => e.source == 'manual')
          .toList();
      if (!mounted) return;
      setState(() {
        _fixedEvents.removeWhere((e) => e.source == 'manual');
        _fixedEvents.addAll(loaded);
      });
      _pushExternalBusyToStore();
    } catch (_) {}
  }

  Future<void> _persistManualEvents() async {
    final manual = _fixedEvents.where((e) => e.source == 'manual').map((e) {
      return {
        'id': e.id,
        'title': e.title,
        'start_time': e.startTime.toIso8601String(),
        'end_time': e.endTime.toIso8601String(),
        'source': e.source,
        'is_fixed': e.isFixed,
        'description': e.description,
      };
    }).toList();
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(_manualEventsKey, jsonEncode(manual));
  }

  Future<void> _loadSavedFeeds() async {
    final prefs = await SharedPreferences.getInstance();
    final raw = prefs.getStringList('ical_feeds') ?? [];
    for (final item in raw) {
      final feed = jsonDecode(item) as Map<String, dynamic>;
      final id = feed['id'] as String;
      final name = feed['name'] as String;
      final url = feed['url'] as String;
      _icalFeeds.add({'id': id, 'name': name, 'url': url});
      _syncFeed(id, name, url).catchError((_) {});
    }
    if (mounted) _pushExternalBusyToStore();
  }

  Future<void> _syncFeed(String feedId, String name, String url) async {
    final resp = await Dio().post(
      '${ApiConstants.baseUrl}/events/ical-feeds/preview',
      data: {'url': url, 'name': name},
    );
    final events = (resp.data['events'] as List)
        .map((e) => EventModel.fromJson(e as Map<String, dynamic>))
        .toList();
    if (mounted) {
      setState(() => _feedEvents[feedId] = events);
      _pushExternalBusyToStore();
    }
  }

  Future<void> _addFeed(String url, String name) async {
    final id = const Uuid().v4();
    final prefs = await SharedPreferences.getInstance();
    _icalFeeds.add({'id': id, 'name': name, 'url': url});
    await prefs.setStringList(
        'ical_feeds', _icalFeeds.map((f) => jsonEncode(f)).toList());
    await _syncFeed(id, name, url);
    if (mounted) _pushExternalBusyToStore();
  }

  Future<void> _removeFeed(String feedId) async {
    final prefs = await SharedPreferences.getInstance();
    _icalFeeds.removeWhere((f) => f['id'] == feedId);
    await prefs.setStringList(
        'ical_feeds', _icalFeeds.map((f) => jsonEncode(f)).toList());
    setState(() => _feedEvents.remove(feedId));
    _pushExternalBusyToStore();
  }

  List<EventModel> _canvasOnDay(DateTime day) =>
      _allEvents().where((e) => e.source == 'canvas' && isSameDay(e.startTime, day)).toList();

  /// Canvas items that also occupy the time grid (vs due-date-only chips in the all-day row).
  static bool _canvasShowsInTimeGrid(EventModel e) {
    if (e.source != 'canvas') return false;
    final durMin = e.endTime.difference(e.startTime).inMinutes;
    if (durMin >= 30) return true;
    final h = e.startTime.hour;
    if (h >= 6 && h <= 21) return true;
    return false;
  }

  List<EventModel> _timedEventsOnDay(DateTime day) => _allEvents()
      .where((e) => isSameDay(e.startTime, day))
      .where((e) => e.source != 'canvas' || _canvasShowsInTimeGrid(e))
      .toList();

  List<ScheduleBlockModel> _blocksOnDay(DateTime day) =>
      _scheduleStore.blocks.where((b) => isSameDay(b.startTime, day)).toList();

  /// Sidebar / month markers — timed grid Canvas is included only via [_timedEventsOnDay].
  List<dynamic> _eventsForDay(DateTime day) {
    final timed = _timedEventsOnDay(day);
    final canvasChipsOnly =
        _canvasOnDay(day).where((c) => !_canvasShowsInTimeGrid(c)).toList();
    final blocks = _blocksOnDay(day);
    return [...timed, ...canvasChipsOnly, ...blocks];
  }

  DateTime _startOfWeek(DateTime d) {
    final day = DateTime(d.year, d.month, d.day);
    return day.subtract(Duration(days: day.weekday - DateTime.monday));
  }

  List<DateTime> _visibleDays() {
    if (_viewMode == _CalendarViewMode.day) {
      return [DateTime(_focusedDay.year, _focusedDay.month, _focusedDay.day)];
    }
    final start = _startOfWeek(_focusedDay);
    return List.generate(7, (i) => start.add(Duration(days: i)));
  }

  void _goToday() {
    final n = DateTime.now();
    setState(() {
      _focusedDay = n;
      _selectedDay = n;
    });
  }

  void _shiftPeriod(int delta) {
    setState(() {
      switch (_viewMode) {
        case _CalendarViewMode.day:
          _focusedDay = _focusedDay.add(Duration(days: delta));
          _selectedDay = _focusedDay;
        case _CalendarViewMode.week:
          _focusedDay = _focusedDay.add(Duration(days: 7 * delta));
        case _CalendarViewMode.month:
          _focusedDay = DateTime(_focusedDay.year, _focusedDay.month + delta, 1);
      }
    });
  }

  String _toolbarTitle() {
    switch (_viewMode) {
      case _CalendarViewMode.day:
        return DateFormat('EEEE, MMMM d, y').format(_focusedDay);
      case _CalendarViewMode.week:
        final days = _visibleDays();
        final a = days.first;
        final b = days.last;
        if (a.month == b.month && a.year == b.year) {
          return '${DateFormat('MMM d').format(a)} – ${DateFormat('d, y').format(b)}';
        }
        if (a.year == b.year) {
          return '${DateFormat('MMM d').format(a)} – ${DateFormat('MMM d, y').format(b)}';
        }
        return '${DateFormat('MMM d, y').format(a)} – ${DateFormat('MMM d, y').format(b)}';
      case _CalendarViewMode.month:
        return DateFormat('MMMM y').format(_focusedDay);
    }
  }

  void _onDaySelected(DateTime selected, DateTime focused) {
    setState(() {
      _selectedDay = selected;
      _focusedDay = focused;
    });
  }

  void _openIcalFeedsSheet() {
    showModalBottomSheet(
      context: context,
      isScrollControlled: true,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(16)),
      ),
      builder: (_) => _IcalFeedsSheet(
        feeds: List.from(_icalFeeds),
        feedEventCounts: {for (final e in _feedEvents.entries) e.key: e.value.length},
        onAdd: (url, name) async {
          await _addFeed(url, name);
        },
        onRemove: (id) async {
          await _removeFeed(id);
        },
        onSync: (id, name, url) async {
          await _syncFeed(id, name, url);
        },
      ),
    );
  }

  void _openAssignmentSheet(EventModel assignment) {
    showModalBottomSheet(
      context: context,
      isScrollControlled: true,
      showDragHandle: true,
      builder: (sheetCtx) => _AssignmentDetailSheet(
        event: assignment,
        onScheduleStudy: () {
          Navigator.pop(sheetCtx);
          final mins = assignment.endTime.difference(assignment.startTime).inMinutes;
          final hours = (mins / 60.0).clamp(0.5, 4.0);
          final msg = GetIt.instance<ScheduleChatCoordinator>().scheduleStudyForDueItem(
            taskId: 'cv-${assignment.id}',
            title: assignment.title,
            dueDate: assignment.startTime,
            hours: hours < 0.5 ? 1.5 : hours,
          );
          if (mounted) {
            ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(msg)));
          }
        },
      ),
    );
  }

  void _openBlockSheet(ScheduleBlockModel block) {
    showModalBottomSheet(
      context: context,
      isScrollControlled: true,
      showDragHandle: true,
      builder: (sheetCtx) => _BlockDetailSheet(
        block: block,
        parentContext: context,
      ),
    );
  }

  void _onGridEventTimeChanged(EventModel e, DateTime start, DateTime end) {
    if (e.source == 'synctra_preview') return;
    if (e.source == 'manual') {
      final i = _fixedEvents.indexWhere((x) => x.id == e.id);
      if (i >= 0) {
        setState(() => _fixedEvents[i] = e.copyWith(startTime: start, endTime: end));
        _persistManualEvents();
      }
    } else {
      for (final key in _feedEvents.keys.toList()) {
        final list = _feedEvents[key];
        if (list == null) continue;
        final j = list.indexWhere((x) => x.id == e.id);
        if (j >= 0) {
          setState(() => list[j] = e.copyWith(startTime: start, endTime: end));
          break;
        }
      }
    }
    _pushExternalBusyToStore();
  }

  void _onGridBlockTimeChanged(ScheduleBlockModel b, DateTime start, DateTime end) {
    GetIt.instance<SuggestedScheduleStore>().updateBlockTimes(id: b.id, start: start, end: end);
  }

  void _runSuggestSchedule() {
    _pushExternalBusyToStore();
    final store = _scheduleStore;
    final llm = GetIt.instance<LlmService>();
    final now = DateTime.now();
    final weekStart = DateTime(now.year, now.month, now.day)
        .subtract(Duration(days: now.weekday - DateTime.monday));
    final weekEnd = weekStart.add(const Duration(days: 7));
    final fixed = store.fixedEventsForScheduling();

    final flex = <FlexibleTask>[];
    final seen = <String>{};
    for (var i = 0; i < 7; i++) {
      final day = weekStart.add(Duration(days: i));
      for (final e in _canvasOnDay(day)) {
        if (!seen.add(e.id)) continue;
        final minutes = e.endTime.difference(e.startTime).inMinutes;
        final hours = (minutes / 60.0).clamp(0.5, 3.0);
        final enriched = llm.enrichTaskStub(
          taskId: 'cv-${e.id}',
          title: e.title,
          hours: hours < 1 ? 1.0 : hours,
          priority: 'medium',
          urgency: false,
        );
        if (SchedulingService.validateEnrichedTask(enriched) != null) continue;
        flex.add(
          SchedulingService.flexibleFromLlm(
            enriched,
            title: e.title,
            dueDate: e.startTime,
            preferMorning: false,
          ),
        );
      }
    }
    if (flex.isEmpty) {
      final enriched = llm.enrichTaskStub(
        taskId: 'fallback-weekly',
        title: 'Focused study',
        hours: 2,
        priority: 'medium',
        urgency: false,
      );
      flex.add(
        SchedulingService.flexibleFromLlm(
          enriched,
          title: 'Focused study',
          dueDate: weekEnd.subtract(const Duration(seconds: 1)),
          preferMorning: true,
        ),
      );
    }

    const scheduling = SchedulingService();
    final blocks = scheduling.scheduleWeek(
      weekStart: weekStart,
      weekEnd: weekEnd,
      fixedEvents: fixed,
      flexibleTasks: flex,
      config: const SchedulingConfig(
        bufferAroundFixedEvents: Duration(minutes: 15),
        minimumBlockSize: Duration(minutes: 30),
      ),
    );

    final titles = <String, String>{for (final f in flex) f.id: f.title};
    for (final s in blocks) {
      titles.putIfAbsent(s.taskId, () => s.taskId);
    }
    store.applySynctraPreview(scheduled: blocks, taskTitles: titles, fixed: fixed);

    if (mounted) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(
            blocks.isEmpty
                ? 'No openings found this week — add feeds or shorten study chunks.'
                : 'Placed ${blocks.length} study block(s) around your busy times.',
          ),
        ),
      );
    }
  }

  Future<void> _openQuickAddSheet() async {
    final titleCtrl = TextEditingController();
    final descCtrl = TextEditingController();
    DateTime day = DateTime(_focusedDay.year, _focusedDay.month, _focusedDay.day);
    var startT = const TimeOfDay(hour: 14, minute: 0);
    var endT = const TimeOfDay(hour: 15, minute: 0);
    final clock = DateTime.now();

    final ok = await showModalBottomSheet<bool>(
      context: context,
      isScrollControlled: true,
      showDragHandle: true,
      builder: (ctx) {
        return Padding(
          padding: EdgeInsets.only(
            left: 20,
            right: 20,
            top: 8,
            bottom: MediaQuery.viewInsetsOf(ctx).bottom + 20,
          ),
          child: StatefulBuilder(
            builder: (ctx, setModal) {
              Future<void> pickDay() async {
                final d = await showDatePicker(
                  context: ctx,
                  initialDate: day,
                  firstDate: DateTime(clock.year - 1),
                  lastDate: DateTime(clock.year + 2),
                );
                if (d != null) setModal(() => day = d);
              }

              Future<void> pickStart() async {
                final t = await showTimePicker(context: ctx, initialTime: startT);
                if (t != null) setModal(() => startT = t);
              }

              Future<void> pickEnd() async {
                final t = await showTimePicker(context: ctx, initialTime: endT);
                if (t != null) setModal(() => endT = t);
              }

              return Column(
                mainAxisSize: MainAxisSize.min,
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  Text('Quick event', style: Theme.of(ctx).textTheme.titleLarge),
                  const SizedBox(height: 12),
                  TextField(
                    controller: titleCtrl,
                    decoration: const InputDecoration(
                      labelText: 'Title',
                      border: OutlineInputBorder(),
                    ),
                    textCapitalization: TextCapitalization.sentences,
                  ),
                  const SizedBox(height: 10),
                  TextField(
                    controller: descCtrl,
                    decoration: const InputDecoration(
                      labelText: 'Description (optional)',
                      hintText: 'Notes, location, links…',
                      alignLabelWithHint: true,
                      border: OutlineInputBorder(),
                    ),
                    textCapitalization: TextCapitalization.sentences,
                    minLines: 2,
                    maxLines: 4,
                  ),
                  const SizedBox(height: 8),
                  ListTile(
                    contentPadding: EdgeInsets.zero,
                    title: const Text('Date'),
                    subtitle: Text(DateFormat.yMMMd().format(day)),
                    trailing: const Icon(Icons.chevron_right),
                    onTap: pickDay,
                  ),
                  ListTile(
                    contentPadding: EdgeInsets.zero,
                    title: const Text('Starts'),
                    subtitle: Text(startT.format(ctx)),
                    trailing: const Icon(Icons.schedule),
                    onTap: pickStart,
                  ),
                  ListTile(
                    contentPadding: EdgeInsets.zero,
                    title: const Text('Ends'),
                    subtitle: Text(endT.format(ctx)),
                    trailing: const Icon(Icons.schedule),
                    onTap: pickEnd,
                  ),
                  const SizedBox(height: 12),
                  FilledButton(
                    onPressed: () {
                      if (titleCtrl.text.trim().isEmpty) return;
                      Navigator.pop(ctx, true);
                    },
                    child: const Text('Add to calendar'),
                  ),
                ],
              );
            },
          ),
        );
      },
    );

    if (ok != true || !mounted) {
      titleCtrl.dispose();
      descCtrl.dispose();
      return;
    }

    final start = DateTime(day.year, day.month, day.day, startT.hour, startT.minute);
    var end = DateTime(day.year, day.month, day.day, endT.hour, endT.minute);
    final endResolved = end.isAfter(start) ? end : start.add(const Duration(hours: 1));

    setState(() {
      _fixedEvents.add(
        EventModel(
          id: const Uuid().v4(),
          title: titleCtrl.text.trim(),
          startTime: start,
          endTime: endResolved,
          source: 'manual',
          isFixed: true,
          description: descCtrl.text.trim(),
        ),
      );
    });
    titleCtrl.dispose();
    descCtrl.dispose();
    await _persistManualEvents();
    _pushExternalBusyToStore();
    if (mounted) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Event added to your calendar.')),
      );
    }
  }

  Widget _buildMainPanel({required bool showMenuButton}) {
    return _CalendarMainPanel(
      toolbarTitle: _toolbarTitle(),
      viewMode: _viewMode,
      onViewModeChanged: (m) => setState(() => _viewMode = m),
      aiChatOpen: _calendarChatOpen,
      onToggleAiChat: _toggleAiChat,
      showMenuButton: showMenuButton,
      onOpenMenu: () => CalendarShellBridge.instance.openDrawer?.call(),
      onPrev: () => _shiftPeriod(-1),
      onNext: () => _shiftPeriod(1),
      onToday: _goToday,
      onOpenIcal: _openIcalFeedsSheet,
      onSuggestSchedule: _runSuggestSchedule,
      focusedDay: _focusedDay,
      selectedDay: _selectedDay,
      monthFormat: _monthFormat,
      onMonthFormatChanged: (f) => setState(() => _monthFormat = f),
      onDaySelected: _onDaySelected,
      onPageChanged: (d) => setState(() => _focusedDay = d),
      timedEventsOnDay: _timedEventsOnDay,
      canvasOnDay: _canvasOnDay,
      blocksOnDay: _blocksOnDay,
      visibleDays: _visibleDays(),
      viewModeEnum: _viewMode,
      firstHour: _firstHour,
      lastHour: _lastHour,
      hourHeight: _hourHeight,
      timeScrollController: _timeScrollController,
      onTapCanvas: _openAssignmentSheet,
      onTapBlock: _openBlockSheet,
      onEventTimeChanged: _onGridEventTimeChanged,
      onBlockTimeChanged: _onGridBlockTimeChanged,
    );
  }

  static const _calendarChatChips = [
    'Plan this week',
    'Add 2h study tomorrow',
    "What's on my calendar?",
    'Move my study block to Friday',
  ];

  void _toggleAiChat() {
    setState(() => _calendarChatOpen = !_calendarChatOpen);
  }

  void _closeAiChat() {
    if (_calendarChatOpen) setState(() => _calendarChatOpen = false);
  }

  /// Google Calendar–style docked side panel (calendar shrinks; panel does not overlap the grid).
  Widget _wrapCalendarWithChat(BuildContext context, Widget calendarBody) {
    final scheme = Theme.of(context).colorScheme;
    final divider = VerticalDivider(
      width: 1,
      thickness: 1,
      color: scheme.outlineVariant.withValues(alpha: 0.75),
    );

    if (!_calendarChatOpen) return calendarBody;

    final w = MediaQuery.sizeOf(context).width;
    final panelW = w >= 1100 ? 360.0 : (w * 0.36).clamp(300.0, 400.0);

    return Row(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Expanded(child: calendarBody),
        divider,
        SizedBox(
          width: panelW,
          child: _CalendarChatSidePanel(
            onClose: _closeAiChat,
            suggestionChips: _calendarChatChips,
          ),
        ),
      ],
    );
  }

  @override
  Widget build(BuildContext context) {
    _publishPlannerToShell();

    final useDrawerLayout = MediaQuery.sizeOf(context).width < 1000;

    return Scaffold(
      backgroundColor: Theme.of(context).colorScheme.surface,
      body: SafeArea(
        child: _wrapCalendarWithChat(
          context,
          _buildMainPanel(showMenuButton: useDrawerLayout),
        ),
      ),
      floatingActionButton: FloatingActionButton(
        heroTag: 'synctra_add_event',
        onPressed: _openQuickAddSheet,
        tooltip: 'Add event',
        child: const Icon(Icons.add),
      ),
    );
  }
}

// ── Main panel (toolbar + month or time grid) ───────────────────────────────

class _CalendarMainPanel extends StatelessWidget {
  final String toolbarTitle;
  final _CalendarViewMode viewMode;
  final ValueChanged<_CalendarViewMode> onViewModeChanged;
  final bool aiChatOpen;
  final VoidCallback onToggleAiChat;
  final bool showMenuButton;
  final VoidCallback onOpenMenu;
  final VoidCallback onPrev;
  final VoidCallback onNext;
  final VoidCallback onToday;
  final VoidCallback onOpenIcal;
  final VoidCallback onSuggestSchedule;
  final DateTime focusedDay;
  final DateTime selectedDay;
  final CalendarFormat monthFormat;
  final ValueChanged<CalendarFormat> onMonthFormatChanged;
  final void Function(DateTime, DateTime) onDaySelected;
  final void Function(DateTime) onPageChanged;
  final List<EventModel> Function(DateTime) timedEventsOnDay;
  final List<EventModel> Function(DateTime) canvasOnDay;
  final List<ScheduleBlockModel> Function(DateTime) blocksOnDay;
  final List<DateTime> visibleDays;
  final _CalendarViewMode viewModeEnum;
  final int firstHour;
  final int lastHour;
  final double hourHeight;
  final ScrollController timeScrollController;
  final void Function(EventModel) onTapCanvas;
  final void Function(ScheduleBlockModel) onTapBlock;
  final void Function(EventModel event, DateTime start, DateTime end) onEventTimeChanged;
  final void Function(ScheduleBlockModel block, DateTime start, DateTime end) onBlockTimeChanged;

  const _CalendarMainPanel({
    required this.toolbarTitle,
    required this.viewMode,
    required this.onViewModeChanged,
    required this.aiChatOpen,
    required this.onToggleAiChat,
    required this.showMenuButton,
    required this.onOpenMenu,
    required this.onPrev,
    required this.onNext,
    required this.onToday,
    required this.onOpenIcal,
    required this.onSuggestSchedule,
    required this.focusedDay,
    required this.selectedDay,
    required this.monthFormat,
    required this.onMonthFormatChanged,
    required this.onDaySelected,
    required this.onPageChanged,
    required this.timedEventsOnDay,
    required this.canvasOnDay,
    required this.blocksOnDay,
    required this.visibleDays,
    required this.viewModeEnum,
    required this.firstHour,
    required this.lastHour,
    required this.hourHeight,
    required this.timeScrollController,
    required this.onTapCanvas,
    required this.onTapBlock,
    required this.onEventTimeChanged,
    required this.onBlockTimeChanged,
  });

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;

    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        _CalendarToolbar(
          title: toolbarTitle,
          viewMode: viewMode,
          onViewModeChanged: onViewModeChanged,
          aiChatOpen: aiChatOpen,
          onToggleAiChat: onToggleAiChat,
          showMenuButton: showMenuButton,
          onOpenMenu: onOpenMenu,
          onPrev: onPrev,
          onNext: onNext,
          onToday: onToday,
          onOpenIcal: onOpenIcal,
          onSuggestSchedule: onSuggestSchedule,
        ),
        Expanded(
          child: viewMode == _CalendarViewMode.month
              ? _MonthTableCalendar(
                  focusedDay: focusedDay,
                  selectedDay: selectedDay,
                  format: monthFormat,
                  onDaySelected: onDaySelected,
                  onFormatChanged: onMonthFormatChanged,
                  onPageChanged: onPageChanged,
                  eventLoader: (d) {
                    final t = timedEventsOnDay(d);
                    final c = canvasOnDay(d);
                    final b = blocksOnDay(d);
                    return [...t, ...c, ...b];
                  },
                )
              : DecoratedBox(
                  decoration: BoxDecoration(
                    gradient: LinearGradient(
                      begin: Alignment.topCenter,
                      end: Alignment.bottomCenter,
                      colors: [
                        scheme.surface,
                        scheme.surfaceContainerHighest.withValues(alpha: 0.35),
                      ],
                    ),
                  ),
                  child: _WeekDayTimeGrid(
                    key: ValueKey(
                      'grid_${viewModeEnum.name}_${visibleDays.first.millisecondsSinceEpoch}',
                    ),
                    days: visibleDays,
                    selectedDay: selectedDay,
                    firstHour: firstHour,
                    lastHour: lastHour,
                    hourHeight: hourHeight,
                    scrollController: timeScrollController,
                    timedEventsOnDay: timedEventsOnDay,
                    canvasOnDay: canvasOnDay,
                    blocksOnDay: blocksOnDay,
                    onTapCanvas: onTapCanvas,
                    onTapBlock: onTapBlock,
                    onEventTimeChanged: onEventTimeChanged,
                    onBlockTimeChanged: onBlockTimeChanged,
                  ),
                ),
        ),
      ],
    );
  }
}

// ── Toolbar ───────────────────────────────────────────────────────────────────

class _CalendarToolbar extends StatelessWidget {
  final String title;
  final _CalendarViewMode viewMode;
  final ValueChanged<_CalendarViewMode> onViewModeChanged;
  final bool aiChatOpen;
  final VoidCallback onToggleAiChat;
  final bool showMenuButton;
  final VoidCallback onOpenMenu;
  final VoidCallback onPrev;
  final VoidCallback onNext;
  final VoidCallback onToday;
  final VoidCallback onOpenIcal;
  final VoidCallback onSuggestSchedule;

  const _CalendarToolbar({
    required this.title,
    required this.viewMode,
    required this.onViewModeChanged,
    required this.aiChatOpen,
    required this.onToggleAiChat,
    required this.showMenuButton,
    required this.onOpenMenu,
    required this.onPrev,
    required this.onNext,
    required this.onToday,
    required this.onOpenIcal,
    required this.onSuggestSchedule,
  });

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final textTheme = Theme.of(context).textTheme;

    return Material(
      color: scheme.surface,
      elevation: 0.5,
      shadowColor: Colors.black.withValues(alpha: 0.08),
      surfaceTintColor: Colors.transparent,
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 6),
        decoration: BoxDecoration(
          border: Border(bottom: BorderSide(color: scheme.outlineVariant.withValues(alpha: 0.6))),
        ),
        child: LayoutBuilder(
          builder: (context, constraints) {
            return Row(
              children: [
                Expanded(
                  child: SingleChildScrollView(
                    scrollDirection: Axis.horizontal,
                    child: Row(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        IconButton(
                          tooltip: 'Previous',
                          onPressed: onPrev,
                          icon: const Icon(Icons.chevron_left),
                        ),
                        IconButton(
                          tooltip: 'Next',
                          onPressed: onNext,
                          icon: const Icon(Icons.chevron_right),
                        ),
                        TextButton(onPressed: onToday, child: const Text('Today')),
                        const SizedBox(width: 8),
                        ConstrainedBox(
                          constraints: BoxConstraints(
                            maxWidth: (constraints.maxWidth * 0.35).clamp(120, 360),
                          ),
                          child: Text(
                            title,
                            style: textTheme.titleMedium?.copyWith(fontWeight: FontWeight.w500),
                            overflow: TextOverflow.ellipsis,
                          ),
                        ),
                        const SizedBox(width: 8),
                        SegmentedButton<_CalendarViewMode>(
                          segments: const [
                            ButtonSegment(value: _CalendarViewMode.day, label: Text('Day')),
                            ButtonSegment(value: _CalendarViewMode.week, label: Text('Week')),
                            ButtonSegment(value: _CalendarViewMode.month, label: Text('Month')),
                          ],
                          selected: {viewMode},
                          onSelectionChanged: (s) => onViewModeChanged(s.first),
                        ),
                        if (showMenuButton)
                          IconButton(
                            tooltip: 'Menu — nav & planner',
                            onPressed: onOpenMenu,
                            icon: const Icon(Icons.menu),
                          ),
                        IconButton(
                          tooltip: 'Suggest schedule',
                          onPressed: onSuggestSchedule,
                          icon: const Icon(Icons.schedule_outlined),
                        ),
                        IconButton(
                          tooltip: 'iCal Feeds',
                          onPressed: onOpenIcal,
                          icon: const Icon(Icons.link_outlined),
                        ),
                        IconButton(
                          tooltip: 'Account & settings',
                          onPressed: () => context.push('/settings'),
                          icon: const Icon(Icons.person_outline),
                        ),
                      ],
                    ),
                  ),
                ),
                Padding(
                  padding: const EdgeInsets.only(left: 8, right: 4),
                  child: SyncItLaunchButton(
                    isOpen: aiChatOpen,
                    onPressed: onToggleAiChat,
                  ),
                ),
              ],
            );
          },
        ),
      ),
    );
  }
}

// ── Month + upcoming planner (desktop column or mobile sheet) ───────────────

class _CalendarPlannerPanel extends StatelessWidget {
  final DateTime focusedDay;
  final DateTime selectedDay;
  final List<dynamic> Function(DateTime) eventsForDay;
  final void Function(DateTime, DateTime) onDaySelected;
  final void Function(DateTime) onPageChanged;
  final VoidCallback onOpenIcal;
  final ScrollController? scrollController;
  final bool showHeader;

  const _CalendarPlannerPanel({
    required this.focusedDay,
    required this.selectedDay,
    required this.eventsForDay,
    required this.onDaySelected,
    required this.onPageChanged,
    required this.onOpenIcal,
    this.scrollController,
    this.showHeader = false,
  });

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final textTheme = Theme.of(context).textTheme;

    final upcoming = <_UpcomingItem>[];
    final today = DateTime.now();
    for (var i = 0; i < 14; i++) {
      final d = DateTime(today.year, today.month, today.day).add(Duration(days: i));
      for (final raw in eventsForDay(d)) {
        if (raw is EventModel) {
          upcoming.add(_UpcomingItem(date: d, label: raw.title, time: raw.startTime));
        } else if (raw is ScheduleBlockModel) {
          upcoming.add(_UpcomingItem(date: d, label: raw.taskTitle, time: raw.startTime));
        }
      }
    }
    upcoming.sort((a, b) => a.time.compareTo(b.time));
    final slice = upcoming.take(24).toList();

    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        if (showHeader)
          Padding(
            padding: const EdgeInsets.fromLTRB(20, 4, 20, 0),
            child: Text('Planner', style: textTheme.titleMedium?.copyWith(fontWeight: FontWeight.w600)),
          ),
        Padding(
          padding: const EdgeInsets.fromLTRB(8, 4, 8, 8),
          child: TableCalendar<dynamic>(
            firstDay: DateTime.utc(2024, 1, 1),
            lastDay: DateTime.utc(2030, 12, 31),
            focusedDay: focusedDay,
            selectedDayPredicate: (d) => isSameDay(selectedDay, d),
            calendarFormat: CalendarFormat.month,
            startingDayOfWeek: StartingDayOfWeek.monday,
            eventLoader: eventsForDay,
            onDaySelected: onDaySelected,
            onPageChanged: onPageChanged,
            rowHeight: 32,
            daysOfWeekHeight: 16,
            headerStyle: HeaderStyle(
              formatButtonVisible: false,
              titleCentered: true,
              headerPadding: const EdgeInsets.symmetric(vertical: 4),
              leftChevronPadding: EdgeInsets.zero,
              rightChevronPadding: EdgeInsets.zero,
              titleTextStyle: textTheme.labelLarge!,
            ),
            calendarStyle: CalendarStyle(
              cellMargin: const EdgeInsets.all(1),
              outsideDaysVisible: true,
              weekendTextStyle: TextStyle(color: scheme.onSurfaceVariant, fontSize: 12),
              defaultTextStyle: TextStyle(color: scheme.onSurface, fontSize: 12),
              todayDecoration: BoxDecoration(
                color: scheme.primary.withValues(alpha: 0.16),
                shape: BoxShape.circle,
              ),
              selectedDecoration: BoxDecoration(
                color: scheme.primary,
                shape: BoxShape.circle,
              ),
              selectedTextStyle: TextStyle(color: scheme.onPrimary, fontSize: 12),
              todayTextStyle: TextStyle(color: scheme.primary, fontWeight: FontWeight.w600, fontSize: 12),
              markersMaxCount: 3,
              markerDecoration: BoxDecoration(
                color: scheme.secondary,
                shape: BoxShape.circle,
              ),
            ),
          ),
        ),
        const Divider(height: 1),
        Padding(
          padding: const EdgeInsets.fromLTRB(16, 12, 16, 8),
          child: Text('Upcoming', style: textTheme.titleSmall),
        ),
        Expanded(
          child: slice.isEmpty
              ? Center(
                  child: Padding(
                    padding: const EdgeInsets.all(16),
                    child: Text(
                      'No events yet.\nLink an iCal feed to see classes here.',
                      textAlign: TextAlign.center,
                      style: textTheme.bodySmall,
                    ),
                  ),
                )
              : ListView.separated(
                  controller: scrollController,
                  padding: const EdgeInsets.symmetric(horizontal: 12),
                  itemCount: slice.length,
                  separatorBuilder: (_, __) => const SizedBox(height: 4),
                  itemBuilder: (_, i) {
                    final u = slice[i];
                    return ListTile(
                      dense: true,
                      contentPadding: const EdgeInsets.symmetric(horizontal: 8, vertical: 0),
                      title: Text(u.label, maxLines: 2, overflow: TextOverflow.ellipsis),
                      subtitle: Text(
                        '${DateFormat('EEE M/d').format(u.date)} · ${DateFormat('jm').format(u.time)}',
                        style: textTheme.bodySmall,
                      ),
                    );
                  },
                ),
        ),
        Padding(
          padding: const EdgeInsets.all(12),
          child: OutlinedButton.icon(
            onPressed: onOpenIcal,
            icon: const Icon(Icons.link, size: 18),
            label: const Text('iCal feeds'),
          ),
        ),
      ],
    );
  }
}

class _UpcomingItem {
  final DateTime date;
  final String label;
  final DateTime time;
  _UpcomingItem({required this.date, required this.label, required this.time});
}

void _showTimedEventPeek(BuildContext context, EventModel e) {
  showModalBottomSheet<void>(
    context: context,
    showDragHandle: true,
    builder: (ctx) {
      return Padding(
        padding: EdgeInsets.fromLTRB(24, 8, 24, MediaQuery.paddingOf(ctx).bottom + 24),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Text(e.title, style: Theme.of(ctx).textTheme.titleMedium),
            const SizedBox(height: 8),
            Text(
              '${DateFormat('EEE, MMM d').format(e.startTime)} · '
              '${DateFormat('jm').format(e.startTime)} – ${DateFormat('jm').format(e.endTime)}',
              style: Theme.of(ctx).textTheme.bodyMedium,
            ),
            const SizedBox(height: 16),
            Text('Description', style: Theme.of(ctx).textTheme.labelLarge),
            const SizedBox(height: 6),
            if (e.description.trim().isNotEmpty)
              Text(e.description.trim(), style: Theme.of(ctx).textTheme.bodyMedium)
            else
              Text(
                'No notes for this event.',
                style: Theme.of(ctx).textTheme.bodySmall?.copyWith(
                      color: Theme.of(ctx).colorScheme.onSurfaceVariant,
                    ),
              ),
          ],
        ),
      );
    },
  );
}

// ── Month view (TableCalendar) ───────────────────────────────────────────────

class _MonthTableCalendar extends StatelessWidget {
  final DateTime focusedDay;
  final DateTime selectedDay;
  final CalendarFormat format;
  final void Function(DateTime, DateTime) onDaySelected;
  final void Function(CalendarFormat) onFormatChanged;
  final void Function(DateTime) onPageChanged;
  final List<dynamic> Function(DateTime) eventLoader;

  const _MonthTableCalendar({
    required this.focusedDay,
    required this.selectedDay,
    required this.format,
    required this.onDaySelected,
    required this.onFormatChanged,
    required this.onPageChanged,
    required this.eventLoader,
  });

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return TableCalendar<dynamic>(
      firstDay: DateTime.utc(2024, 1, 1),
      lastDay: DateTime.utc(2030, 12, 31),
      focusedDay: focusedDay,
      calendarFormat: format,
      selectedDayPredicate: (d) => isSameDay(selectedDay, d),
      eventLoader: eventLoader,
      onDaySelected: onDaySelected,
      onFormatChanged: onFormatChanged,
      onPageChanged: onPageChanged,
      startingDayOfWeek: StartingDayOfWeek.monday,
      calendarStyle: CalendarStyle(
        outsideDaysVisible: true,
        cellMargin: const EdgeInsets.all(2),
        todayDecoration: BoxDecoration(
          color: scheme.primary.withValues(alpha: 0.16),
          shape: BoxShape.circle,
        ),
        selectedDecoration: BoxDecoration(
          color: scheme.primary,
          shape: BoxShape.circle,
        ),
        selectedTextStyle: TextStyle(color: scheme.onPrimary),
        todayTextStyle: TextStyle(color: scheme.primary, fontWeight: FontWeight.w600),
        markerDecoration: BoxDecoration(color: scheme.secondary, shape: BoxShape.circle),
      ),
      headerStyle: const HeaderStyle(titleCentered: true, formatButtonVisible: true),
    );
  }
}

// ── Week / day time grid ─────────────────────────────────────────────────────

/// Day name + date above each column (aligned with the time grid).
class _WeekDayHeaderRow extends StatelessWidget {
  final List<DateTime> days;
  final DateTime selectedDay;

  const _WeekDayHeaderRow({
    required this.days,
    required this.selectedDay,
  });

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final theme = Theme.of(context).textTheme;
    final now = DateTime.now();
    final multiDay = days.length > 1;

    return Container(
      decoration: BoxDecoration(
        color: scheme.surface,
        border: Border(bottom: BorderSide(color: scheme.outlineVariant)),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.center,
        children: [
          SizedBox(
            width: 56,
            child: Center(
              child: Text(
                multiDay ? 'GMT' : '',
                style: theme.labelSmall?.copyWith(
                  color: scheme.onSurfaceVariant,
                  fontSize: 10,
                ),
              ),
            ),
          ),
          for (final d in days)
            Expanded(
              child: Container(
                decoration: BoxDecoration(
                  border: Border(left: BorderSide(color: scheme.outlineVariant)),
                  color: isSameDay(d, selectedDay)
                      ? scheme.primary.withValues(alpha: 0.06)
                      : null,
                ),
                padding: const EdgeInsets.symmetric(horizontal: 4, vertical: 10),
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    Text(
                      DateFormat('EEE').format(d).toUpperCase(),
                      style: theme.labelSmall?.copyWith(
                        color: scheme.onSurfaceVariant,
                        fontWeight: FontWeight.w600,
                        letterSpacing: 0.6,
                        fontSize: 11,
                      ),
                    ),
                    const SizedBox(height: 2),
                    Text(
                      '${d.day}',
                      style: theme.titleLarge?.copyWith(
                        fontWeight: FontWeight.w600,
                        height: 1,
                        color: isSameDay(d, now) ? scheme.primary : scheme.onSurface,
                      ),
                    ),
                    if (multiDay)
                      Text(
                        DateFormat('MMM').format(d),
                        style: theme.labelSmall?.copyWith(
                          color: scheme.onSurfaceVariant,
                          fontSize: 11,
                        ),
                      ),
                    if (isSameDay(d, now)) ...[
                      const SizedBox(height: 4),
                      Text(
                        'Today',
                        style: theme.labelSmall?.copyWith(
                          color: scheme.primary,
                          fontWeight: FontWeight.w600,
                          fontSize: 10,
                        ),
                      ),
                    ],
                  ],
                ),
              ),
            ),
        ],
      ),
    );
  }
}

/// One timed segment for column packing (events + study blocks).
class _SegLay {
  _SegLay({
    required this.startMin,
    required this.endMin,
    required this.id,
    this.event,
    this.block,
  });

  final int startMin;
  final int endMin;
  final String id;
  final EventModel? event;
  final ScheduleBlockModel? block;
  int col = 0;
}

class _WeekDayTimeGrid extends StatefulWidget {
  final List<DateTime> days;
  final DateTime selectedDay;
  final int firstHour;
  final int lastHour;
  final double hourHeight;
  final ScrollController scrollController;
  final List<EventModel> Function(DateTime) timedEventsOnDay;
  final List<EventModel> Function(DateTime) canvasOnDay;
  final List<ScheduleBlockModel> Function(DateTime) blocksOnDay;
  final void Function(EventModel) onTapCanvas;
  final void Function(ScheduleBlockModel) onTapBlock;
  final void Function(EventModel event, DateTime start, DateTime end) onEventTimeChanged;
  final void Function(ScheduleBlockModel block, DateTime start, DateTime end) onBlockTimeChanged;

  const _WeekDayTimeGrid({
    super.key,
    required this.days,
    required this.selectedDay,
    required this.firstHour,
    required this.lastHour,
    required this.hourHeight,
    required this.scrollController,
    required this.timedEventsOnDay,
    required this.canvasOnDay,
    required this.blocksOnDay,
    required this.onTapCanvas,
    required this.onTapBlock,
    required this.onEventTimeChanged,
    required this.onBlockTimeChanged,
  });

  @override
  State<_WeekDayTimeGrid> createState() => _WeekDayTimeGridState();
}

class _WeekDayTimeGridState extends State<_WeekDayTimeGrid> {
  double get _gridHeight => (widget.lastHour - widget.firstHour + 1) * widget.hourHeight;

  /// Scroll so ~7:00 is near the top of the viewport (same anchor as [_CalendarScreenState._firstHour]).
  void _scrollToWorkdayStart() {
    final c = widget.scrollController;
    if (!c.hasClients) return;
    const targetHour = 7;
    final raw = (targetHour - widget.firstHour) * widget.hourHeight;
    final max = c.position.maxScrollExtent;
    c.jumpTo(raw.clamp(0.0, max));
  }

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) => _scrollToWorkdayStart());
  }

  @override
  void didUpdateWidget(covariant _WeekDayTimeGrid oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.days.first != widget.days.first ||
        oldWidget.days.length != widget.days.length) {
      WidgetsBinding.instance.addPostFrameCallback((_) => _scrollToWorkdayStart());
    }
  }

  @override
  Widget build(BuildContext context) {
    final now = DateTime.now();

    return Column(
      children: [
        _WeekDayHeaderRow(
          days: widget.days,
          selectedDay: widget.selectedDay,
        ),
        _AllDayAssignmentStrip(
          days: widget.days,
          canvasOnDay: widget.canvasOnDay,
          onTap: widget.onTapCanvas,
        ),
        Expanded(
          child: Scrollbar(
            controller: widget.scrollController,
            thumbVisibility: true,
            child: SingleChildScrollView(
              controller: widget.scrollController,
              child: SizedBox(
                height: _gridHeight,
                child: Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    _TimeGutter(
                      firstHour: widget.firstHour,
                      lastHour: widget.lastHour,
                      hourHeight: widget.hourHeight,
                    ),
                    Expanded(
                      child: Row(
                        children: [
                          for (final d in widget.days)
                            Expanded(
                              child: _DayTimeColumn(
                                day: d,
                                isToday: isSameDay(d, now),
                                isSelected: isSameDay(d, widget.selectedDay),
                                firstHour: widget.firstHour,
                                lastHour: widget.lastHour,
                                hourHeight: widget.hourHeight,
                                timedEvents: widget.timedEventsOnDay(d),
                                blocks: widget.blocksOnDay(d),
                                now: now,
                                onTapCanvas: widget.onTapCanvas,
                                onTapBlock: widget.onTapBlock,
                                onEventTimeChanged: widget.onEventTimeChanged,
                                onBlockTimeChanged: widget.onBlockTimeChanged,
                              ),
                            ),
                        ],
                      ),
                    ),
                  ],
                ),
              ),
            ),
          ),
        ),
      ],
    );
  }
}

class _AllDayAssignmentStrip extends StatelessWidget {
  final List<DateTime> days;
  final List<EventModel> Function(DateTime) canvasOnDay;
  final void Function(EventModel) onTap;

  const _AllDayAssignmentStrip({
    required this.days,
    required this.canvasOnDay,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final maxChips = days.map((d) => canvasOnDay(d).length).fold<int>(0, (a, b) => a > b ? a : b);
    final rowHeight = maxChips == 0 ? 36.0 : 28.0 + maxChips * 26.0;

    return Container(
      decoration: BoxDecoration(
        color: scheme.surface,
        border: Border(bottom: BorderSide(color: scheme.outlineVariant)),
      ),
      constraints: BoxConstraints(minHeight: rowHeight.clamp(36, 120)),
      child: Row(
        children: [
          SizedBox(
            width: 56,
            child: Center(
              child: Text(
                'All-day',
                style: Theme.of(context).textTheme.labelSmall?.copyWith(
                      color: scheme.onSurfaceVariant,
                    ),
              ),
            ),
          ),
          for (final d in days)
            Expanded(
              child: Container(
                decoration: BoxDecoration(
                  border: Border(left: BorderSide(color: scheme.outlineVariant)),
                ),
                padding: const EdgeInsets.symmetric(horizontal: 4, vertical: 4),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    for (final a in canvasOnDay(d))
                      Padding(
                        padding: const EdgeInsets.only(bottom: 2),
                        child: Material(
                          color: AppColors.canvasAssignmentContainer,
                          borderRadius: BorderRadius.circular(8),
                          elevation: 1,
                          shadowColor: Colors.black.withValues(alpha: 0.06),
                          clipBehavior: Clip.antiAlias,
                          child: InkWell(
                            onTap: () => onTap(a),
                            child: Padding(
                              padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 4),
                              child: Text(
                                a.title,
                                maxLines: 1,
                                overflow: TextOverflow.ellipsis,
                                style: Theme.of(context).textTheme.labelSmall?.copyWith(
                                      color: AppColors.canvasAssignment,
                                      fontWeight: FontWeight.w600,
                                    ),
                              ),
                            ),
                          ),
                        ),
                      ),
                  ],
                ),
              ),
            ),
        ],
      ),
    );
  }
}

class _TimeGutter extends StatelessWidget {
  final int firstHour;
  final int lastHour;
  final double hourHeight;

  const _TimeGutter({
    required this.firstHour,
    required this.lastHour,
    required this.hourHeight,
  });

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return SizedBox(
      width: 56,
      child: Column(
        children: [
          for (int h = firstHour; h <= lastHour; h++)
            SizedBox(
              height: hourHeight,
              child: Align(
                alignment: Alignment.topRight,
                child: Padding(
                  padding: const EdgeInsets.only(right: 6, top: 0),
                  child: Text(
                    DateFormat('ha').format(DateTime(2020, 1, 1, h)),
                    style: Theme.of(context).textTheme.labelSmall?.copyWith(
                          color: scheme.onSurfaceVariant,
                          height: 1,
                        ),
                  ),
                ),
              ),
            ),
        ],
      ),
    );
  }
}

class _DayTimeColumn extends StatelessWidget {
  final DateTime day;
  final bool isToday;
  final bool isSelected;
  final int firstHour;
  final int lastHour;
  final double hourHeight;
  final List<EventModel> timedEvents;
  final List<ScheduleBlockModel> blocks;
  final DateTime now;
  final void Function(EventModel) onTapCanvas;
  final void Function(ScheduleBlockModel) onTapBlock;
  final void Function(EventModel event, DateTime start, DateTime end) onEventTimeChanged;
  final void Function(ScheduleBlockModel block, DateTime start, DateTime end) onBlockTimeChanged;

  const _DayTimeColumn({
    required this.day,
    required this.isToday,
    required this.isSelected,
    required this.firstHour,
    required this.lastHour,
    required this.hourHeight,
    required this.timedEvents,
    required this.blocks,
    required this.now,
    required this.onTapCanvas,
    required this.onTapBlock,
    required this.onEventTimeChanged,
    required this.onBlockTimeChanged,
  });

  double _minutesFromStart(DateTime dt) {
    final start = DateTime(dt.year, dt.month, dt.day, firstHour);
    return dt.difference(start).inMinutes.toDouble();
  }

  /// Greedy column assignment: overlapping items split column width evenly.
  static List<_SegLay> _packSegments(List<_SegLay> raw) {
    if (raw.isEmpty) return raw;
    raw.sort((a, b) {
      final c = a.startMin.compareTo(b.startMin);
      if (c != 0) return c;
      return (b.endMin - b.startMin).compareTo(a.endMin - a.startMin);
    });
    final colEnd = <int>[];
    for (final s in raw) {
      var placed = false;
      for (var i = 0; i < colEnd.length; i++) {
        if (colEnd[i] <= s.startMin) {
          s.col = i;
          colEnd[i] = s.endMin;
          placed = true;
          break;
        }
      }
      if (!placed) {
        s.col = colEnd.length;
        colEnd.add(s.endMin);
      }
    }
    return raw;
  }

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final gridHeight = (lastHour - firstHour + 1) * hourHeight;
    final dayStart = DateTime(day.year, day.month, day.day, firstHour);
    final dayEndExclusive = DateTime(day.year, day.month, day.day, lastHour + 1);
    final totalMins = (lastHour - firstHour + 1) * 60;

    double? nowY;
    if (isToday) {
      if (!now.isBefore(dayStart) && now.isBefore(dayEndExclusive)) {
        nowY = (_minutesFromStart(now) / 60.0) * hourHeight;
        nowY = nowY.clamp(0.0, gridHeight);
      }
    }

    final segs = <_SegLay>[];
    for (final e in timedEvents) {
      var sm = e.startTime.difference(dayStart).inMinutes;
      var em = e.endTime.difference(dayStart).inMinutes;
      if (em <= sm) continue;
      sm = sm.clamp(0, totalMins);
      em = em.clamp(0, totalMins);
      if (em <= sm) continue;
      segs.add(_SegLay(startMin: sm, endMin: em, id: 'e_${e.id}', event: e));
    }
    for (final b in blocks) {
      var sm = b.startTime.difference(dayStart).inMinutes;
      var em = b.endTime.difference(dayStart).inMinutes;
      if (em <= sm) continue;
      sm = sm.clamp(0, totalMins);
      em = em.clamp(0, totalMins);
      if (em <= sm) continue;
      segs.add(_SegLay(startMin: sm, endMin: em, id: 'b_${b.id}', block: b));
    }
    _packSegments(segs);
    final maxCols = segs.isEmpty ? 1 : segs.map((s) => s.col).reduce((a, b) => a > b ? a : b) + 1;

    return DecoratedBox(
      decoration: BoxDecoration(
        color: isToday ? scheme.primary.withValues(alpha: 0.04) : scheme.surface,
        border: Border(
          left: BorderSide(color: scheme.outlineVariant),
          right: BorderSide(
            color: isSelected ? scheme.primary : Colors.transparent,
            width: isSelected ? 2 : 0,
          ),
        ),
      ),
      child: LayoutBuilder(
        builder: (context, constraints) {
          final w = constraints.maxWidth;
          const pad = 4.0;
          final inner = (w - pad * 2).clamp(4.0, w);
          final colW = inner / maxCols;

          return Stack(
            clipBehavior: Clip.hardEdge,
            children: [
              CustomPaint(
                size: Size(w, gridHeight),
                painter: _HourGridPainter(
                  lineColor: Theme.of(context).brightness == Brightness.dark
                      ? scheme.outlineVariant
                      : AppColors.calendarGridLine,
                  firstHour: firstHour,
                  lastHour: lastHour,
                  hourHeight: hourHeight,
                ),
              ),
              ...segs.map(
                (s) => _positionedSeg(
                  context: context,
                  s: s,
                  gridHeight: gridHeight,
                  pad: pad,
                  colW: colW,
                  totalMins: totalMins,
                  dayStart: dayStart,
                ),
              ),
              if (nowY != null)
                Positioned(
                  top: nowY,
                  left: 0,
                  right: 0,
                  child: Row(
                    children: [
                      Container(
                        width: 8,
                        height: 8,
                        decoration: const BoxDecoration(
                          color: AppColors.currentTimeLine,
                          shape: BoxShape.circle,
                        ),
                      ),
                      Expanded(child: Container(height: 2, color: AppColors.currentTimeLine)),
                    ],
                  ),
                ),
            ],
          );
        },
      ),
    );
  }

  Widget _positionedSeg({
    required BuildContext context,
    required _SegLay s,
    required double gridHeight,
    required double pad,
    required double colW,
    required int totalMins,
    required DateTime dayStart,
  }) {
    final top = (s.startMin / 60.0) * hourHeight;
    final h = ((s.endMin - s.startMin) / 60.0) * hourHeight;
    if (h <= 0 || top >= gridHeight) return const SizedBox.shrink();
    final topVis = top.clamp(0.0, gridHeight);
    final maxH = (gridHeight - topVis).clamp(0.0, gridHeight);
    final left = pad + s.col * colW;
    final width = (colW - 2).clamp(8.0, colW);

    double chipHeight(double minH) {
      if (maxH <= 0) return 0;
      final capped = math.min(h, maxH);
      if (capped < 4) return 0;
      return math.max(capped, math.min(minH, maxH));
    }

    if (s.event != null) {
      final e = s.event!;
      final color = e.source == 'canvas'
          ? AppColors.canvasAssignment
          : (e.source == 'ical' ? AppColors.icalAccent : AppColors.fixedEvent);
      final onTap = e.source == 'canvas'
          ? () => onTapCanvas(e)
          : () => _showTimedEventPeek(context, e);
      final ht = chipHeight(20);
      if (ht <= 0) return const SizedBox.shrink();
      final canDrag = e.source != 'synctra_preview';
      final chip = _TimedEventChip(event: e, color: color, onTap: onTap);
      return Positioned(
        top: topVis,
        left: left,
        width: width,
        height: ht,
        child: _DragTimeChipShell(
          enabled: canDrag,
          heightPx: ht,
          hourHeight: hourHeight,
          startMin: s.startMin,
          endMin: s.endMin,
          totalMins: totalMins,
          onCommitMinutes: (ns, ne) {
            final start = dayStart.add(Duration(minutes: ns));
            final end = dayStart.add(Duration(minutes: ne));
            onEventTimeChanged(e, start, end);
          },
          child: chip,
        ),
      );
    }
    if (s.block != null) {
      final b = s.block!;
      final bg = b.isAiGenerated ? AppColors.aiStudyBlock : AppColors.confirmedStudyBlock;
      final ht = chipHeight(24);
      if (ht <= 0) return const SizedBox.shrink();
      final chip = _StudyBlockChip(block: b, color: bg, onTap: () => onTapBlock(b));
      return Positioned(
        top: topVis,
        left: left,
        width: width,
        height: ht,
        child: _DragTimeChipShell(
          enabled: true,
          heightPx: ht,
          hourHeight: hourHeight,
          startMin: s.startMin,
          endMin: s.endMin,
          totalMins: totalMins,
          onCommitMinutes: (ns, ne) {
            final start = dayStart.add(Duration(minutes: ns));
            final end = dayStart.add(Duration(minutes: ne));
            onBlockTimeChanged(b, start, end);
          },
          child: chip,
        ),
      );
    }
    return const SizedBox.shrink();
  }
}

/// Vertical drag on the grip strip moves the chip; snaps to 15-minute steps.
class _DragTimeChipShell extends StatefulWidget {
  const _DragTimeChipShell({
    required this.enabled,
    required this.heightPx,
    required this.hourHeight,
    required this.startMin,
    required this.endMin,
    required this.totalMins,
    required this.onCommitMinutes,
    required this.child,
  });

  final bool enabled;
  final double heightPx;
  final double hourHeight;
  final int startMin;
  final int endMin;
  final int totalMins;
  final void Function(int newStartMin, int newEndMin) onCommitMinutes;
  final Widget child;

  @override
  State<_DragTimeChipShell> createState() => _DragTimeChipShellState();
}

class _DragTimeChipShellState extends State<_DragTimeChipShell> {
  double _dy = 0;

  static int _snap(int m) => ((m / 15).round() * 15).clamp(0, 24 * 60);

  @override
  Widget build(BuildContext context) {
    if (!widget.enabled) {
      return SizedBox(height: widget.heightPx, child: widget.child);
    }
    return SizedBox(
      height: widget.heightPx,
      child: ClipRRect(
        borderRadius: BorderRadius.circular(10),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Expanded(
              child: Transform.translate(
                offset: Offset(0, _dy),
                child: widget.child,
              ),
            ),
            GestureDetector(
              behavior: HitTestBehavior.opaque,
              onVerticalDragUpdate: (d) => setState(() => _dy += d.delta.dy),
              onVerticalDragEnd: (_) {
                final dur = widget.endMin - widget.startMin;
                final dm = (_dy / widget.hourHeight * 60).round();
                setState(() => _dy = 0);
                var ns = _snap(widget.startMin + dm);
                if (ns < 0) ns = 0;
                if (ns > widget.totalMins - 15) ns = (widget.totalMins - 15).clamp(0, widget.totalMins);
                var ne = ns + dur;
                if (ne > widget.totalMins) {
                  ne = widget.totalMins;
                  ns = (ne - dur).clamp(0, ne - 15);
                }
                if (ne - ns < 15) return;
                widget.onCommitMinutes(ns, ne);
              },
              child: DecoratedBox(
                decoration: BoxDecoration(
                  color: Colors.black.withValues(alpha: 0.2),
                ),
                child: const SizedBox(
                  width: 11,
                  child: Center(
                    child: Icon(Icons.drag_indicator, size: 10, color: Colors.white70),
                  ),
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _HourGridPainter extends CustomPainter {
  final Color lineColor;
  final int firstHour;
  final int lastHour;
  final double hourHeight;

  _HourGridPainter({
    required this.lineColor,
    required this.firstHour,
    required this.lastHour,
    required this.hourHeight,
  });

  @override
  void paint(Canvas canvas, Size size) {
    final p = Paint()
      ..color = lineColor
      ..strokeWidth = 1;
    for (var i = 0; i <= (lastHour - firstHour); i++) {
      final y = i * hourHeight;
      canvas.drawLine(Offset(0, y), Offset(size.width, y), p);
    }
  }

  @override
  bool shouldRepaint(covariant _HourGridPainter oldDelegate) =>
      oldDelegate.lineColor != lineColor || oldDelegate.hourHeight != hourHeight;
}

class _TimedEventChip extends StatelessWidget {
  final EventModel event;
  final Color color;
  final VoidCallback? onTap;

  const _TimedEventChip({
    required this.event,
    required this.color,
    this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    final dur = event.endTime.difference(event.startTime);
    final durLabel = dur.inHours >= 1
        ? '${dur.inHours}h ${dur.inMinutes % 60}m'
        : '${dur.inMinutes}m';
    return Material(
      color: color.withValues(alpha: 0.94),
      borderRadius: BorderRadius.circular(10),
      elevation: 2,
      shadowColor: Colors.black.withValues(alpha: 0.18),
      clipBehavior: Clip.antiAlias,
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(10),
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 5),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                event.title,
                maxLines: 2,
                overflow: TextOverflow.ellipsis,
                style: Theme.of(context).textTheme.labelMedium?.copyWith(
                      color: Colors.white,
                      fontWeight: FontWeight.w600,
                      height: 1.2,
                    ),
              ),
              Text(
                durLabel,
                style: Theme.of(context).textTheme.labelSmall?.copyWith(
                      color: Colors.white.withValues(alpha: 0.92),
                      fontWeight: FontWeight.w500,
                    ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _StudyBlockChip extends StatelessWidget {
  final ScheduleBlockModel block;
  final Color color;
  final VoidCallback onTap;

  const _StudyBlockChip({required this.block, required this.color, required this.onTap});

  @override
  Widget build(BuildContext context) {
    final dur = block.endTime.difference(block.startTime);
    final durLabel = dur.inHours >= 1
        ? '${dur.inHours}h ${dur.inMinutes % 60}m'
        : '${dur.inMinutes}m';
    return Material(
      color: color.withValues(alpha: 0.94),
      borderRadius: BorderRadius.circular(10),
      elevation: 2,
      shadowColor: Colors.black.withValues(alpha: 0.2),
      clipBehavior: Clip.antiAlias,
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(10),
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 5),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  if (block.isAiGenerated)
                    Padding(
                      padding: const EdgeInsets.only(right: 4),
                      child: Icon(Icons.auto_awesome, size: 12, color: Colors.white.withValues(alpha: 0.95)),
                    ),
                  Expanded(
                    child: Text(
                      block.taskTitle,
                      maxLines: 2,
                      overflow: TextOverflow.ellipsis,
                      style: Theme.of(context).textTheme.labelMedium?.copyWith(
                            color: Colors.white,
                            fontWeight: FontWeight.w600,
                            height: 1.2,
                          ),
                    ),
                  ),
                ],
              ),
              Text(
                durLabel,
                style: Theme.of(context).textTheme.labelSmall?.copyWith(
                      color: Colors.white.withValues(alpha: 0.92),
                      fontWeight: FontWeight.w500,
                    ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

// ── Bottom sheets ─────────────────────────────────────────────────────────────

class _AssignmentDetailSheet extends StatelessWidget {
  final EventModel event;
  final VoidCallback onScheduleStudy;

  const _AssignmentDetailSheet({
    required this.event,
    required this.onScheduleStudy,
  });

  (String course, String title) _splitTitle(String t) {
    final i = t.indexOf(':');
    if (i > 0 && i < t.length - 1) {
      return (t.substring(0, i).trim(), t.substring(i + 1).trim());
    }
    return ('—', t);
  }

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final textTheme = Theme.of(context).textTheme;
    final parts = _splitTitle(event.title);

    return Padding(
      padding: EdgeInsets.only(
        left: 24,
        right: 24,
        top: 8,
        bottom: MediaQuery.paddingOf(context).bottom + 24,
      ),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Text(parts.$2, style: textTheme.titleMedium),
          const SizedBox(height: 8),
          _SheetRow(icon: Icons.school_outlined, label: 'Course', value: parts.$1),
          _SheetRow(
            icon: Icons.event_outlined,
            label: 'Due',
            value: DateFormat('EEEE, MMM d, y · jm').format(event.startTime),
          ),
          _SheetRow(
            icon: Icons.timer_outlined,
            label: 'Estimated duration',
            value: '${event.endTime.difference(event.startTime).inMinutes.clamp(1, 9999)} min',
          ),
          const SizedBox(height: 16),
          Text('Description', style: textTheme.labelLarge),
          const SizedBox(height: 6),
          Container(
            width: double.infinity,
            padding: const EdgeInsets.all(12),
            decoration: BoxDecoration(
              color: scheme.surfaceContainerHighest,
              borderRadius: BorderRadius.circular(12),
              border: Border.all(color: scheme.outlineVariant),
            ),
            child: Text(
              event.description.trim().isEmpty ? 'No description.' : event.description.trim(),
              style: textTheme.bodyMedium?.copyWith(
                color: event.description.trim().isEmpty ? scheme.onSurfaceVariant : null,
                height: 1.35,
              ),
            ),
          ),
          const SizedBox(height: 12),
          Text('Priority', style: textTheme.labelLarge),
          const SizedBox(height: 6),
          Align(
            alignment: Alignment.centerLeft,
            child: Chip(
              label: const Text('Not set'),
              backgroundColor: scheme.surfaceContainerHighest,
              side: BorderSide.none,
            ),
          ),
          const SizedBox(height: 20),
          FilledButton.icon(
            onPressed: onScheduleStudy,
            icon: const Icon(Icons.schedule),
            label: const Text('Schedule study time'),
          ),
        ],
      ),
    );
  }
}

class _BlockDetailSheet extends StatefulWidget {
  final ScheduleBlockModel block;
  final BuildContext parentContext;

  const _BlockDetailSheet({
    required this.block,
    required this.parentContext,
  });

  @override
  State<_BlockDetailSheet> createState() => _BlockDetailSheetState();
}

class _BlockDetailSheetState extends State<_BlockDetailSheet> {
  late final TextEditingController _descCtrl;

  @override
  void initState() {
    super.initState();
    _descCtrl = TextEditingController(text: widget.block.description);
  }

  @override
  void dispose() {
    _descCtrl.dispose();
    super.dispose();
  }

  Future<void> _move(BuildContext sheetContext) async {
    Navigator.pop(sheetContext);
    final day = await showDatePicker(
      context: widget.parentContext,
      initialDate: widget.block.startTime,
      firstDate: DateTime(widget.block.startTime.year - 1),
      lastDate: DateTime(widget.block.startTime.year + 2),
    );
    if (day == null || !widget.parentContext.mounted) return;
    final time = await showTimePicker(
      context: widget.parentContext,
      initialTime: TimeOfDay.fromDateTime(widget.block.startTime),
    );
    if (time == null || !widget.parentContext.mounted) return;
    final newStart = DateTime(day.year, day.month, day.day, time.hour, time.minute);
    final dur = widget.block.endTime.difference(widget.block.startTime);
    GetIt.instance<SuggestedScheduleStore>().updateBlockTimes(
      id: widget.block.id,
      start: newStart,
      end: newStart.add(dur),
    );
    if (widget.parentContext.mounted) {
      ScaffoldMessenger.of(widget.parentContext).showSnackBar(
        const SnackBar(content: Text('Block moved.')),
      );
    }
  }

  Future<void> _resize(BuildContext sheetContext) async {
    Navigator.pop(sheetContext);
    final choice = await showDialog<int>(
      context: widget.parentContext,
      builder: (ctx) => SimpleDialog(
        title: const Text('Block length'),
        children: [
          for (final m in [30, 45, 60, 90, 120])
            SimpleDialogOption(
              onPressed: () => Navigator.pop(ctx, m),
              child: Text('$m minutes'),
            ),
        ],
      ),
    );
    if (choice == null || !widget.parentContext.mounted) return;
    GetIt.instance<SuggestedScheduleStore>().updateBlockTimes(
      id: widget.block.id,
      start: widget.block.startTime,
      end: widget.block.startTime.add(Duration(minutes: choice)),
    );
    ScaffoldMessenger.of(widget.parentContext).showSnackBar(
      const SnackBar(content: Text('Block length updated.')),
    );
  }

  void _delete(BuildContext sheetContext) {
    Navigator.pop(sheetContext);
    GetIt.instance<SuggestedScheduleStore>().removeBlock(widget.block.id);
    if (widget.parentContext.mounted) {
      ScaffoldMessenger.of(widget.parentContext).showSnackBar(
        const SnackBar(content: Text('Study block removed.')),
      );
    }
  }

  void _saveDescription() {
    GetIt.instance<SuggestedScheduleStore>().updateBlockDescription(
      widget.block.id,
      _descCtrl.text.trim(),
    );
    if (mounted) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Notes saved.')),
      );
    }
  }

  @override
  Widget build(BuildContext context) {
    final textTheme = Theme.of(context).textTheme;
    final scheme = Theme.of(context).colorScheme;
    final time =
        '${DateFormat('jm').format(widget.block.startTime)} – ${DateFormat('jm').format(widget.block.endTime)}';

    return Padding(
      padding: EdgeInsets.only(
        left: 24,
        right: 24,
        top: 8,
        bottom: MediaQuery.paddingOf(context).bottom + 24,
      ),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Text(widget.block.taskTitle, style: textTheme.titleMedium),
          const SizedBox(height: 4),
          Text(time, style: textTheme.bodyMedium),
          const SizedBox(height: 16),
          Text('Description / notes', style: textTheme.labelLarge),
          const SizedBox(height: 6),
          TextField(
            controller: _descCtrl,
            minLines: 2,
            maxLines: 5,
            decoration: InputDecoration(
              hintText: 'Add context for this study block…',
              filled: true,
              fillColor: scheme.surfaceContainerHighest,
              border: OutlineInputBorder(borderRadius: BorderRadius.circular(12)),
            ),
          ),
          const SizedBox(height: 8),
          Align(
            alignment: Alignment.centerRight,
            child: TextButton.icon(
              onPressed: _saveDescription,
              icon: const Icon(Icons.save_outlined, size: 18),
              label: const Text('Save notes'),
            ),
          ),
          const SizedBox(height: 12),
          ListTile(
            leading: const Icon(Icons.open_with),
            title: const Text('Move'),
            onTap: () => _move(context),
          ),
          ListTile(
            leading: const Icon(Icons.aspect_ratio),
            title: const Text('Resize'),
            onTap: () => _resize(context),
          ),
          ListTile(
            leading: Icon(Icons.delete_outline, color: scheme.error),
            title: Text('Delete', style: TextStyle(color: scheme.error)),
            onTap: () => _delete(context),
          ),
        ],
      ),
    );
  }
}

class _SheetRow extends StatelessWidget {
  final IconData icon;
  final String label;
  final String value;

  const _SheetRow({required this.icon, required this.label, required this.value});

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 10),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Icon(icon, size: 20, color: Theme.of(context).colorScheme.onSurfaceVariant),
          const SizedBox(width: 12),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(label, style: Theme.of(context).textTheme.labelSmall),
                Text(value, style: Theme.of(context).textTheme.bodyMedium),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

// ── iCal feeds bottom sheet (unchanged behavior) ─────────────────────────────

class _IcalFeedsSheet extends StatefulWidget {
  final List<Map<String, String>> feeds;
  final Map<String, int> feedEventCounts;
  final Future<void> Function(String url, String name) onAdd;
  final Future<void> Function(String feedId) onRemove;
  final Future<void> Function(String id, String name, String url) onSync;

  const _IcalFeedsSheet({
    required this.feeds,
    required this.feedEventCounts,
    required this.onAdd,
    required this.onRemove,
    required this.onSync,
  });

  @override
  State<_IcalFeedsSheet> createState() => _IcalFeedsSheetState();
}

class _IcalFeedsSheetState extends State<_IcalFeedsSheet> {
  bool _showForm = false;
  final _urlCtrl = TextEditingController();
  final _nameCtrl = TextEditingController();
  bool _isLoading = false;
  String? _error;

  @override
  void dispose() {
    _urlCtrl.dispose();
    _nameCtrl.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    final url = _urlCtrl.text.trim();
    if (url.isEmpty) {
      setState(() => _error = 'Please enter a URL.');
      return;
    }
    if (!url.startsWith('http://') &&
        !url.startsWith('https://') &&
        !url.startsWith('webcal://')) {
      setState(() => _error = 'URL must start with http://, https://, or webcal://');
      return;
    }

    setState(() {
      _isLoading = true;
      _error = null;
    });
    try {
      await widget.onAdd(url, _nameCtrl.text.trim());
      if (mounted) Navigator.of(context).pop();
    } on DioException catch (e) {
      if (mounted) {
        final detail = e.response?.data?['detail']?.toString() ?? e.message ?? 'Unknown error';
        setState(() {
          _isLoading = false;
          _error = detail;
        });
      }
    } catch (e) {
      if (mounted) {
        setState(() {
          _isLoading = false;
          _error = e.toString();
        });
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: EdgeInsets.only(
        left: 16,
        right: 16,
        top: 16,
        bottom: MediaQuery.of(context).viewInsets.bottom + 24,
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Center(
            child: Container(
              width: 40,
              height: 4,
              margin: const EdgeInsets.only(bottom: 16),
              decoration: BoxDecoration(
                color: Colors.grey[300],
                borderRadius: BorderRadius.circular(2),
              ),
            ),
          ),
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              const Text('iCal Feeds', style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold)),
              TextButton.icon(
                onPressed: () => setState(() {
                  _showForm = !_showForm;
                  _error = null;
                }),
                icon: Icon(_showForm ? Icons.close : Icons.add),
                label: Text(_showForm ? 'Cancel' : 'Add Feed'),
              ),
            ],
          ),
          Expanded(
            child: SingleChildScrollView(
              keyboardDismissBehavior: ScrollViewKeyboardDismissBehavior.onDrag,
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                mainAxisSize: MainAxisSize.min,
                children: [
                  if (_showForm) ...[
                    const SizedBox(height: 12),
                    TextField(
                      controller: _urlCtrl,
                      decoration: const InputDecoration(
                        labelText: 'Calendar URL',
                        hintText: 'https://…  or  webcal://…',
                        border: OutlineInputBorder(),
                      ),
                      keyboardType: TextInputType.url,
                      autocorrect: false,
                      autofocus: true,
                    ),
                    const SizedBox(height: 8),
                    TextField(
                      controller: _nameCtrl,
                      decoration: const InputDecoration(
                        labelText: 'Name (optional)',
                        hintText: 'e.g. Work Calendar',
                        border: OutlineInputBorder(),
                      ),
                    ),
                    if (_error != null) ...[
                      const SizedBox(height: 8),
                      Text(_error!, style: const TextStyle(color: Colors.red, fontSize: 13)),
                    ],
                    const SizedBox(height: 12),
                    FilledButton(
                      onPressed: _isLoading ? null : _submit,
                      child: _isLoading
                          ? const SizedBox(
                              width: 20,
                              height: 20,
                              child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white),
                            )
                          : const Text('Import'),
                    ),
                  ],
                  if (widget.feeds.isEmpty && !_showForm) ...[
                    const SizedBox(height: 24),
                    Center(
                      child: Column(
                        children: [
                          Icon(Icons.link_off, size: 44, color: Colors.grey[300]),
                          const SizedBox(height: 8),
                          Text('No iCal feeds yet.', style: TextStyle(color: Colors.grey[500])),
                          const SizedBox(height: 4),
                          Text(
                            'Paste a link from Google Calendar, Outlook,\nApple Calendar, or any .ics URL.',
                            textAlign: TextAlign.center,
                            style: TextStyle(fontSize: 12, color: Colors.grey[400]),
                          ),
                        ],
                      ),
                    ),
                    const SizedBox(height: 24),
                  ],
                  if (widget.feeds.isNotEmpty) ...[
                    const SizedBox(height: 12),
                    ...widget.feeds.map((feed) {
                      final count = widget.feedEventCounts[feed['id']] ?? -1;
                      final countLabel = count < 0 ? 'not synced' : '$count events';
                      return ListTile(
                        contentPadding: EdgeInsets.zero,
                        leading: const Icon(Icons.calendar_today_outlined, size: 20),
                        title: Text(feed['name'] ?? 'Unnamed Feed'),
                        subtitle: Text(
                          '$countLabel\n${feed['url'] ?? ''}',
                          maxLines: 2,
                          overflow: TextOverflow.ellipsis,
                          style: const TextStyle(fontSize: 11),
                        ),
                        isThreeLine: true,
                        trailing: Row(
                          mainAxisSize: MainAxisSize.min,
                          children: [
                            IconButton(
                              icon: const Icon(Icons.refresh, size: 20),
                              tooltip: 'Re-sync',
                              onPressed: () async {
                                try {
                                  await widget.onSync(feed['id']!, feed['name']!, feed['url']!);
                                  if (context.mounted) Navigator.of(context).pop();
                                } catch (e) {
                                  if (context.mounted) {
                                    ScaffoldMessenger.of(context).showSnackBar(
                                      SnackBar(content: Text('Sync failed: $e'), backgroundColor: Colors.red),
                                    );
                                  }
                                }
                              },
                            ),
                            IconButton(
                              icon: Icon(Icons.delete_outline, size: 20, color: Colors.red[300]),
                              onPressed: () async {
                                await widget.onRemove(feed['id']!);
                                if (context.mounted) Navigator.of(context).pop();
                              },
                            ),
                          ],
                        ),
                      );
                    }),
                  ],
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }
}

/// Docked assistant column beside the calendar grid (does not cover events).
class _CalendarChatSidePanel extends StatelessWidget {
  final VoidCallback onClose;
  final List<String> suggestionChips;

  const _CalendarChatSidePanel({
    required this.onClose,
    required this.suggestionChips,
  });

  @override
  Widget build(BuildContext context) {
    return SyncItPanelFrame(
      onClose: onClose,
      child: SynctraChatPanel(
        compact: true,
        showHeader: false,
        suggestionChips: suggestionChips,
      ),
    );
  }
}

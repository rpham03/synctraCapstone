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
import '../../../data/models/habit_model.dart';
import '../../../data/models/schedule_block_model.dart';
import '../../../data/models/task_model.dart';
import '../../../data/services/course_import_service.dart';
import '../../../shared/services/calendar_view_prefs.dart';
import '../../../shared/services/canvas_tasks_service.dart';
import '../../../shared/services/llm_service.dart';
import '../../../shared/services/manual_events_storage.dart';
import '../../../shared/services/manual_events_store.dart';
import '../../../shared/services/synctra_chat_constants.dart';
import '../../../shared/services/synctra_chat_service.dart';
import '../../../shared/services/scheduling_service.dart';
import '../../../shared/services/user_settings_service.dart';
import '../../../shared/services/habit_session_store.dart';
import '../../../shared/services/suggested_schedule_store.dart';
import '../../../shared/state/calendar_shell_bridge.dart';
import '../../../shared/state/shell_sidebar_controller.dart';
import '../../../shared/state/course_import_tasks_bridge.dart';
import '../../../shared/state/manual_tasks_bridge.dart';
import '../../../shared/utils/calendar_display_utils.dart';
import '../../../shared/utils/local_time_format.dart';
import '../../../shared/utils/undo_snackbar.dart';
import '../../../shared/utils/manual_tasks_calendar.dart';
import '../../../shared/utils/task_schedule_utils.dart';
import '../../../shared/services/course_color_map.dart';
import '../../../shared/widgets/responsive_layout.dart';
import '../../../shared/widgets/dashed_border_painter.dart';
import '../../../shared/widgets/synctra_chat_panel.dart';
import '../../../shared/widgets/sync_it_chrome.dart';
import '../widgets/calendar_left_sidebar.dart';
import '../widgets/calendar_top_bar.dart';

enum _CalendarViewMode { day, week, month }

class _EventDeleteSnapshot {
  const _EventDeleteSnapshot({
    required this.event,
    required this.canUndo,
    this.canvasTask,
    this.manualTask,
    this.icalFeedId,
  });

  final EventModel event;
  final bool canUndo;
  final TaskModel? canvasTask;
  final TaskModel? manualTask;
  final String? icalFeedId;
}

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
  bool _calendarSidebarOpen = false;
  int _weekNavDirection = 1;
  final Set<String> _hiddenFeedIds = {};
  final Map<String, String> _eventIdToFeedId = {};
  final _scaffoldKey = GlobalKey<ScaffoldState>();

  static const _hiddenFeedsKey = 'synctra_hidden_ical_feeds';

  final List<EventModel> _fixedEvents = [];
  final List<EventModel> _canvasEvents = [];
  final List<EventModel> _manualTaskEvents = [];
  late final SuggestedScheduleStore _scheduleStore;
  late final HabitSessionStore _habitStore;
  late final ManualEventsStore _manualEventsStore;
  late final CanvasTasksService _canvasTasks;
  late final CourseImportService _courseImportService;

  final Map<String, List<EventModel>> _feedEvents = {};
  final List<Map<String, String>> _icalFeeds = [];
  final List<CourseImportRecord> _courseImports = [];

  final ScrollController _timeScrollController = ScrollController();
  Timer? _nowTicker;

  /// Full 24-hour day column: midnight (0) through 11 PM (23).
  static const int _firstHour = 0;
  static const int _lastHour = 23;
  static const double _hourHeight = AppTokens.calendarHourHeight;

  @override
  void initState() {
    super.initState();
    _scheduleStore = GetIt.instance<SuggestedScheduleStore>();
    _habitStore = GetIt.instance<HabitSessionStore>();
    _manualEventsStore = GetIt.instance<ManualEventsStore>();
    _canvasTasks = GetIt.instance<CanvasTasksService>();
    _courseImportService = CourseImportService();
    _canvasTasks.addListener(_reloadCanvasEvents);
    CourseImportTasksBridge.instance.addListener(_handleCourseImportsRefresh);
    ManualTasksBridge.instance.addListener(_handleManualTasksRefresh);
    _scheduleStore.addListener(_onScheduleStoreChanged);
    _habitStore.addListener(_onHabitStoreChanged);
    // Chat can move/delete manual events; reload them when that store changes.
    _manualEventsStore.addListener(_loadManualEvents);
    _loadSavedFeeds();
    _loadHiddenFeeds();
    CourseColorMap.instance.ensureLoaded();
    _loadManualEvents();
    _loadManualTaskEvents();
    _loadCourseImports();
    _reloadCanvasEvents();
    _nowTicker = Timer.periodic(const Duration(minutes: 1), (_) {
      if (mounted) setState(() {});
    });
    CalendarShellBridge.instance.registerImportActions(
      onIcal: _openIcalFeedsSheet,
      onCourseImport: _openCourseImportSheet,
    );
    _loadCalendarViewPref();
  }

  Future<void> _loadCalendarViewPref() async {
    final stored = await CalendarViewPrefs.load();
    final mode = _viewModeFromString(stored);
    if (!mounted || mode == null) return;
    setState(() => _viewMode = mode);
  }

  _CalendarViewMode? _viewModeFromString(String? value) {
    switch (value) {
      case 'day':
        return _CalendarViewMode.day;
      case 'week':
        return _CalendarViewMode.week;
      case 'month':
        return _CalendarViewMode.month;
      default:
        return null;
    }
  }

  void _setViewMode(_CalendarViewMode mode) {
    setState(() => _viewMode = mode);
    CalendarViewPrefs.save(mode.name);
  }

  void _onScheduleStoreChanged() {
    if (mounted) setState(() {});
  }

  void _onHabitStoreChanged() {
    if (mounted) setState(() {});
  }

  void _handleCourseImportsRefresh() {
    _loadCourseImports();
  }

  void _handleManualTasksRefresh() {
    _loadManualTaskEvents();
  }

  Future<void> _loadManualTaskEvents() async {
    final events = await ManualTasksCalendar.loadEvents();
    if (!mounted) return;
    setState(() {
      _manualTaskEvents
        ..clear()
        ..addAll(events);
    });
    _pushExternalBusyToStore();
  }

  void _pushExternalBusyToStore() {
    final events = _allEvents().toList();
    _scheduleStore.setExternalBusy(events);
    _habitStore.setCalendarEvents(events);
    unawaited(_scheduleHabits());
  }

  Future<void> _scheduleHabits() async {
    await _habitStore.refreshSchedule(
      calendarEvents: _allEvents(),
      weekStart: _startOfWeek(_focusedDay),
    );
  }

  @override
  void dispose() {
    CalendarShellBridge.instance.registerImportActions();
    _canvasTasks.removeListener(_reloadCanvasEvents);
    CourseImportTasksBridge.instance
        .removeListener(_handleCourseImportsRefresh);
    ManualTasksBridge.instance.removeListener(_handleManualTasksRefresh);
    _scheduleStore.removeListener(_onScheduleStoreChanged);
    _habitStore.removeListener(_onHabitStoreChanged);
    _manualEventsStore.removeListener(_loadManualEvents);
    _nowTicker?.cancel();
    _timeScrollController.dispose();
    super.dispose();
  }

  Iterable<EventModel> _allEvents() sync* {
    for (final e in _fixedEvents) {
      yield e;
    }
    for (final e in _canvasEvents) {
      yield e;
    }
    for (final e in _manualTaskEvents) {
      yield e;
    }
    for (final entry in _feedEvents.entries) {
      if (_hiddenFeedIds.contains(entry.key)) continue;
      for (final e in entry.value) {
        yield e;
      }
    }
  }

  void _rebuildEventFeedIndex() {
    _eventIdToFeedId.clear();
    for (final entry in _feedEvents.entries) {
      for (final e in entry.value) {
        _eventIdToFeedId[e.id] = entry.key;
      }
    }
  }

  Color _colorForEvent(EventModel event) {
    final feedId = _eventIdToFeedId[event.id];
    if (feedId != null) {
      return CourseColorMap.instance.colorFor(feedId);
    }
    return switch (event.source) {
      'canvas' => AppColors.canvasAssignment,
      'course' => AppColors.courseOrange,
      'manual_task' => AppColors.manualTask,
      'manual' => AppColors.fixedEvent,
      _ => AppColors.fixedEvent,
    };
  }

  bool _isLockedEvent(EventModel event) {
    if (event.source == 'manual_task') return false;
    if (!event.isFixed) return false;
    return event.source == 'course' ||
        event.source == 'canvas' ||
        event.source.startsWith('ical') ||
        _eventIdToFeedId.containsKey(event.id);
  }

  Future<void> _loadHiddenFeeds() async {
    final prefs = await SharedPreferences.getInstance();
    final raw = prefs.getStringList(_hiddenFeedsKey) ?? [];
    if (!mounted) return;
    setState(() {
      _hiddenFeedIds
        ..clear()
        ..addAll(raw);
    });
  }

  Future<void> _toggleFeedVisibility(String feedId) async {
    setState(() {
      if (_hiddenFeedIds.contains(feedId)) {
        _hiddenFeedIds.remove(feedId);
      } else {
        _hiddenFeedIds.add(feedId);
      }
    });
    final prefs = await SharedPreferences.getInstance();
    await prefs.setStringList(_hiddenFeedsKey, _hiddenFeedIds.toList());
    _pushExternalBusyToStore();
  }

  List<CalendarUpcomingItem> _upcomingItems({int limit = 7}) {
    final now = DateTime.now();
    final items = <({DateTime sort, CalendarUpcomingItem item})>[];

    for (final event in _allEvents()) {
      if (event.isDueDateChip) continue;
      if (event.startTime.isBefore(now.subtract(const Duration(hours: 1)))) {
        continue;
      }
      final color = _colorForEvent(event);
      final (title, course) = _chipTitleParts(event.title);
      final display = course != null ? '$course · $title' : title;
      final day = DateTime(
        event.startTime.year,
        event.startTime.month,
        event.startTime.day,
      );
      String timeLabel;
      if (isSameDay(event.startTime, now)) {
        timeLabel = DateFormat('h:mm a').format(event.startTime);
      } else if (isSameDay(
        event.startTime,
        now.add(const Duration(days: 1)),
      )) {
        timeLabel = 'Tomorrow';
      } else {
        timeLabel = DateFormat('MMM d').format(event.startTime);
      }
      items.add((
        sort: event.startTime,
        item: CalendarUpcomingItem(
          title: display,
          timeLabel: timeLabel,
          color: color,
          targetDay: day,
        ),
      ));
    }

    for (final block in _scheduleStore.blocks) {
      if (block.startTime.isBefore(now.subtract(const Duration(hours: 1)))) {
        continue;
      }
      final day = DateTime(
        block.startTime.year,
        block.startTime.month,
        block.startTime.day,
      );
      String timeLabel;
      if (isSameDay(block.startTime, now)) {
        timeLabel = DateFormat('h:mm a').format(block.startTime);
      } else if (isSameDay(
        block.startTime,
        now.add(const Duration(days: 1)),
      )) {
        timeLabel = 'Tomorrow';
      } else {
        timeLabel = DateFormat('MMM d').format(block.startTime);
      }
      items.add((
        sort: block.startTime,
        item: CalendarUpcomingItem(
          title: block.taskTitle,
          timeLabel: timeLabel,
          color: AppColors.aiStudyBlock,
          targetDay: day,
        ),
      ));
    }

    items.sort((a, b) => a.sort.compareTo(b.sort));
    return items.take(limit).map((e) => e.item).toList();
  }

  List<CalendarFeedChipData> _feedChipData() {
    return [
      for (final feed in _icalFeeds)
        CalendarFeedChipData(
          id: feed['id']!,
          name: feed['name']!,
          color: CourseColorMap.instance.colorFor(feed['id']!),
          visible: !_hiddenFeedIds.contains(feed['id']),
        ),
    ];
  }

  void _navigateToDay(DateTime day) {
    setState(() {
      _focusedDay = day;
      _selectedDay = day;
    });
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
    final loaded = await loadManualEvents();
    if (!mounted) return;
    setState(() {
      _fixedEvents.removeWhere((e) => e.source == 'manual');
      _fixedEvents.addAll(loaded);
    });
    _pushExternalBusyToStore();
  }

  Future<void> _persistManualEvents() async {
    final manual = _fixedEvents.where((e) => e.source == 'manual').toList();
    await saveManualEvents(manual);
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
      unawaited(CourseColorMap.instance.assignFor(id));
      _syncFeed(id, name, url).catchError((_) {});
    }
    _rebuildEventFeedIndex();
    if (mounted) _pushExternalBusyToStore();
  }

  Future<void> _loadCourseImports() async {
    try {
      final imports = await _courseImportService.loadImports();
      final events = <EventModel>[];
      for (final import in imports) {
        events
            .addAll(await _courseImportService.loadEventsForImport(import.id));
      }
      if (!mounted) return;
      setState(() {
        _courseImports
          ..clear()
          ..addAll(imports);
        _fixedEvents.removeWhere((e) => e.source == 'course');
        _fixedEvents.addAll(events);
      });
      _pushExternalBusyToStore();
    } catch (_) {}
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
      setState(() {
        _feedEvents[feedId] = events;
        _rebuildEventFeedIndex();
      });
      _pushExternalBusyToStore();
    }
  }

  Future<void> _addFeed(String url, String name) async {
    final id = const Uuid().v4();
    final prefs = await SharedPreferences.getInstance();
    _icalFeeds.add({'id': id, 'name': name, 'url': url});
    await CourseColorMap.instance.assignFor(id);
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
    await CourseColorMap.instance.remove(feedId);
    setState(() {
      _feedEvents.remove(feedId);
      _hiddenFeedIds.remove(feedId);
      _rebuildEventFeedIndex();
    });
    _pushExternalBusyToStore();
  }

  Future<void> _addCourseImport(String url, String name) async {
    await _courseImportService.addImport(url, name);
    await _loadCourseImports();
    CourseImportTasksBridge.instance.refresh();
  }

  Future<void> _removeCourseImport(String importId) async {
    await _courseImportService.removeImport(importId);
    await _loadCourseImports();
    CourseImportTasksBridge.instance.refresh();
  }

  List<EventModel> _timedEventsOnDay(DateTime day) =>
      CalendarDisplayUtils.timedEventsOnDay(_allEvents(), day);

  List<EventModel> _canvasChipsOnDay(DateTime day) =>
      CalendarDisplayUtils.canvasOnDay(_allEvents(), day)
          .where((c) => !CalendarDisplayUtils.canvasShowsInTimeGrid(c))
          .toList();

  List<EventModel> _courseAllDayOnDay(DateTime day) =>
      CalendarDisplayUtils.courseAllDayOnDay(_allEvents(), day);

  List<EventModel> _manualTasksOnDay(DateTime day) =>
      CalendarDisplayUtils.manualTasksOnDay(_allEvents(), day);

  List<ScheduleBlockModel> _blocksOnDay(DateTime day) =>
      _scheduleStore.blocks.where((b) => isSameDay(b.startTime, day)).toList();

  List<HabitSessionModel> _habitSessionsOnDay(DateTime day) =>
      _habitStore.sessionsOnDay(day);

  /// Sidebar / month markers — timed grid Canvas is included only via timedEventsOnDay.
  List<dynamic> _eventsForDay(DateTime day) => CalendarDisplayUtils.entriesForDay(
        allEvents: _allEvents(),
        blocks: _scheduleStore.blocks,
        habitSessions: _habitStore.sessions,
        day: day,
      );

  DateTime _startOfWeek(DateTime d) {
    final day = DateTime(d.year, d.month, d.day);
    // Sunday = start of week (DateTime.weekday: Mon=1 … Sun=7).
    return day.subtract(Duration(days: day.weekday % 7));
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

  bool _isViewingToday() {
    final now = DateTime.now();
    switch (_viewMode) {
      case _CalendarViewMode.day:
        return isSameDay(_focusedDay, now);
      case _CalendarViewMode.week:
        return _visibleDays().any((d) => isSameDay(d, now));
      case _CalendarViewMode.month:
        return _focusedDay.year == now.year && _focusedDay.month == now.month;
    }
  }

  String _todayChipLabel() {
    return 'Today · ${DateFormat('MMM d').format(DateTime.now())}';
  }

  void _shiftPeriod(int delta) {
    setState(() {
      _weekNavDirection = delta >= 0 ? 1 : -1;
      switch (_viewMode) {
        case _CalendarViewMode.day:
          _focusedDay = _focusedDay.add(Duration(days: delta));
          _selectedDay = _focusedDay;
        case _CalendarViewMode.week:
          _focusedDay = _focusedDay.add(Duration(days: 7 * delta));
        case _CalendarViewMode.month:
          _focusedDay =
              DateTime(_focusedDay.year, _focusedDay.month + delta, 1);
      }
    });
    unawaited(_scheduleHabits());
  }

  String _toolbarTitle() {
    switch (_viewMode) {
      case _CalendarViewMode.day:
        return DateFormat('EEEE, MMMM d, yyyy').format(_focusedDay);
      case _CalendarViewMode.week:
        final days = _visibleDays();
        final a = days.first;
        final b = days.last;
        if (a.month == b.month && a.year == b.year) {
          return '${DateFormat('MMMM d').format(a)} – ${DateFormat('d, yyyy').format(b)}';
        }
        if (a.year == b.year) {
          return '${DateFormat('MMM d').format(a)} – ${DateFormat('MMM d, y').format(b)}';
        }
        return '${DateFormat('MMM d, y').format(a)} – ${DateFormat('MMM d, y').format(b)}';
      case _CalendarViewMode.month:
        return DateFormat('MMMM yyyy').format(_focusedDay);
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
        feedEventCounts: {
          for (final e in _feedEvents.entries) e.key: e.value.length
        },
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

  void _openCourseImportSheet() {
    showModalBottomSheet(
      context: context,
      isScrollControlled: true,
      showDragHandle: true,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(16)),
      ),
      builder: (_) => _CourseImportSheet(
        imports: List.from(_courseImports),
        onImport: _addCourseImport,
        onRemove: _removeCourseImport,
      ),
    );
  }

  void _openCalendarEntry(Object item) {
    if (item is ScheduleBlockModel) {
      _openBlockSheet(item);
    } else if (item is EventModel) {
      _openEventDetail(item);
    }
  }

  void _openEventDetail(EventModel event) {
    if (_canEditEvent(event)) {
      _openEditEvent(event);
      return;
    }
    showModalBottomSheet(
      context: context,
      isScrollControlled: true,
      showDragHandle: true,
      builder: (sheetCtx) => _CalendarEventDetailSheet(
        event: event,
        canDelete: _canDeleteEvent(event),
        canEdit: false,
        showScheduleStudy:
            event.source == 'canvas' || event.isCourseAssignment,
        onEdit: () {},
        onScheduleStudy: () async {
          Navigator.pop(sheetCtx);
          final mins = event.estimatedMinutes ??
              event.endTime.difference(event.startTime).inMinutes;
          final hours = (mins / 60.0).clamp(0.5, 4.0);
          final result =
              await GetIt.instance<SynctraChatService>().scheduleStudyForDueItem(
            title: event.title,
            dueDate: event.startTime,
            hours: hours < 0.5 ? 1.5 : hours,
          );
          if (mounted) {
            ScaffoldMessenger.of(context)
                .showSnackBar(SnackBar(content: Text(result.reply)));
          }
        },
        onDelete: () => _confirmDeleteEvent(event, sheetCtx),
      ),
    );
  }

  bool _canDeleteEvent(EventModel event) => event.source != 'synctra_preview';

  bool _canEditEvent(EventModel event) => event.source != 'synctra_preview';

  String _deleteEventMessage(EventModel event) {
    switch (event.source) {
      case 'canvas':
        return 'Remove this assignment from Synctra? It stays on Canvas until you sync again.';
      case 'course':
        return 'Remove this from your imported course and the Tasks tab?';
      case 'manual_task':
        return 'Remove this task from Synctra and the Tasks tab?';
      case 'manual':
        return 'Delete this event from your calendar?';
      default:
        if (event.source.startsWith('ical')) {
          return 'Remove this feed event from Synctra? It may return when the feed syncs.';
        }
        return 'Remove this from Synctra?';
    }
  }

  Future<void> _confirmDeleteEvent(
    EventModel event,
    BuildContext sheetCtx,
  ) async {
    Navigator.pop(sheetCtx);
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Remove from Synctra?'),
        content: Text(_deleteEventMessage(event)),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx, false),
            child: const Text('Cancel'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(ctx, true),
            child: const Text('Remove'),
          ),
        ],
      ),
    );
    if (ok != true || !mounted) return;

    final snapshot = await _snapshotBeforeDelete(event);
    await _removeEventFromSynctra(event);
    if (!mounted) return;

    setState(() {});
    _pushExternalBusyToStore();

    if (event.source == 'canvas') {
      await _canvasTasks.reloadFromCache();
    } else if (event.source == 'course') {
      CourseImportTasksBridge.instance.refresh();
    } else if (event.source == 'manual_task') {
      ManualTasksBridge.instance.refresh();
    }
    if (!mounted) return;

    if (snapshot.canUndo) {
      showUndoSnackBar(
        context,
        message: 'Removed from Synctra.',
        onUndo: () => _restoreEventSnapshot(snapshot),
      );
    } else {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Removed from Synctra.')),
      );
    }
  }

  Future<_EventDeleteSnapshot> _snapshotBeforeDelete(EventModel event) async {
    switch (event.source) {
      case 'manual':
        return _EventDeleteSnapshot(event: event, canUndo: true);
      case 'canvas':
        final taskId = event.id.startsWith('canvas-')
            ? event.id.substring('canvas-'.length)
            : event.id;
        final tasks = await _canvasTasks.loadCached();
        TaskModel? task;
        for (final t in tasks) {
          if (t.id == taskId) {
            task = t;
            break;
          }
        }
        return _EventDeleteSnapshot(
          event: event,
          canUndo: task != null,
          canvasTask: task,
        );
      case 'manual_task':
        final taskId = event.id.replaceFirst('manual-task-', '');
        final tasks = await ManualTasksCalendar.loadTasks();
        TaskModel? task;
        for (final t in tasks) {
          if (t.id == taskId) {
            task = t;
            break;
          }
        }
        return _EventDeleteSnapshot(
          event: event,
          canUndo: task != null,
          manualTask: task,
        );
      case 'course':
        return _EventDeleteSnapshot(event: event, canUndo: false);
      default:
        if (event.source.startsWith('ical')) {
          for (final entry in _feedEvents.entries) {
            if (entry.value.any((e) => e.id == event.id)) {
              return _EventDeleteSnapshot(
                event: event,
                canUndo: true,
                icalFeedId: entry.key,
              );
            }
          }
        }
        return _EventDeleteSnapshot(event: event, canUndo: false);
    }
  }

  Future<void> _restoreEventSnapshot(_EventDeleteSnapshot snapshot) async {
    final event = snapshot.event;
    switch (event.source) {
      case 'manual':
        setState(() => _fixedEvents.add(event));
        await _persistManualEvents();
      case 'canvas':
        final task = snapshot.canvasTask;
        if (task != null) {
          final tasks = await _canvasTasks.loadCached();
          await _canvasTasks.saveCache([...tasks, task]);
          await _reloadCanvasEvents();
        }
      case 'manual_task':
        final task = snapshot.manualTask;
        if (task != null) {
          final tasks = await ManualTasksCalendar.loadTasks();
          await ManualTasksCalendar.saveTasks([...tasks, task]);
          await _loadManualTaskEvents();
          ManualTasksBridge.instance.refresh();
        }
      default:
        if (event.source.startsWith('ical') && snapshot.icalFeedId != null) {
          setState(() {
            _feedEvents.putIfAbsent(snapshot.icalFeedId!, () => []).add(event);
          });
        }
    }
    if (!mounted) return;
    setState(() {});
    _pushExternalBusyToStore();
  }

  Future<void> _removeEventFromSynctra(EventModel event) async {
    switch (event.source) {
      case 'manual':
        _fixedEvents.removeWhere((e) => e.id == event.id);
        await _persistManualEvents();
      case 'canvas':
        final taskId = event.id.startsWith('canvas-')
            ? event.id.substring('canvas-'.length)
            : event.id;
        final tasks = await _canvasTasks.loadCached();
        await _canvasTasks.saveCache(tasks.where((t) => t.id != taskId).toList());
        await _reloadCanvasEvents();
      case 'course':
        await _courseImportService.removeEventForCalendar(event);
        _fixedEvents.removeWhere((e) => e.id == event.id);
      case 'manual_task':
        final taskId = event.id.replaceFirst('manual-task-', '');
        await ManualTasksCalendar.removeTaskById(taskId);
        _manualTaskEvents.removeWhere((e) => e.id == event.id);
      default:
        if (event.source.startsWith('ical')) {
          for (final list in _feedEvents.values) {
            list.removeWhere((e) => e.id == event.id);
          }
        }
    }
  }

  void _openBlockSheet(ScheduleBlockModel block) {
    _openEditBlock(block);
  }

  Future<void> _openEditBlock(ScheduleBlockModel block) async {
    final result = await showModalBottomSheet<_QuickEditBlockResult>(
      context: context,
      isScrollControlled: true,
      showDragHandle: true,
      builder: (ctx) => _QuickEditBlockSheet(block: block),
    );
    if (result == null || !mounted) return;

    if (result.delete) {
      GetIt.instance<SuggestedScheduleStore>().removeBlock(block.id);
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Study block removed.')),
      );
      return;
    }

    GetIt.instance<SuggestedScheduleStore>().updateBlockTimes(
      id: block.id,
      start: result.start,
      end: result.end,
    );
    if (result.description != block.description) {
      GetIt.instance<SuggestedScheduleStore>().updateBlockDescription(
        block.id,
        result.description,
      );
    }
    if (mounted) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Block updated.')),
      );
    }
  }

  void _onGridEventTimeChanged(EventModel e, DateTime start, DateTime end) {
    if (e.source == 'synctra_preview') return;
    switch (e.source) {
      case 'manual':
        final i = _fixedEvents.indexWhere((x) => x.id == e.id);
        if (i >= 0) {
          setState(
              () => _fixedEvents[i] = e.copyWith(startTime: start, endTime: end));
          _persistManualEvents();
        }
      case 'manual_task':
        final updated = e.copyWith(startTime: start, endTime: end);
        ManualTasksCalendar.updateTaskFromEvent(e, updated);
        final mi = _manualTaskEvents.indexWhere((x) => x.id == e.id);
        if (mi >= 0) {
          setState(() => _manualTaskEvents[mi] = updated);
        } else {
          _loadManualTaskEvents();
        }
        ManualTasksBridge.instance.refresh();
      default:
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

  void _onGridBlockTimeChanged(
      ScheduleBlockModel b, DateTime start, DateTime end) {
    GetIt.instance<SuggestedScheduleStore>()
        .updateBlockTimes(id: b.id, start: start, end: end);
  }

  void _runSuggestSchedule() {
    _pushExternalBusyToStore();
    final store = _scheduleStore;
    final llm = GetIt.instance<LlmService>();
    final now = DateTime.now();
    final weekStart = DateTime(now.year, now.month, now.day)
        .subtract(Duration(days: now.weekday % 7));
    final weekEnd = weekStart.add(const Duration(days: 7));
    final fixed = store.fixedEventsForScheduling();

    final flex = <FlexibleTask>[];
    final seen = <String>{};
    for (var i = 0; i < 7; i++) {
      final day = weekStart.add(Duration(days: i));
      for (final e in CalendarDisplayUtils.canvasOnDay(_allEvents(), day)) {
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
    final workPrefs = GetIt.instance<UserSettingsService>().workPreferences;
    final blocks = scheduling.scheduleWeek(
      weekStart: weekStart,
      weekEnd: weekEnd,
      fixedEvents: fixed,
      flexibleTasks: flex,
      config: const SchedulingConfig(
        bufferAroundFixedEvents: Duration(minutes: 15),
        minimumBlockSize: Duration(minutes: 30),
      ),
      workPreferences: workPrefs,
    );

    final titles = <String, String>{for (final f in flex) f.id: f.title};
    for (final s in blocks) {
      titles.putIfAbsent(s.taskId, () => s.taskId);
    }
    store.applySynctraPreview(
        scheduled: blocks, taskTitles: titles, fixed: fixed);

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

  Future<void> _openEditEvent(EventModel event) async {
    final day = DateTime(
      event.startTime.year,
      event.startTime.month,
      event.startTime.day,
    );
    final result = await showModalBottomSheet<_QuickAddEventResult>(
      context: context,
      isScrollControlled: true,
      showDragHandle: true,
      builder: (ctx) => _QuickAddEventSheet(
        initialDay: day,
        existing: event,
        canDelete: _canDeleteEvent(event),
        onDelete: () => _confirmDeleteEvent(event, ctx),
      ),
    );
    if (result == null || !mounted) return;
    await _applyEventEdit(event, result);
  }

  Future<void> _applyEventEdit(
    EventModel original,
    _QuickAddEventResult result,
  ) async {
    final updated = original.copyWith(
      title: result.title,
      description: result.description,
      startTime: result.start,
      endTime: result.end,
    );

    switch (original.source) {
      case 'manual':
        final i = _fixedEvents.indexWhere((e) => e.id == original.id);
        if (i >= 0) {
          setState(() => _fixedEvents[i] = updated);
          await _persistManualEvents();
        }
      case 'canvas':
        final taskId = original.id.startsWith('canvas-')
            ? original.id.substring('canvas-'.length)
            : original.id;
        final tasks = await _canvasTasks.loadCached();
        final ti = tasks.indexWhere((t) => t.id == taskId);
        if (ti >= 0) {
          tasks[ti] = tasks[ti].copyWith(
            title: result.title,
            dueDate: result.start,
            description: result.description,
          );
          await _canvasTasks.saveCache(tasks);
          await _reloadCanvasEvents();
          await _canvasTasks.reloadFromCache();
        }
      case 'course':
        await _courseImportService.updateCalendarEvent(updated);
        final fi = _fixedEvents.indexWhere((e) => e.id == original.id);
        if (fi >= 0) {
          setState(() => _fixedEvents[fi] = updated);
        } else {
          await _loadCourseImports();
        }
        CourseImportTasksBridge.instance.refresh();
      case 'manual_task':
        await ManualTasksCalendar.updateTaskFromEvent(original, updated);
        final mi = _manualTaskEvents.indexWhere((e) => e.id == original.id);
        if (mi >= 0) {
          setState(() => _manualTaskEvents[mi] = updated);
        } else {
          await _loadManualTaskEvents();
        }
        ManualTasksBridge.instance.refresh();
      default:
        if (original.source.startsWith('ical')) {
          for (final list in _feedEvents.values) {
            final j = list.indexWhere((e) => e.id == original.id);
            if (j >= 0) {
              setState(() => list[j] = updated);
              break;
            }
          }
        }
    }

    if (!mounted) return;
    setState(() {});
    _pushExternalBusyToStore();
    ScaffoldMessenger.of(context).showSnackBar(
      const SnackBar(content: Text('Event updated.')),
    );
  }

  Future<void> _openQuickAddSheet({
    DateTime? initialDay,
    TimeOfDay? initialStartTime,
    TimeOfDay? initialEndTime,
  }) async {
    final day = initialDay ??
        DateTime(_focusedDay.year, _focusedDay.month, _focusedDay.day);

    final result = await showModalBottomSheet<_QuickAddEventResult>(
      context: context,
      isScrollControlled: true,
      showDragHandle: true,
      builder: (ctx) => _QuickAddEventSheet(
        initialDay: day,
        initialStartTime: initialStartTime,
        initialEndTime: initialEndTime,
      ),
    );

    if (result == null || !mounted) return;

    final newEvent = EventModel(
      id: const Uuid().v4(),
      title: result.title,
      startTime: result.start,
      endTime: result.end,
      source: 'manual',
      isFixed: true,
      description: result.description,
    );
    setState(() => _fixedEvents.add(newEvent));
    await _persistManualEvents();
    _scheduleStore.setExternalBusy(_allEvents());
    _habitStore.setCalendarEvents(_allEvents());
    await _habitStore.rescheduleForNewEvent(
      newEvent: newEvent,
      weekStart: _startOfWeek(_focusedDay),
    );
    if (mounted) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Event added to your calendar.')),
      );
    }
  }

  void _openHabitSessionSheet(HabitSessionModel session) {
    showModalBottomSheet<void>(
      context: context,
      showDragHandle: true,
      builder: (ctx) => Padding(
        padding: const EdgeInsets.fromLTRB(24, 0, 24, 32),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Text(
              session.habitTitle,
              style: Theme.of(ctx).textTheme.titleLarge,
            ),
            const SizedBox(height: AppTokens.space8),
            Text(
              '${DateFormat('EEE h:mm a').format(session.startTime)} – '
              '${DateFormat('h:mm a').format(session.endTime)}',
              style: Theme.of(ctx).textTheme.bodyMedium,
            ),
            if (session.explanation.isNotEmpty) ...[
              const SizedBox(height: AppTokens.space12),
              Text(
                session.explanation,
                style: Theme.of(ctx).textTheme.bodySmall,
              ),
            ],
            const SizedBox(height: AppTokens.space8),
            Text(
              'Flexible habit — moves when conflicts occur.',
              style: Theme.of(ctx).textTheme.bodySmall?.copyWith(
                    color: Theme.of(ctx).colorScheme.onSurfaceVariant,
                  ),
            ),
          ],
        ),
      ),
    );
  }

  void _onGridHabitSessionTimeChanged(
    HabitSessionModel session,
    DateTime start,
    DateTime end,
  ) {
    _habitStore.updateSessionTimes(id: session.id, start: start, end: end);
  }

  Widget _buildMainPanel({
    required CalendarLayoutInfo layout,
    required bool showMenuButton,
    VoidCallback? onOpenCalendarSidebar,
  }) {
    return _CalendarMainPanel(
      toolbarTitle: _toolbarTitle(),
      layout: layout,
      weekNavDirection: _weekNavDirection,
      viewMode: _viewMode,
      onViewModeChanged: _setViewMode,
      aiChatOpen: _calendarChatOpen,
      onToggleAiChat: _toggleAiChat,
      showMenuButton: showMenuButton,
      onOpenMenu: () {
        onOpenCalendarSidebar?.call();
        CalendarShellBridge.instance.openDrawer?.call();
      },
      onNew: _openQuickAddSheet,
      onPrev: () => _shiftPeriod(-1),
      onNext: () => _shiftPeriod(1),
      onToday: _goToday,
      onOpenIcal: _openIcalFeedsSheet,
      onOpenCourseImport: _openCourseImportSheet,
      onSuggestSchedule: _runSuggestSchedule,
      calendarSidebarOpen: _calendarSidebarOpen,
      onToggleCalendarSidebar: layout.size == CalendarLayoutSize.expanded
          ? _toggleCalendarSidebar
          : null,
      resolveEventColor: _colorForEvent,
      isLockedEvent: _isLockedEvent,
      focusedDay: _focusedDay,
      selectedDay: _selectedDay,
      monthFormat: _monthFormat,
      onMonthFormatChanged: (f) => setState(() => _monthFormat = f),
      onDaySelected: _onDaySelected,
      onPageChanged: (d) => setState(() => _focusedDay = d),
      timedEventsOnDay: _timedEventsOnDay,
      canvasOnDay: _canvasChipsOnDay,
      courseAllDayOnDay: _courseAllDayOnDay,
      manualTasksOnDay: _manualTasksOnDay,
      blocksOnDay: _blocksOnDay,
      habitSessionsOnDay: _habitSessionsOnDay,
      visibleDays: _visibleDays(),
      viewModeEnum: _viewMode,
      firstHour: _firstHour,
      lastHour: _lastHour,
      hourHeight: _hourHeight,
      timeScrollController: _timeScrollController,
      onOpenEvent: _openEventDetail,
      onOpenCalendarEntry: _openCalendarEntry,
      onTapBlock: _openBlockSheet,
      onTapHabitSession: _openHabitSessionSheet,
      onEventTimeChanged: _onGridEventTimeChanged,
      onBlockTimeChanged: _onGridBlockTimeChanged,
      onHabitSessionTimeChanged: _onGridHabitSessionTimeChanged,
      onEmptySlotTap: (day, start) => _openQuickAddSheet(
        initialDay: day,
        initialStartTime: TimeOfDay.fromDateTime(start),
        initialEndTime: TimeOfDay.fromDateTime(
          start.add(const Duration(hours: 1)),
        ),
      ),
      eventsForDay: _eventsForDay,
    );
  }

  static const _calendarChatChips = SynctraChatConstants.suggestionChips;

  void _toggleAiChat() {
    setState(() => _calendarChatOpen = !_calendarChatOpen);
  }

  void _toggleCalendarSidebar() {
    setState(() => _calendarSidebarOpen = !_calendarSidebarOpen);
  }

  void _openCalendarSidebar() {
    final layout = CalendarLayoutInfo(width: MediaQuery.sizeOf(context).width);
    if (layout.size == CalendarLayoutSize.expanded) {
      setState(() => _calendarSidebarOpen = true);
    } else {
      _scaffoldKey.currentState?.openDrawer();
    }
  }

  void _closeAiChat() {
    if (_calendarChatOpen) setState(() => _calendarChatOpen = false);
  }

  Widget _buildCalendarSidebar() {
    return CalendarLeftSidebar(
      focusedDay: _focusedDay,
      selectedDay: _selectedDay,
      onDaySelected: _onDaySelected,
      onPageChanged: (d) => setState(() => _focusedDay = d),
      upcoming: _upcomingItems(),
      feedChips: _feedChipData(),
      onUpcomingTap: _navigateToDay,
      onFeedToggle: _toggleFeedVisibility,
    );
  }

  Widget _buildMobileChatOverlay(CalendarLayoutInfo layout, Widget body) {
    if (!_calendarChatOpen || layout.showRightPanelDocked) return body;

    final screenH = MediaQuery.sizeOf(context).height;
    final sheetHeight = math.min(screenH * 0.55, math.max(300.0, screenH - 220));
    final scheme = Theme.of(context).colorScheme;

    return Stack(
      fit: StackFit.expand,
      clipBehavior: Clip.hardEdge,
      children: [
        body,
        Positioned.fill(
          child: Column(
            children: [
              Expanded(
                child: GestureDetector(
                  onTap: _closeAiChat,
                  behavior: HitTestBehavior.opaque,
                  child: ColoredBox(
                    color: scheme.shadow.withValues(alpha: 0.18),
                  ),
                ),
              ),
              Material(
                elevation: 0,
                color: scheme.surface,
                borderRadius: const BorderRadius.vertical(
                  top: Radius.circular(AppTokens.radiusLg),
                ),
                clipBehavior: Clip.antiAlias,
                child: SizedBox(
                  height: sheetHeight,
                  width: double.infinity,
                  child: _CalendarChatSidePanel(
                    onClose: _closeAiChat,
                    suggestionChips: _calendarChatChips,
                  ),
                ),
              ),
            ],
          ),
        ),
      ],
    );
  }

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;

    return ResponsiveLayout(
      builder: (context, layout) {
        final showShellMenu = layout.isCompact ||
            layout.size == CalendarLayoutSize.medium;
        final canDockSidebar = layout.size == CalendarLayoutSize.expanded;
        final showDockedSidebar = canDockSidebar && _calendarSidebarOpen;
        final chatPanelOpen =
            _calendarChatOpen && layout.showRightPanelDocked;
        final chatPanelInset = chatPanelOpen
            ? AppTokens.calendarRightPanelWidth +
                AppTokens.calendarDividerThickness
            : 0.0;
        final showTodayChip = !_isViewingToday();
        final showAddFab = layout.isCompact && !_calendarChatOpen;

        final mainPanel = _buildMainPanel(
          layout: layout,
          showMenuButton: showShellMenu,
          onOpenCalendarSidebar: canDockSidebar ? null : _openCalendarSidebar,
        );

        Widget content = Row(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            AnimatedContainer(
              duration: AppTokens.calendarPanelAnimation,
              curve: AppTokens.calendarPanelCurve,
              width: showDockedSidebar ? AppTokens.calendarSidebarWidth : 0,
              decoration: showDockedSidebar
                  ? BoxDecoration(
                      border: Border(
                        right: BorderSide(
                          color: AppTokens.calendarDivider(context),
                          width: AppTokens.calendarDividerThickness,
                        ),
                      ),
                    )
                  : null,
              clipBehavior: showDockedSidebar ? Clip.hardEdge : Clip.none,
              child: showDockedSidebar
                  ? _buildCalendarSidebar()
                  : const SizedBox.shrink(),
            ),
            Expanded(child: mainPanel),
            AnimatedContainer(
                  duration: AppTokens.calendarPanelAnimation,
                  curve: AppTokens.calendarPanelCurve,
                  width: chatPanelOpen ? AppTokens.calendarRightPanelWidth : 0,
                  decoration: chatPanelOpen
                      ? BoxDecoration(
                          border: Border(
                            left: BorderSide(
                              color: AppTokens.calendarDivider(context),
                              width: AppTokens.calendarDividerThickness,
                            ),
                          ),
                        )
                      : null,
                  clipBehavior: chatPanelOpen ? Clip.hardEdge : Clip.none,
                  child: chatPanelOpen
                      ? _CalendarChatSidePanel(
                          onClose: _closeAiChat,
                          suggestionChips: _calendarChatChips,
                        )
                      : const SizedBox.shrink(),
                ),
              ],
            );

        content = _buildMobileChatOverlay(layout, content);

        return Scaffold(
          key: _scaffoldKey,
          backgroundColor: AppTokens.calendarGridSurface(context),
          drawer: canDockSidebar
              ? null
              : Drawer(child: _buildCalendarSidebar()),
          body: SafeArea(
            child: Stack(
              clipBehavior: Clip.none,
              children: [
                content,
              if (showTodayChip && layout.isCompact)
                Positioned(
                  left: AppTokens.space16,
                  right: AppTokens.space16,
                  bottom: showAddFab ? 88 : AppTokens.space16,
                  child: Center(
                    child: _TodayReturnChip(
                      label: _todayChipLabel(),
                      onTap: _goToday,
                    ),
                  ),
                ),
              ],
            ),
          ),
          floatingActionButtonLocation: chatPanelInset > 0
              ? _ChatAwareFabLocation(rightInset: chatPanelInset)
              : FloatingActionButtonLocation.endFloat,
          floatingActionButton: showAddFab
              ? FloatingActionButton(
                  heroTag: 'synctra_add_event',
                  onPressed: _openQuickAddSheet,
                  tooltip: 'Add event',
                  child: const Icon(Icons.add),
                )
              : null,
        );
      },
    );
  }
}

class _TodayReturnChip extends StatelessWidget {
  const _TodayReturnChip({
    required this.label,
    required this.onTap,
  });

  final String label;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return Material(
      elevation: 3,
      shadowColor: Colors.black.withValues(alpha: 0.18),
      color: scheme.primaryContainer,
      borderRadius: BorderRadius.circular(24),
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(24),
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
          child: Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              Icon(Icons.today_outlined, size: 18, color: scheme.onPrimaryContainer),
              const SizedBox(width: 8),
              Text(
                label,
                style: TextStyle(
                  color: scheme.onPrimaryContainer,
                  fontWeight: FontWeight.w600,
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

// ── Main panel (toolbar + month or time grid) ───────────────────────────────

class _CalendarMainPanel extends StatelessWidget {
  final String toolbarTitle;
  final CalendarLayoutInfo layout;
  final int weekNavDirection;
  final _CalendarViewMode viewMode;
  final ValueChanged<_CalendarViewMode> onViewModeChanged;
  final bool aiChatOpen;
  final VoidCallback onToggleAiChat;
  final bool showMenuButton;
  final VoidCallback onOpenMenu;
  final VoidCallback onNew;
  final VoidCallback onPrev;
  final VoidCallback onNext;
  final VoidCallback onToday;
  final VoidCallback onOpenIcal;
  final VoidCallback onOpenCourseImport;
  final VoidCallback onSuggestSchedule;
  final bool calendarSidebarOpen;
  final VoidCallback? onToggleCalendarSidebar;
  final Color Function(EventModel) resolveEventColor;
  final bool Function(EventModel) isLockedEvent;
  final DateTime focusedDay;
  final DateTime selectedDay;
  final CalendarFormat monthFormat;
  final ValueChanged<CalendarFormat> onMonthFormatChanged;
  final void Function(DateTime, DateTime) onDaySelected;
  final void Function(DateTime) onPageChanged;
  final List<EventModel> Function(DateTime) timedEventsOnDay;
  final List<EventModel> Function(DateTime) canvasOnDay;
  final List<EventModel> Function(DateTime) courseAllDayOnDay;
  final List<EventModel> Function(DateTime) manualTasksOnDay;
  final List<ScheduleBlockModel> Function(DateTime) blocksOnDay;
  final List<HabitSessionModel> Function(DateTime) habitSessionsOnDay;
  final List<DateTime> visibleDays;
  final _CalendarViewMode viewModeEnum;
  final int firstHour;
  final int lastHour;
  final double hourHeight;
  final ScrollController timeScrollController;
  final void Function(EventModel) onOpenEvent;
  final void Function(Object) onOpenCalendarEntry;
  final void Function(ScheduleBlockModel) onTapBlock;
  final void Function(HabitSessionModel) onTapHabitSession;
  final void Function(EventModel event, DateTime start, DateTime end)
      onEventTimeChanged;
  final void Function(ScheduleBlockModel block, DateTime start, DateTime end)
      onBlockTimeChanged;
  final void Function(HabitSessionModel session, DateTime start, DateTime end)
      onHabitSessionTimeChanged;
  final void Function(DateTime day, DateTime startTime) onEmptySlotTap;
  final List<dynamic> Function(DateTime) eventsForDay;

  const _CalendarMainPanel({
    required this.toolbarTitle,
    required this.layout,
    required this.weekNavDirection,
    required this.viewMode,
    required this.onViewModeChanged,
    required this.aiChatOpen,
    required this.onToggleAiChat,
    required this.showMenuButton,
    required this.onOpenMenu,
    required this.onNew,
    required this.onPrev,
    required this.onNext,
    required this.onToday,
    required this.onOpenIcal,
    required this.onOpenCourseImport,
    required this.onSuggestSchedule,
    required this.calendarSidebarOpen,
    this.onToggleCalendarSidebar,
    required this.resolveEventColor,
    required this.isLockedEvent,
    required this.focusedDay,
    required this.selectedDay,
    required this.monthFormat,
    required this.onMonthFormatChanged,
    required this.onDaySelected,
    required this.onPageChanged,
    required this.timedEventsOnDay,
    required this.canvasOnDay,
    required this.courseAllDayOnDay,
    required this.manualTasksOnDay,
    required this.blocksOnDay,
    required this.habitSessionsOnDay,
    required this.visibleDays,
    required this.viewModeEnum,
    required this.firstHour,
    required this.lastHour,
    required this.hourHeight,
    required this.timeScrollController,
    required this.onOpenEvent,
    required this.onOpenCalendarEntry,
    required this.onTapBlock,
    required this.onTapHabitSession,
    required this.onEventTimeChanged,
    required this.onBlockTimeChanged,
    required this.onHabitSessionTimeChanged,
    required this.onEmptySlotTap,
    required this.eventsForDay,
  });

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final useReclaimTopBar = !layout.isCompact;

    final gridChild = viewMode == _CalendarViewMode.month
        ? _CalendarMonthView(
            focusedDay: focusedDay,
            selectedDay: selectedDay,
            format: monthFormat,
            onDaySelected: onDaySelected,
            onFormatChanged: onMonthFormatChanged,
            onPageChanged: onPageChanged,
            eventsForDay: eventsForDay,
            onOpenCalendarEntry: onOpenCalendarEntry,
          )
        : _WeekDayTimeGrid(
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
            courseAllDayOnDay: courseAllDayOnDay,
            manualTasksOnDay: manualTasksOnDay,
            blocksOnDay: blocksOnDay,
            habitSessionsOnDay: habitSessionsOnDay,
            onOpenEvent: onOpenEvent,
            onTapBlock: onTapBlock,
            onTapHabitSession: onTapHabitSession,
            onEventTimeChanged: onEventTimeChanged,
            onBlockTimeChanged: onBlockTimeChanged,
            onHabitSessionTimeChanged: onHabitSessionTimeChanged,
            onEmptySlotTap: onEmptySlotTap,
            resolveEventColor: resolveEventColor,
            isLockedEvent: isLockedEvent,
          );

    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        if (useReclaimTopBar)
          CalendarTopBar<_CalendarViewMode>(
            dateRangeLabel: toolbarTitle,
            viewMode: viewMode,
            viewSegments: const [
              _CalendarViewMode.day,
              _CalendarViewMode.week,
              _CalendarViewMode.month,
            ],
            viewLabelBuilder: (m) => switch (m) {
              _CalendarViewMode.day => 'Day',
              _CalendarViewMode.week => 'Week',
              _CalendarViewMode.month => 'Month',
            },
            onViewModeChanged: onViewModeChanged,
            onPrev: onPrev,
            onNext: onNext,
            onToday: onToday,
            onNew: onNew,
            aiChatOpen: aiChatOpen,
            onToggleAiChat: onToggleAiChat,
            showMenuButton: showMenuButton,
            onOpenMenu: onOpenMenu,
            calendarSidebarOpen: calendarSidebarOpen,
            onToggleCalendarSidebar: onToggleCalendarSidebar,
            onSuggestSchedule: onSuggestSchedule,
            onOpenIcal: onOpenIcal,
            onOpenCourseImport: onOpenCourseImport,
          )
        else
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
            onOpenCourseImport: onOpenCourseImport,
            onSuggestSchedule: onSuggestSchedule,
          ),
        Expanded(
          child: ColoredBox(
            color: AppTokens.calendarGridSurface(context),
            child: AnimatedSwitcher(
              duration: viewMode == _CalendarViewMode.month
                  ? AppTokens.calendarViewCrossfade
                  : AppTokens.calendarWeekSlideAnimation,
              switchInCurve: AppTokens.calendarWeekSlideCurve,
              switchOutCurve: AppTokens.calendarWeekSlideCurve,
              transitionBuilder: (child, animation) {
                if (viewMode == _CalendarViewMode.month) {
                  return FadeTransition(opacity: animation, child: child);
                }
                final slide = Tween<Offset>(
                  begin: Offset(0.08 * weekNavDirection, 0),
                  end: Offset.zero,
                ).animate(animation);
                return SlideTransition(
                  position: slide,
                  child: FadeTransition(opacity: animation, child: child),
                );
              },
              child: KeyedSubtree(
                key: ValueKey(
                  '${viewMode.name}_${visibleDays.first.millisecondsSinceEpoch}',
                ),
                child: gridChild,
              ),
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
  final VoidCallback onOpenCourseImport;
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
    required this.onOpenCourseImport,
    required this.onSuggestSchedule,
  });

  static const _compactToolbarBreakpoint = 720.0;

  Widget _sidebarMenuButton(BuildContext context) {
    final isDesktop =
        MediaQuery.sizeOf(context).width >= ShellSidebarController.desktopBreakpoint;
    if (!isDesktop) {
      return _compactIconButton(
        context,
        tooltip: 'Navigation menu',
        onPressed: onOpenMenu,
        icon: Icons.menu,
      );
    }
    return ListenableBuilder(
      listenable: ShellSidebarController.instance,
      builder: (context, _) {
        final open = ShellSidebarController.instance.visible;
        return _compactIconButton(
          context,
          tooltip: open ? 'Hide navigation' : 'Show navigation',
          onPressed: onOpenMenu,
          icon: Icons.menu,
        );
      },
    );
  }

  Widget _navCluster(BuildContext context) {
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        if (showMenuButton) _sidebarMenuButton(context),
        _compactIconButton(
          context,
          tooltip: 'Previous',
          onPressed: onPrev,
          icon: Icons.chevron_left,
        ),
        _compactIconButton(
          context,
          tooltip: 'Next',
          onPressed: onNext,
          icon: Icons.chevron_right,
        ),
        TextButton(
          onPressed: onToday,
          style: TextButton.styleFrom(
            visualDensity: VisualDensity.compact,
            padding: const EdgeInsets.symmetric(horizontal: 10),
            minimumSize: const Size(0, 36),
          ),
          child: const Text('Today'),
        ),
      ],
    );
  }

  Widget _viewModeControl(BuildContext context, {required bool iconOnly}) {
    if (iconOnly) {
      return SegmentedButton<_CalendarViewMode>(
        style: const ButtonStyle(
          visualDensity: VisualDensity.compact,
          tapTargetSize: MaterialTapTargetSize.shrinkWrap,
        ),
        segments: const [
          ButtonSegment(
            value: _CalendarViewMode.day,
            icon: Icon(Icons.view_day_outlined, size: 18),
            tooltip: 'Day',
          ),
          ButtonSegment(
            value: _CalendarViewMode.week,
            icon: Icon(Icons.view_week_outlined, size: 18),
            tooltip: 'Week',
          ),
          ButtonSegment(
            value: _CalendarViewMode.month,
            icon: Icon(Icons.calendar_view_month_outlined, size: 18),
            tooltip: 'Month',
          ),
        ],
        selected: {viewMode},
        onSelectionChanged: (s) => onViewModeChanged(s.first),
      );
    }
    return SegmentedButton<_CalendarViewMode>(
      style: const ButtonStyle(visualDensity: VisualDensity.compact),
      segments: const [
        ButtonSegment(value: _CalendarViewMode.day, label: Text('Day')),
        ButtonSegment(value: _CalendarViewMode.week, label: Text('Week')),
        ButtonSegment(value: _CalendarViewMode.month, label: Text('Month')),
      ],
      selected: {viewMode},
      onSelectionChanged: (s) => onViewModeChanged(s.first),
    );
  }

  Widget _compactIconButton(
    BuildContext context, {
    required String tooltip,
    required VoidCallback onPressed,
    required IconData icon,
  }) {
    return IconButton(
      tooltip: tooltip,
      onPressed: onPressed,
      visualDensity: VisualDensity.compact,
      padding: EdgeInsets.zero,
      constraints: const BoxConstraints(minWidth: 40, minHeight: 40),
      icon: Icon(icon, size: 22),
    );
  }

  List<Widget> _actionIconButtons(BuildContext context) {
    return [
      _compactIconButton(
        context,
        tooltip: 'Auto-fill study blocks this week',
        onPressed: onSuggestSchedule,
        icon: Icons.view_timeline_outlined,
      ),
      _compactIconButton(
        context,
        tooltip: 'iCal feeds',
        onPressed: onOpenIcal,
        icon: Icons.link_outlined,
      ),
      _compactIconButton(
        context,
        tooltip: 'Course import',
        onPressed: onOpenCourseImport,
        icon: Icons.school_outlined,
      ),
      _compactIconButton(
        context,
        tooltip: 'Account & settings',
        onPressed: () => context.push('/settings'),
        icon: Icons.person_outline,
      ),
    ];
  }

  Widget _overflowMenu(BuildContext context) {
    return PopupMenuButton<_ToolbarMenuAction>(
      tooltip: 'More calendar actions',
      icon: const Icon(Icons.more_horiz),
      padding: EdgeInsets.zero,
      constraints: const BoxConstraints(minWidth: 40, minHeight: 40),
      onSelected: (action) {
        switch (action) {
          case _ToolbarMenuAction.schedule:
            onSuggestSchedule();
          case _ToolbarMenuAction.ical:
            onOpenIcal();
          case _ToolbarMenuAction.course:
            onOpenCourseImport();
          case _ToolbarMenuAction.settings:
            context.push('/settings');
        }
      },
      itemBuilder: (context) => const [
        PopupMenuItem(
          value: _ToolbarMenuAction.schedule,
          child: ListTile(
            dense: true,
            leading: Icon(Icons.view_timeline_outlined),
            title: Text('Auto-schedule week'),
            subtitle: Text('Fill study blocks automatically'),
            contentPadding: EdgeInsets.zero,
          ),
        ),
        PopupMenuItem(
          value: _ToolbarMenuAction.ical,
          child: ListTile(
            dense: true,
            leading: Icon(Icons.link_outlined),
            title: Text('iCal feeds'),
            contentPadding: EdgeInsets.zero,
          ),
        ),
        PopupMenuItem(
          value: _ToolbarMenuAction.course,
          child: ListTile(
            dense: true,
            leading: Icon(Icons.school_outlined),
            title: Text('Course import'),
            contentPadding: EdgeInsets.zero,
          ),
        ),
        PopupMenuItem(
          value: _ToolbarMenuAction.settings,
          child: ListTile(
            dense: true,
            leading: Icon(Icons.person_outline),
            title: Text('Settings'),
            contentPadding: EdgeInsets.zero,
          ),
        ),
      ],
    );
  }

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
        padding: const EdgeInsets.fromLTRB(8, 6, 8, 8),
        decoration: BoxDecoration(
          border: Border(
            bottom: BorderSide(
              color: scheme.outlineVariant.withValues(alpha: 0.6),
            ),
          ),
        ),
        child: LayoutBuilder(
          builder: (context, constraints) {
            final compact = constraints.maxWidth < _compactToolbarBreakpoint;
            final useOverflowMenu = constraints.maxWidth < 400;

            final syncIt = Padding(
              padding: const EdgeInsets.only(left: 4),
              child: SyncItLaunchButton(
                isOpen: aiChatOpen,
                onPressed: onToggleAiChat,
                compact: compact,
              ),
            );

            if (!compact) {
              return Row(
                children: [
                  _navCluster(context),
                  const SizedBox(width: 4),
                  Expanded(
                    child: Text(
                      title,
                      style: textTheme.titleMedium?.copyWith(
                        fontWeight: FontWeight.w500,
                      ),
                      overflow: TextOverflow.ellipsis,
                      maxLines: 1,
                    ),
                  ),
                  const SizedBox(width: 8),
                  _viewModeControl(context, iconOnly: false),
                  const SizedBox(width: 4),
                  ..._actionIconButtons(context),
                  syncIt,
                ],
              );
            }

            final actions = useOverflowMenu
                ? [_overflowMenu(context)]
                : _actionIconButtons(context);

            return Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              mainAxisSize: MainAxisSize.min,
              children: [
                Row(
                  children: [
                    _navCluster(context),
                    const Spacer(),
                    syncIt,
                  ],
                ),
                const SizedBox(height: 4),
                Text(
                  title,
                  style: textTheme.titleMedium?.copyWith(
                    fontWeight: FontWeight.w600,
                    height: 1.25,
                  ),
                  maxLines: 2,
                  softWrap: true,
                ),
                const SizedBox(height: 8),
                Row(
                  children: [
                    _viewModeControl(context, iconOnly: true),
                    const Spacer(),
                    ...actions,
                  ],
                ),
              ],
            );
          },
        ),
      ),
    );
  }
}

enum _ToolbarMenuAction { schedule, ical, course, settings }

// ── Month view: calendar grid + selected-day agenda ───────────────────────────

class _DayAgendaItem {
  final Object source;
  final DateTime sortTime;
  final String title;
  final String timeLabel;
  final String typeLabel;
  final Color accent;
  final Color accentSurface;

  const _DayAgendaItem({
    required this.source,
    required this.sortTime,
    required this.title,
    required this.timeLabel,
    required this.typeLabel,
    required this.accent,
    required this.accentSurface,
  });

  factory _DayAgendaItem.fromEvent(EventModel event, {DateTime? viewDay}) {
    final (title, course) = _chipTitleParts(event.title);
    final displayTitle =
        course != null ? '$course · $title' : title.trim();

    final accent = switch (event.source) {
      'canvas' => AppColors.canvasAssignment,
      'course' => AppColors.deadline,
      'manual_task' => AppColors.manualTask,
      'manual' => AppColors.fixedEvent,
      _ when event.source.startsWith('ical') => AppColors.icalAccent,
      _ => AppColors.primary,
    };

    final typeLabel = switch (event.source) {
      'canvas' => 'Canvas',
      'course' => 'Course',
      'manual_task' => 'Your task',
      'manual' => 'Event',
      _ when event.source.startsWith('ical') => 'iCal',
      _ => 'Calendar',
    };

    String timeLabel;
    if (event.isManualTask) {
      timeLabel = manualTaskDayLabel(
        viewDay: viewDay ?? event.endTime,
        rangeStart: event.startTime,
        rangeEnd: event.endTime,
      );
    } else if (event.isDateOnlyCourseEvent || event.isCourseAssignment) {
      timeLabel = viewDay != null && isSameDay(event.startTime, viewDay)
          ? 'Due today'
          : 'Due ${DateFormat('MMM d').format(event.startTime)}';
    } else {
      final end = event.endTime;
      timeLabel = end.isAfter(event.startTime)
          ? '${DateFormat('h:mm a').format(event.startTime)} – ${DateFormat('h:mm a').format(end)}'
          : DateFormat('h:mm a').format(event.startTime);
    }

    return _DayAgendaItem(
      source: event,
      sortTime: event.startTime,
      title: displayTitle,
      timeLabel: timeLabel,
      typeLabel: typeLabel,
      accent: accent,
      accentSurface: accent.withValues(alpha: 0.12),
    );
  }

  factory _DayAgendaItem.fromBlock(ScheduleBlockModel block) {
    final end = block.endTime;
    final timeLabel = end.isAfter(block.startTime)
        ? '${DateFormat('h:mm a').format(block.startTime)} – ${DateFormat('h:mm a').format(end)}'
        : DateFormat('h:mm a').format(block.startTime);

    return _DayAgendaItem(
      source: block,
      sortTime: block.startTime,
      title: block.taskTitle,
      timeLabel: timeLabel,
      typeLabel: 'Study block',
      accent: AppColors.aiStudyBlock,
      accentSurface: AppColors.aiStudyBlock.withValues(alpha: 0.12),
    );
  }
}

class _CalendarMonthView extends StatelessWidget {
  static const _desktopFormatBreakpoint = 1000.0;

  final DateTime focusedDay;
  final DateTime selectedDay;
  final CalendarFormat format;
  final void Function(DateTime, DateTime) onDaySelected;
  final void Function(CalendarFormat) onFormatChanged;
  final void Function(DateTime) onPageChanged;
  final List<dynamic> Function(DateTime) eventsForDay;
  final void Function(Object) onOpenCalendarEntry;

  const _CalendarMonthView({
    required this.focusedDay,
    required this.selectedDay,
    required this.format,
    required this.onDaySelected,
    required this.onFormatChanged,
    required this.onPageChanged,
    required this.eventsForDay,
    required this.onOpenCalendarEntry,
  });

  List<_DayAgendaItem> _itemsForSelectedDay() {
    final day = DateTime(
      selectedDay.year,
      selectedDay.month,
      selectedDay.day,
    );
    final items = <_DayAgendaItem>[];
    for (final raw in eventsForDay(day)) {
      if (raw is EventModel) {
        items.add(_DayAgendaItem.fromEvent(raw, viewDay: day));
      } else if (raw is ScheduleBlockModel) {
        items.add(_DayAgendaItem.fromBlock(raw));
      }
    }
    items.sort((a, b) => a.sortTime.compareTo(b.sortTime));
    return items;
  }

  String _selectedDayHeading(DateTime day) {
    final today = DateTime.now();
    final todayOnly = DateTime(today.year, today.month, today.day);
    final selectedOnly = DateTime(day.year, day.month, day.day);
    final diff = selectedOnly.difference(todayOnly).inDays;
    if (diff == 0) return 'Today';
    if (diff == 1) return 'Tomorrow';
    if (diff == -1) return 'Yesterday';
    return DateFormat('EEEE').format(day);
  }

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final textTheme = Theme.of(context).textTheme;
    final items = _itemsForSelectedDay();
    final bottomInset = MediaQuery.paddingOf(context).bottom + 88;
    final heading = _selectedDayHeading(selectedDay);
    final dateLine = DateFormat('MMMM d, yyyy').format(selectedDay);
    final isDesktop =
        MediaQuery.sizeOf(context).width >= _desktopFormatBreakpoint;
    final calendarFormat = isDesktop ? format : CalendarFormat.month;

    return CustomScrollView(
      slivers: [
        SliverToBoxAdapter(
          child: Padding(
            padding: const EdgeInsets.fromLTRB(12, 4, 12, 10),
            child: DecoratedBox(
              decoration: BoxDecoration(
                color: scheme.surface,
                borderRadius: BorderRadius.circular(16),
                border: Border.all(
                  color: scheme.outlineVariant.withValues(alpha: 0.55),
                ),
              ),
              child: ClipRRect(
                borderRadius: BorderRadius.circular(16),
                child: _MonthTableCalendar(
                  focusedDay: focusedDay,
                  selectedDay: selectedDay,
                  format: calendarFormat,
                  showFormatButton: isDesktop,
                  onDaySelected: onDaySelected,
                  onFormatChanged: onFormatChanged,
                  onPageChanged: onPageChanged,
                  eventLoader: eventsForDay,
                ),
              ),
            ),
          ),
        ),
        SliverToBoxAdapter(
          child: Padding(
            padding: const EdgeInsets.fromLTRB(16, 4, 16, 10),
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.end,
              children: [
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        heading,
                        style: textTheme.titleMedium?.copyWith(
                          fontWeight: FontWeight.w700,
                          letterSpacing: -0.3,
                        ),
                      ),
                      const SizedBox(height: 2),
                      Text(
                        dateLine,
                        style: textTheme.bodySmall?.copyWith(
                          color: scheme.onSurfaceVariant,
                        ),
                      ),
                    ],
                  ),
                ),
                Container(
                  padding:
                      const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
                  decoration: BoxDecoration(
                    color: scheme.primary.withValues(alpha: 0.12),
                    borderRadius: BorderRadius.circular(20),
                  ),
                  child: Text(
                    items.isEmpty
                        ? 'Free day'
                        : '${items.length} ${items.length == 1 ? 'item' : 'items'}',
                    style: textTheme.labelMedium?.copyWith(
                      color: scheme.primary,
                      fontWeight: FontWeight.w600,
                    ),
                  ),
                ),
              ],
            ),
          ),
        ),
        if (items.isEmpty)
          SliverToBoxAdapter(
            child: Padding(
              padding: const EdgeInsets.fromLTRB(16, 0, 16, 16),
              child: Container(
                width: double.infinity,
                padding: const EdgeInsets.symmetric(vertical: 28, horizontal: 20),
                decoration: BoxDecoration(
                  color: scheme.surfaceContainerHighest.withValues(alpha: 0.45),
                  borderRadius: BorderRadius.circular(14),
                  border: Border.all(
                    color: scheme.outlineVariant.withValues(alpha: 0.5),
                  ),
                ),
                child: Column(
                  children: [
                    Icon(
                      Icons.event_available_outlined,
                      size: 32,
                      color: scheme.onSurfaceVariant.withValues(alpha: 0.7),
                    ),
                    const SizedBox(height: 10),
                    Text(
                      'Nothing scheduled',
                      style: textTheme.titleSmall?.copyWith(
                        fontWeight: FontWeight.w600,
                      ),
                    ),
                    const SizedBox(height: 4),
                    Text(
                      'Tap another day or use + to add an event.',
                      textAlign: TextAlign.center,
                      style: textTheme.bodySmall?.copyWith(
                        color: scheme.onSurfaceVariant,
                      ),
                    ),
                  ],
                ),
              ),
            ),
          )
        else
          SliverPadding(
            padding: const EdgeInsets.symmetric(horizontal: 12),
            sliver: SliverList(
              delegate: SliverChildBuilderDelegate(
                (context, i) {
                  final item = items[i];
                  return Padding(
                    padding: const EdgeInsets.only(bottom: 10),
                    child: _MonthDayAgendaCard(
                      item: item,
                      onTap: () => onOpenCalendarEntry(item.source),
                    ),
                  );
                },
                childCount: items.length,
              ),
            ),
          ),
        SliverToBoxAdapter(child: SizedBox(height: bottomInset)),
      ],
    );
  }
}

class _MonthDayAgendaCard extends StatelessWidget {
  final _DayAgendaItem item;
  final VoidCallback onTap;

  const _MonthDayAgendaCard({
    required this.item,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final theme = Theme.of(context).textTheme;

    return Material(
      color: item.accentSurface,
      elevation: 0,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(12),
        side: BorderSide(color: item.accent.withValues(alpha: 0.28)),
      ),
      clipBehavior: Clip.antiAlias,
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(12),
        child: IntrinsicHeight(
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Container(width: 4, color: item.accent),
            Expanded(
              child: Padding(
                padding: const EdgeInsets.fromLTRB(12, 10, 12, 10),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Row(
                      children: [
                        Container(
                          padding: const EdgeInsets.symmetric(
                            horizontal: 7,
                            vertical: 2,
                          ),
                          decoration: BoxDecoration(
                            color: item.accent.withValues(alpha: 0.18),
                            borderRadius: BorderRadius.circular(6),
                          ),
                          child: Text(
                            item.typeLabel,
                            style: theme.labelSmall?.copyWith(
                              color: item.accent,
                              fontWeight: FontWeight.w700,
                              fontSize: 10,
                            ),
                          ),
                        ),
                        const Spacer(),
                        Text(
                          item.timeLabel,
                          style: theme.labelSmall?.copyWith(
                            color: scheme.onSurfaceVariant,
                            fontWeight: FontWeight.w500,
                          ),
                        ),
                      ],
                    ),
                    const SizedBox(height: 6),
                    Text(
                      item.title,
                      maxLines: 3,
                      overflow: TextOverflow.ellipsis,
                      style: theme.titleSmall?.copyWith(
                        fontWeight: FontWeight.w600,
                        height: 1.25,
                      ),
                    ),
                  ],
                ),
              ),
            ),
          ],
        ),
        ),
      ),
    );
  }
}

class _QuickAddEventResult {
  final String title;
  final String description;
  final DateTime start;
  final DateTime end;

  const _QuickAddEventResult({
    required this.title,
    required this.description,
    required this.start,
    required this.end,
  });
}

class _QuickEditBlockResult {
  final DateTime start;
  final DateTime end;
  final String description;
  final bool delete;

  const _QuickEditBlockResult({
    required this.start,
    required this.end,
    required this.description,
    this.delete = false,
  });
}

class _QuickAddEventSheet extends StatefulWidget {
  final DateTime initialDay;
  final TimeOfDay? initialStartTime;
  final TimeOfDay? initialEndTime;
  final EventModel? existing;
  final bool canDelete;
  final VoidCallback? onDelete;

  const _QuickAddEventSheet({
    required this.initialDay,
    this.initialStartTime,
    this.initialEndTime,
    this.existing,
    this.canDelete = false,
    this.onDelete,
  });

  @override
  State<_QuickAddEventSheet> createState() => _QuickAddEventSheetState();
}

class _QuickAddEventSheetState extends State<_QuickAddEventSheet> {
  late final TextEditingController _titleCtrl;
  late final TextEditingController _descCtrl;
  late DateTime _day;
  late TimeOfDay _startT;
  late TimeOfDay _endT;

  bool get _isEdit => widget.existing != null;

  @override
  void initState() {
    super.initState();
    final e = widget.existing;
    _titleCtrl = TextEditingController(text: e?.title ?? '');
    _descCtrl = TextEditingController(text: e?.description ?? '');
    if (e != null) {
      _day = DateTime(e.startTime.year, e.startTime.month, e.startTime.day);
      _startT = TimeOfDay.fromDateTime(e.startTime);
      _endT = TimeOfDay.fromDateTime(e.endTime);
    } else {
      _day = widget.initialDay;
      _startT = widget.initialStartTime ?? const TimeOfDay(hour: 14, minute: 0);
      _endT = widget.initialEndTime ?? const TimeOfDay(hour: 15, minute: 0);
    }
  }

  @override
  void dispose() {
    _titleCtrl.dispose();
    _descCtrl.dispose();
    super.dispose();
  }

  Future<void> _pickDay() async {
    final clock = DateTime.now();
    final picked = await showDatePicker(
      context: context,
      initialDate: _day,
      firstDate: DateTime(clock.year - 1),
      lastDate: DateTime(clock.year + 2),
    );
    if (picked != null && mounted) setState(() => _day = picked);
  }

  Future<void> _pickStart() async {
    final picked = await showTimePicker(context: context, initialTime: _startT);
    if (picked != null && mounted) setState(() => _startT = picked);
  }

  Future<void> _pickEnd() async {
    final picked = await showTimePicker(context: context, initialTime: _endT);
    if (picked != null && mounted) setState(() => _endT = picked);
  }

  void _submit() {
    final title = _titleCtrl.text.trim();
    if (title.isEmpty) return;

    final start =
        DateTime(_day.year, _day.month, _day.day, _startT.hour, _startT.minute);
    final end =
        DateTime(_day.year, _day.month, _day.day, _endT.hour, _endT.minute);
    final endResolved =
        end.isAfter(start) ? end : start.add(const Duration(hours: 1));

    Navigator.pop(
      context,
      _QuickAddEventResult(
        title: title,
        description: _descCtrl.text.trim(),
        start: start,
        end: endResolved,
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: EdgeInsets.only(
        left: 20,
        right: 20,
        top: 8,
        bottom: MediaQuery.viewInsetsOf(context).bottom + 20,
      ),
      child: SingleChildScrollView(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Text(
              _isEdit
                  ? (_titleCtrl.text.trim().isEmpty
                      ? 'Event'
                      : _titleCtrl.text.trim())
                  : 'Quick event',
              style: Theme.of(context).textTheme.titleLarge,
            ),
            if (_isEdit) ...[
              const SizedBox(height: 4),
              Text(
                'Tap date or time below to change',
                style: Theme.of(context).textTheme.labelMedium?.copyWith(
                      color: AppColors.textSecondary,
                    ),
              ),
            ],
            const SizedBox(height: 12),
            TextField(
              controller: _titleCtrl,
              decoration: const InputDecoration(
                labelText: 'Title',
                border: OutlineInputBorder(),
              ),
              textCapitalization: TextCapitalization.sentences,
            ),
            const SizedBox(height: 10),
            TextField(
              controller: _descCtrl,
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
              subtitle: Text(DateFormat.yMMMd().format(_day)),
              trailing: const Icon(Icons.chevron_right),
              onTap: _pickDay,
            ),
            ListTile(
              contentPadding: EdgeInsets.zero,
              title: const Text('Starts'),
              subtitle: Text(_startT.format(context)),
              trailing: const Icon(Icons.schedule),
              onTap: _pickStart,
            ),
            ListTile(
              contentPadding: EdgeInsets.zero,
              title: const Text('Ends'),
              subtitle: Text(_endT.format(context)),
              trailing: const Icon(Icons.schedule),
              onTap: _pickEnd,
            ),
            const SizedBox(height: 12),
            FilledButton(
              onPressed: _submit,
              child: Text(_isEdit ? 'Save changes' : 'Add to calendar'),
            ),
            if (_isEdit && widget.canDelete && widget.onDelete != null) ...[
              const SizedBox(height: 8),
              OutlinedButton.icon(
                onPressed: () {
                  Navigator.pop(context);
                  widget.onDelete!();
                },
                icon: Icon(Icons.delete_outline,
                    color: Theme.of(context).colorScheme.error),
                label: Text(
                  'Remove from Synctra',
                  style: TextStyle(color: Theme.of(context).colorScheme.error),
                ),
                style: OutlinedButton.styleFrom(
                  side: BorderSide(
                    color: Theme.of(context)
                        .colorScheme
                        .error
                        .withValues(alpha: 0.5),
                  ),
                ),
              ),
            ],
          ],
        ),
      ),
    );
  }
}

class _QuickEditBlockSheet extends StatefulWidget {
  const _QuickEditBlockSheet({required this.block});

  final ScheduleBlockModel block;

  @override
  State<_QuickEditBlockSheet> createState() => _QuickEditBlockSheetState();
}

class _QuickEditBlockSheetState extends State<_QuickEditBlockSheet> {
  late final TextEditingController _descCtrl;
  late DateTime _day;
  late TimeOfDay _startT;
  late TimeOfDay _endT;

  @override
  void initState() {
    super.initState();
    _descCtrl = TextEditingController(text: widget.block.description);
    _day = DateTime(
      widget.block.startTime.year,
      widget.block.startTime.month,
      widget.block.startTime.day,
    );
    _startT = TimeOfDay.fromDateTime(widget.block.startTime);
    _endT = TimeOfDay.fromDateTime(widget.block.endTime);
  }

  @override
  void dispose() {
    _descCtrl.dispose();
    super.dispose();
  }

  Future<void> _pickDay() async {
    final clock = DateTime.now();
    final picked = await showDatePicker(
      context: context,
      initialDate: _day,
      firstDate: DateTime(clock.year - 1),
      lastDate: DateTime(clock.year + 2),
    );
    if (picked != null && mounted) setState(() => _day = picked);
  }

  Future<void> _pickStart() async {
    final picked = await showTimePicker(context: context, initialTime: _startT);
    if (picked != null && mounted) setState(() => _startT = picked);
  }

  Future<void> _pickEnd() async {
    final picked = await showTimePicker(context: context, initialTime: _endT);
    if (picked != null && mounted) setState(() => _endT = picked);
  }

  void _submit() {
    final start =
        DateTime(_day.year, _day.month, _day.day, _startT.hour, _startT.minute);
    final end =
        DateTime(_day.year, _day.month, _day.day, _endT.hour, _endT.minute);
    final endResolved =
        end.isAfter(start) ? end : start.add(const Duration(hours: 1));

    Navigator.pop(
      context,
      _QuickEditBlockResult(
        start: start,
        end: endResolved,
        description: _descCtrl.text.trim(),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;

    return Padding(
      padding: EdgeInsets.only(
        left: 20,
        right: 20,
        top: 8,
        bottom: MediaQuery.viewInsetsOf(context).bottom + 20,
      ),
      child: SingleChildScrollView(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Text(
              widget.block.taskTitle,
              style: Theme.of(context).textTheme.titleLarge,
            ),
            const SizedBox(height: 4),
            Text(
              widget.block.isAiGenerated ? 'Suggested study block' : 'Study block',
              style: Theme.of(context).textTheme.labelMedium?.copyWith(
                    color: AppColors.textSecondary,
                  ),
            ),
            const SizedBox(height: 12),
            TextField(
              controller: _descCtrl,
              decoration: const InputDecoration(
                labelText: 'Notes (optional)',
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
              subtitle: Text(DateFormat.yMMMd().format(_day)),
              trailing: const Icon(Icons.chevron_right),
              onTap: _pickDay,
            ),
            ListTile(
              contentPadding: EdgeInsets.zero,
              title: const Text('Starts'),
              subtitle: Text(_startT.format(context)),
              trailing: const Icon(Icons.schedule),
              onTap: _pickStart,
            ),
            ListTile(
              contentPadding: EdgeInsets.zero,
              title: const Text('Ends'),
              subtitle: Text(_endT.format(context)),
              trailing: const Icon(Icons.schedule),
              onTap: _pickEnd,
            ),
            const SizedBox(height: 12),
            FilledButton(
              onPressed: _submit,
              child: const Text('Save changes'),
            ),
            const SizedBox(height: 8),
            OutlinedButton.icon(
              onPressed: () => Navigator.pop(
                context,
                _QuickEditBlockResult(
                  start: widget.block.startTime,
                  end: widget.block.endTime,
                  description: widget.block.description,
                  delete: true,
                ),
              ),
              icon: Icon(Icons.delete_outline, color: scheme.error),
              label: Text(
                'Remove block',
                style: TextStyle(color: scheme.error),
              ),
              style: OutlinedButton.styleFrom(
                side: BorderSide(color: scheme.error.withValues(alpha: 0.5)),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

// ── Month view (TableCalendar) ───────────────────────────────────────────────

class _MonthTableCalendar extends StatelessWidget {
  final DateTime focusedDay;
  final DateTime selectedDay;
  final CalendarFormat format;
  final bool showFormatButton;
  final void Function(DateTime, DateTime) onDaySelected;
  final void Function(CalendarFormat) onFormatChanged;
  final void Function(DateTime) onPageChanged;
  final List<dynamic> Function(DateTime) eventLoader;

  const _MonthTableCalendar({
    required this.focusedDay,
    required this.selectedDay,
    required this.format,
    required this.showFormatButton,
    required this.onDaySelected,
    required this.onFormatChanged,
    required this.onPageChanged,
    required this.eventLoader,
  });

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final textTheme = Theme.of(context).textTheme;

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
      startingDayOfWeek: StartingDayOfWeek.sunday,
      sixWeekMonthsEnforced: false,
      rowHeight: 46,
      daysOfWeekHeight: 20,
      calendarStyle: CalendarStyle(
        outsideDaysVisible: false,
        cellMargin: const EdgeInsets.all(3),
        weekendTextStyle: TextStyle(color: scheme.onSurfaceVariant),
        defaultTextStyle: TextStyle(
          color: scheme.onSurface,
          fontWeight: FontWeight.w500,
        ),
        todayDecoration: BoxDecoration(
          color: scheme.surfaceContainerHighest,
          shape: BoxShape.circle,
          border: Border.all(color: scheme.outlineVariant),
        ),
        selectedDecoration: BoxDecoration(
          color: Colors.transparent,
          shape: BoxShape.circle,
          border: Border.all(color: scheme.onSurface, width: 2),
        ),
        selectedTextStyle: TextStyle(
          color: scheme.onSurface,
          fontWeight: FontWeight.w700,
        ),
        todayTextStyle: TextStyle(
          color: scheme.onSurface,
          fontWeight: FontWeight.w600,
        ),
        markersMaxCount: 4,
        markerSize: 5,
        markerMargin: const EdgeInsets.symmetric(horizontal: 0.5),
        markerDecoration: BoxDecoration(
          color: AppColors.secondary,
          shape: BoxShape.circle,
        ),
      ),
      headerStyle: HeaderStyle(
        titleCentered: true,
        formatButtonVisible: showFormatButton,
        formatButtonDecoration: BoxDecoration(
          color: scheme.surfaceContainerHighest,
          borderRadius: BorderRadius.circular(20),
          border: Border.all(color: scheme.outlineVariant),
        ),
        formatButtonTextStyle: (textTheme.labelMedium ?? const TextStyle())
            .copyWith(
          color: scheme.onSurface,
          fontWeight: FontWeight.w600,
        ),
        titleTextStyle: (textTheme.titleSmall ?? const TextStyle()).copyWith(
          fontWeight: FontWeight.w700,
          letterSpacing: -0.2,
        ),
        leftChevronIcon:
            Icon(Icons.chevron_left_rounded, color: scheme.onSurfaceVariant),
        rightChevronIcon:
            Icon(Icons.chevron_right_rounded, color: scheme.onSurfaceVariant),
      ),
    );
  }
}

// ── Week / day time grid ─────────────────────────────────────────────────────

/// Day name + date above each column (aligned with the time grid).
class _WeekDayHeaderRow extends StatelessWidget {
  final List<DateTime> days;

  const _WeekDayHeaderRow({
    required this.days,
  });

  @override
  Widget build(BuildContext context) {
    final brightness = Theme.of(context).brightness;
    final divider = AppTokens.calendarDivider(context);
    final now = DateTime.now();

    return DecoratedBox(
      decoration: BoxDecoration(
        color: Theme.of(context).colorScheme.surface,
        border: Border(
          bottom: BorderSide(
            color: divider,
            width: AppTokens.calendarDividerThickness,
          ),
        ),
      ),
      child: Row(
        children: [
          SizedBox(width: AppTokens.calendarTimeGutterWidth),
          for (final d in days)
            Expanded(
              child: DecoratedBox(
                decoration: BoxDecoration(
                  color: isSameDay(d, now)
                      ? AppTokens.calendarTodayWash(context)
                      : Colors.transparent,
                  border: Border(
                    left: BorderSide(
                      color: divider,
                      width: AppTokens.calendarDividerThickness,
                    ),
                  ),
                ),
                child: Padding(
                  padding: const EdgeInsets.symmetric(vertical: AppTokens.space12),
                  child: Column(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      Text(
                        DateFormat('EEE').format(d),
                        style: CalendarTextStyles.dayHeader(brightness),
                      ),
                      const SizedBox(height: AppTokens.space4),
                      if (isSameDay(d, now))
                        Container(
                          width: 28,
                          height: 28,
                          alignment: Alignment.center,
                          decoration: const BoxDecoration(
                            color: AppColors.primary,
                            shape: BoxShape.circle,
                          ),
                          child: Text(
                            '${d.day}',
                            style: CalendarTextStyles.todayDateInCircle(
                              brightness,
                            ).copyWith(color: Colors.white),
                          ),
                        )
                      else
                        Text(
                          '${d.day}',
                          style: CalendarTextStyles.dayHeader(brightness),
                        ),
                    ],
                  ),
                ),
              ),
            ),
        ],
      ),
    );
  }
}

/// Max side-by-side columns when many events overlap (avoids 1px-wide chips).
const _kMaxOverlapCols = 3;

/// Split "CSE 331 · Quiz 4" into course + assignment for clearer chips.
(String title, String? course) _chipTitleParts(String raw) {
  final parts = raw.split(' · ');
  if (parts.length >= 2) {
    return (parts.sublist(1).join(' · ').trim(), parts.first.trim());
  }
  return (raw.trim(), null);
}

/// Squarer corners on narrow overlap chips (avoids tall "pill/cylinder" look).
BorderRadius timedChipBorderRadius(double width, double height) {
  final r = math.min(3.0, math.min(width, height) * 0.08);
  return BorderRadius.circular(r);
}

/// One timed segment for column packing (events + study blocks).
class _SegLay {
  _SegLay({
    required this.startMin,
    required this.endMin,
    required this.id,
    this.event,
    this.block,
    this.habitSession,
  });

  final int startMin;
  final int endMin;
  final String id;
  final EventModel? event;
  final ScheduleBlockModel? block;
  final HabitSessionModel? habitSession;
  int col = 0;
  /// Columns in this segment's overlap cluster (for side-by-side width).
  int colSpan = 1;
}

class _GridDragSession {
  _GridDragSession({
    required this.id,
    required this.sourceDayIndex,
    required this.startMin,
    required this.endMin,
    required this.heightPx,
    required this.widthPx,
    required this.leftPx,
    required this.accentColor,
    this.flexible = false,
    this.event,
    this.block,
    this.habitSession,
  })  : targetDayIndex = sourceDayIndex,
        targetStartMin = startMin,
        targetEndMin = endMin;

  final String id;
  final int sourceDayIndex;
  final int startMin;
  final int endMin;
  final double heightPx;
  final double widthPx;
  final double leftPx;
  final Color accentColor;
  final bool flexible;
  final EventModel? event;
  final ScheduleBlockModel? block;
  final HabitSessionModel? habitSession;
  int targetDayIndex;
  int targetStartMin;
  int targetEndMin;
  Offset floatLocal = Offset.zero;
  double grabOffsetX = 0;
  double grabOffsetY = 0;

  bool get hasMoved =>
      targetDayIndex != sourceDayIndex ||
      targetStartMin != startMin ||
      targetEndMin != endMin;
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
  final List<EventModel> Function(DateTime) courseAllDayOnDay;
  final List<EventModel> Function(DateTime) manualTasksOnDay;
  final List<ScheduleBlockModel> Function(DateTime) blocksOnDay;
  final List<HabitSessionModel> Function(DateTime) habitSessionsOnDay;
  final void Function(EventModel) onOpenEvent;
  final void Function(ScheduleBlockModel) onTapBlock;
  final void Function(HabitSessionModel) onTapHabitSession;
  final void Function(EventModel event, DateTime start, DateTime end)
      onEventTimeChanged;
  final void Function(ScheduleBlockModel block, DateTime start, DateTime end)
      onBlockTimeChanged;
  final void Function(HabitSessionModel session, DateTime start, DateTime end)
      onHabitSessionTimeChanged;
  final void Function(DateTime day, DateTime startTime) onEmptySlotTap;
  final Color Function(EventModel) resolveEventColor;
  final bool Function(EventModel) isLockedEvent;

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
    required this.courseAllDayOnDay,
    required this.manualTasksOnDay,
    required this.blocksOnDay,
    required this.habitSessionsOnDay,
    required this.onOpenEvent,
    required this.onTapBlock,
    required this.onTapHabitSession,
    required this.onEventTimeChanged,
    required this.onBlockTimeChanged,
    required this.onHabitSessionTimeChanged,
    required this.onEmptySlotTap,
    required this.resolveEventColor,
    required this.isLockedEvent,
  });

  @override
  State<_WeekDayTimeGrid> createState() => _WeekDayTimeGridState();
}

class _WeekDayTimeGridState extends State<_WeekDayTimeGrid> {
  final _gridDaysRowKey = GlobalKey();
  _GridDragSession? _drag;

  double get _gridHeight =>
      (widget.lastHour - widget.firstHour + 1) * widget.hourHeight;

  int get _totalMins => (widget.lastHour - widget.firstHour + 1) * 60;

  static int _snapMin(int minutes) => ((minutes / 15).round() * 15);

  (int, int) _clampDragMinutes(int rawStart, int duration) {
    var ns = _snapMin(rawStart);
    if (ns < 0) ns = 0;
    if (ns > _totalMins - 15) {
      ns = (_totalMins - 15).clamp(0, _totalMins);
    }
    var ne = ns + duration;
    if (ne > _totalMins) {
      ne = _totalMins;
      ns = (ne - duration).clamp(0, ne - 15);
    }
    return (ns, ne);
  }

  void _startDrag(_GridDragSession session, Offset globalPosition) {
    final box = _gridDaysRowKey.currentContext?.findRenderObject() as RenderBox?;
    if (box != null) {
      final local = box.globalToLocal(globalPosition);
      final colW = box.size.width / widget.days.length;
      final blockTop = (session.startMin / 60.0) * widget.hourHeight;
      final blockLeft = session.sourceDayIndex * colW + session.leftPx;
      session.grabOffsetX = local.dx - blockLeft;
      session.grabOffsetY = local.dy - blockTop;
      session.floatLocal = local;
    }
    setState(() => _drag = session);
  }

  void _updateDrag(Offset globalPosition) {
    if (_drag == null) return;
    final box = _gridDaysRowKey.currentContext?.findRenderObject() as RenderBox?;
    if (box == null) return;

    final local = box.globalToLocal(globalPosition);
    final colW = box.size.width / widget.days.length;
    final dayIdx =
        (local.dx / colW).floor().clamp(0, widget.days.length - 1);
    final anchorY =
        (local.dy - _drag!.grabOffsetY).clamp(0.0, box.size.height);
    final rawStart = (anchorY / widget.hourHeight * 60).round();
    final dur = _drag!.endMin - _drag!.startMin;
    final (ns, ne) = _clampDragMinutes(rawStart, dur);

    setState(() {
      _drag!
        ..targetDayIndex = dayIdx
        ..targetStartMin = ns
        ..targetEndMin = ne
        ..floatLocal = local;
    });
  }

  void _cancelDrag() {
    if (_drag == null) return;
    setState(() => _drag = null);
  }

  void _endDrag() {
    final drag = _drag;
    if (drag == null) return;

    final moved = drag.targetDayIndex != drag.sourceDayIndex ||
        drag.targetStartMin != drag.startMin ||
        drag.targetEndMin != drag.endMin;

    setState(() => _drag = null);
    if (!moved || drag.targetEndMin - drag.targetStartMin < 15) return;

    final day = widget.days[drag.targetDayIndex];
    final dayStart =
        DateTime(day.year, day.month, day.day, widget.firstHour);
    final start = dayStart.add(Duration(minutes: drag.targetStartMin));
    final end = dayStart.add(Duration(minutes: drag.targetEndMin));

    if (drag.event != null) {
      widget.onEventTimeChanged(drag.event!, start, end);
    } else if (drag.block != null) {
      widget.onBlockTimeChanged(drag.block!, start, end);
    } else if (drag.habitSession != null) {
      widget.onHabitSessionTimeChanged(drag.habitSession!, start, end);
    }
  }

  void _scheduleWhenVisible(VoidCallback action) {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted) return;
      final route = ModalRoute.of(context);
      if (route != null && !route.isCurrent) return;
      action();
    });
  }

  /// Scroll to the first visible timed event, falling back to ~7:00.
  void _scrollToRelevantTime() {
    final c = widget.scrollController;
    if (!c.hasClients) return;
    final firstEventMinute = _firstTimedEventMinute();
    final raw = firstEventMinute == null
        ? (7 - widget.firstHour) * widget.hourHeight
        : ((firstEventMinute - widget.firstHour * 60 - 45) / 60.0) *
            widget.hourHeight;
    final max = c.position.maxScrollExtent;
    c.jumpTo(raw.clamp(0.0, max));
  }

  int? _firstTimedEventMinute() {
    int? earliest;
    for (final day in widget.days) {
      for (final event in widget.timedEventsOnDay(day)) {
        if (event.isDateOnlyCourseEvent) continue;
        if (!isSameDay(event.startTime, day)) continue;
        final minute = event.startTime.hour * 60 + event.startTime.minute;
        final minVisible = widget.firstHour * 60;
        final maxVisible = (widget.lastHour + 1) * 60;
        if (minute < minVisible || minute >= maxVisible) continue;
        earliest = earliest == null || minute < earliest ? minute : earliest;
      }
    }
    return earliest;
  }

  static String _timedEventSignature(_WeekDayTimeGrid widget) {
    return widget.days
        .map(
          (day) => widget
              .timedEventsOnDay(day)
              .map(
                (event) =>
                    '${event.id}:${event.startTime.toIso8601String()}:${event.endTime.toIso8601String()}',
              )
              .join(','),
        )
        .join('|');
  }

  @override
  void initState() {
    super.initState();
    _scheduleWhenVisible(_scrollToRelevantTime);
  }

  @override
  void didUpdateWidget(covariant _WeekDayTimeGrid oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.days.first != widget.days.first ||
        oldWidget.days.length != widget.days.length ||
        _timedEventSignature(oldWidget) != _timedEventSignature(widget)) {
      _scheduleWhenVisible(_scrollToRelevantTime);
    }
  }

  @override
  Widget build(BuildContext context) {
    final now = DateTime.now();

    return Column(
      children: [
        _WeekDayHeaderRow(
          days: widget.days,
        ),
        _AllDayAssignmentStrip(
          days: widget.days,
          canvasOnDay: widget.canvasOnDay,
          courseAllDayOnDay: widget.courseAllDayOnDay,
          manualTasksOnDay: widget.manualTasksOnDay,
          onOpenEvent: widget.onOpenEvent,
        ),
        Expanded(
          child: Scrollbar(
            controller: widget.scrollController,
            thumbVisibility: true,
            child: SingleChildScrollView(
              controller: widget.scrollController,
              physics: _drag != null
                  ? const NeverScrollableScrollPhysics()
                  : null,
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
                      child: Listener(
                        onPointerMove: _drag != null
                            ? (e) => _updateDrag(e.position)
                            : null,
                        onPointerUp: _drag != null
                            ? (_) => _endDrag()
                            : null,
                        onPointerCancel: _drag != null
                            ? (_) => _cancelDrag()
                            : null,
                        child: Stack(
                          clipBehavior: Clip.none,
                          children: [
                            Row(
                              key: _gridDaysRowKey,
                              children: [
                              for (var i = 0; i < widget.days.length; i++)
                                Expanded(
                                  child: _DayTimeColumn(
                                    day: widget.days[i],
                                    dayIndex: i,
                                    isToday: isSameDay(widget.days[i], now),
                                    firstHour: widget.firstHour,
                                    lastHour: widget.lastHour,
                                    hourHeight: widget.hourHeight,
                                    timedEvents:
                                        widget.timedEventsOnDay(widget.days[i]),
                                    blocks:
                                        widget.blocksOnDay(widget.days[i]),
                                    habitSessions: widget
                                        .habitSessionsOnDay(widget.days[i]),
                                    now: now,
                                    activeDragId: _drag?.id,
                                    blockGridTaps: _drag != null,
                                    onStartDrag: _startDrag,
                                    onUpdateDrag: _updateDrag,
                                    onEndDrag: _endDrag,
                                    onCancelDrag: _cancelDrag,
                                    onOpenEvent: widget.onOpenEvent,
                                    onTapBlock: widget.onTapBlock,
                                    onTapHabitSession: widget.onTapHabitSession,
                                    onEventTimeChanged:
                                        widget.onEventTimeChanged,
                                    onBlockTimeChanged:
                                        widget.onBlockTimeChanged,
                                    onHabitSessionTimeChanged:
                                        widget.onHabitSessionTimeChanged,
                                    onEmptySlotTap: widget.onEmptySlotTap,
                                    resolveEventColor: widget.resolveEventColor,
                                    isLockedEvent: widget.isLockedEvent,
                                  ),
                                ),
                            ],
                          ),
                          if (_drag != null)
                            LayoutBuilder(
                              builder: (context, constraints) {
                                final drag = _drag!;
                                final colW =
                                    constraints.maxWidth / widget.days.length;

                                final sourceLeft =
                                    drag.sourceDayIndex * colW + drag.leftPx;
                                final sourceTop =
                                    (drag.startMin / 60.0) * widget.hourHeight;

                                final snapLeft =
                                    drag.targetDayIndex * colW + drag.leftPx;
                                final snapTop =
                                    (drag.targetStartMin / 60.0) *
                                        widget.hourHeight;

                                final floatLeft =
                                    (drag.floatLocal.dx - drag.grabOffsetX)
                                        .clamp(
                                  0.0,
                                  constraints.maxWidth - drag.widthPx,
                                );
                                final floatTop =
                                    (drag.floatLocal.dy - drag.grabOffsetY)
                                        .clamp(
                                  0.0,
                                  _gridHeight - drag.heightPx,
                                );

                                return Stack(
                                  clipBehavior: Clip.none,
                                  children: [
                                    Positioned(
                                      left: sourceLeft,
                                      top: sourceTop,
                                      width: drag.widthPx,
                                      height: drag.heightPx,
                                      child: _DragSourcePlaceholder(
                                        widthPx: drag.widthPx,
                                        heightPx: drag.heightPx,
                                      ),
                                    ),
                                    if (drag.hasMoved)
                                      Positioned(
                                        left: snapLeft,
                                        top: snapTop,
                                        width: drag.widthPx,
                                        height: drag.heightPx,
                                        child: _DragSnapOutline(
                                          color: drag.accentColor,
                                          heightPx: drag.heightPx,
                                        ),
                                      ),
                                    Positioned(
                                      left: floatLeft,
                                      top: floatTop,
                                      width: drag.widthPx,
                                      height: drag.heightPx,
                                      child: _DragFloatingBlock(
                                        color: drag.accentColor,
                                        heightPx: drag.heightPx,
                                        flexible: drag.flexible,
                                      ),
                                    ),
                                  ],
                                );
                              },
                            ),
                          ],
                        ),
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
  final List<EventModel> Function(DateTime) courseAllDayOnDay;
  final List<EventModel> Function(DateTime) manualTasksOnDay;
  final void Function(EventModel) onOpenEvent;

  const _AllDayAssignmentStrip({
    required this.days,
    required this.canvasOnDay,
    required this.courseAllDayOnDay,
    required this.manualTasksOnDay,
    required this.onOpenEvent,
  });

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final maxChips = days
        .map((d) =>
            canvasOnDay(d).length +
            courseAllDayOnDay(d).length +
            manualTasksOnDay(d).length)
        .fold<int>(0, (a, b) => a > b ? a : b);
    final rowHeight = maxChips == 0 ? 36.0 : 28.0 + maxChips * 26.0;

    final divider = AppTokens.calendarDivider(context);

    return Container(
      decoration: BoxDecoration(
        color: scheme.surface,
        border: Border(
          bottom: BorderSide(
            color: divider,
            width: AppTokens.calendarDividerThickness,
          ),
        ),
      ),
      constraints: BoxConstraints(minHeight: rowHeight.clamp(36, 120)),
      child: Row(
        children: [
          SizedBox(
            width: AppTokens.calendarTimeGutterWidth,
            child: Center(
              child: Text(
                'All-day',
                style: CalendarTextStyles.hourLabel(
                  Theme.of(context).brightness,
                ),
              ),
            ),
          ),
          for (final d in days)
            Expanded(
              child: Container(
                decoration: BoxDecoration(
                  border: Border(
                    left: BorderSide(
                      color: divider,
                      width: AppTokens.calendarDividerThickness,
                    ),
                  ),
                ),
                padding: const EdgeInsets.symmetric(horizontal: 4, vertical: 4),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    for (final a in courseAllDayOnDay(d))
                      Padding(
                        padding: const EdgeInsets.only(bottom: 2),
                        child: _AllDayEventChip(
                          event: a,
                          color: AppColors.deadline,
                          onTap: () => onOpenEvent(a),
                        ),
                      ),
                    for (final a in canvasOnDay(d))
                      Padding(
                        padding: const EdgeInsets.only(bottom: 2),
                        child: _AllDayEventChip(
                          event: a,
                          color: AppColors.canvasAssignment,
                          onTap: () => onOpenEvent(a),
                        ),
                      ),
                    for (final a in manualTasksOnDay(d))
                      Padding(
                        padding: const EdgeInsets.only(bottom: 2),
                        child: _AllDayEventChip(
                          event: a,
                          color: AppColors.manualTask,
                          onTap: () => onOpenEvent(a),
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

class _AllDayEventChip extends StatelessWidget {
  final EventModel event;
  final Color color;
  final VoidCallback onTap;

  const _AllDayEventChip({
    required this.event,
    required this.color,
    required this.onTap,
  });

  String _formatEstimate(int minutes) {
    final hours = minutes ~/ 60;
    final mins = minutes % 60;
    if (hours == 0) return '${mins}m';
    if (mins == 0) return '${hours}h';
    return '${hours}h ${mins}m';
  }

  @override
  Widget build(BuildContext context) {
    final estimate = event.estimatedMinutes;
    final (title, course) = _chipTitleParts(event.title);
    final compactLabel =
        course != null ? '$course · $title' : title;

    return Material(
      color: color.withValues(alpha: 0.14),
      borderRadius: BorderRadius.circular(8),
      elevation: 1,
      shadowColor: Colors.black.withValues(alpha: 0.06),
      clipBehavior: Clip.antiAlias,
      child: InkWell(
        onTap: onTap,
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 4, vertical: 4),
          child: LayoutBuilder(
            builder: (context, constraints) {
              final w = constraints.maxWidth;
              final showBar = w >= 36;
              final showEstimate = estimate != null && w >= 88;
              final showStackedCourse = course != null && w >= 64 && !showEstimate;

              final titleStyle =
                  Theme.of(context).textTheme.labelSmall?.copyWith(
                        color: color,
                        fontWeight: FontWeight.w600,
                        height: 1.15,
                      );
              final courseStyle =
                  Theme.of(context).textTheme.labelSmall?.copyWith(
                        color: color.withValues(alpha: 0.85),
                        fontSize: 10,
                        height: 1.1,
                      );

              return Row(
                children: [
                  if (showBar) ...[
                    Container(
                      width: 3,
                      height: 14,
                      decoration: BoxDecoration(
                        color: color,
                        borderRadius: BorderRadius.circular(999),
                      ),
                    ),
                    SizedBox(width: showEstimate ? 5 : 3),
                  ],
                  Expanded(
                    child: showStackedCourse
                        ? Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            mainAxisSize: MainAxisSize.min,
                            children: [
                              Text(
                                course,
                                maxLines: 1,
                                overflow: TextOverflow.ellipsis,
                                style: courseStyle,
                              ),
                              Text(
                                title,
                                maxLines: 1,
                                overflow: TextOverflow.ellipsis,
                                style: titleStyle,
                              ),
                            ],
                          )
                        : Text(
                            compactLabel,
                            maxLines: 1,
                            overflow: TextOverflow.ellipsis,
                            style: titleStyle,
                          ),
                  ),
                  if (showEstimate) ...[
                    const SizedBox(width: 4),
                    Flexible(
                      child: Text(
                        _formatEstimate(estimate),
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: Theme.of(context).textTheme.labelSmall?.copyWith(
                              color: color.withValues(alpha: 0.88),
                              fontWeight: FontWeight.w700,
                            ),
                      ),
                    ),
                  ],
                ],
              );
            },
          ),
        ),
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
    final brightness = Theme.of(context).brightness;
    return SizedBox(
      width: AppTokens.calendarTimeGutterWidth,
      child: Column(
        children: [
          for (int h = firstHour; h <= lastHour; h++)
            SizedBox(
              height: hourHeight,
              child: Align(
                alignment: Alignment.topRight,
                child: Padding(
                  padding: const EdgeInsets.only(
                    right: AppTokens.space8,
                    top: 0,
                  ),
                  child: Text(
                    DateFormat('ha').format(DateTime(2020, 1, 1, h)),
                    style: CalendarTextStyles.hourLabel(brightness),
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
  final int dayIndex;
  final bool isToday;
  final int firstHour;
  final int lastHour;
  final double hourHeight;
  final List<EventModel> timedEvents;
  final List<ScheduleBlockModel> blocks;
  final List<HabitSessionModel> habitSessions;
  final DateTime now;
  final String? activeDragId;
  final bool blockGridTaps;
  final void Function(_GridDragSession session, Offset globalPosition)
      onStartDrag;
  final void Function(Offset globalPosition) onUpdateDrag;
  final VoidCallback onEndDrag;
  final VoidCallback onCancelDrag;
  final void Function(EventModel) onOpenEvent;
  final void Function(ScheduleBlockModel) onTapBlock;
  final void Function(HabitSessionModel) onTapHabitSession;
  final void Function(EventModel event, DateTime start, DateTime end)
      onEventTimeChanged;
  final void Function(ScheduleBlockModel block, DateTime start, DateTime end)
      onBlockTimeChanged;
  final void Function(HabitSessionModel session, DateTime start, DateTime end)
      onHabitSessionTimeChanged;
  final void Function(DateTime day, DateTime startTime) onEmptySlotTap;
  final Color Function(EventModel) resolveEventColor;
  final bool Function(EventModel) isLockedEvent;

  const _DayTimeColumn({
    required this.day,
    required this.dayIndex,
    required this.isToday,
    required this.firstHour,
    required this.lastHour,
    required this.hourHeight,
    required this.timedEvents,
    required this.blocks,
    required this.habitSessions,
    required this.now,
    required this.activeDragId,
    this.blockGridTaps = false,
    required this.onStartDrag,
    required this.onUpdateDrag,
    required this.onEndDrag,
    required this.onCancelDrag,
    required this.onOpenEvent,
    required this.onTapBlock,
    required this.onTapHabitSession,
    required this.onEventTimeChanged,
    required this.onBlockTimeChanged,
    required this.onHabitSessionTimeChanged,
    required this.onEmptySlotTap,
    required this.resolveEventColor,
    required this.isLockedEvent,
  });

  static int _snapMinutes(int minutes) => ((minutes / 15).round() * 15);

  DateTime _startTimeFromLocalY(double y, int totalMins) {
    final rawMinutes = (y / hourHeight * 60).round();
    final snapped = _snapMinutes(rawMinutes).clamp(0, totalMins - 15);
    return DateTime(
      day.year,
      day.month,
      day.day,
      firstHour + snapped ~/ 60,
      snapped % 60,
    );
  }

  double _minutesFromStart(DateTime dt) {
    final start = DateTime(dt.year, dt.month, dt.day, firstHour);
    return dt.difference(start).inMinutes.toDouble();
  }

  int _wallClockMinutesFromGridStart(DateTime dt) {
    return dt.hour * 60 + dt.minute - firstHour * 60;
  }

  static bool _segmentsOverlap(_SegLay a, _SegLay b) =>
      a.startMin < b.endMin && b.startMin < a.endMin;

  /// Assign columns so time-overlapping chips sit side-by-side (Google Cal style).
  static List<_SegLay> _packSegments(List<_SegLay> raw) {
    if (raw.isEmpty) return raw;
    raw.sort((a, b) {
      final c = a.startMin.compareTo(b.startMin);
      if (c != 0) return c;
      return (b.endMin - b.startMin).compareTo(a.endMin - a.startMin);
    });

    final columns = <List<_SegLay>>[];
    for (final seg in raw) {
      var placed = false;
      for (var col = 0; col < columns.length; col++) {
        final canPlace =
            columns[col].every((other) => !_segmentsOverlap(other, seg));
        if (canPlace) {
          columns[col].add(seg);
          seg.col = col;
          placed = true;
          break;
        }
      }
      if (!placed) {
        seg.col = columns.length;
        columns.add([seg]);
      }
    }

    for (final seg in raw) {
      final cluster =
          raw.where((other) => _segmentsOverlap(other, seg)).toList();
      final span = cluster.isEmpty
          ? 1
          : cluster.map((s) => s.col).reduce(math.max) + 1;
      seg.colSpan = math.max(1, math.min(span, _kMaxOverlapCols));
    }

    // Exact same start/end (e.g. Lunch + Gym both 12:45–1:45) → force columns.
    final bySlot = <String, List<_SegLay>>{};
    for (final seg in raw) {
      final key = '${seg.startMin}_${seg.endMin}';
      bySlot.putIfAbsent(key, () => []).add(seg);
    }
    for (final group in bySlot.values) {
      if (group.length < 2) continue;
      group.sort((a, b) => a.id.compareTo(b.id));
      final span = math.min(group.length, _kMaxOverlapCols);
      for (var i = 0; i < group.length; i++) {
        group[i].col = i % span;
        group[i].colSpan = span;
      }
    }
    return raw;
  }

  /// Side-by-side overlap with a readable minimum width; cascades when tight.
  static ({double left, double width}) _sideBySideRect({
    required double pad,
    required double inner,
    required int col,
    required int clusterMaxCols,
  }) {
    if (clusterMaxCols <= 1) {
      return (left: pad, width: inner);
    }
    final cols = math.min(clusterMaxCols, _kMaxOverlapCols);
    const gap = 1.0;
    const minColW = 28.0;
    final evenSplit = (inner - gap * (cols - 1)) / cols;
    final colW = math.max(minColW, evenSplit);
    final colIndex = col.clamp(0, cols - 1);
    final totalNeeded = colW * cols + gap * (cols - 1);
    if (totalNeeded > inner && cols > 1) {
      final step = math.max(10.0, (inner - minColW) / (cols - 1));
      return (
        left: pad + colIndex * step,
        width: math.min(minColW, inner),
      );
    }
    return (
      left: pad + colIndex * (colW + gap),
      width: colW,
    );
  }

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final gridHeight = (lastHour - firstHour + 1) * hourHeight;
    final dayStart = DateTime(day.year, day.month, day.day, firstHour);
    final dayEndExclusive =
        DateTime(day.year, day.month, day.day, lastHour + 1);
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
      var sm = _wallClockMinutesFromGridStart(e.startTime);
      var em = isSameDay(e.endTime, day)
          ? _wallClockMinutesFromGridStart(e.endTime)
          : totalMins;
      if (em <= sm && e.source == 'course') {
        em = sm + 15;
      }
      if (em <= sm) continue;
      sm = sm.clamp(0, totalMins);
      em = em.clamp(0, totalMins);
      if (em <= sm) continue;
      segs.add(_SegLay(startMin: sm, endMin: em, id: 'e_${e.id}', event: e));
    }
    for (final b in blocks) {
      var sm = _wallClockMinutesFromGridStart(b.startTime);
      var em = isSameDay(b.endTime, day)
          ? _wallClockMinutesFromGridStart(b.endTime)
          : totalMins;
      if (em <= sm) continue;
      sm = sm.clamp(0, totalMins);
      em = em.clamp(0, totalMins);
      if (em <= sm) continue;
      segs.add(_SegLay(startMin: sm, endMin: em, id: 'b_${b.id}', block: b));
    }
    for (final h in habitSessions) {
      var sm = _wallClockMinutesFromGridStart(h.startTime);
      var em = isSameDay(h.endTime, day)
          ? _wallClockMinutesFromGridStart(h.endTime)
          : totalMins;
      if (em <= sm) continue;
      sm = sm.clamp(0, totalMins);
      em = em.clamp(0, totalMins);
      if (em <= sm) continue;
      segs.add(
        _SegLay(
          startMin: sm,
          endMin: em,
          id: 'h_${h.id}',
          habitSession: h,
        ),
      );
    }
    _packSegments(segs);

    final divider = AppTokens.calendarDivider(context);

    return DecoratedBox(
      decoration: BoxDecoration(
        color: isToday
            ? AppTokens.calendarTodayWash(context)
            : AppTokens.calendarGridSurface(context),
        border: Border(
          left: BorderSide(
            color: divider,
            width: AppTokens.calendarDividerThickness,
          ),
        ),
      ),
      child: LayoutBuilder(
        builder: (context, constraints) {
          final w = constraints.maxWidth;
          const pad = AppTokens.space4;
          final inner = (w - pad * 2).clamp(4.0, w);

          return Stack(
            clipBehavior: Clip.hardEdge,
            children: [
              CustomPaint(
                size: Size(w, gridHeight),
                painter: _HourGridPainter(
                  hourLineColor: divider,
                  halfHourLineColor: AppTokens.calendarHalfHourLine(context),
                  firstHour: firstHour,
                  lastHour: lastHour,
                  hourHeight: hourHeight,
                ),
              ),
              Positioned.fill(
                child: IgnorePointer(
                  ignoring: blockGridTaps,
                  child: _GridSlotTapLayer(
                    gridHeight: gridHeight,
                    totalMins: totalMins,
                    enabled: !blockGridTaps,
                    onTapAtY: (y) =>
                        onEmptySlotTap(day, _startTimeFromLocalY(y, totalMins)),
                  ),
                ),
              ),
              ...segs.map(
                (s) => _positionedSeg(
                  context: context,
                  s: s,
                  gridHeight: gridHeight,
                  pad: pad,
                  innerWidth: inner,
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
                        width: AppTokens.space8,
                        height: AppTokens.space8,
                        decoration: const BoxDecoration(
                          color: AppColors.currentTimeLine,
                          shape: BoxShape.circle,
                        ),
                      ),
                      Expanded(
                        child: Container(
                          height: AppTokens.calendarDividerThickness,
                          color: AppColors.currentTimeLine,
                        ),
                      ),
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
    required double innerWidth,
    required int totalMins,
    required DateTime dayStart,
  }) {
    final top = (s.startMin / 60.0) * hourHeight;
    final h = ((s.endMin - s.startMin) / 60.0) * hourHeight;
    if (h <= 0 || top >= gridHeight) return const SizedBox.shrink();
    final topVis = top.clamp(0.0, gridHeight);
    final maxH = (gridHeight - topVis).clamp(0.0, gridHeight);
    const gap = 3.0;
    final span = math.max(1, s.colSpan);
    final colW = innerWidth / span;
    final left = pad + s.col * colW + gap / 2;
    final width = math.max(8.0, colW - gap);

    double chipHeight(double minH) {
      if (maxH <= 0) return 0;
      final capped = math.min(h, maxH);
      if (capped < 4) return 0;
      return math.max(capped, math.min(minH, maxH));
    }

    if (s.event != null) {
      final e = s.event!;
      final color = resolveEventColor(e);
      final locked = isLockedEvent(e);
      final onTap = () => onOpenEvent(e);
      final ht = chipHeight(20);
      if (ht <= 0) return const SizedBox.shrink();
      final canDrag = !locked && e.source != 'synctra_preview';
      final isDragging = activeDragId == s.id;
      if (isDragging) {
        return const SizedBox.shrink();
      }
      final chip = _TimedEventChip(
        event: e,
        color: color,
        onTap: onTap,
        locked: locked,
        hideContent: false,
      );
      return Positioned(
        top: topVis,
        left: left,
        width: width,
        child: _DragTimeChipShell(
          enabled: canDrag,
          widthPx: width,
          heightPx: ht,
          accentColor: color,
          onTap: onTap,
          onDragStart: (pos) => onStartDrag(
            _GridDragSession(
              id: s.id,
              sourceDayIndex: dayIndex,
              startMin: s.startMin,
              endMin: s.endMin,
              heightPx: ht,
              widthPx: width,
              leftPx: left,
              accentColor: color,
              event: e,
            ),
            pos,
          ),
          onDragUpdate: onUpdateDrag,
          onDragEnd: onEndDrag,
          onDragCancel: onCancelDrag,
          child: chip,
        ),
      );
    }
    if (s.block != null) {
      final b = s.block!;
      final bg = b.isAiGenerated
          ? AppColors.aiStudyBlock
          : AppColors.confirmedStudyBlock;
      final ht = chipHeight(24);
      if (ht <= 0) return const SizedBox.shrink();
      final isDragging = activeDragId == s.id;
      if (isDragging) {
        return const SizedBox.shrink();
      }
      final chip = _StudyBlockChip(
        block: b,
        color: bg,
        onTap: () => onTapBlock(b),
        flexible: b.isAiGenerated,
        hideContent: false,
      );
      return Positioned(
        top: topVis,
        left: left,
        width: width,
        child: _DragTimeChipShell(
          enabled: true,
          widthPx: width,
          heightPx: ht,
          accentColor: bg,
          onTap: () => onTapBlock(b),
          onDragStart: (pos) => onStartDrag(
            _GridDragSession(
              id: s.id,
              sourceDayIndex: dayIndex,
              startMin: s.startMin,
              endMin: s.endMin,
              heightPx: ht,
              widthPx: width,
              leftPx: left,
              accentColor: bg,
              flexible: b.isAiGenerated,
              block: b,
            ),
            pos,
          ),
          onDragUpdate: onUpdateDrag,
          onDragEnd: onEndDrag,
          onDragCancel: onCancelDrag,
          child: chip,
        ),
      );
    }
    if (s.habitSession != null) {
      final h = s.habitSession!;
      const bg = AppColors.habitBlock;
      final ht = chipHeight(24);
      if (ht <= 0) return const SizedBox.shrink();
      final isDragging = activeDragId == s.id;
      if (isDragging) {
        return const SizedBox.shrink();
      }
      final chip = _HabitSessionChip(
        session: h,
        onTap: () => onTapHabitSession(h),
        hideContent: false,
      );
      return Positioned(
        top: topVis,
        left: left,
        width: width,
        child: _DragTimeChipShell(
          enabled: true,
          widthPx: width,
          heightPx: ht,
          accentColor: bg,
          onTap: () => onTapHabitSession(h),
          onDragStart: (pos) => onStartDrag(
            _GridDragSession(
              id: s.id,
              sourceDayIndex: dayIndex,
              startMin: s.startMin,
              endMin: s.endMin,
              heightPx: ht,
              widthPx: width,
              leftPx: left,
              accentColor: bg,
              flexible: true,
              habitSession: h,
            ),
            pos,
          ),
          onDragUpdate: onUpdateDrag,
          onDragEnd: onEndDrag,
          onDragCancel: onCancelDrag,
          child: chip,
        ),
      );
    }
    return const SizedBox.shrink();
  }
}

/// Pointer-based drag with movement threshold; preview at week-grid level.
class _DragTimeChipShell extends StatefulWidget {
  const _DragTimeChipShell({
    required this.enabled,
    required this.widthPx,
    required this.heightPx,
    required this.onTap,
    required this.onDragStart,
    required this.onDragUpdate,
    required this.onDragEnd,
    required this.onDragCancel,
    required this.child,
    this.accentColor,
  });

  final bool enabled;
  final double widthPx;
  final double heightPx;
  final VoidCallback onTap;
  final void Function(Offset globalPosition) onDragStart;
  final void Function(Offset globalPosition) onDragUpdate;
  final VoidCallback onDragEnd;
  final VoidCallback onDragCancel;
  final Widget child;
  final Color? accentColor;

  @override
  State<_DragTimeChipShell> createState() => _DragTimeChipShellState();
}

class _DragTimeChipShellState extends State<_DragTimeChipShell> {
  static const _dragThreshold = 8.0;

  Offset? _pointerDown;
  bool _dragging = false;

  @override
  Widget build(BuildContext context) {
    if (!widget.enabled) {
      return SizedBox(
        width: widget.widthPx,
        height: widget.heightPx,
        child: widget.child,
      );
    }

    return Listener(
      behavior: HitTestBehavior.opaque,
      onPointerDown: (event) {
        _pointerDown = event.position;
        _dragging = false;
      },
      onPointerMove: (event) {
        if (_pointerDown == null) return;
        if (!_dragging) {
          if ((event.position - _pointerDown!).distance < _dragThreshold) {
            return;
          }
          _dragging = true;
          widget.onDragStart(event.position);
        }
        widget.onDragUpdate(event.position);
      },
      onPointerUp: (event) {
        if (_dragging) {
          widget.onDragEnd();
        } else if (_pointerDown != null) {
          widget.onTap();
        }
        _pointerDown = null;
        _dragging = false;
      },
      onPointerCancel: (_) {
        if (_dragging) widget.onDragCancel();
        _pointerDown = null;
        _dragging = false;
      },
      child: MouseRegion(
        cursor: SystemMouseCursors.grab,
        child: SizedBox(
          width: widget.widthPx,
          height: widget.heightPx,
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Expanded(child: widget.child),
              DecoratedBox(
                decoration: BoxDecoration(
                  color: Colors.black.withValues(alpha: 0.22),
                  borderRadius: const BorderRadius.horizontal(
                    right: Radius.circular(AppTokens.calendarEventRadius),
                  ),
                ),
                child: const SizedBox(
                  width: 10,
                  child: Center(
                    child: Icon(
                      Icons.drag_indicator,
                      size: 10,
                      color: Colors.white70,
                    ),
                  ),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

/// Dashed drop target shown while dragging an event or study block.
class _DragSourcePlaceholder extends StatelessWidget {
  const _DragSourcePlaceholder({
    required this.widthPx,
    required this.heightPx,
  });

  final double widthPx;
  final double heightPx;

  @override
  Widget build(BuildContext context) {
    return DecoratedBox(
      decoration: BoxDecoration(
        color: AppColors.grey100.withValues(alpha: 0.9),
        borderRadius: BorderRadius.circular(AppTokens.calendarEventRadius),
        border: Border.all(
          color: AppColors.border.withValues(alpha: 0.8),
        ),
      ),
      child: const SizedBox.expand(),
    );
  }
}

class _DragSnapOutline extends StatelessWidget {
  const _DragSnapOutline({
    required this.color,
    required this.heightPx,
  });

  final Color color;
  final double heightPx;

  @override
  Widget build(BuildContext context) {
    return CustomPaint(
      painter: _DashedOutlinePainter(
        color: color.withValues(alpha: 0.7),
        radius: AppTokens.calendarEventRadius,
      ),
      child: DecoratedBox(
        decoration: BoxDecoration(
          borderRadius: BorderRadius.circular(AppTokens.calendarEventRadius),
          color: color.withValues(alpha: 0.08),
        ),
        child: const SizedBox.expand(),
      ),
    );
  }
}

/// Follows the pointer during drag — same size as the original block, no text.
class _DragFloatingBlock extends StatelessWidget {
  const _DragFloatingBlock({
    required this.color,
    required this.heightPx,
    this.flexible = false,
  });

  final Color color;
  final double heightPx;
  final bool flexible;

  @override
  Widget build(BuildContext context) {
    final fill = flexible ? color.withValues(alpha: 0.35) : color.withValues(alpha: 0.88);

    return Material(
      elevation: 8,
      shadowColor: Colors.black.withValues(alpha: 0.3),
      borderRadius: BorderRadius.circular(AppTokens.calendarEventRadius),
      clipBehavior: Clip.antiAlias,
      color: fill,
      child: flexible
          ? CustomPaint(
              painter: _DashedOutlinePainter(
                color: color.withValues(alpha: 0.85),
                radius: AppTokens.calendarEventRadius,
              ),
              child: const SizedBox.expand(),
            )
          : const SizedBox.expand(),
    );
  }
}

class _DashedOutlinePainter extends CustomPainter {
  _DashedOutlinePainter({
    required this.color,
    required this.radius,
  });

  final Color color;
  final double radius;

  @override
  void paint(Canvas canvas, Size size) {
    final paint = Paint()
      ..color = color
      ..style = PaintingStyle.stroke
      ..strokeWidth = 2;

    final rect = Rect.fromLTWH(1, 1, size.width - 2, size.height - 2);
    final path = Path()..addRRect(RRect.fromRectAndRadius(rect, Radius.circular(radius)));

    for (final metric in path.computeMetrics()) {
      const dash = 6.0;
      const gap = 4.0;
      var distance = 0.0;
      while (distance < metric.length) {
        final end = (distance + dash).clamp(0.0, metric.length);
        canvas.drawPath(metric.extractPath(distance, end), paint);
        distance += dash + gap;
      }
    }
  }

  @override
  bool shouldRepaint(covariant _DashedOutlinePainter oldDelegate) =>
      oldDelegate.color != color || oldDelegate.radius != radius;
}

class _GridSlotTapLayer extends StatefulWidget {
  final double gridHeight;
  final int totalMins;
  final void Function(double y) onTapAtY;
  final bool enabled;

  const _GridSlotTapLayer({
    required this.gridHeight,
    required this.totalMins,
    required this.onTapAtY,
    this.enabled = true,
  });

  @override
  State<_GridSlotTapLayer> createState() => _GridSlotTapLayerState();
}

class _GridSlotTapLayerState extends State<_GridSlotTapLayer> {
  double? _hoverY;

  double get _slotHeight => widget.gridHeight / (widget.totalMins / 15);

  double _snapY(double y) {
    final slot = _slotHeight;
    return ((y / slot).floor() * slot).clamp(0.0, widget.gridHeight - slot);
  }

  @override
  Widget build(BuildContext context) {
    if (!widget.enabled) return const SizedBox.expand();

    final hoverY = _hoverY == null ? null : _snapY(_hoverY!);

    return MouseRegion(
      cursor: SystemMouseCursors.click,
      onExit: (_) => setState(() => _hoverY = null),
      onHover: (event) {
        final y = event.localPosition.dy.clamp(0.0, widget.gridHeight);
        if (_hoverY == null || (y - _hoverY!).abs() > 1) {
          setState(() => _hoverY = y);
        }
      },
      child: GestureDetector(
        behavior: HitTestBehavior.translucent,
        onTapUp: (details) {
          final y = details.localPosition.dy.clamp(0.0, widget.gridHeight);
          widget.onTapAtY(y);
        },
        child: Stack(
          children: [
            if (hoverY != null)
              Positioned(
                top: hoverY,
                left: 4,
                right: 4,
                height: _slotHeight,
                child: DecoratedBox(
                  decoration: BoxDecoration(
                    color: AppColors.primary.withValues(alpha: 0.08),
                    borderRadius: BorderRadius.circular(4),
                    border: Border.all(
                      color: AppColors.primary.withValues(alpha: 0.28),
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
  final Color hourLineColor;
  final Color halfHourLineColor;
  final int firstHour;
  final int lastHour;
  final double hourHeight;

  _HourGridPainter({
    required this.hourLineColor,
    required this.halfHourLineColor,
    required this.firstHour,
    required this.lastHour,
    required this.hourHeight,
  });

  @override
  void paint(Canvas canvas, Size size) {
    final hourPaint = Paint()
      ..color = hourLineColor
      ..strokeWidth = AppTokens.calendarDividerThickness;
    final halfPaint = Paint()
      ..color = halfHourLineColor
      ..strokeWidth = AppTokens.calendarDividerThickness;

    final hourCount = lastHour - firstHour + 1;
    for (var i = 0; i <= hourCount; i++) {
      final y = i * hourHeight;
      canvas.drawLine(Offset(0, y), Offset(size.width, y), hourPaint);
    }
    for (var i = 0; i < hourCount; i++) {
      final y = i * hourHeight + hourHeight / 2;
      canvas.drawLine(Offset(0, y), Offset(size.width, y), halfPaint);
    }
  }

  @override
  bool shouldRepaint(covariant _HourGridPainter oldDelegate) =>
      oldDelegate.hourLineColor != hourLineColor ||
      oldDelegate.halfHourLineColor != halfHourLineColor ||
      oldDelegate.hourHeight != hourHeight;
}

class _TimedEventChip extends StatelessWidget {
  final EventModel event;
  final Color color;
  final VoidCallback? onTap;
  final bool locked;
  final bool hideContent;

  const _TimedEventChip({
    required this.event,
    required this.color,
    this.onTap,
    this.locked = true,
    this.hideContent = false,
  });

  String _compactTitle(String title, String? course) {
    if (course != null && course.isNotEmpty) {
      return course.length > 14 ? '${course.substring(0, 13)}…' : course;
    }
    return title.length > 16 ? '${title.substring(0, 15)}…' : title;
  }

  @override
  Widget build(BuildContext context) {
    final (title, course) = _chipTitleParts(event.title);
    final timeLabel =
        '${DateFormat('h:mm a').format(event.startTime)} – ${DateFormat('h:mm a').format(event.endTime)}';
    final onColor = calendarContrastText(color);
    final line1 = course != null ? '$course · $title' : title;
    final tip = locked
        ? ''
        : 'Click to edit · drag to move';

    return Tooltip(
      message: hideContent ? '' : tip,
      child: MouseRegion(
        cursor: locked ? SystemMouseCursors.basic : SystemMouseCursors.grab,
        child: Material(
          color: color,
          borderRadius: BorderRadius.circular(AppTokens.calendarEventRadius),
          clipBehavior: Clip.antiAlias,
          child: hideContent
              ? const SizedBox.expand()
              : LayoutBuilder(
                  builder: (context, constraints) {
                    final h = constraints.maxHeight;
                    final showTime = h >= 40;
                    return Padding(
                      padding: const EdgeInsets.symmetric(
                        horizontal: AppTokens.space8,
                        vertical: AppTokens.space4,
                      ),
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(
                            line1,
                            maxLines: 1,
                            overflow: TextOverflow.ellipsis,
                            style: CalendarTextStyles.eventTitle(onColor),
                          ),
                          if (showTime)
                            Text(
                              timeLabel,
                              maxLines: 1,
                              overflow: TextOverflow.ellipsis,
                              style: CalendarTextStyles.eventTime(onColor),
                            ),
                        ],
                      ),
                    );
                  },
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
  final bool flexible;
  final bool hideContent;

  const _StudyBlockChip({
    required this.block,
    required this.color,
    required this.onTap,
    this.flexible = false,
    this.hideContent = false,
  });

  @override
  Widget build(BuildContext context) {
    final onColor = calendarContrastText(color);
    final timeLabel =
        '${DateFormat('h:mm a').format(block.startTime)} – ${DateFormat('h:mm a').format(block.endTime)}';

    final fill = flexible ? color.withValues(alpha: 0.25) : color;
    final borderColor =
        flexible ? color.withValues(alpha: 0.7) : Colors.transparent;

    return Tooltip(
      message: hideContent ? '' : 'Click to edit · drag to move',
      child: MouseRegion(
        cursor: SystemMouseCursors.grab,
        child: Stack(
          fit: StackFit.expand,
          children: [
            Material(
              color: fill,
              borderRadius:
                  BorderRadius.circular(AppTokens.calendarEventRadius),
              clipBehavior: Clip.antiAlias,
              child: hideContent
                  ? const SizedBox.expand()
                  : LayoutBuilder(
                      builder: (context, constraints) {
                        final h = constraints.maxHeight;
                        final showTime = h >= 40;
                        return Padding(
                          padding: const EdgeInsets.symmetric(
                            horizontal: AppTokens.space8,
                            vertical: AppTokens.space4,
                          ),
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Row(
                                children: [
                                  if (flexible) ...[
                                    Icon(
                                      Icons.auto_awesome,
                                      size: 10,
                                      color: color,
                                    ),
                                    const SizedBox(width: AppTokens.space4),
                                  ],
                                  Expanded(
                                    child: Text(
                                      block.taskTitle,
                                      maxLines: 1,
                                      overflow: TextOverflow.ellipsis,
                                      style: CalendarTextStyles.eventTitle(
                                        flexible ? color : onColor,
                                      ),
                                    ),
                                  ),
                                ],
                              ),
                              if (showTime)
                                Text(
                                  timeLabel,
                                  maxLines: 1,
                                  overflow: TextOverflow.ellipsis,
                                  style: CalendarTextStyles.eventTime(
                                    flexible ? color : onColor,
                                  ),
                                ),
                            ],
                          ),
                        );
                      },
                    ),
            ),
            if (flexible && !hideContent)
              CustomPaint(
                painter: DashedBorderPainter(
                  color: borderColor,
                  radius: AppTokens.calendarEventRadius,
                  strokeWidth: 1.5,
                ),
              ),
          ],
        ),
      ),
    );
  }
}

class _HabitSessionChip extends StatelessWidget {
  final HabitSessionModel session;
  final VoidCallback onTap;
  final bool hideContent;

  const _HabitSessionChip({
    required this.session,
    required this.onTap,
    this.hideContent = false,
  });

  @override
  Widget build(BuildContext context) {
    const color = AppColors.habitBlock;
    final timeLabel =
        '${DateFormat('h:mm a').format(session.startTime)} – ${DateFormat('h:mm a').format(session.endTime)}';

    return Tooltip(
      message: hideContent ? '' : 'Habit · click for details · drag to move',
      child: MouseRegion(
        cursor: SystemMouseCursors.grab,
        child: Stack(
          fit: StackFit.expand,
          children: [
            Material(
              color: color.withValues(alpha: 0.22),
              borderRadius:
                  BorderRadius.circular(AppTokens.calendarEventRadius),
              clipBehavior: Clip.antiAlias,
              child: hideContent
                  ? const SizedBox.expand()
                  : LayoutBuilder(
                      builder: (context, constraints) {
                        final h = constraints.maxHeight;
                        final w = constraints.maxWidth;
                        final showTime = h >= 36 && w >= 64;
                        return Padding(
                          padding: EdgeInsets.symmetric(
                            horizontal:
                                w < 56 ? AppTokens.space4 : AppTokens.space8,
                            vertical: AppTokens.space4,
                          ),
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Row(
                                children: [
                                  const Icon(
                                    Icons.repeat,
                                    size: 10,
                                    color: color,
                                  ),
                                  const SizedBox(width: AppTokens.space4),
                                  Expanded(
                                    child: Text(
                                      session.habitTitle,
                                      maxLines: 1,
                                      overflow: TextOverflow.ellipsis,
                                      style:
                                          CalendarTextStyles.eventTitle(color),
                                    ),
                                  ),
                                ],
                              ),
                              if (showTime)
                                Text(
                                  timeLabel,
                                  maxLines: 1,
                                  overflow: TextOverflow.ellipsis,
                                  style: CalendarTextStyles.eventTime(color),
                                ),
                            ],
                          ),
                        );
                      },
                    ),
            ),
            if (!hideContent)
              CustomPaint(
                painter: DashedBorderPainter(
                  color: color.withValues(alpha: 0.75),
                  radius: AppTokens.calendarEventRadius,
                  strokeWidth: 1.5,
                ),
              ),
          ],
        ),
      ),
    );
  }
}

// ── Bottom sheets ─────────────────────────────────────────────────────────────

class _CalendarEventDetailSheet extends StatelessWidget {
  final EventModel event;
  final bool canDelete;
  final bool canEdit;
  final bool showScheduleStudy;
  final VoidCallback onEdit;
  final VoidCallback onScheduleStudy;
  final VoidCallback onDelete;

  const _CalendarEventDetailSheet({
    required this.event,
    required this.canDelete,
    required this.canEdit,
    required this.showScheduleStudy,
    required this.onEdit,
    required this.onScheduleStudy,
    required this.onDelete,
  });

  String _sourceLabel() {
    switch (event.source) {
      case 'canvas':
        return 'Canvas';
      case 'course':
        return 'Course import';
      case 'manual_task':
        return 'Your task';
      case 'manual':
        return 'Your event';
      default:
        if (event.source.startsWith('ical')) return 'iCal feed';
        return 'Calendar';
    }
  }

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final textTheme = Theme.of(context).textTheme;
    final (title, course) = _chipTitleParts(event.title);
    final displayTitle =
        course != null ? '$course · $title' : event.title.trim();

    final whenText = event.isDateOnlyCourseEvent
        ? DateFormat('EEE, MMM d').format(event.startTime)
        : '${DateFormat('EEE, MMM d').format(event.startTime)} · '
            '${DateFormat('jm').format(event.startTime)} – ${DateFormat('jm').format(event.endTime)}';

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
          Row(
            children: [
              Expanded(
                child: Container(
                  padding:
                      const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
                  decoration: BoxDecoration(
                    color: scheme.surfaceContainerHighest,
                    borderRadius: BorderRadius.circular(8),
                  ),
                  child: Text(
                    _sourceLabel(),
                    style: textTheme.labelSmall?.copyWith(
                      color: scheme.onSurfaceVariant,
                      fontWeight: FontWeight.w600,
                    ),
                  ),
                ),
              ),
              if (canEdit)
                IconButton(
                  tooltip: 'Edit',
                  icon: const Icon(Icons.edit_outlined),
                  onPressed: onEdit,
                ),
            ],
          ),
          const SizedBox(height: 10),
          Text(displayTitle, style: textTheme.titleMedium),
          const SizedBox(height: 8),
          Text(whenText, style: textTheme.bodyMedium),
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
              event.description.trim().isEmpty
                  ? 'No notes for this event.'
                  : event.description.trim(),
              style: textTheme.bodyMedium?.copyWith(
                height: 1.35,
                color: event.description.trim().isEmpty
                    ? scheme.onSurfaceVariant
                    : null,
              ),
            ),
          ),
          if (showScheduleStudy) ...[
            const SizedBox(height: 20),
            FilledButton.icon(
              onPressed: onScheduleStudy,
              icon: const Icon(Icons.schedule),
              label: const Text('Schedule study time'),
            ),
          ],
          if (canDelete) ...[
            const SizedBox(height: 12),
            OutlinedButton.icon(
              onPressed: onDelete,
              icon: Icon(Icons.delete_outline, color: scheme.error),
              label: Text(
                'Remove from Synctra',
                style: TextStyle(color: scheme.error),
              ),
              style: OutlinedButton.styleFrom(
                side: BorderSide(color: scheme.error.withValues(alpha: 0.5)),
              ),
            ),
          ],
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
    final newStart =
        DateTime(day.year, day.month, day.day, time.hour, time.minute);
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
              border:
                  OutlineInputBorder(borderRadius: BorderRadius.circular(12)),
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

// ── Course import bottom sheet ────────────────────────────────────────────────

class _CourseImportSheet extends StatefulWidget {
  final List<CourseImportRecord> imports;
  final Future<void> Function(String url, String name) onImport;
  final Future<void> Function(String importId) onRemove;

  const _CourseImportSheet({
    required this.imports,
    required this.onImport,
    required this.onRemove,
  });

  @override
  State<_CourseImportSheet> createState() => _CourseImportSheetState();
}

class _CourseImportSheetState extends State<_CourseImportSheet> {
  final _urlCtrl = TextEditingController();
  final _nameCtrl = TextEditingController();
  bool _isLoading = false;
  String? _deletingCourseId;
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
      setState(() => _error = 'Please enter a course page URL.');
      return;
    }
    if (!url.startsWith('http://') && !url.startsWith('https://')) {
      setState(() => _error = 'URL must start with http:// or https://');
      return;
    }

    setState(() {
      _isLoading = true;
      _error = null;
    });
    try {
      await widget.onImport(url, _nameCtrl.text.trim());
      if (mounted) Navigator.of(context).pop();
    } on DioException catch (e) {
      if (!mounted) return;
      final detail = e.response?.data?['detail']?.toString() ??
          e.message ??
          'Unknown error';
      setState(() {
        _isLoading = false;
        _error = detail;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _isLoading = false;
        _error = e.toString();
      });
    }
  }

  Future<void> _deleteCourse(CourseImportRecord course) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Delete course import?'),
        content: Text(
          'Remove ${course.courseName} and its ${course.eventCount} calendar events?',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx, false),
            child: const Text('Cancel'),
          ),
          FilledButton.tonalIcon(
            onPressed: () => Navigator.pop(ctx, true),
            icon: const Icon(Icons.delete_outline),
            label: const Text('Delete'),
          ),
        ],
      ),
    );
    if (confirmed != true || !mounted) return;

    setState(() {
      _deletingCourseId = course.id;
      _error = null;
    });
    try {
      await widget.onRemove(course.id);
      if (!mounted) return;
      Navigator.of(context).pop();
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _deletingCourseId = null;
        _error = e.toString();
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return Padding(
      padding: EdgeInsets.fromLTRB(
        16,
        4,
        16,
        MediaQuery.of(context).viewInsets.bottom + 24,
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Row(
            children: [
              const Icon(Icons.school_outlined),
              const SizedBox(width: 10),
              const Expanded(
                child: Text(
                  'Course Import',
                  style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold),
                ),
              ),
              TextButton(
                onPressed:
                    _isLoading ? null : () => Navigator.of(context).pop(),
                child: const Text('Cancel'),
              ),
            ],
          ),
          const SizedBox(height: 12),
          TextField(
            controller: _urlCtrl,
            decoration: const InputDecoration(
              labelText: 'Course Page URL',
              hintText:
                  'https://courses.cs.washington.edu/courses/cse333/26sp/',
              border: OutlineInputBorder(),
            ),
            keyboardType: TextInputType.url,
            autocorrect: false,
            autofocus: true,
            onSubmitted: (_) => _isLoading ? null : _submit(),
          ),
          const SizedBox(height: 10),
          TextField(
            controller: _nameCtrl,
            decoration: const InputDecoration(
              labelText: 'Course Name (optional)',
              hintText: 'e.g. CSE 333',
              border: OutlineInputBorder(),
            ),
            onSubmitted: (_) => _isLoading ? null : _submit(),
          ),
          const SizedBox(height: 8),
          Text(
            'Use this for UW course websites. Use iCal feeds only for .ics or webcal calendar links.',
            style: Theme.of(context).textTheme.bodySmall?.copyWith(
                  color: scheme.onSurfaceVariant,
                ),
          ),
          if (_error != null) ...[
            const SizedBox(height: 8),
            Text(_error!, style: TextStyle(color: scheme.error, fontSize: 13)),
          ],
          const SizedBox(height: 12),
          FilledButton.icon(
            onPressed: _isLoading ? null : _submit,
            icon: _isLoading
                ? const SizedBox(
                    width: 18,
                    height: 18,
                    child: CircularProgressIndicator(strokeWidth: 2),
                  )
                : const Icon(Icons.auto_awesome),
            label: Text(_isLoading ? 'Importing…' : 'Import'),
          ),
          if (widget.imports.isNotEmpty) ...[
            const SizedBox(height: 20),
            Text('Imported courses',
                style: Theme.of(context).textTheme.titleSmall),
            const SizedBox(height: 6),
            ...widget.imports.map((course) {
              final isDeleting = _deletingCourseId == course.id;
              return ListTile(
                contentPadding: EdgeInsets.zero,
                leading: const Icon(Icons.school_outlined, size: 20),
                title: Text(course.courseName),
                subtitle:
                    Text('${course.eventCount} events · ${course.courseUrl}'),
                trailing: IconButton(
                  tooltip: 'Delete course import',
                  onPressed: _isLoading || isDeleting
                      ? null
                      : () => _deleteCourse(course),
                  icon: isDeleting
                      ? const SizedBox(
                          width: 18,
                          height: 18,
                          child: CircularProgressIndicator(strokeWidth: 2),
                        )
                      : const Icon(Icons.delete_outline),
                ),
              );
            }),
          ],
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
      setState(
          () => _error = 'URL must start with http://, https://, or webcal://');
      return;
    }
    final parsedUrl = Uri.tryParse(url);
    final isUwCoursePage = parsedUrl != null &&
        parsedUrl.host == 'courses.cs.washington.edu' &&
        parsedUrl.pathSegments.contains('courses') &&
        parsedUrl.pathSegments
            .any((segment) => segment.toLowerCase().startsWith('cse'));
    final looksLikeIcal = url.startsWith('webcal://') ||
        parsedUrl?.path.toLowerCase().endsWith('.ics') == true;
    if (isUwCoursePage && !looksLikeIcal) {
      setState(() {
        _error =
            'This is a course website, not an iCal feed. Use Course Import for UW course pages, or paste a .ics / webcal calendar URL here.';
      });
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
        final detail = e.response?.data?['detail']?.toString() ??
            e.message ??
            'Unknown error';
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
              const Text('iCal Feeds',
                  style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold)),
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
                      Text(_error!,
                          style:
                              const TextStyle(color: Colors.red, fontSize: 13)),
                    ],
                    const SizedBox(height: 12),
                    FilledButton(
                      onPressed: _isLoading ? null : _submit,
                      child: _isLoading
                          ? const SizedBox(
                              width: 20,
                              height: 20,
                              child: CircularProgressIndicator(
                                  strokeWidth: 2, color: Colors.white),
                            )
                          : const Text('Import'),
                    ),
                  ],
                  if (widget.feeds.isEmpty && !_showForm) ...[
                    const SizedBox(height: 24),
                    Center(
                      child: Column(
                        children: [
                          Icon(Icons.link_off,
                              size: 44, color: Colors.grey[300]),
                          const SizedBox(height: 8),
                          Text('No iCal feeds yet.',
                              style: TextStyle(color: Colors.grey[500])),
                          const SizedBox(height: 4),
                          Text(
                            'Paste a link from Google Calendar, Outlook,\nApple Calendar, or any .ics URL.',
                            textAlign: TextAlign.center,
                            style: TextStyle(
                                fontSize: 12, color: Colors.grey[400]),
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
                      final countLabel =
                          count < 0 ? 'not synced' : '$count events';
                      return ListTile(
                        contentPadding: EdgeInsets.zero,
                        leading:
                            const Icon(Icons.calendar_today_outlined, size: 20),
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
                                  await widget.onSync(
                                      feed['id']!, feed['name']!, feed['url']!);
                                  if (context.mounted) {
                                    Navigator.of(context).pop();
                                  }
                                } catch (e) {
                                  if (context.mounted) {
                                    ScaffoldMessenger.of(context).showSnackBar(
                                      SnackBar(
                                          content: Text('Sync failed: $e'),
                                          backgroundColor: Colors.red),
                                    );
                                  }
                                }
                              },
                            ),
                            IconButton(
                              icon: Icon(Icons.delete_outline,
                                  size: 20, color: Colors.red[300]),
                              onPressed: () async {
                                await widget.onRemove(feed['id']!);
                                if (context.mounted) {
                                  Navigator.of(context).pop();
                                }
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

/// Keeps the add (+) FAB aligned with the calendar column when Sync It is docked.
class _ChatAwareFabLocation extends FloatingActionButtonLocation {
  const _ChatAwareFabLocation({required this.rightInset});

  final double rightInset;

  @override
  Offset getOffset(ScaffoldPrelayoutGeometry scaffoldGeometry) {
    final base =
        FloatingActionButtonLocation.endFloat.getOffset(scaffoldGeometry);
    return Offset(math.max(0, base.dx - rightInset), base.dy);
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

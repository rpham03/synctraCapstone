// Task list view — shows Canvas assignments and manually added tasks with due dates.
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:get_it/get_it.dart';
import 'package:intl/intl.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:uuid/uuid.dart';

import '../../../core/theme/app_theme.dart';
import '../../../data/models/task_model.dart';
import '../../../data/services/course_import_service.dart';
import '../../../shared/services/canvas_tasks_service.dart';
import '../../../shared/state/course_import_tasks_bridge.dart';
import '../../../shared/utils/task_timeline_utils.dart';
import '../../../shared/widgets/synctra_empty_state.dart';
import '../../../shared/widgets/synctra_page_header.dart';
import '../widgets/task_timeline_list.dart';
import '../widgets/weekly_tasks_board.dart';

class TasksScreen extends StatefulWidget {
  const TasksScreen({super.key});

  @override
  State<TasksScreen> createState() => _TasksScreenState();
}

class _TasksScreenState extends State<TasksScreen> {
  final Set<String> _activeFilters = {'canvas', 'manual', 'course'};

  final List<TaskModel> _tasks = [];
  bool _syncing = false;
  bool _weekView = true;
  DateTime _weekMonday = weekMondayOf(DateTime.now());
  late final CanvasTasksService _canvasService;
  late final CourseImportService _courseImportService;

  static const _manualTasksKey = 'synctra_manual_tasks_v1';
  static const _pastLoadBatchSize = 5;
  static const _timelineRetentionDays = 120;

  int _revealedPastCount = 0;
  bool _loadingOlder = false;

  /// Canvas/course imports may carry scraped page text; keep titles only in the UI.
  TaskModel _taskForDisplay(TaskModel task) {
    if (task.source == 'manual') return task;
    if (task.description.isEmpty) return task;
    return task.copyWith(description: '');
  }

  List<TaskModel> get _displayTasks {
    final manual = _tasks.where((t) => t.source == 'manual').toList();
    final canvas = _tasks.where((t) => t.source == 'canvas');
    final course = _tasks.where((t) => t.source == 'course');
    final merged = mergeCanvasAndCourseTasks(canvas, course)
        .map(_taskForDisplay)
        .toList();
    return [...manual, ...merged];
  }

  List<TaskModel> get _filtered {
    return _displayTasks
        .where((t) => _activeFilters.contains(t.source))
        .where(isTaskDueTodayOrLater)
        .toList()
      ..sort(compareTasksTimeline);
  }

  /// List timeline pool: today+ always; completed past kept for scroll-up history.
  List<TaskModel> get _timelinePool {
    final today = taskDateOnly(DateTime.now());
    final pruneBefore =
        today.subtract(const Duration(days: _timelineRetentionDays));
    return _displayTasks
        .where((t) => _activeFilters.contains(t.source))
        .where((t) {
          if (isTaskDueTodayOrLater(t)) return true;
          if (!t.isCompleted) return false;
          return !taskDateOnly(t.dueDate).isBefore(pruneBefore);
        })
        .toList()
      ..sort(compareTasksTimeline);
  }

  TimelineVisibleTasks get _timelineVisible {
    return buildTimelineVisibleTasks(
      _timelinePool,
      revealedPastCount: _revealedPastCount,
    );
  }

  void _loadOlderTasks() {
    if (_loadingOlder || !_timelineVisible.hasMorePast) return;
    setState(() {
      _loadingOlder = true;
      _revealedPastCount += _pastLoadBatchSize;
      _loadingOlder = false;
    });
  }

  @override
  void initState() {
    super.initState();
    _canvasService = GetIt.instance<CanvasTasksService>();
    _courseImportService = CourseImportService();
    CourseImportTasksBridge.instance.addListener(_handleCourseTasksRefresh);
    _loadManualTasks();
    _loadCourseTasks();
    _loadCachedCanvas();
    _syncCanvas(silent: true);
  }

  @override
  void dispose() {
    CourseImportTasksBridge.instance.removeListener(_handleCourseTasksRefresh);
    super.dispose();
  }

  void _handleCourseTasksRefresh() {
    _loadCourseTasks();
  }

  Future<void> _loadCachedCanvas() async {
    final cached = await _canvasService.loadCached();
    if (!mounted || cached.isEmpty) return;
    setState(() {
      _tasks.removeWhere((t) => t.source == 'canvas');
      _tasks.addAll(cached);
    });
  }

  Future<void> _loadManualTasks() async {
    final prefs = await SharedPreferences.getInstance();
    final raw = prefs.getString(_manualTasksKey);
    if (raw == null || raw.isEmpty) return;
    try {
      final list = jsonDecode(raw) as List<dynamic>;
      final loaded = list
          .whereType<Map>()
          .map((m) => TaskModel.fromJson(Map<String, dynamic>.from(m)))
          .where((t) => t.source == 'manual')
          .toList();
      if (!mounted) return;
      setState(() {
        _tasks.removeWhere((t) => t.source == 'manual');
        _tasks.addAll(loaded);
      });
    } catch (_) {}
  }

  Future<void> _loadCourseTasks() async {
    final loaded = await _courseImportService.loadCachedTasks();
    if (!mounted) return;
    setState(() {
      _tasks.removeWhere((task) => task.source == 'course');
      _tasks.addAll(loaded);
    });
  }

  Future<void> _persistManualTasks() async {
    final manual = _tasks
        .where((t) => t.source == 'manual')
        .map((t) => t.toJson())
        .toList();
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(_manualTasksKey, jsonEncode(manual));
  }

  Future<void> _syncCanvas({bool silent = false}) async {
    setState(() => _syncing = true);
    try {
      final incoming = await _canvasService.syncFromApi();
      if (!mounted) return;
      setState(() {
        _tasks.removeWhere((t) => t.source == 'canvas');
        _tasks.addAll(incoming);
        _syncing = false;
      });
      if (!silent && mounted && incoming.isEmpty) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(
              content: Text('Canvas: no dated assignments returned.')),
        );
      }
    } catch (e) {
      if (!mounted) return;
      setState(() => _syncing = false);
      if (!silent && mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Canvas sync: $e')),
        );
      }
    }
  }

  Future<void> _refreshTasks() async {
    await Future.wait([
      _syncCanvas(),
      _loadCourseTasks(),
    ]);
  }

  Future<void> _showAddTask() async {
    final titleCtrl = TextEditingController();
    final descCtrl = TextEditingController();
    DateTime due = DateTime.now().add(const Duration(days: 1));
    var est = 180;

    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => StatefulBuilder(
        builder: (ctx, setModal) {
          return AlertDialog(
            title: const Text('New task'),
            content: SingleChildScrollView(
              child: Column(
                mainAxisSize: MainAxisSize.min,
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  TextField(
                    controller: titleCtrl,
                    decoration: const InputDecoration(
                      labelText: 'Title',
                      border: OutlineInputBorder(),
                    ),
                    textCapitalization: TextCapitalization.sentences,
                    autofocus: true,
                  ),
                  const SizedBox(height: 12),
                  ListTile(
                    contentPadding: EdgeInsets.zero,
                    title: const Text('Due date'),
                    subtitle: Text(DateFormat.yMMMd().format(due)),
                    onTap: () async {
                      final picked = await showDatePicker(
                        context: ctx,
                        initialDate: due,
                        firstDate:
                            DateTime.now().subtract(const Duration(days: 1)),
                        lastDate:
                            DateTime.now().add(const Duration(days: 365 * 2)),
                      );
                      if (picked != null) setModal(() => due = picked);
                    },
                  ),
                  Row(
                    children: [
                      const Text('Estimate (min)'),
                      const Spacer(),
                      DropdownButton<int>(
                        value: est,
                        items: [15, 30, 45, 60, 90, 120, 180]
                            .map((m) =>
                                DropdownMenuItem(value: m, child: Text('$m')))
                            .toList(),
                        onChanged: (v) => setModal(() => est = v ?? 60),
                      ),
                    ],
                  ),
                  const SizedBox(height: 12),
                  TextField(
                    controller: descCtrl,
                    decoration: const InputDecoration(
                      labelText: 'Description (optional)',
                      hintText: 'Details, links, rubric notes…',
                      alignLabelWithHint: true,
                      border: OutlineInputBorder(),
                    ),
                    minLines: 2,
                    maxLines: 4,
                  ),
                ],
              ),
            ),
            actions: [
              TextButton(
                  onPressed: () => Navigator.pop(ctx, false),
                  child: const Text('Cancel')),
              FilledButton(
                  onPressed: () => Navigator.pop(ctx, true),
                  child: const Text('Add')),
            ],
          );
        },
      ),
    );

    if (ok != true || !mounted) {
      titleCtrl.dispose();
      descCtrl.dispose();
      return;
    }
    final title = titleCtrl.text.trim();
    final desc = descCtrl.text.trim();
    titleCtrl.dispose();
    descCtrl.dispose();
    if (title.isEmpty) return;

    setState(() {
      _tasks.add(
        TaskModel(
          id: const Uuid().v4(),
          title: title,
          dueDate: DateTime(due.year, due.month, due.day, 23, 59),
          estimatedMinutes: est,
          source: 'manual',
          description: desc,
        ),
      );
    });
    await _persistManualTasks();
    if (mounted) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Task added.')),
      );
    }
  }

  Future<void> _setTaskDone(TaskModel task, bool done) async {
    final i = _tasks.indexWhere((t) => t.id == task.id);
    if (i < 0) return;
    setState(() => _tasks[i] = task.copyWith(isCompleted: done));
    if (task.source == 'manual') await _persistManualTasks();
    if (task.source == 'course') {
      await _courseImportService.updateCachedTask(_tasks[i]);
    }
  }

  Future<void> _applyDueChange(TaskModel task, DateTime newDue) async {
    final i = _tasks.indexWhere((t) => t.id == task.id);
    if (i < 0) return;
    setState(() => _tasks[i] = task.copyWith(dueDate: newDue));
    if (task.source == 'manual') {
      await _persistManualTasks();
    } else if (task.source == 'course') {
      await _courseImportService.updateCachedTask(_tasks[i]);
    } else if (task.source == 'canvas') {
      final cached = await _canvasService.loadCached();
      final updated = cached
          .map((t) => t.id == task.id ? t.copyWith(dueDate: newDue) : t)
          .toList();
      await _canvasService.saveCache(updated);
      await _canvasService.reloadFromCache();
    }
  }

  Future<bool> _confirm({
    required String title,
    required String message,
    String confirmLabel = 'Remove',
  }) async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: Text(title),
        content: Text(message),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx, false),
            child: const Text('Cancel'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(ctx, true),
            child: Text(confirmLabel),
          ),
        ],
      ),
    );
    return ok == true;
  }

  Future<void> _persistCanvasFromState() async {
    final canvas = _tasks.where((t) => t.source == 'canvas').toList();
    await _canvasService.saveCache(canvas);
    await _canvasService.reloadFromCache();
  }

  Future<void> _deleteTask(TaskModel task) async {
    final sourceNote = task.source == 'canvas'
        ? ' It stays on Canvas; use Sync to pull assignments again.'
        : '';
    final ok = await _confirm(
      title: 'Remove task?',
      message:
          'Remove "${task.title}" from Synctra?$sourceNote',
    );
    if (!ok) return;

    setState(() => _tasks.removeWhere((t) => t.id == task.id));
    if (task.source == 'manual') {
      await _persistManualTasks();
    } else if (task.source == 'canvas') {
      await _persistCanvasFromState();
    }
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      const SnackBar(content: Text('Task removed.')),
    );
  }

  Future<void> _clearTasks({required String? source}) async {
    final String title;
    final String message;
    if (source == 'canvas') {
      title = 'Clear Canvas tasks?';
      message =
          'Remove all cached Canvas assignments from Synctra. Tap Sync to import fresh tasks from Canvas.';
    } else if (source == 'manual') {
      title = 'Clear manual tasks?';
      message = 'Remove every task you added manually. This cannot be undone.';
    } else {
      title = 'Clear all tasks?';
      message =
          'Remove all Canvas and manual tasks from Synctra. Tap Sync to reload Canvas assignments.';
    }

    final ok = await _confirm(
      title: title,
      message: message,
      confirmLabel: 'Clear',
    );
    if (!ok) return;

    if (source == null || source == 'canvas') {
      await _canvasService.clearCache();
    }
    if (source == null) {
      final prefs = await SharedPreferences.getInstance();
      await prefs.remove(_manualTasksKey);
    }

    setState(() {
      if (source == null) {
        _tasks.clear();
      } else {
        _tasks.removeWhere((t) => t.source == source);
      }
    });

    if (source == 'manual' || source == null) {
      await _persistManualTasks();
    }

    if (!mounted) return;
    final label = source == 'canvas'
        ? 'Canvas tasks cleared. Tap Sync to reload.'
        : source == 'manual'
            ? 'Manual tasks cleared.'
            : 'All tasks cleared. Tap Sync to reload Canvas.';
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(content: Text(label)),
    );
  }

  void _showTasksMenu() {
    final hasCanvas = _tasks.any((t) => t.source == 'canvas');
    final hasManual = _tasks.any((t) => t.source == 'manual');
    showModalBottomSheet<void>(
      context: context,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(20)),
      ),
      builder: (ctx) => SafeArea(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            ListTile(
              leading: const Icon(Icons.sync),
              title: const Text('Sync Canvas'),
              subtitle: const Text('Pull latest assignments from Canvas'),
              onTap: () {
                Navigator.pop(ctx);
                _syncCanvas();
              },
            ),
            ListTile(
              leading: const Icon(Icons.school_outlined),
              title: const Text('Clear Canvas tasks'),
              subtitle: const Text('Then sync again for a fresh import'),
              enabled: hasCanvas,
              onTap: hasCanvas
                  ? () {
                      Navigator.pop(ctx);
                      _clearTasks(source: 'canvas');
                    }
                  : null,
            ),
            ListTile(
              leading: const Icon(Icons.edit_note_outlined),
              title: const Text('Clear manual tasks'),
              enabled: hasManual,
              onTap: hasManual
                  ? () {
                      Navigator.pop(ctx);
                      _clearTasks(source: 'manual');
                    }
                  : null,
            ),
            ListTile(
              leading: Icon(Icons.delete_outline, color: Theme.of(ctx).colorScheme.error),
              title: Text(
                'Clear all tasks',
                style: TextStyle(color: Theme.of(ctx).colorScheme.error),
              ),
              enabled: _tasks.isNotEmpty,
              onTap: _tasks.isNotEmpty
                  ? () {
                      Navigator.pop(ctx);
                      _clearTasks(source: null);
                    }
                  : null,
            ),
            const SizedBox(height: 8),
          ],
        ),
      ),
    );
  }

  Future<void> _quickAddBoard(String title, DateTime dueEndOfDay) async {
    setState(() {
      _tasks.add(
        TaskModel(
          id: const Uuid().v4(),
          title: title,
          dueDate: dueEndOfDay,
          estimatedMinutes: 180,
          source: 'manual',
          description: '',
        ),
      );
    });
    await _persistManualTasks();
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      const SnackBar(content: Text('Task added.')),
    );
  }

  void _shiftWeek(int weeks) {
    setState(() {
      _weekMonday = _weekMonday.add(Duration(days: 7 * weeks));
    });
  }

  int _countDueOutsideVisibleWeek() {
    return _filtered.where((t) => !taskDueInWeek(t, _weekMonday)).length;
  }

  int _countDueInVisibleWeek() {
    return _filtered.where((t) => taskDueInWeek(t, _weekMonday)).length;
  }

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final weekEnd = _weekMonday.add(const Duration(days: 6));
    final rangeLabel = _weekMonday.year == weekEnd.year
        ? '${DateFormat.MMMd().format(_weekMonday)} – ${DateFormat('MMM d, yyyy').format(weekEnd)}'
        : '${DateFormat('MMM d, yyyy').format(_weekMonday)} – ${DateFormat('MMM d, yyyy').format(weekEnd)}';

    return Scaffold(
      backgroundColor: scheme.surface,
      appBar: SynctraPageHeader(
        title: 'Tasks',
            subtitle: _weekView
            ? 'Week review · use List view for today onward'
            : 'Today and upcoming · scroll up for older work',
        showSettings: true,
        actions: [
          IconButton(
            icon: _syncing
                ? SizedBox(
                    width: 22,
                    height: 22,
                    child: CircularProgressIndicator(
                        strokeWidth: 2, color: scheme.primary),
                  )
                : Icon(Icons.sync, color: scheme.onSurfaceVariant, size: 22),
            tooltip: 'Sync tasks',
            onPressed: _syncing ? null : _refreshTasks,
          ),
          IconButton(
            icon: Icon(Icons.filter_list,
                color: scheme.onSurfaceVariant, size: 22),
            tooltip: 'Filter',
            onPressed: _showFilterSheet,
          ),
          IconButton(
            icon: Icon(Icons.more_vert, color: scheme.onSurfaceVariant, size: 22),
            tooltip: 'Task options',
            onPressed: _showTasksMenu,
          ),
        ],
      ),
      body: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 8, 16, 0),
            child: SegmentedButton<bool>(
              segments: const [
                ButtonSegment(
                    value: true,
                    label: Text('Week'),
                    icon: Icon(Icons.view_week_outlined, size: 18)),
                ButtonSegment(
                    value: false,
                    label: Text('List'),
                    icon: Icon(Icons.view_list_outlined, size: 18)),
              ],
              selected: {_weekView},
              onSelectionChanged: (s) => setState(() => _weekView = s.first),
              showSelectedIcon: false,
              style: ButtonStyle(
                visualDensity: VisualDensity.compact,
                padding: WidgetStateProperty.all(
                    const EdgeInsets.symmetric(horizontal: 12, vertical: 10)),
              ),
            ),
          ),
          if (_weekView) ...[
            const SizedBox(height: 8),
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 8),
              child: Row(
                children: [
                  IconButton(
                    tooltip: 'Previous week',
                    onPressed: () => _shiftWeek(-1),
                    icon: Icon(Icons.chevron_left,
                        color: scheme.onSurfaceVariant),
                  ),
                  Expanded(
                    child: Text(
                      rangeLabel,
                      textAlign: TextAlign.center,
                      style: Theme.of(context).textTheme.titleSmall?.copyWith(
                            fontWeight: FontWeight.w600,
                            letterSpacing: -0.2,
                          ),
                    ),
                  ),
                  IconButton(
                    tooltip: 'Next week',
                    onPressed: () => _shiftWeek(1),
                    icon: Icon(Icons.chevron_right,
                        color: scheme.onSurfaceVariant),
                  ),
                ],
              ),
            ),
          ],
          const SizedBox(height: 4),
          Expanded(
            child: _weekView
                ? _WeekBody(
                    weekMonday: _weekMonday,
                    tasks: _filtered,
                    outsideWeekCount: _countDueOutsideVisibleWeek(),
                    inWeekCount: _countDueInVisibleWeek(),
                    onTaskDueChanged: _applyDueChange,
                    onQuickAdd: _quickAddBoard,
                    onToggleDone: _setTaskDone,
                    onDeleteTask: _deleteTask,
                    onAddTask: _showAddTask,
                    isEmpty: _filtered.isEmpty,
                  )
                : _timelineVisible.tasks.isEmpty
                    ? _EmptyTasks(onAdd: _showAddTask)
                    : TaskTimelineList(
                        tasks: _timelineVisible.tasks,
                        loadingOlder: _loadingOlder,
                        hasOlderOutsideWindow: _timelineVisible.hasMorePast,
                        onLoadOlder: _loadOlderTasks,
                        onToggleDone: _setTaskDone,
                        onDeleteTask: _deleteTask,
                      ),
          ),
        ],
      ),
      floatingActionButton: FloatingActionButton(
        onPressed: _showAddTask,
        child: const Icon(Icons.add),
      ),
    );
  }

  void _showFilterSheet() {
    showModalBottomSheet(
      context: context,
      shape: const RoundedRectangleBorder(
          borderRadius: BorderRadius.vertical(top: Radius.circular(20))),
      builder: (_) => StatefulBuilder(
        builder: (ctx, setModal) => Padding(
          padding: const EdgeInsets.all(24),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const Text('Filter Sources',
                  style: TextStyle(fontWeight: FontWeight.bold, fontSize: 16)),
              const SizedBox(height: 16),
              for (final source in ['canvas', 'course', 'manual'])
                CheckboxListTile(
                  value: _activeFilters.contains(source),
                  title: Text(_sourceFilterLabel(source)),
                  activeColor: AppColors.primary,
                  onChanged: (v) {
                    setModal(() {
                      setState(() {
                        if (v == true) {
                          _activeFilters.add(source);
                        } else {
                          _activeFilters.remove(source);
                        }
                      });
                    });
                  },
                ),
            ],
          ),
        ),
      ),
    );
  }

  String _sourceFilterLabel(String source) {
    switch (source) {
      case 'canvas':
        return 'Canvas Assignments';
      case 'course':
        return 'Course Imports';
      default:
        return 'Manual Tasks';
    }
  }
}

class _WeekBody extends StatelessWidget {
  final DateTime weekMonday;
  final List<TaskModel> tasks;
  final int outsideWeekCount;
  final int inWeekCount;
  final Future<void> Function(TaskModel task, DateTime newDue) onTaskDueChanged;
  final Future<void> Function(String title, DateTime dueEndOfDay) onQuickAdd;
  final Future<void> Function(TaskModel task, bool done) onToggleDone;
  final Future<void> Function(TaskModel task) onDeleteTask;
  final VoidCallback onAddTask;
  final bool isEmpty;

  const _WeekBody({
    required this.weekMonday,
    required this.tasks,
    required this.outsideWeekCount,
    required this.inWeekCount,
    required this.onTaskDueChanged,
    required this.onQuickAdd,
    required this.onToggleDone,
    required this.onDeleteTask,
    required this.onAddTask,
    required this.isEmpty,
  });

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final hintStyle = Theme.of(context).textTheme.bodySmall?.copyWith(
          color: scheme.onSurfaceVariant,
          height: 1.35,
        );

    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        if (isEmpty)
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 8, 16, 0),
            child: SynctraEmptyState(
              icon: Icons.checklist_outlined,
              title: 'No tasks this week',
              message: 'Sync Canvas or add a task to fill the week board.',
              action: FilledButton.icon(
                onPressed: onAddTask,
                icon: const Icon(Icons.add, size: 18),
                label: const Text('Add task'),
              ),
            ),
          )
        else if (inWeekCount == 0 && tasks.isNotEmpty)
          Padding(
            padding: const EdgeInsets.fromLTRB(20, 4, 20, 8),
            child: Text(
              'Nothing due this week. $outsideWeekCount ${_plural(outsideWeekCount, 'task', 'tasks')} in other weeks — try List.',
              textAlign: TextAlign.center,
              style: hintStyle,
            ),
          ),
        if (!isEmpty)
          Expanded(
            child: Padding(
              padding: const EdgeInsets.fromLTRB(8, 0, 8, 8),
              child: WeeklyTasksBoard(
                weekMonday: weekMonday,
                tasks: tasks,
                onTaskDueChanged: (t, d) => onTaskDueChanged(t, d),
                onQuickAdd: (title, due) => onQuickAdd(title, due),
                onToggleDone: (t, d) => onToggleDone(t, d),
                onDeleteTask: onDeleteTask,
              ),
            ),
          )
        else
          const Spacer(),
        if (outsideWeekCount > 0 && inWeekCount > 0)
          Padding(
            padding: const EdgeInsets.fromLTRB(20, 0, 20, 12),
            child: Text(
              '$outsideWeekCount more not shown this week — open List for the full queue.',
              textAlign: TextAlign.center,
              style: hintStyle,
            ),
          ),
      ],
    );
  }

  static String _plural(int n, String one, String many) => n == 1 ? one : many;
}

// ── Sub-widgets ────────────────────────────────────────────────────────────────

class _EmptyTasks extends StatelessWidget {
  final VoidCallback onAdd;
  const _EmptyTasks({required this.onAdd});

  @override
  Widget build(BuildContext context) {
    return SynctraEmptyState(
      icon: Icons.checklist_outlined,
      title: 'No tasks yet',
      message: 'Sync Canvas from the toolbar or add a task manually.',
      action: FilledButton.icon(
        onPressed: onAdd,
        icon: const Icon(Icons.add, size: 18),
        label: const Text('Add task'),
      ),
    );
  }
}

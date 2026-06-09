import 'package:flutter/material.dart';
import 'package:get_it/get_it.dart';
import 'package:google_fonts/google_fonts.dart';

import '../../../core/theme/app_tokens.dart';
import '../../../data/models/habit_model.dart';
import '../../../shared/services/habit_service.dart';
import '../../../shared/services/habit_session_store.dart';
import '../../../shared/widgets/synctra_page_scaffold.dart';
import '../../../theme.dart';
import '../widgets/habit_edit_view.dart';

class HabitsScreen extends StatefulWidget {
  const HabitsScreen({super.key});

  @override
  State<HabitsScreen> createState() => _HabitsScreenState();
}

class _HabitsScreenState extends State<HabitsScreen> {
  final _service = HabitService();
  late final HabitSessionStore _sessionStore;

  List<HabitModel> _habits = [];
  bool _loading = true;
  String? _error;
  HabitModel? _editing;

  @override
  void initState() {
    super.initState();
    _sessionStore = GetIt.instance<HabitSessionStore>();
    _load();
  }

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final habits = await _service.listHabits();
      if (!mounted) return;
      setState(() {
        _habits = habits;
        _loading = false;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _error = 'Could not load habits. Is the backend running?';
        _loading = false;
      });
    }
  }

  void _openEditor([HabitModel? existing]) {
    setState(() => _editing = existing ?? const _NewHabitMarker());
  }

  void _closeEditor() {
    setState(() => _editing = null);
  }

  Future<void> _saveHabit(Map<String, dynamic> payload, String? id) async {
    if (id == null) {
      await _service.createHabit(payload);
    } else {
      await _service.updateHabit(id, payload);
    }
    await _load();
    if (_sessionStore.hasCachedCalendarEvents) {
      await _sessionStore.refreshFromCachedEvents();
    }
    if (mounted) {
      _closeEditor();
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Habit saved.')),
      );
    }
  }

  Future<void> _delete(HabitModel habit) async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Delete habit?'),
        content: Text('Remove "${habit.title}" from your schedule?'),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx, false),
            child: const Text('Cancel'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(ctx, true),
            child: const Text('Delete'),
          ),
        ],
      ),
    );
    if (ok != true) return;
    await _service.deleteHabit(habit.id);
    await _load();
    if (_sessionStore.hasCachedCalendarEvents) {
      await _sessionStore.refreshFromCachedEvents();
    }
    if (mounted) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('Deleted ${habit.title}')),
      );
    }
  }

  @override
  Widget build(BuildContext context) {
    if (_editing != null) {
      final isNew = _editing is _NewHabitMarker;
      return HabitEditView(
        habit: isNew ? null : _editing,
        onSave: _saveHabit,
        onCancel: _closeEditor,
      );
    }

    return SynctraPageScaffold(
      title: 'Habits',
      body: _loading
          ? const Center(child: CircularProgressIndicator())
          : _error != null
              ? _ErrorState(message: _error!, onRetry: _load)
              : _habits.isEmpty
                  ? _EmptyState(onCreate: () => _openEditor())
                  : ListView.separated(
                      padding: const EdgeInsets.all(AppTokens.space24),
                      itemCount: _habits.length,
                      separatorBuilder: (_, __) =>
                          const SizedBox(height: AppTokens.space12),
                      itemBuilder: (context, i) {
                        final h = _habits[i];
                        return _HabitListTile(
                          habit: h,
                          onTap: () => _openEditor(h),
                          onDelete: () => _delete(h),
                        );
                      },
                    ),
      bottomBar: _habits.isEmpty
          ? null
          : Padding(
              padding: const EdgeInsets.all(AppTokens.space16),
              child: SynctraPrimaryButton(
                label: 'New habit',
                icon: Icons.add,
                expand: true,
                onPressed: () => _openEditor(),
              ),
            ),
    );
  }
}

/// Sentinel for "creating new habit" vs editing existing.
class _NewHabitMarker extends HabitModel {
  const _NewHabitMarker()
      : super(
          id: '',
          userId: '',
          title: '',
          durationMinutes: 60,
          frequencyPerWeek: 5,
          preferredDays: const [],
          preferredTimeRanges: const {},
          priority: 7,
        );
}

class _HabitListTile extends StatelessWidget {
  const _HabitListTile({
    required this.habit,
    required this.onTap,
    required this.onDelete,
  });

  final HabitModel habit;
  final VoidCallback onTap;
  final VoidCallback onDelete;

  String get _priorityLabel {
    if (habit.priority >= 9) return 'Critical';
    if (habit.priority >= 7) return 'High';
    if (habit.priority >= 4) return 'Medium';
    return 'Low';
  }

  @override
  Widget build(BuildContext context) {
    final days = habit.preferredDays.map(HabitModel.dayLabel).join(' · ');
    return Material(
      color: AppColors.surface,
      borderRadius: BorderRadius.circular(AppTokens.radiusMd),
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(AppTokens.radiusMd),
        child: Container(
          padding: const EdgeInsets.all(AppTokens.space16),
          decoration: BoxDecoration(
            borderRadius: BorderRadius.circular(AppTokens.radiusMd),
            border: Border.all(color: AppColors.border),
          ),
          child: Row(
            children: [
              Container(
                width: 12,
                height: 12,
                decoration: const BoxDecoration(
                  color: AppColors.habitBlock,
                  shape: BoxShape.circle,
                ),
              ),
              const SizedBox(width: AppTokens.space12),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      habit.title,
                      style: GoogleFonts.inter(
                        fontSize: 16,
                        fontWeight: FontWeight.w600,
                      ),
                    ),
                    const SizedBox(height: AppTokens.space4),
                    Text(
                      '${habit.durationMinutes} min · $_priorityLabel · ${habit.frequencyPerWeek}×/week',
                      style: GoogleFonts.inter(
                        fontSize: 13,
                        color: AppColors.textTertiary,
                      ),
                    ),
                    if (days.isNotEmpty)
                      Text(
                        days,
                        style: GoogleFonts.inter(
                          fontSize: 12,
                          color: AppColors.textTertiary,
                        ),
                      ),
                  ],
                ),
              ),
              IconButton(
                icon: const Icon(Icons.chevron_right),
                onPressed: onTap,
              ),
              IconButton(
                icon: const Icon(Icons.delete_outline, size: 20),
                onPressed: onDelete,
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _EmptyState extends StatelessWidget {
  const _EmptyState({required this.onCreate});

  final VoidCallback onCreate;

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(AppTokens.space32),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(
              Icons.repeat,
              size: 48,
              color: AppColors.primary.withValues(alpha: 0.6),
            ),
            const SizedBox(height: AppTokens.space16),
            Text(
              'No habits yet',
              style: GoogleFonts.inter(
                fontSize: 20,
                fontWeight: FontWeight.w600,
              ),
            ),
            const SizedBox(height: AppTokens.space8),
            Text(
              'Create flexible routines like lunch, gym, or focus time. '
              'Synctra schedules them around your classes.',
              textAlign: TextAlign.center,
              style: GoogleFonts.inter(
                fontSize: 14,
                color: AppColors.textSecondary,
                height: 1.5,
              ),
            ),
            const SizedBox(height: AppTokens.space24),
            SynctraPrimaryButton(
              label: 'Create your first habit',
              icon: Icons.add,
              onPressed: onCreate,
            ),
          ],
        ),
      ),
    );
  }
}

class _ErrorState extends StatelessWidget {
  const _ErrorState({required this.message, required this.onRetry});

  final String message;
  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(AppTokens.space24),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Text(message, textAlign: TextAlign.center),
            const SizedBox(height: AppTokens.space16),
            OutlinedButton(onPressed: onRetry, child: const Text('Retry')),
          ],
        ),
      ),
    );
  }
}

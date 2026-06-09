import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';

import '../../../core/theme/app_tokens.dart';
import '../../../data/models/habit_model.dart';
import '../../../shared/widgets/synctra_page_scaffold.dart';
import '../../../theme.dart';

/// Reclaim-style habit create / edit form.
class HabitEditView extends StatefulWidget {
  const HabitEditView({
    super.key,
    required this.onSave,
    required this.onCancel,
    this.habit,
  });

  final HabitModel? habit;
  final Future<void> Function(Map<String, dynamic> payload, String? id) onSave;
  final VoidCallback onCancel;

  @override
  State<HabitEditView> createState() => _HabitEditViewState();
}

class _HabitEditViewState extends State<HabitEditView> {
  late final TextEditingController _title;
  late final TextEditingController _notes;
  late int _durationMin;
  late int _durationMax;
  late int _priority;
  late Set<int> _days;
  late Map<String, List<HabitTimeRange>> _ranges;
  late String _emoji;
  late String _category;
  late Color _habitColor;
  late String _hoursType;
  late bool _removeOnConflict;
  bool _saving = false;

  static const _defaultDays = [0, 1, 2, 3, 4];
  static const _defaultRange = HabitTimeRange(start: '11:30am', end: '2:00pm');

  /// Display order: Su … Sa (backend weekday in parens).
  static const _dayOrder = [
    (6, 'Su', 'Sunday'),
    (0, 'Mo', 'Monday'),
    (1, 'Tu', 'Tuesday'),
    (2, 'We', 'Wednesday'),
    (3, 'Th', 'Thursday'),
    (4, 'Fr', 'Friday'),
    (5, 'Sa', 'Saturday'),
  ];

  static const _priorityLevels = [10, 9, 8, 7, 6, 5, 4, 3, 2, 1];

  static String _priorityLabel(int value) {
    final tier = switch (value) {
      >= 9 => 'Critical',
      >= 7 => 'High',
      >= 5 => 'Medium',
      _ => 'Low',
    };
    return '$tier ($value)';
  }

  static IconData _priorityIcon(int value) => switch (value) {
        >= 9 => Icons.signal_cellular_alt,
        >= 7 => Icons.signal_cellular_alt_2_bar,
        >= 5 => Icons.signal_cellular_alt_1_bar,
        _ => Icons.signal_cellular_0_bar,
      };

  static const _categories = ['Personal', 'Work', 'Health', 'Learning'];
  static const _habitColors = [
    Color(0xFFE05D52),
    Color(0xFF6366F1),
    Color(0xFF2D9E6E),
    Color(0xFFF9AB00),
    Color(0xFF7C5CBF),
  ];

  @override
  void initState() {
    super.initState();
    final h = widget.habit;
    _title = TextEditingController(text: h?.title ?? '');
    _notes = TextEditingController();
    _durationMin = h?.durationMinutes ?? 30;
    _durationMax = (h?.durationMinutes ?? 60).clamp(_durationMin, 180);
    _priority = (h?.priority ?? 9).clamp(1, 10);
    _days = Set<int>.from(h?.preferredDays ?? _defaultDays);
    _ranges = Map<String, List<HabitTimeRange>>.from(
      h?.preferredTimeRanges ??
          {for (final d in _defaultDays) d.toString(): const [_defaultRange]},
    );
    _emoji = _emojiForTitle(h?.title ?? '');
    _category = 'Personal';
    _habitColor = AppColors.habitBlock;
    _hoursType = 'One-off hours';
    _removeOnConflict = false;
  }

  @override
  void dispose() {
    _title.dispose();
    _notes.dispose();
    super.dispose();
  }

  String _emojiForTitle(String title) {
    final t = title.toLowerCase();
    if (t.contains('lunch')) return '🍱';
    if (t.contains('gym') || t.contains('workout')) return '💪';
    if (t.contains('focus') || t.contains('study')) return '📚';
    if (t.contains('walk')) return '🚶';
    return '✨';
  }

  int get _frequency => _days.length;

  String get _frequencySummary {
    if (_days.isEmpty) return 'Select days to repeat this habit.';
    final names = _dayOrder
        .where((d) => _days.contains(d.$1))
        .map((d) => d.$3)
        .toList();
    if (names.length == 7) {
      return 'Repeat $_frequency times every week on all days.';
    }
    if (names.length >= 2 &&
        _isConsecutiveWeekdays(names)) {
      return 'Repeat $_frequency times every week on ${names.first} through ${names.last}.';
    }
    return 'Repeat $_frequency times every week on ${names.join(', ')}.';
  }

  bool _isConsecutiveWeekdays(List<String> names) {
    const order = [
      'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday',
    ];
    final idx = names.map(order.indexOf).toList()..sort();
    for (var i = 1; i < idx.length; i++) {
      if (idx[i] != idx[i - 1] + 1) return false;
    }
    return true;
  }

  void _toggleDay(int backendDay) {
    setState(() {
      if (_days.contains(backendDay)) {
        if (_days.length <= 1) return;
        _days.remove(backendDay);
        _ranges.remove(backendDay.toString());
      } else {
        _days.add(backendDay);
        _ranges.putIfAbsent(backendDay.toString(), () => const [_defaultRange]);
      }
    });
  }

  void _copyFirstRangeToAll() {
    final sorted = _days.toList()..sort();
    if (sorted.isEmpty) return;
    final template = List<HabitTimeRange>.from(
      _ranges[sorted.first.toString()] ?? const [_defaultRange],
    );
    setState(() {
      for (final d in sorted) {
        _ranges[d.toString()] = template
            .map((r) => HabitTimeRange(start: r.start, end: r.end))
            .toList();
      }
    });
  }

  void _addRangeForDay(int day) {
    setState(() {
      final key = day.toString();
      final list = List<HabitTimeRange>.from(_ranges[key] ?? const [_defaultRange]);
      list.add(const HabitTimeRange(start: '6:00pm', end: '9:00pm'));
      _ranges[key] = list;
    });
  }

  Future<void> _save() async {
    final title = _title.text.trim();
    if (title.isEmpty) return;
    setState(() => _saving = true);
    try {
      final payload = {
        'title': title,
        'duration_minutes': _durationMin,
        'frequency_per_week': _frequency,
        'preferred_days': _days.toList()..sort(),
        'preferred_time_ranges': {
          for (final d in _days)
            d.toString(): [
              for (final r in (_ranges[d.toString()] ?? const [_defaultRange]))
                r.toJson(),
            ],
        },
        'priority': _priority,
        'is_active': true,
      };
      await widget.onSave(payload, widget.habit?.id);
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Save failed: $e')),
        );
      }
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final isEdit = widget.habit != null;
    return Scaffold(
      backgroundColor: AppColors.grey100,
      body: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          _buildTopBar(context, isEdit),
          Expanded(
            child: SingleChildScrollView(
              child: SynctraPageContent(
                maxWidth: 720,
                padding: const EdgeInsets.fromLTRB(24, 8, 24, 48),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    _FrequencyBanner(summary: _frequencySummary, dayCount: _days.length),
                    const SizedBox(height: AppTokens.space24),
                    _TitleField(
                      controller: _title,
                      emoji: _emoji,
                      onEmojiTap: () {
                        setState(() {
                          const options = ['🍱', '💪', '📚', '🚶', '☕', '✨', '🧘', '🏃'];
                          final i = options.indexOf(_emoji);
                          _emoji = options[(i + 1) % options.length];
                        });
                      },
                    ),
                    const SizedBox(height: AppTokens.space20),
                    _LabeledField(
                      label: 'Priority',
                      child: _PrioritySelect(
                        value: _priority,
                        onChanged: (v) => setState(() => _priority = v),
                      ),
                    ),
                    const SizedBox(height: AppTokens.space16),
                    _SectionLabel(
                      label: 'Color & Category',
                      trailing: Icon(
                        Icons.info_outline,
                        size: 16,
                        color: AppColors.textTertiary,
                      ),
                    ),
                    const SizedBox(height: AppTokens.space8),
                    Row(
                      children: [
                        Expanded(
                          child: _ColorSelect(
                            value: _habitColor,
                            colors: _habitColors,
                            onChanged: (c) => setState(() => _habitColor = c),
                          ),
                        ),
                        const SizedBox(width: AppTokens.space12),
                        Expanded(
                          child: _CategorySelect(
                            value: _category,
                            options: _categories,
                            onChanged: (v) => setState(() => _category = v),
                          ),
                        ),
                      ],
                    ),
                    const SizedBox(height: AppTokens.space24),
                    _SectionHeader(
                      title: 'Duration',
                      subtitle: 'How long should each session be?',
                    ),
                    const SizedBox(height: AppTokens.space12),
                    Row(
                      children: [
                        Expanded(
                          child: _DurationStepper(
                            label: 'Minimum',
                            minutes: _durationMin,
                            onChanged: (v) => setState(() {
                              _durationMin = v;
                              if (_durationMax < v) _durationMax = v;
                            }),
                          ),
                        ),
                        const SizedBox(width: AppTokens.space16),
                        Expanded(
                          child: _DurationStepper(
                            label: 'Maximum',
                            minutes: _durationMax,
                            onChanged: (v) => setState(() {
                              _durationMax = v;
                              if (_durationMin > v) _durationMin = v;
                            }),
                          ),
                        ),
                      ],
                    ),
                    const SizedBox(height: AppTokens.space24),
                    _SectionHeader(
                      title: 'Scheduling',
                      subtitle:
                          'Set the scheduling hours, frequency, and ideal days & times for your Habit.',
                    ),
                    const SizedBox(height: AppTokens.space16),
                    _LabeledField(
                      label: 'Hours',
                      child: _DropdownShell<String>(
                        value: _hoursType,
                        items: const ['One-off hours', 'Anytime', 'Morning', 'Afternoon', 'Evening'],
                        itemLabel: (v) => v,
                        onChanged: (v) => setState(() => _hoursType = v ?? _hoursType),
                      ),
                    ),
                    const SizedBox(height: AppTokens.space16),
                    _DayPillRow(
                      days: _dayOrder,
                      selected: _days,
                      onToggle: _toggleDay,
                    ),
                    const SizedBox(height: AppTokens.space20),
                    for (final (day, _, fullName) in _dayOrder)
                      if (_days.contains(day)) ...[
                        _DayScheduleRow(
                          dayName: fullName,
                          ranges: _ranges[day.toString()] ?? const [_defaultRange],
                          showCopyToAll: day == (_days.toList()..sort()).first,
                          onCopyToAll: _copyFirstRangeToAll,
                          onRangeChanged: (i, r) => setState(() {
                            final list = List<HabitTimeRange>.from(
                              _ranges[day.toString()] ?? const [_defaultRange],
                            );
                            list[i] = r;
                            _ranges[day.toString()] = list;
                          }),
                          onAddRange: () => _addRangeForDay(day),
                        ),
                        const SizedBox(height: AppTokens.space12),
                      ],
                    const SizedBox(height: AppTokens.space24),
                    _SectionHeader(
                      title: 'If your Habit can\'t be scheduled…',
                      subtitle: null,
                    ),
                    const SizedBox(height: AppTokens.space12),
                    _ConflictOption(
                      label: 'Leave it on the calendar',
                      selected: !_removeOnConflict,
                      onTap: () => setState(() => _removeOnConflict = false),
                    ),
                    const SizedBox(height: AppTokens.space8),
                    _ConflictOption(
                      label: 'Remove it from the calendar',
                      selected: _removeOnConflict,
                      onTap: () => setState(() => _removeOnConflict = true),
                    ),
                    const SizedBox(height: AppTokens.space24),
                    _SectionHeader(title: 'Other details', subtitle: null),
                    const SizedBox(height: AppTokens.space12),
                    TextField(
                      controller: _notes,
                      maxLines: 4,
                      decoration: InputDecoration(
                        hintText: 'Add notes here…',
                        filled: true,
                        fillColor: AppColors.surface,
                        border: OutlineInputBorder(
                          borderRadius: BorderRadius.circular(AppTokens.radiusMd),
                          borderSide: const BorderSide(color: AppColors.border),
                        ),
                        enabledBorder: OutlineInputBorder(
                          borderRadius: BorderRadius.circular(AppTokens.radiusMd),
                          borderSide: const BorderSide(color: AppColors.border),
                        ),
                      ),
                    ),
                    const SizedBox(height: AppTokens.space8),
                    Text(
                      'Notes are saved locally for now.',
                      style: Theme.of(context).textTheme.bodySmall?.copyWith(
                            color: AppColors.textTertiary,
                          ),
                    ),
                    const SizedBox(height: AppTokens.space32),
                    Row(
                      children: [
                        SynctraPrimaryButton(
                          label: _saving ? 'Saving…' : 'Save',
                          onPressed: _saving ? null : _save,
                        ),
                        const SizedBox(width: AppTokens.space16),
                        SynctraGhostButton(
                          label: 'Cancel',
                          onPressed: widget.onCancel,
                        ),
                      ],
                    ),
                    const SizedBox(height: AppTokens.space24),
                    TextButton(
                      onPressed: () {},
                      style: TextButton.styleFrom(
                        foregroundColor: AppColors.primary,
                        alignment: Alignment.centerLeft,
                      ),
                      child: const Text('Make Time for Your Habits  ›'),
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

  Widget _buildTopBar(BuildContext context, bool isEdit) {
    return Material(
      color: AppColors.surface,
      child: Container(
        height: AppTokens.pageTopBarHeight,
        padding: const EdgeInsets.symmetric(horizontal: AppTokens.space16),
        decoration: const BoxDecoration(
          border: Border(bottom: BorderSide(color: AppColors.border)),
        ),
        child: Row(
          children: [
            TextButton.icon(
              onPressed: widget.onCancel,
              icon: const Icon(Icons.arrow_back, size: 18),
              label: const Text('Back'),
              style: TextButton.styleFrom(
                foregroundColor: AppColors.textSecondary,
                padding: EdgeInsets.zero,
              ),
            ),
            const Spacer(),
            Text(
              isEdit ? 'Habit / Edit' : 'Habit / New',
              style: GoogleFonts.inter(
                fontSize: 13,
                color: AppColors.textTertiary,
                fontWeight: FontWeight.w500,
              ),
            ),
          ],
        ),
      ),
    );
  }
}

// ── Sub-widgets ───────────────────────────────────────────────────────────────

class _FrequencyBanner extends StatelessWidget {
  const _FrequencyBanner({required this.summary, required this.dayCount});

  final String summary;
  final int dayCount;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(AppTokens.space16),
      decoration: BoxDecoration(
        color: AppColors.surface,
        borderRadius: BorderRadius.circular(AppTokens.radiusMd),
        border: Border.all(color: AppColors.border),
      ),
      child: Row(
        children: [
          Row(
            children: List.generate(
              dayCount.clamp(0, 7),
              (i) => Padding(
                padding: EdgeInsets.only(right: i < dayCount - 1 ? 4 : 0),
                child: Container(
                  width: 22,
                  height: 22,
                  decoration: BoxDecoration(
                    color: AppColors.success.withValues(alpha: 0.15),
                    shape: BoxShape.circle,
                    border: Border.all(color: AppColors.success, width: 1.5),
                  ),
                  child: const Icon(Icons.check, size: 12, color: AppColors.success),
                ),
              ),
            ),
          ),
          const SizedBox(width: AppTokens.space12),
          Expanded(
            child: Text(
              summary,
              style: GoogleFonts.inter(
                fontSize: 13,
                color: AppColors.textSecondary,
                height: 1.4,
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _TitleField extends StatelessWidget {
  const _TitleField({
    required this.controller,
    required this.emoji,
    required this.onEmojiTap,
  });

  final TextEditingController controller;
  final String emoji;
  final VoidCallback onEmojiTap;

  @override
  Widget build(BuildContext context) {
    return TextField(
      controller: controller,
      style: GoogleFonts.inter(fontSize: 28, fontWeight: FontWeight.w600),
      decoration: InputDecoration(
        filled: true,
        fillColor: AppColors.surface,
        prefixIcon: GestureDetector(
          onTap: onEmojiTap,
          child: Padding(
            padding: const EdgeInsets.symmetric(horizontal: 12),
            child: Text(emoji, style: const TextStyle(fontSize: 22)),
          ),
        ),
        prefixIconConstraints: const BoxConstraints(minWidth: 48),
        hintText: 'Lunch',
        border: OutlineInputBorder(
          borderRadius: BorderRadius.circular(AppTokens.radiusMd),
          borderSide: const BorderSide(color: AppColors.border),
        ),
        enabledBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(AppTokens.radiusMd),
          borderSide: const BorderSide(color: AppColors.border),
        ),
        contentPadding: const EdgeInsets.symmetric(vertical: 16, horizontal: 8),
      ),
    );
  }
}

class _SectionHeader extends StatelessWidget {
  const _SectionHeader({required this.title, this.subtitle});

  final String title;
  final String? subtitle;

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          title,
          style: GoogleFonts.inter(
            fontSize: 15,
            fontWeight: FontWeight.w600,
            color: AppColors.textPrimary,
          ),
        ),
        if (subtitle != null) ...[
          const SizedBox(height: AppTokens.space4),
          Text(
            subtitle!,
            style: GoogleFonts.inter(
              fontSize: 13,
              color: AppColors.textTertiary,
              height: 1.4,
            ),
          ),
        ],
      ],
    );
  }
}

class _SectionLabel extends StatelessWidget {
  const _SectionLabel({required this.label, this.trailing});

  final String label;
  final Widget? trailing;

  @override
  Widget build(BuildContext context) {
    return Row(
      children: [
        Text(
          label,
          style: GoogleFonts.inter(
            fontSize: 13,
            fontWeight: FontWeight.w500,
            color: AppColors.textSecondary,
          ),
        ),
        if (trailing != null) ...[
          const SizedBox(width: AppTokens.space4),
          trailing!,
        ],
      ],
    );
  }
}

class _LabeledField extends StatelessWidget {
  const _LabeledField({required this.label, required this.child});

  final String label;
  final Widget child;

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          label,
          style: GoogleFonts.inter(
            fontSize: 13,
            fontWeight: FontWeight.w500,
            color: AppColors.textSecondary,
          ),
        ),
        const SizedBox(height: AppTokens.space8),
        child,
      ],
    );
  }
}

class _PrioritySelect extends StatelessWidget {
  const _PrioritySelect({required this.value, required this.onChanged});

  final int value;
  final ValueChanged<int> onChanged;

  @override
  Widget build(BuildContext context) {
    final safeValue = value.clamp(1, 10);

    return _DropdownShell<int>(
      value: safeValue,
      items: _HabitEditViewState._priorityLevels,
      itemLabel: _HabitEditViewState._priorityLabel,
      leading: Icon(
        _HabitEditViewState._priorityIcon(safeValue),
        size: 18,
        color: AppColors.textSecondary,
      ),
      displayLabel: _HabitEditViewState._priorityLabel(safeValue),
      onChanged: (v) {
        if (v != null) onChanged(v);
      },
    );
  }
}

class _ColorSelect extends StatelessWidget {
  const _ColorSelect({
    required this.value,
    required this.colors,
    required this.onChanged,
  });

  final Color value;
  final List<Color> colors;
  final ValueChanged<Color> onChanged;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 4),
      decoration: BoxDecoration(
        color: AppColors.surface,
        borderRadius: BorderRadius.circular(AppTokens.radiusMd),
        border: Border.all(color: AppColors.border),
      ),
      child: DropdownButtonHideUnderline(
        child: DropdownButton<Color>(
          value: value,
          isExpanded: true,
          items: [
            for (final c in colors)
              DropdownMenuItem(
                value: c,
                child: Row(
                  children: [
                    Container(
                      width: 16,
                      height: 16,
                      decoration: BoxDecoration(color: c, shape: BoxShape.circle),
                    ),
                    const SizedBox(width: 8),
                    Text(_colorName(c)),
                  ],
                ),
              ),
          ],
          onChanged: (c) {
            if (c != null) onChanged(c);
          },
        ),
      ),
    );
  }

  String _colorName(Color c) {
    if (c == AppColors.habitBlock) return 'Coral';
    if (c == AppColors.primary) return 'Purple';
    if (c == AppColors.success) return 'Green';
    if (c == AppColors.secondary) return 'Gold';
    return 'Violet';
  }
}

class _CategorySelect extends StatelessWidget {
  const _CategorySelect({
    required this.value,
    required this.options,
    required this.onChanged,
  });

  final String value;
  final List<String> options;
  final ValueChanged<String> onChanged;

  @override
  Widget build(BuildContext context) {
    return _DropdownShell<String>(
      value: value,
      items: options,
      itemLabel: (v) => v,
      onChanged: (v) {
        if (v != null) onChanged(v);
      },
    );
  }
}

class _DropdownShell<T> extends StatelessWidget {
  const _DropdownShell({
    required this.value,
    required this.items,
    required this.itemLabel,
    required this.onChanged,
    this.leading,
    this.displayLabel,
  });

  final T value;
  final List<T> items;
  final String Function(T) itemLabel;
  final ValueChanged<T?> onChanged;
  final Widget? leading;
  final String? displayLabel;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 12),
      decoration: BoxDecoration(
        color: AppColors.surface,
        borderRadius: BorderRadius.circular(AppTokens.radiusMd),
        border: Border.all(color: AppColors.border),
      ),
      child: DropdownButtonHideUnderline(
        child: DropdownButton<T>(
          value: value,
          isExpanded: true,
          icon: const Icon(Icons.keyboard_arrow_down, size: 20),
          items: [
            for (final item in items)
              DropdownMenuItem(value: item, child: Text(itemLabel(item))),
          ],
          selectedItemBuilder: (context) => [
            for (final item in items)
              Align(
                alignment: Alignment.centerLeft,
                child: Row(
                  children: [
                    if (leading != null && item == value) ...[
                      leading!,
                      const SizedBox(width: 8),
                    ],
                    Text(displayLabel ?? itemLabel(item)),
                  ],
                ),
              ),
          ],
          onChanged: onChanged,
        ),
      ),
    );
  }
}

class _DayPillRow extends StatelessWidget {
  const _DayPillRow({
    required this.days,
    required this.selected,
    required this.onToggle,
  });

  final List<(int, String, String)> days;
  final Set<int> selected;
  final ValueChanged<int> onToggle;

  @override
  Widget build(BuildContext context) {
    return Row(
      children: [
        for (final (backendDay, short, _) in days) ...[
          _DayPill(
            label: short,
            selected: selected.contains(backendDay),
            onTap: () => onToggle(backendDay),
          ),
          if (backendDay != days.last.$1) const SizedBox(width: 8),
        ],
      ],
    );
  }
}

class _DayPill extends StatelessWidget {
  const _DayPill({
    required this.label,
    required this.selected,
    required this.onTap,
  });

  final String label;
  final bool selected;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return Material(
      color: selected ? AppColors.primary : AppColors.surface,
      shape: const CircleBorder(
        side: BorderSide(color: AppColors.border),
      ),
      child: InkWell(
        onTap: onTap,
        customBorder: const CircleBorder(),
        child: SizedBox(
          width: 40,
          height: 40,
          child: Center(
            child: Text(
              label,
              style: GoogleFonts.inter(
                fontSize: 12,
                fontWeight: FontWeight.w600,
                color: selected ? Colors.white : AppColors.textSecondary,
              ),
            ),
          ),
        ),
      ),
    );
  }
}

class _DayScheduleRow extends StatelessWidget {
  const _DayScheduleRow({
    required this.dayName,
    required this.ranges,
    required this.showCopyToAll,
    required this.onCopyToAll,
    required this.onRangeChanged,
    required this.onAddRange,
  });

  final String dayName;
  final List<HabitTimeRange> ranges;
  final bool showCopyToAll;
  final VoidCallback onCopyToAll;
  final void Function(int index, HabitTimeRange range) onRangeChanged;
  final VoidCallback onAddRange;

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        for (var i = 0; i < ranges.length; i++) ...[
          Row(
            crossAxisAlignment: CrossAxisAlignment.center,
            children: [
              SizedBox(
                width: 88,
                child: Text(
                  i == 0 ? dayName : '',
                  style: GoogleFonts.inter(
                    fontSize: 14,
                    fontWeight: FontWeight.w500,
                  ),
                ),
              ),
              Expanded(
                child: _TimeInput(
                  value: ranges[i].start,
                  onChanged: (v) => onRangeChanged(i, ranges[i].copyWith(start: v)),
                ),
              ),
              Padding(
                padding: const EdgeInsets.symmetric(horizontal: 8),
                child: Text('to', style: TextStyle(color: AppColors.textTertiary)),
              ),
              Expanded(
                child: _TimeInput(
                  value: ranges[i].end,
                  onChanged: (v) => onRangeChanged(i, ranges[i].copyWith(end: v)),
                ),
              ),
              IconButton(
                icon: const Icon(Icons.add, color: AppColors.primary, size: 20),
                onPressed: onAddRange,
                tooltip: 'Add time range',
              ),
              if (showCopyToAll && i == 0)
                TextButton.icon(
                  onPressed: onCopyToAll,
                  icon: const Icon(Icons.copy, size: 14),
                  label: const Text('Copy to all'),
                  style: TextButton.styleFrom(
                    foregroundColor: AppColors.primary,
                    visualDensity: VisualDensity.compact,
                  ),
                ),
            ],
          ),
        ],
      ],
    );
  }
}

class _TimeInput extends StatefulWidget {
  const _TimeInput({required this.value, required this.onChanged});

  final String value;
  final ValueChanged<String> onChanged;

  @override
  State<_TimeInput> createState() => _TimeInputState();
}

class _TimeInputState extends State<_TimeInput> {
  late TextEditingController _controller;

  @override
  void initState() {
    super.initState();
    _controller = TextEditingController(text: widget.value);
  }

  @override
  void didUpdateWidget(covariant _TimeInput oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.value != widget.value && _controller.text != widget.value) {
      _controller.text = widget.value;
    }
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return TextField(
      controller: _controller,
      onChanged: widget.onChanged,
      style: GoogleFonts.inter(fontSize: 14),
      decoration: InputDecoration(
        isDense: true,
        filled: true,
        fillColor: AppColors.surface,
        contentPadding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
        border: OutlineInputBorder(
          borderRadius: BorderRadius.circular(AppTokens.radiusMd),
          borderSide: const BorderSide(color: AppColors.border),
        ),
        enabledBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(AppTokens.radiusMd),
          borderSide: const BorderSide(color: AppColors.border),
        ),
      ),
    );
  }
}

class _DurationStepper extends StatelessWidget {
  const _DurationStepper({
    required this.label,
    required this.minutes,
    required this.onChanged,
  });

  final String label;
  final int minutes;
  final ValueChanged<int> onChanged;

  String get _label {
    if (minutes < 60) return '$minutes mins';
    if (minutes % 60 == 0) return '${minutes ~/ 60} hr';
    return '${minutes ~/ 60} hr ${minutes % 60} mins';
  }

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          label,
          style: GoogleFonts.inter(fontSize: 13, color: AppColors.textSecondary),
        ),
        const SizedBox(height: AppTokens.space8),
        Container(
          padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
          decoration: BoxDecoration(
            color: AppColors.surface,
            borderRadius: BorderRadius.circular(AppTokens.radiusMd),
            border: Border.all(color: AppColors.border),
          ),
          child: Row(
            children: [
              _StepBtn(
                icon: Icons.remove,
                onTap: minutes > 15 ? () => onChanged(minutes - 15) : null,
              ),
              Expanded(
                child: Text(
                  _label,
                  textAlign: TextAlign.center,
                  style: GoogleFonts.inter(fontWeight: FontWeight.w500),
                ),
              ),
              _StepBtn(
                icon: Icons.add,
                onTap: minutes < 240 ? () => onChanged(minutes + 15) : null,
              ),
            ],
          ),
        ),
      ],
    );
  }
}

class _StepBtn extends StatelessWidget {
  const _StepBtn({required this.icon, required this.onTap});

  final IconData icon;
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) {
    return IconButton(
      onPressed: onTap,
      icon: Icon(icon, size: 18),
      visualDensity: VisualDensity.compact,
      color: AppColors.textSecondary,
    );
  }
}

class _ConflictOption extends StatelessWidget {
  const _ConflictOption({
    required this.label,
    required this.selected,
    required this.onTap,
  });

  final String label;
  final bool selected;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return Material(
      color: selected ? AppColors.grey100 : AppColors.surface,
      borderRadius: BorderRadius.circular(AppTokens.radiusMd),
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(AppTokens.radiusMd),
        child: Container(
          padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 14),
          decoration: BoxDecoration(
            borderRadius: BorderRadius.circular(AppTokens.radiusMd),
            border: Border.all(
              color: selected ? AppColors.primary.withValues(alpha: 0.4) : AppColors.border,
            ),
          ),
          child: Row(
            children: [
              Icon(
                selected ? Icons.radio_button_checked : Icons.radio_button_off,
                size: 20,
                color: selected ? AppColors.primary : AppColors.textTertiary,
              ),
              const SizedBox(width: AppTokens.space12),
              Text(label, style: GoogleFonts.inter(fontSize: 14)),
            ],
          ),
        ),
      ),
    );
  }
}

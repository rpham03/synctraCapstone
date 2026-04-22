// Main calendar view — displays fixed events and AI-suggested schedule blocks.
// On desktop: calendar on the left, day event list on the right.
// On mobile: stacked vertically with bottom FAB.
import 'package:flutter/material.dart';
import 'package:table_calendar/table_calendar.dart';
import 'package:intl/intl.dart';

import '../../../core/theme/app_theme.dart';
import '../../../core/utils/responsive.dart';
import '../../../data/models/event_model.dart';
import '../../../data/models/schedule_block_model.dart';

class CalendarScreen extends StatefulWidget {
  const CalendarScreen({super.key});

  @override
  State<CalendarScreen> createState() => _CalendarScreenState();
}

class _CalendarScreenState extends State<CalendarScreen> {
  DateTime _focusedDay  = DateTime.now();
  DateTime _selectedDay = DateTime.now();
  CalendarFormat _format = CalendarFormat.month;

  // TODO: replace with real data from repository
  final List<EventModel> _fixedEvents = [];
  final List<ScheduleBlockModel> _suggestedBlocks = [];

  List<dynamic> _eventsForDay(DateTime day) {
    final fixed  = _fixedEvents.where((e) => isSameDay(e.startTime, day)).toList();
    final blocks = _suggestedBlocks.where((b) => isSameDay(b.startTime, day)).toList();
    return [...fixed, ...blocks];
  }

  void _onDaySelected(DateTime selected, DateTime focused) {
    setState(() {
      _selectedDay = selected;
      _focusedDay  = focused;
    });
  }

  @override
  Widget build(BuildContext context) {
    return Responsive.isDesktop(context)
        ? _DesktopLayout(
            focusedDay:  _focusedDay,
            selectedDay: _selectedDay,
            format:      _format,
            eventsForDay: _eventsForDay,
            onDaySelected: _onDaySelected,
            onFormatChanged: (f) => setState(() => _format = f),
            onPageChanged: (f) => setState(() => _focusedDay = f),
          )
        : _MobileLayout(
            focusedDay:  _focusedDay,
            selectedDay: _selectedDay,
            format:      _format,
            eventsForDay: _eventsForDay,
            onDaySelected: _onDaySelected,
            onFormatChanged: (f) => setState(() => _format = f),
            onPageChanged: (f) => setState(() => _focusedDay = f),
          );
  }
}

// ── Desktop two-column layout ──────────────────────────────────────────────────

class _DesktopLayout extends StatelessWidget {
  final DateTime focusedDay;
  final DateTime selectedDay;
  final CalendarFormat format;
  final List<dynamic> Function(DateTime) eventsForDay;
  final void Function(DateTime, DateTime) onDaySelected;
  final void Function(CalendarFormat) onFormatChanged;
  final void Function(DateTime) onPageChanged;

  const _DesktopLayout({
    required this.focusedDay,
    required this.selectedDay,
    required this.format,
    required this.eventsForDay,
    required this.onDaySelected,
    required this.onFormatChanged,
    required this.onPageChanged,
  });

  @override
  Widget build(BuildContext context) {
    final dayEvents = eventsForDay(selectedDay);

    return Scaffold(
      appBar: AppBar(
        title: Row(children: [
          Text(
            DateFormat('MMMM yyyy').format(focusedDay),
            style: const TextStyle(fontWeight: FontWeight.bold),
          ),
        ]),
        actions: [
          // AI schedule button in the top bar on desktop
          FilledButton.icon(
            onPressed: () {/* TODO: trigger AI schedule generation */},
            icon: const Icon(Icons.auto_awesome, size: 18),
            label: const Text('Suggest Schedule'),
            style: FilledButton.styleFrom(backgroundColor: AppColors.primary),
          ),
          const SizedBox(width: 8),
          IconButton(icon: const Icon(Icons.sync), tooltip: 'Sync', onPressed: () {}),
          IconButton(icon: const Icon(Icons.person_outline), onPressed: () {}),
          const SizedBox(width: 8),
        ],
      ),
      body: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          // ── Left: full calendar ─────────────────────────────────
          Expanded(
            flex: 3,
            child: Column(
              children: [
                _CalendarWidget(
                  focusedDay: focusedDay,
                  selectedDay: selectedDay,
                  format: CalendarFormat.month, // always show month on desktop
                  eventsForDay: eventsForDay,
                  onDaySelected: onDaySelected,
                  onFormatChanged: onFormatChanged,
                  onPageChanged: onPageChanged,
                  showFormatButton: false,
                ),

                // Legend
                Padding(
                  padding: const EdgeInsets.fromLTRB(16, 8, 16, 12),
                  child: Row(children: [
                    _LegendDot(color: AppColors.fixedEvent,    label: 'Classes & Exams'),
                    const SizedBox(width: 16),
                    _LegendDot(color: AppColors.flexibleBlock, label: 'Study Blocks'),
                    const SizedBox(width: 16),
                    _LegendDot(color: AppColors.collabEvent,   label: 'Group Events'),
                    const SizedBox(width: 16),
                    _LegendDot(color: AppColors.deadline,      label: 'Deadlines'),
                  ]),
                ),
              ],
            ),
          ),

          const VerticalDivider(width: 1),

          // ── Right: event list for selected day ──────────────────
          SizedBox(
            width: 340,
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                // Day header
                Padding(
                  padding: const EdgeInsets.fromLTRB(16, 20, 16, 8),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        DateFormat('EEEE').format(selectedDay),
                        style: TextStyle(
                            color: Colors.grey[500], fontSize: 13),
                      ),
                      Text(
                        DateFormat('MMMM d, y').format(selectedDay),
                        style: const TextStyle(
                            fontWeight: FontWeight.bold, fontSize: 18),
                      ),
                      const SizedBox(height: 4),
                      Text(
                        '${dayEvents.length} event${dayEvents.length == 1 ? '' : 's'}',
                        style: TextStyle(color: Colors.grey[400], fontSize: 12),
                      ),
                    ],
                  ),
                ),
                const Divider(height: 1),

                // Events
                Expanded(
                  child: dayEvents.isEmpty
                      ? _EmptyDay(day: selectedDay)
                      : ListView.builder(
                          padding: const EdgeInsets.all(12),
                          itemCount: dayEvents.length,
                          itemBuilder: (_, i) {
                            final item = dayEvents[i];
                            if (item is EventModel)       return _FixedEventTile(event: item);
                            if (item is ScheduleBlockModel) return _BlockTile(block: item);
                            return const SizedBox.shrink();
                          },
                        ),
                ),

                // Add event button at bottom of panel
                Padding(
                  padding: const EdgeInsets.all(12),
                  child: OutlinedButton.icon(
                    onPressed: () {/* TODO: add event */},
                    icon: const Icon(Icons.add),
                    label: const Text('Add Event'),
                    style: OutlinedButton.styleFrom(
                      minimumSize: const Size.fromHeight(44),
                      shape: RoundedRectangleBorder(
                          borderRadius: BorderRadius.circular(10)),
                    ),
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

// ── Mobile stacked layout ─────────────────────────────────────────────────────

class _MobileLayout extends StatelessWidget {
  final DateTime focusedDay;
  final DateTime selectedDay;
  final CalendarFormat format;
  final List<dynamic> Function(DateTime) eventsForDay;
  final void Function(DateTime, DateTime) onDaySelected;
  final void Function(CalendarFormat) onFormatChanged;
  final void Function(DateTime) onPageChanged;

  const _MobileLayout({
    required this.focusedDay,
    required this.selectedDay,
    required this.format,
    required this.eventsForDay,
    required this.onDaySelected,
    required this.onFormatChanged,
    required this.onPageChanged,
  });

  @override
  Widget build(BuildContext context) {
    final dayEvents = eventsForDay(selectedDay);

    return Scaffold(
      appBar: AppBar(
        title: const Text('Synctra'),
        actions: [
          IconButton(icon: const Icon(Icons.person_outline), onPressed: () {}),
        ],
      ),
      body: Column(
        children: [
          _CalendarWidget(
            focusedDay: focusedDay,
            selectedDay: selectedDay,
            format: format,
            eventsForDay: eventsForDay,
            onDaySelected: onDaySelected,
            onFormatChanged: onFormatChanged,
            onPageChanged: onPageChanged,
            showFormatButton: true,
          ),
          const Divider(height: 1),
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 10, 16, 4),
            child: Row(
              mainAxisAlignment: MainAxisAlignment.spaceBetween,
              children: [
                Text(
                  DateFormat('EEEE, MMM d').format(selectedDay),
                  style: const TextStyle(fontWeight: FontWeight.w600, fontSize: 15),
                ),
                Text(
                  '${dayEvents.length} event${dayEvents.length == 1 ? '' : 's'}',
                  style: TextStyle(color: Colors.grey[500], fontSize: 13),
                ),
              ],
            ),
          ),
          Expanded(
            child: dayEvents.isEmpty
                ? _EmptyDay(day: selectedDay)
                : ListView.builder(
                    padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
                    itemCount: dayEvents.length,
                    itemBuilder: (_, i) {
                      final item = dayEvents[i];
                      if (item is EventModel)       return _FixedEventTile(event: item);
                      if (item is ScheduleBlockModel) return _BlockTile(block: item);
                      return const SizedBox.shrink();
                    },
                  ),
          ),
        ],
      ),
      floatingActionButton: FloatingActionButton.extended(
        onPressed: () {/* TODO: trigger AI schedule generation */},
        icon: const Icon(Icons.auto_awesome),
        label: const Text('Suggest Schedule'),
        backgroundColor: AppColors.primary,
      ),
    );
  }
}

// ── Shared calendar widget ─────────────────────────────────────────────────────

class _CalendarWidget extends StatelessWidget {
  final DateTime focusedDay;
  final DateTime selectedDay;
  final CalendarFormat format;
  final List<dynamic> Function(DateTime) eventsForDay;
  final void Function(DateTime, DateTime) onDaySelected;
  final void Function(CalendarFormat) onFormatChanged;
  final void Function(DateTime) onPageChanged;
  final bool showFormatButton;

  const _CalendarWidget({
    required this.focusedDay,
    required this.selectedDay,
    required this.format,
    required this.eventsForDay,
    required this.onDaySelected,
    required this.onFormatChanged,
    required this.onPageChanged,
    required this.showFormatButton,
  });

  @override
  Widget build(BuildContext context) {
    return TableCalendar(
      firstDay: DateTime.utc(2024, 1, 1),
      lastDay: DateTime.utc(2030, 12, 31),
      focusedDay: focusedDay,
      calendarFormat: format,
      selectedDayPredicate: (d) => isSameDay(selectedDay, d),
      eventLoader: eventsForDay,
      onDaySelected: onDaySelected,
      onFormatChanged: onFormatChanged,
      onPageChanged: onPageChanged,
      calendarStyle: CalendarStyle(
        todayDecoration: BoxDecoration(
          color: AppColors.primary.withAlpha(60),
          shape: BoxShape.circle,
        ),
        selectedDecoration: const BoxDecoration(
          color: AppColors.primary,
          shape: BoxShape.circle,
        ),
        markerDecoration: const BoxDecoration(
          color: AppColors.flexibleBlock,
          shape: BoxShape.circle,
        ),
      ),
      headerStyle: HeaderStyle(
        formatButtonVisible: showFormatButton,
        titleCentered: true,
      ),
    );
  }
}

// ── Shared sub-widgets ─────────────────────────────────────────────────────────

class _EmptyDay extends StatelessWidget {
  final DateTime day;
  const _EmptyDay({required this.day});

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(Icons.event_available, size: 48, color: Colors.grey[300]),
          const SizedBox(height: 12),
          Text('Nothing scheduled', style: TextStyle(color: Colors.grey[500])),
          const SizedBox(height: 4),
          Text(
            'Ask the AI to suggest a schedule for this day.',
            style: TextStyle(color: Colors.grey[400], fontSize: 12),
          ),
        ],
      ),
    );
  }
}

class _FixedEventTile extends StatelessWidget {
  final EventModel event;
  const _FixedEventTile({required this.event});

  @override
  Widget build(BuildContext context) {
    final time = '${_fmt(event.startTime)} – ${_fmt(event.endTime)}';
    return Card(
      margin: const EdgeInsets.only(bottom: 8),
      child: ListTile(
        leading: Container(
          width: 4, height: 40,
          decoration: BoxDecoration(
            color: AppColors.fixedEvent,
            borderRadius: BorderRadius.circular(2),
          ),
        ),
        title: Text(event.title,
            style: const TextStyle(fontWeight: FontWeight.w600)),
        subtitle: Text(time),
        trailing: _SourceBadge(source: event.source),
      ),
    );
  }

  String _fmt(DateTime dt) => DateFormat('h:mm a').format(dt);
}

class _BlockTile extends StatelessWidget {
  final ScheduleBlockModel block;
  const _BlockTile({required this.block});

  @override
  Widget build(BuildContext context) {
    final time = '${_fmt(block.startTime)} – ${_fmt(block.endTime)}';
    return Card(
      margin: const EdgeInsets.only(bottom: 8),
      child: ListTile(
        leading: Container(
          width: 4, height: 40,
          decoration: BoxDecoration(
            color: AppColors.flexibleBlock,
            borderRadius: BorderRadius.circular(2),
          ),
        ),
        title: Text(block.taskTitle,
            style: const TextStyle(fontWeight: FontWeight.w600)),
        subtitle: Text(time),
        trailing: block.isAiGenerated
            ? const Icon(Icons.auto_awesome, size: 16, color: Colors.grey)
            : null,
      ),
    );
  }

  String _fmt(DateTime dt) => DateFormat('h:mm a').format(dt);
}

class _SourceBadge extends StatelessWidget {
  final String source;
  const _SourceBadge({required this.source});

  @override
  Widget build(BuildContext context) {
    final label = switch (source) {
      'canvas'          => 'Canvas',
      'google_calendar' => 'GCal',
      _                 => 'Manual',
    };
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
      decoration: BoxDecoration(
        color: Colors.grey[100],
        borderRadius: BorderRadius.circular(8),
      ),
      child: Text(label, style: TextStyle(fontSize: 11, color: Colors.grey[600])),
    );
  }
}

class _LegendDot extends StatelessWidget {
  final Color color;
  final String label;
  const _LegendDot({required this.color, required this.label});

  @override
  Widget build(BuildContext context) {
    return Row(children: [
      Container(
        width: 10, height: 10,
        decoration: BoxDecoration(color: color, shape: BoxShape.circle),
      ),
      const SizedBox(width: 6),
      Text(label, style: TextStyle(fontSize: 12, color: Colors.grey[600])),
    ]);
  }
}

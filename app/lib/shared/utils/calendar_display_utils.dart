// Shared calendar display rules (dedupe, day filtering) — used by Calendar + Chat.
import 'package:intl/intl.dart';
import 'package:table_calendar/table_calendar.dart';

import '../../data/models/event_model.dart';
import '../../data/models/schedule_block_model.dart';
import 'task_schedule_utils.dart';

class CalendarDisplayUtils {
  CalendarDisplayUtils._();

  static List<EventModel> dedupeCalendarEvents(Iterable<EventModel> events) {
    final unique = <EventModel>[];
    final indexByKey = <String, int>{};

    for (final event in events) {
      final key = _displayDedupeKey(event);
      if (key == null) {
        unique.add(event);
        continue;
      }

      final existingIndex = indexByKey[key];
      if (existingIndex == null) {
        indexByKey[key] = unique.length;
        unique.add(event);
        continue;
      }

      final existing = unique[existingIndex];
      if (_eventDisplayScore(event) > _eventDisplayScore(existing)) {
        unique[existingIndex] = event;
      }
    }

    return unique;
  }

  static bool canvasShowsInTimeGrid(EventModel e) {
    if (e.source != 'canvas') return false;
    final durMin = e.endTime.difference(e.startTime).inMinutes;
    if (durMin >= 30) return true;
    final h = e.startTime.hour;
    if (h >= 6 && h <= 21) return true;
    return false;
  }

  static List<EventModel> timedEventsOnDay(
    Iterable<EventModel> all,
    DateTime day,
  ) =>
      dedupeCalendarEvents(
        all
            .where((e) => isSameDay(e.startTime, day))
            .where((e) => !e.isDateOnlyCourseEvent)
            .where((e) => !e.isCourseAssignment)
            .where((e) => !e.isManualTask)
            .where((e) => e.source != 'canvas' || canvasShowsInTimeGrid(e)),
      );

  static List<EventModel> manualTasksOnDay(
    Iterable<EventModel> all,
    DateTime day,
  ) =>
      all
          .where((e) =>
              e.isManualTask &&
              eventCoversDay(e.startTime, e.endTime, day))
          .toList();

  static List<EventModel> canvasOnDay(Iterable<EventModel> all, DateTime day) =>
      all.where((e) => e.source == 'canvas' && isSameDay(e.startTime, day)).toList();

  static List<EventModel> courseAllDayOnDay(
    Iterable<EventModel> all,
    DateTime day,
  ) =>
      dedupeCalendarEvents(
        all.where((e) =>
            (e.isDateOnlyCourseEvent || e.isCourseAssignment) &&
            isSameDay(e.startTime, day)),
      );

  static List<dynamic> entriesForDay({
    required Iterable<EventModel> allEvents,
    required Iterable<ScheduleBlockModel> blocks,
    required DateTime day,
  }) {
    final timed = timedEventsOnDay(allEvents, day);
    final canvasChipsOnly = canvasOnDay(allEvents, day)
        .where((c) => !canvasShowsInTimeGrid(c))
        .toList();
    final courseAllDay = courseAllDayOnDay(allEvents, day);
    final manualTasks = manualTasksOnDay(allEvents, day);
    final dayBlocks = blocks.where((b) => isSameDay(b.startTime, day)).toList();
    return [
      ...timed,
      ...canvasChipsOnly,
      ...courseAllDay,
      ...manualTasks,
      ...dayBlocks,
    ];
  }

  static String localDateKey(DateTime dt) =>
      DateFormat('yyyy-MM-dd').format(DateTime(dt.year, dt.month, dt.day));

  static String? _displayDedupeKey(EventModel event) {
    if (event.source != 'course') return null;

    final importKey = _courseImportKey(event);
    final dateKey = localDateKey(event.startTime);
    if (event.isCourseAssignment) {
      return [
        'course-assignment',
        importKey,
        dateKey,
        _normalizedEventTitle(event.title),
      ].join('|');
    }

    final normalizedTitle = _normalizedEventTitle(event.title);
    if (!normalizedTitle.startsWith('lecture')) return null;
    return [
      'course-lecture',
      importKey,
      dateKey,
      _timeKey(event.startTime),
      _timeKey(event.endTime),
    ].join('|');
  }

  static String _courseImportKey(EventModel event) {
    final sourceEventId = event.sourceEventId;
    if (sourceEventId == null || sourceEventId.isEmpty) return 'unknown';
    if (sourceEventId.length <= 36) return sourceEventId;
    return sourceEventId.substring(0, 36);
  }

  static String _normalizedEventTitle(String title) =>
      title.toLowerCase().replaceAll(RegExp(r'[^a-z0-9]+'), '');

  static String _timeKey(DateTime time) =>
      '${time.hour.toString().padLeft(2, '0')}:${time.minute.toString().padLeft(2, '0')}';

  static int _eventDisplayScore(EventModel event) {
    var score = 0;
    final normalizedTitle = event.title.trim().toLowerCase();
    final generic = RegExp(r'^(lecture|section|lab|discussion)(\s+[a-z])?$')
        .hasMatch(normalizedTitle);
    if (!generic) score += 100;
    if (event.description.trim().isNotEmpty) score += 20;
    score += event.title.length > 80 ? 80 : event.title.length;
    return score;
  }
}

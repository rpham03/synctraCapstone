import 'package:flutter_test/flutter_test.dart';
import 'package:synctra/data/models/scheduling_models.dart';
import 'package:synctra/shared/services/scheduling_service.dart';

void main() {
  final monday = DateTime.utc(2026, 5, 4, 0, 0);
  final nextMonday = monday.add(const Duration(days: 7));

  group('SchedulingService', () {
    const svc = SchedulingService();
    const config = SchedulingConfig(
      bufferAroundFixedEvents: Duration(minutes: 15),
      minimumBlockSize: Duration(minutes: 30),
    );

    test('empty fixed events schedules full task in one block', () {
      final task = FlexibleTask(
        id: 't1',
        title: 'Essay',
        dueDate: monday.add(const Duration(days: 2, hours: 23)),
        estimatedDuration: const Duration(hours: 2),
        priority: 0,
      );

      final blocks = svc.scheduleWeek(
        weekStart: monday,
        weekEnd: nextMonday,
        fixedEvents: const [],
        flexibleTasks: [task],
        config: config,
      );

      expect(blocks, hasLength(1));
      expect(blocks.single.taskId, 't1');
      expect(blocks.single.startTime, monday);
      expect(blocks.single.duration, const Duration(hours: 2));
    });

    test('fixed event with buffer — scheduled work never overlaps buffered busy time', () {
      final fixed = FixedEvent(
        id: 'e1',
        title: 'Lecture',
        startTime: monday.add(const Duration(hours: 10)),
        endTime: monday.add(const Duration(hours: 11)),
        isRecurring: false,
      );

      final task = FlexibleTask(
        id: 'hw',
        title: 'Problem set',
        dueDate: monday.add(const Duration(days: 1)),
        estimatedDuration: const Duration(hours: 1),
        priority: 0,
      );

      final blocks = svc.scheduleWeek(
        weekStart: monday,
        weekEnd: nextMonday,
        fixedEvents: [fixed],
        flexibleTasks: [task],
        config: config,
      );

      // Buffered busy: 9:45–11:15. Greedy placement uses the earliest ≥30m free slice (midnight–9:45).
      final busyStart = monday.add(const Duration(hours: 9, minutes: 45));
      final busyEnd = monday.add(const Duration(hours: 11, minutes: 15));
      final b = blocks.single;
      final overlapsBusy = b.startTime.isBefore(busyEnd) && b.endTime.isAfter(busyStart);
      expect(overlapsBusy, isFalse);
      expect(b.duration, const Duration(hours: 1));
    });

    test('splits long task across multiple free windows when no single gap fits', () {
      // Block midnight–11:00 so the first usable gap is only the 30m lunch slice
      // between buffered classes; remaining work continues after the afternoon class.
      final fixed = [
        FixedEvent(
          id: 'morning',
          title: 'Busy morning',
          startTime: monday,
          endTime: monday.add(const Duration(hours: 11)),
          isRecurring: false,
        ),
        FixedEvent(
          id: 'a',
          title: 'Class A',
          startTime: monday.add(const Duration(hours: 12)),
          endTime: monday.add(const Duration(hours: 13)),
          isRecurring: false,
        ),
        FixedEvent(
          id: 'b',
          title: 'Class B',
          startTime: monday.add(const Duration(hours: 14)),
          endTime: monday.add(const Duration(hours: 15)),
          isRecurring: false,
        ),
      ];

      final task = FlexibleTask(
        id: 'big',
        title: 'Project',
        dueDate: nextMonday,
        estimatedDuration: const Duration(hours: 3),
        priority: 0,
      );

      final blocks = svc.scheduleWeek(
        weekStart: monday,
        weekEnd: nextMonday,
        fixedEvents: fixed,
        flexibleTasks: [task],
        config: config,
      );

      expect(blocks.length, greaterThanOrEqualTo(2));
      expect(blocks.map((b) => b.taskId), everyElement(equals('big')));
      final total = blocks.fold<Duration>(Duration.zero, (s, b) => s + b.duration);
      expect(total, const Duration(hours: 3));
      // First usable slice after the long morning block is the 30m lunch gap.
      expect(blocks.first.duration, const Duration(minutes: 30));
      for (var i = 1; i < blocks.length; i++) {
        expect(blocks[i].startTime.isBefore(blocks[i - 1].endTime), isFalse);
      }
    });

    test('does not schedule fragments below minimum block size', () {
      // Gap ~20m after buffers — below 30m minimum.
      final fixed = FixedEvent(
        id: 'e',
        title: 'Short',
        startTime: monday.add(const Duration(hours: 10)),
        endTime: monday.add(const Duration(hours: 10, minutes: 20)),
        isRecurring: false,
      );

      final task = FlexibleTask(
        id: 't',
        title: 'Tiny',
        dueDate: nextMonday,
        estimatedDuration: const Duration(minutes: 20),
        priority: 0,
      );

      final blocks = svc.scheduleWeek(
        weekStart: monday,
        weekEnd: nextMonday,
        fixedEvents: [fixed],
        flexibleTasks: [task],
        config: config,
      );

      expect(blocks, isEmpty);
    });

    test('respects due date — no block ends after dueDate', () {
      final due = monday.add(const Duration(hours: 14));

      final task = FlexibleTask(
        id: 'dueSoon',
        title: 'Quiz prep',
        dueDate: due,
        estimatedDuration: const Duration(hours: 4),
        priority: 0,
      );

      final blocks = svc.scheduleWeek(
        weekStart: monday,
        weekEnd: nextMonday,
        fixedEvents: const [],
        flexibleTasks: [task],
        config: config,
      );

      expect(blocks, isNotEmpty);
      for (final b in blocks) {
        expect(b.endTime.isAfter(due), isFalse);
      }
      final scheduled = blocks.fold<Duration>(Duration.zero, (s, b) => s + b.duration);
      expect(scheduled, const Duration(hours: 4));
    });

    test('orders by due date then priority for competing tasks', () {
      final sameDue = monday.add(const Duration(days: 3));

      final low = FlexibleTask(
        id: 'low',
        title: 'Low',
        dueDate: sameDue,
        estimatedDuration: const Duration(hours: 1),
        priority: 1,
      );
      final high = FlexibleTask(
        id: 'high',
        title: 'High',
        dueDate: sameDue,
        estimatedDuration: const Duration(hours: 1),
        priority: 5,
      );

      final blocks = svc.scheduleWeek(
        weekStart: monday,
        weekEnd: nextMonday,
        fixedEvents: const [],
        flexibleTasks: [low, high],
        config: config,
      );

      expect(blocks, hasLength(2));
      expect(blocks.first.taskId, 'high');
      expect(blocks.last.taskId, 'low');
    });

    test('sooner due date is scheduled before later due date', () {
      final later = FlexibleTask(
        id: 'later',
        title: 'Later',
        dueDate: monday.add(const Duration(days: 5)),
        estimatedDuration: const Duration(hours: 1),
        priority: 99,
      );
      final sooner = FlexibleTask(
        id: 'sooner',
        title: 'Sooner',
        dueDate: monday.add(const Duration(days: 2)),
        estimatedDuration: const Duration(hours: 1),
        priority: 0,
      );

      final blocks = svc.scheduleWeek(
        weekStart: monday,
        weekEnd: nextMonday,
        fixedEvents: const [],
        flexibleTasks: [later, sooner],
        config: config,
      );

      expect(blocks.first.taskId, 'sooner');
      expect(blocks.last.taskId, 'later');
    });

    test('invalid week window returns empty list', () {
      final blocks = svc.scheduleWeek(
        weekStart: nextMonday,
        weekEnd: monday,
        fixedEvents: const [],
        flexibleTasks: [
          FlexibleTask(
            id: 'x',
            title: 'X',
            dueDate: nextMonday,
            estimatedDuration: const Duration(hours: 1),
          ),
        ],
        config: config,
      );
      expect(blocks, isEmpty);
    });

    test('merges overlapping fixed events before computing gaps', () {
      final fixed = [
        FixedEvent(
          id: '1',
          title: 'Overlap A',
          startTime: monday.add(const Duration(hours: 10)),
          endTime: monday.add(const Duration(hours: 11, minutes: 30)),
          isRecurring: false,
        ),
        FixedEvent(
          id: '2',
          title: 'Overlap B',
          startTime: monday.add(const Duration(hours: 11)),
          endTime: monday.add(const Duration(hours: 12)),
          isRecurring: false,
        ),
      ];

      final task = FlexibleTask(
        id: 'fill',
        title: 'Fill',
        dueDate: nextMonday,
        estimatedDuration: const Duration(hours: 1),
        priority: 0,
      );

      final blocks = svc.scheduleWeek(
        weekStart: monday,
        weekEnd: nextMonday,
        fixedEvents: fixed,
        flexibleTasks: [task],
        config: config,
      );

      // Merged buffered busy spans 9:45–12:15; work must sit outside that span.
      final mergedBusyStart = monday.add(const Duration(hours: 9, minutes: 45));
      final mergedBusyEnd = monday.add(const Duration(hours: 12, minutes: 15));
      final b = blocks.single;
      final overlaps = b.startTime.isBefore(mergedBusyEnd) && b.endTime.isAfter(mergedBusyStart);
      expect(overlaps, isFalse);
      expect(b.duration, const Duration(hours: 1));
    });

    test('expandTaskSessions schedules each session as its own unit', () {
      final task = FlexibleTask(
        id: 'parent',
        title: 'Paper',
        dueDate: nextMonday,
        estimatedDuration: Duration.zero,
        sessions: const [
          TaskSession(duration: Duration(minutes: 40)),
          TaskSession(duration: Duration(minutes: 50)),
        ],
      );

      final blocks = svc.scheduleWeek(
        weekStart: monday,
        weekEnd: nextMonday,
        fixedEvents: const [],
        flexibleTasks: [task],
        config: config,
      );

      expect(blocks, hasLength(2));
      expect(blocks.map((b) => b.taskId), ['parent__s0', 'parent__s1']);
      expect(blocks[0].duration, const Duration(minutes: 40));
      expect(blocks[1].duration, const Duration(minutes: 50));
    });

    test('clips a single slice at local midnight when the free window crosses midnight', () {
      // Local [DateTime]s so `_startOfNextLocalDay` matches the slot calendar day (UTC slots break this on non-UTC hosts).
      final weekStart = DateTime(2026, 5, 4);
      final weekEnd = weekStart.add(const Duration(days: 7));
      final fixed = [
        FixedEvent(
          id: 'day',
          title: 'Busy',
          startTime: weekStart,
          endTime: weekStart.add(const Duration(hours: 22)),
          isRecurring: false,
        ),
        FixedEvent(
          id: 'after',
          title: 'Busy2',
          startTime: weekStart.add(const Duration(days: 1, hours: 1)),
          endTime: weekEnd,
          isRecurring: false,
        ),
      ];

      final task = FlexibleTask(
        id: 'night',
        title: 'Deep work',
        dueDate: weekEnd,
        estimatedDuration: const Duration(hours: 2, minutes: 30),
        priority: 0,
      );

      final blocks = svc.scheduleWeek(
        weekStart: weekStart,
        weekEnd: weekEnd,
        fixedEvents: fixed,
        flexibleTasks: [task],
        config: config,
      );

      expect(blocks, hasLength(2));
      // 15-minute buffer after the 22:00 busy block shifts the gap start to 22:15; clip at midnight → 1h45 + 45m.
      expect(blocks.first.duration, const Duration(hours: 1, minutes: 45));
      expect(blocks.last.duration, const Duration(minutes: 45));
      expect(blocks.last.startTime.isBefore(blocks.last.endTime), isTrue);
      expect(!blocks.last.startTime.isBefore(blocks.first.endTime), isTrue);
    });
  });
}

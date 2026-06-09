import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:synctra/data/models/user_settings.dart';
import 'package:synctra/shared/services/synctra_chat_service.dart';

void main() {
  group('chat request study preferences', () {
    test('payload carries the saved study window, session, and break', () {
      const settings = UserSettings(
        userId: 'u',
        workStartTime: TimeOfDay(hour: 15, minute: 0),
        workEndTime: TimeOfDay(hour: 22, minute: 0),
        preferredSessionMinutes: 60,
        breakMinutes: 10,
      );

      final payload = SynctraChatService.chatStudyPreferences(settings);

      expect(payload['study_start_time'], '15:00');
      expect(payload['study_end_time'], '22:00');
      expect(payload['session_length_minutes'], 60);
      expect(payload['break_minutes'], 10);
    });

    test('changing settings is reflected in the next payload immediately', () {
      var settings = const UserSettings(
        userId: 'u',
        workStartTime: TimeOfDay(hour: 15, minute: 0),
        workEndTime: TimeOfDay(hour: 22, minute: 0),
        preferredSessionMinutes: 60,
        breakMinutes: 10,
      );

      final before = SynctraChatService.chatStudyPreferences(settings);
      expect(before['study_start_time'], '15:00');
      expect(before['study_end_time'], '22:00');

      // User edits Settings to 5 PM–9 PM, 45-min sessions, 15-min breaks.
      settings = settings.copyWith(
        workStartTime: const TimeOfDay(hour: 17, minute: 0),
        workEndTime: const TimeOfDay(hour: 21, minute: 0),
        preferredSessionMinutes: 45,
        breakMinutes: 15,
      );

      // Because the payload is rebuilt from the latest settings each send,
      // the next request reflects the change without an app restart.
      final after = SynctraChatService.chatStudyPreferences(settings);
      expect(after['study_start_time'], '17:00');
      expect(after['study_end_time'], '21:00');
      expect(after['session_length_minutes'], 45);
      expect(after['break_minutes'], 15);
    });

    test('no settings yields an empty payload (backend uses defaults)', () {
      expect(SynctraChatService.chatStudyPreferences(null), isEmpty);
    });
  });
}

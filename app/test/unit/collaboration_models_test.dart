import 'package:flutter_test/flutter_test.dart';
import 'package:synctra/data/models/collaboration_models.dart';

void main() {
  test('collaboration poll parses participants options and votes', () {
    final poll = CollaborationPoll.fromJson({
      'id': 'poll-1',
      'title': 'Project meeting',
      'organizer_id': 'alex',
      'duration_minutes': 60,
      'status': 'open',
      'participants': [
        {
          'id': 'alex',
          'display_name': 'Alex',
          'email': 'alex@example.com',
          'response_status': 'accepted',
          'preferred_periods': ['morning', 'afternoon'],
        },
        {
          'id': 'jordan',
          'display_name': 'Jordan',
          'email': 'jordan@example.com',
          'response_status': 'responded',
        },
      ],
      'options': [
        {
          'id': 'option-1',
          'start_time': '2026-06-08T17:00:00Z',
          'end_time': '2026-06-08T18:00:00Z',
          'preferred_matches': 2,
          'votes': {
            'available': 1,
            'preferred': 1,
            'unavailable': 0,
          },
        },
      ],
    });

    expect(poll.title, 'Project meeting');
    expect(poll.participants.length, 2);
    expect(poll.participants.first.preferredPeriods, ['morning', 'afternoon']);
    expect(poll.participants.last.responseStatus, 'responded');
    expect(poll.options.single.preferredMatches, 2);
    expect(poll.options.single.votes['preferred'], 1);
    expect(poll.options.single.endTime.isAfter(poll.options.single.startTime),
        isTrue);
  });

  test('confirmed poll preserves selected option id', () {
    final poll = CollaborationPoll.fromJson({
      'id': 'poll-2',
      'title': 'Study group',
      'organizer_id': 'alex',
      'status': 'confirmed',
      'confirmed_option_id': 'option-2',
      'participants': const [],
      'options': const [],
    });

    expect(poll.status, 'confirmed');
    expect(poll.confirmedOptionId, 'option-2');
  });
}

class CollaborationParticipant {
  final String id;
  final String displayName;
  final String email;
  final String responseStatus;
  final List<String> preferredPeriods;

  const CollaborationParticipant({
    required this.id,
    required this.displayName,
    required this.email,
    required this.responseStatus,
    required this.preferredPeriods,
  });

  factory CollaborationParticipant.fromJson(Map<String, dynamic> json) =>
      CollaborationParticipant(
        id: json['id']?.toString() ?? '',
        displayName: json['display_name']?.toString() ?? 'Participant',
        email: json['email']?.toString() ?? '',
        responseStatus: json['response_status']?.toString() ?? 'invited',
        preferredPeriods: (json['preferred_periods'] as List? ?? const [])
            .map((value) => value.toString())
            .toList(),
      );
}

class CollaborationOption {
  final String id;
  final DateTime startTime;
  final DateTime endTime;
  final int preferredMatches;
  final Map<String, int> votes;

  const CollaborationOption({
    required this.id,
    required this.startTime,
    required this.endTime,
    required this.preferredMatches,
    required this.votes,
  });

  factory CollaborationOption.fromJson(Map<String, dynamic> json) {
    final rawVotes = json['votes'];
    return CollaborationOption(
      id: json['id']?.toString() ?? '',
      startTime: DateTime.parse(json['start_time'] as String).toLocal(),
      endTime: DateTime.parse(json['end_time'] as String).toLocal(),
      preferredMatches: json['preferred_matches'] as int? ?? 0,
      votes: rawVotes is Map
          ? rawVotes.map(
              (key, value) => MapEntry(key.toString(), value as int? ?? 0),
            )
          : const {},
    );
  }
}

class CollaborationPoll {
  final String id;
  final String title;
  final String description;
  final String organizerId;
  final int durationMinutes;
  final String status;
  final String? confirmedOptionId;
  final List<CollaborationParticipant> participants;
  final List<CollaborationOption> options;

  const CollaborationPoll({
    required this.id,
    required this.title,
    required this.description,
    required this.organizerId,
    required this.durationMinutes,
    required this.status,
    required this.confirmedOptionId,
    required this.participants,
    required this.options,
  });

  factory CollaborationPoll.fromJson(Map<String, dynamic> json) =>
      CollaborationPoll(
        id: json['id']?.toString() ?? '',
        title: json['title']?.toString() ?? 'Group event',
        description: json['description']?.toString() ?? '',
        organizerId: json['organizer_id']?.toString() ?? '',
        durationMinutes: json['duration_minutes'] as int? ?? 60,
        status: json['status']?.toString() ?? 'open',
        confirmedOptionId: json['confirmed_option_id']?.toString(),
        participants: (json['participants'] as List? ?? const [])
            .whereType<Map>()
            .map(
              (value) => CollaborationParticipant.fromJson(
                Map<String, dynamic>.from(value),
              ),
            )
            .toList(),
        options: (json['options'] as List? ?? const [])
            .whereType<Map>()
            .map(
              (value) => CollaborationOption.fromJson(
                Map<String, dynamic>.from(value),
              ),
            )
            .toList(),
      );
}

class CollaborationConfirmation {
  final CollaborationPoll poll;
  final List<Map<String, dynamic>> calendarEvents;

  const CollaborationConfirmation({
    required this.poll,
    required this.calendarEvents,
  });
}

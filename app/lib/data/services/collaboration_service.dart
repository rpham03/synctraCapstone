import 'package:dio/dio.dart';
import 'package:supabase_flutter/supabase_flutter.dart';

import '../../core/constants/api_constants.dart';
import '../models/collaboration_models.dart';
import 'calendar_events_loader.dart';

class CollaborationService {
  CollaborationService({Dio? dio}) : _dio = dio ?? Dio();

  final Dio _dio;

  String get currentUserId =>
      Supabase.instance.client.auth.currentUser?.id ?? 'app-user';

  String get currentUserName {
    final user = Supabase.instance.client.auth.currentUser;
    return user?.userMetadata?['full_name']?.toString() ?? user?.email ?? 'You';
  }

  String get currentUserEmail =>
      Supabase.instance.client.auth.currentUser?.email?.toLowerCase() ?? '';

  String participantIdFor(CollaborationPoll poll) {
    for (final participant in poll.participants) {
      if (participant.id == currentUserId ||
          (currentUserEmail.isNotEmpty &&
              participant.email.toLowerCase() == currentUserEmail)) {
        return participant.id;
      }
    }
    return currentUserId;
  }

  List<String> preferredPeriodsFor(CollaborationPoll poll) {
    final participantId = participantIdFor(poll);
    for (final participant in poll.participants) {
      if (participant.id == participantId) return participant.preferredPeriods;
    }
    return const [];
  }

  Future<List<CollaborationPoll>> listPolls() async {
    final response = await _dio.get<Map<String, dynamic>>(
      '${ApiConstants.baseUrl}/collab/polls',
      queryParameters: {
        'user_id': currentUserId,
        if (currentUserEmail.isNotEmpty) 'email': currentUserEmail,
      },
    );
    final raw = response.data?['polls'];
    if (raw is! List) return const [];
    return raw
        .whereType<Map>()
        .map(
          (value) =>
              CollaborationPoll.fromJson(Map<String, dynamic>.from(value)),
        )
        .toList();
  }

  Future<CollaborationPoll> createPoll({
    required String title,
    required int durationMinutes,
    required DateTime windowStart,
    required DateTime windowEnd,
    required List<String> invitees,
    List<String> preferredPeriods = const [],
    String description = '',
  }) async {
    final busy = await _loadBusyIntervals();

    final participants = <Map<String, dynamic>>[
      {
        'id': currentUserId,
        'display_name': currentUserName,
        'email': Supabase.instance.client.auth.currentUser?.email ?? '',
        'timezone_offset_minutes': DateTime.now().timeZoneOffset.inMinutes,
        'preferred_periods': preferredPeriods,
        'busy': busy,
      },
      for (final invitee in invitees)
        {
          'id': _inviteeId(invitee),
          'display_name': invitee,
          'email': invitee.contains('@') ? invitee : '',
          'timezone_offset_minutes': DateTime.now().timeZoneOffset.inMinutes,
          'preferred_periods': const <String>[],
          'busy': const <Map<String, dynamic>>[],
        },
    ];

    final response = await _dio.post<Map<String, dynamic>>(
      '${ApiConstants.baseUrl}/collab/polls',
      data: {
        'title': title,
        'description': description,
        'organizer_id': currentUserId,
        'duration_minutes': durationMinutes,
        'window_start': windowStart.toUtc().toIso8601String(),
        'window_end': windowEnd.toUtc().toIso8601String(),
        'participants': participants,
        'max_options': 5,
      },
    );
    return CollaborationPoll.fromJson(response.data ?? const {});
  }

  Future<CollaborationPoll> refreshAvailability(
    CollaborationPoll poll, {
    List<String>? preferredPeriods,
  }) async {
    final result = await _dio.post<Map<String, dynamic>>(
      '${ApiConstants.baseUrl}/collab/polls/${poll.id}/availability',
      data: {
        'participant_id': participantIdFor(poll),
        'timezone_offset_minutes': DateTime.now().timeZoneOffset.inMinutes,
        'preferred_periods': preferredPeriods ?? preferredPeriodsFor(poll),
        'busy': await _loadBusyIntervals(),
      },
    );
    return CollaborationPoll.fromJson(result.data ?? const {});
  }

  Future<CollaborationPoll> vote({
    required CollaborationPoll poll,
    required String optionId,
    required String response,
  }) async {
    final result = await _dio.post<Map<String, dynamic>>(
      '${ApiConstants.baseUrl}/collab/polls/${poll.id}/votes',
      data: {
        'participant_id': participantIdFor(poll),
        'option_id': optionId,
        'response': response,
      },
    );
    return CollaborationPoll.fromJson(result.data ?? const {});
  }

  Future<CollaborationConfirmation> confirm({
    required String pollId,
    required String optionId,
  }) async {
    final result = await _dio.post<Map<String, dynamic>>(
      '${ApiConstants.baseUrl}/collab/polls/$pollId/confirm',
      data: {
        'organizer_id': currentUserId,
        'option_id': optionId,
      },
    );
    final body = result.data ?? const <String, dynamic>{};
    final rawEvents = body['calendar_events'];
    return CollaborationConfirmation(
      poll: CollaborationPoll.fromJson(body),
      calendarEvents: rawEvents is List
          ? rawEvents
              .whereType<Map>()
              .map((event) => Map<String, dynamic>.from(event))
              .toList()
          : const [],
    );
  }

  Future<CollaborationPoll> cancel(String pollId) async {
    final result = await _dio.post<Map<String, dynamic>>(
      '${ApiConstants.baseUrl}/collab/polls/$pollId/cancel',
      data: {'organizer_id': currentUserId},
    );
    return CollaborationPoll.fromJson(result.data ?? const {});
  }

  Future<List<Map<String, dynamic>>> _loadBusyIntervals() async {
    final calendar = await CalendarEventsLoader.loadForChat();
    final busy = <Map<String, dynamic>>[];
    for (final event in calendar) {
      final start = event['start_time']?.toString();
      final end = event['end_time']?.toString();
      if (start == null || end == null || event['is_all_day'] == true) continue;
      busy.add({
        'start': start,
        'end': end,
        'flexibility': 'fixed',
      });
    }
    return busy;
  }

  String _inviteeId(String value) {
    if (value.contains('@')) return value.trim().toLowerCase();
    final normalized = value.trim().toLowerCase().replaceAll(
          RegExp(r'[^a-z0-9]+'),
          '-',
        );
    return 'invitee-${normalized.isEmpty ? value.hashCode : normalized}';
  }
}

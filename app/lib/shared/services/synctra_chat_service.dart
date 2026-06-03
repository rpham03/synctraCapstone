// Unified Sync It chat — same backend, calendar context, and study blocks everywhere.
import 'package:dio/dio.dart';
import 'package:get_it/get_it.dart';
import 'package:supabase_flutter/supabase_flutter.dart';
import 'package:uuid/uuid.dart';

import '../../core/constants/api_constants.dart';
import '../../data/models/schedule_block_model.dart';
import '../../data/services/calendar_events_loader.dart';
import 'suggested_schedule_store.dart';

class SynctraChatResult {
  final String reply;
  final int blocksAdded;

  const SynctraChatResult({
    required this.reply,
    this.blocksAdded = 0,
  });
}

class SynctraChatService {
  SynctraChatService({SuggestedScheduleStore? store})
      : _store = store ?? GetIt.instance<SuggestedScheduleStore>();

  final SuggestedScheduleStore _store;

  factory SynctraChatService.fromGetIt() =>
      SynctraChatService(store: GetIt.instance<SuggestedScheduleStore>());

  Future<SynctraChatResult> sendMessage(String userText) async {
    final text = userText.trim();
    if (text.isEmpty) {
      return const SynctraChatResult(
        reply: 'Send me a message about your schedule or tasks.',
      );
    }

    try {
      final calendarEvents = await CalendarEventsLoader.loadForChat();
      final tasks = await CalendarEventsLoader.loadTasksForChat();
      final uid = Supabase.instance.client.auth.currentUser?.id ?? 'app-user';
      final response = await Dio().post<Map<String, dynamic>>(
        '${ApiConstants.baseUrl}/chat/message',
        data: {
          'message': text,
          'user_id': uid,
          'client_today': CalendarEventsLoader.clientTodayIso(),
          'timezone_offset_minutes': DateTime.now().timeZoneOffset.inMinutes,
          'timezone_name': DateTime.now().timeZoneName,
          'calendar_events': calendarEvents,
          'tasks': tasks,
        },
      );

      final reply = response.data?['reply']?.toString() ??
          'Sorry, I did not get a reply from the server.';
      final proposals = _readProposals(response.data?['schedule_proposals']);
      final added = _applyScheduleProposals(proposals);

      return SynctraChatResult(reply: reply, blocksAdded: added);
    } on DioException catch (e) {
      final data = e.response?.data;
      if (data is Map && data['detail'] != null) {
        return SynctraChatResult(reply: data['detail'].toString());
      }
      if (e.type == DioExceptionType.connectionError ||
          e.error?.toString().contains('Connection refused') == true) {
        return SynctraChatResult(
          reply: 'Cannot reach the Synctra backend at ${ApiConstants.baseUrl}. '
              'If you are using Colab, keep the backend uvicorn cell and the '
              'Cloudflare tunnel cell running, then restart Flutter with the '
              'latest API_BASE_URL. For local backend:\n'
              'cd backend && python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000',
        );
      }
      return SynctraChatResult(reply: e.message ?? 'Could not reach the chat API');
    } catch (e) {
      return SynctraChatResult(reply: '$e');
    }
  }

  /// Same engine as chat — used from calendar event detail "Schedule study time".
  Future<SynctraChatResult> scheduleStudyForDueItem({
    required String title,
    required DateTime dueDate,
    int? estimatedMinutes,
    double? hours,
  }) async {
    final mins = estimatedMinutes ??
        (hours != null ? (hours * 60).round().clamp(15, 200 * 60) : 90);
    final dueDay = DateTime(dueDate.year, dueDate.month, dueDate.day);
    final dueIso =
        '${dueDay.year.toString().padLeft(4, '0')}-${dueDay.month.toString().padLeft(2, '0')}-${dueDay.day.toString().padLeft(2, '0')}';
    final hr = mins ~/ 60;
    final min = mins % 60;
    final durationLabel = min == 0 ? '$hr hours' : '$hr hours $min minutes';
    return sendMessage(
      'Propose study blocks for "$title" due on $dueIso. '
      'Use $mins estimated minutes total ($durationLabel). '
      'Avoid busy times on my calendar.',
    );
  }

  List<Map<String, dynamic>> _readProposals(Object? raw) {
    if (raw is! List) return const [];
    return raw
        .whereType<Map>()
        .map((m) => Map<String, dynamic>.from(m))
        .toList();
  }

  int _applyScheduleProposals(List<Map<String, dynamic>> proposals) {
    if (proposals.isEmpty) return 0;

    final taskId = 'chat-${DateTime.now().millisecondsSinceEpoch}';
    final blocks = <ScheduleBlockModel>[];

    for (final p in proposals) {
      final startRaw = p['start_time']?.toString();
      final endRaw = p['end_time']?.toString();
      if (startRaw == null || endRaw == null) continue;
      try {
        blocks.add(
          ScheduleBlockModel(
            id: const Uuid().v4(),
            taskId: taskId,
            taskTitle: p['task_title']?.toString() ?? 'Study block',
            startTime: DateTime.parse(startRaw).toLocal(),
            endTime: DateTime.parse(endRaw).toLocal(),
            isAiGenerated: p['is_ai_generated'] as bool? ?? true,
          ),
        );
      } catch (_) {}
    }

    if (blocks.isEmpty) return 0;
    _store.addStudyBlocks(blocks);
    return blocks.length;
  }
}

void registerSynctraChatService() {
  final g = GetIt.instance;
  if (!g.isRegistered<SynctraChatService>()) {
    g.registerLazySingleton(SynctraChatService.fromGetIt);
  }
}

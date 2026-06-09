// Collaborative scheduling polls: privacy-safe availability, voting, and confirmation.
import 'dart:async';

import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:get_it/get_it.dart';

import '../../../core/theme/app_theme.dart';
import '../../../data/models/collaboration_models.dart';
import '../../../data/models/schedule_block_model.dart';
import '../../../data/services/collaboration_service.dart';
import '../../../features/settings/widgets/settings_sections.dart';
import '../../../shared/services/suggested_schedule_store.dart';
import '../../../shared/widgets/synctra_empty_state.dart';
import '../../../shared/widgets/synctra_page_header.dart';
import '../../../shared/widgets/synctra_page_scaffold.dart';

const _productivityPeriods = ['morning', 'afternoon', 'evening', 'night'];

class CollabScreen extends StatefulWidget {
  const CollabScreen({super.key});

  @override
  State<CollabScreen> createState() => _CollabScreenState();
}

class _CollabScreenState extends State<CollabScreen> {
  // How often to re-check the backend for confirmations/votes while this screen
  // is open. Lower = more "live" but more network calls. Tunable down to ~1s.
  static const _pollInterval = Duration(seconds: 5);

  final _service = CollaborationService();
  var _polls = <CollaborationPoll>[];
  var _loading = true;
  String? _error;
  Timer? _pollTimer;
  bool _polling = false;

  @override
  void initState() {
    super.initState();
    _loadPolls();
    // Live-ish updates: pick up other members' votes and the organizer's
    // confirmation without a manual refresh.
    _pollTimer = Timer.periodic(_pollInterval, (_) => _pollUpdates());
  }

  @override
  void dispose() {
    _pollTimer?.cancel();
    super.dispose();
  }

  /// Lightweight background refresh (no spinner, no re-vote): just re-list the
  /// polls so a confirmation shows live and lands on this user's calendar.
  Future<void> _pollUpdates() async {
    if (_polling || !mounted) return;
    _polling = true;
    try {
      final polls = await _service.listPolls();
      _syncConfirmedEvents(polls);
      if (mounted) setState(() => _polls = polls);
    } catch (_) {
      // Transient network error — keep showing the last good state.
    } finally {
      _polling = false;
    }
  }

  Future<void> _loadPolls() async {
    if (mounted) setState(() => _loading = true);
    try {
      final listedPolls = await _service.listPolls();
      final polls = <CollaborationPoll>[];
      for (final poll in listedPolls) {
        if (poll.status != 'open') {
          polls.add(poll);
          continue;
        }
        try {
          polls.add(await _service.refreshAvailability(poll));
        } catch (_) {
          polls.add(poll);
        }
      }
      _syncConfirmedEvents(polls);
      if (!mounted) return;
      setState(() {
        _polls = polls;
        _error = null;
      });
    } catch (error) {
      if (!mounted) return;
      setState(() => _error = _errorMessage(error));
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _createPoll() async {
    final draft = await showDialog<_PollDraft>(
      context: context,
      builder: (_) => const _CreatePollDialog(),
    );
    if (draft == null || !mounted) return;

    setState(() => _loading = true);
    try {
      final poll = await _service.createPoll(
        title: draft.title,
        description: draft.description,
        durationMinutes: draft.durationMinutes,
        windowStart: draft.windowStart,
        windowEnd: draft.windowEnd,
        invitees: draft.invitees,
        preferredPeriods: draft.preferredPeriods,
      );
      if (!mounted) return;
      setState(() {
        _polls = [poll, ..._polls];
        _error = null;
      });
      _showMessage(
        poll.options.isEmpty
            ? 'Poll created, but no shared times were found.'
            : 'Poll created with ${poll.options.length} shared time options.',
      );
    } catch (error) {
      if (mounted) _showMessage(_errorMessage(error));
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _vote(
    CollaborationPoll poll,
    CollaborationOption option,
    String response,
  ) async {
    try {
      final updated = await _service.vote(
        poll: poll,
        optionId: option.id,
        response: response,
      );
      if (mounted) setState(() => _replacePoll(updated));
    } catch (error) {
      if (mounted) _showMessage(_errorMessage(error));
    }
  }

  Future<void> _confirm(
    CollaborationPoll poll,
    CollaborationOption option,
  ) async {
    try {
      final result = await _service.confirm(
        pollId: poll.id,
        optionId: option.id,
      );
      Map<String, dynamic>? ownEvent;
      for (final event in result.calendarEvents) {
        if (event['participant_id']?.toString() == _service.currentUserId) {
          ownEvent = event;
          break;
        }
      }
      if (ownEvent != null) {
        GetIt.instance<SuggestedScheduleStore>().addStudyBlocks([
          ScheduleBlockModel(
            id: ownEvent['id']?.toString() ?? 'collab-${poll.id}',
            taskId: 'collab-${poll.id}',
            taskTitle: ownEvent['title']?.toString() ?? poll.title,
            startTime:
                DateTime.parse(ownEvent['start_time'] as String).toLocal(),
            endTime: DateTime.parse(ownEvent['end_time'] as String).toLocal(),
            isAiGenerated: false,
            description: 'Confirmed collaborative event',
          ),
        ]);
      }
      if (!mounted) return;
      setState(() => _replacePoll(result.poll));
      _showMessage('Group event confirmed and added to your calendar.');
    } catch (error) {
      if (mounted) _showMessage(_errorMessage(error));
    }
  }

  Future<void> _cancel(CollaborationPoll poll) async {
    try {
      final updated = await _service.cancel(poll.id);
      if (!mounted) return;
      setState(() => _replacePoll(updated));
      _showMessage('Scheduling poll cancelled.');
    } catch (error) {
      if (mounted) _showMessage(_errorMessage(error));
    }
  }

  Future<void> _setPreferences(CollaborationPoll poll) async {
    final selected = _service.preferredPeriodsFor(poll).toSet();
    final periods = await showDialog<List<String>>(
      context: context,
      builder: (dialogContext) => StatefulBuilder(
        builder: (context, setDialogState) => AlertDialog(
          title: const Text('Preferred meeting times'),
          content: Wrap(
            spacing: 8,
            runSpacing: 8,
            children: [
              for (final period in _productivityPeriods)
                FilterChip(
                  label: Text(period),
                  selected: selected.contains(period),
                  onSelected: (enabled) {
                    setDialogState(() {
                      if (enabled) {
                        selected.add(period);
                      } else {
                        selected.remove(period);
                      }
                    });
                  },
                ),
            ],
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(dialogContext),
              child: const Text('Cancel'),
            ),
            FilledButton(
              onPressed: () => Navigator.pop(dialogContext, selected.toList()),
              child: const Text('Update'),
            ),
          ],
        ),
      ),
    );
    if (periods == null || !mounted) return;
    try {
      final updated = await _service.refreshAvailability(
        poll,
        preferredPeriods: periods,
      );
      if (!mounted) return;
      setState(() => _replacePoll(updated));
      _showMessage('Meeting-time preferences updated.');
    } catch (error) {
      if (mounted) _showMessage(_errorMessage(error));
    }
  }

  void _replacePoll(CollaborationPoll updated) {
    final index = _polls.indexWhere((poll) => poll.id == updated.id);
    if (index < 0) {
      _polls = [updated, ..._polls];
      return;
    }
    _polls[index] = updated;
  }

  void _syncConfirmedEvents(List<CollaborationPoll> polls) {
    _service.addConfirmedPollsToCalendar(polls);
  }

  void _showMessage(String message) {
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(content: Text(message)),
    );
  }

  String _errorMessage(Object error) {
    if (error is DioException) {
      final data = error.response?.data;
      if (data is Map && data['detail'] != null) {
        return data['detail'].toString();
      }
      if (error.type == DioExceptionType.connectionError) {
        return 'Cannot reach the Synctra backend. Keep the backend and tunnel running.';
      }
      return error.message ?? 'Collaborative scheduling request failed.';
    }
    return error.toString();
  }

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return Scaffold(
      backgroundColor: AppTokens.calendarGridSurface(context),
      appBar: SynctraPageHeader(
        title: 'Collab',
        subtitle: 'Schedule without exposing calendar details',
        actions: [
          IconButton(
            tooltip: 'Refresh polls',
            onPressed: _loading ? null : _loadPolls,
            icon: Icon(Icons.refresh, color: AppColors.textSecondary),
          ),
        ],
      ),
      body: RefreshIndicator(
        onRefresh: _loadPolls,
        child: ListView(
          padding: const EdgeInsets.fromLTRB(16, 12, 16, 96),
          children: [
            _PrivacyBanner(onCreate: _createPoll),
            const SizedBox(height: 24),
            Row(
              children: [
                Expanded(
                  child: Text(
                    'SCHEDULING POLLS',
                    style: CalendarTextStyles.sidebarSectionHeader(
                      Theme.of(context).brightness,
                    ),
                  ),
                ),
                if (_loading)
                  const SizedBox.square(
                    dimension: 18,
                    child: CircularProgressIndicator(strokeWidth: 2),
                  ),
              ],
            ),
            const SizedBox(height: 12),
            if (_error != null)
              Padding(
                padding: const EdgeInsets.only(bottom: 12),
                child: Text(
                  _error!,
                  style: TextStyle(color: scheme.error),
                ),
              ),
            if (!_loading && _polls.isEmpty)
              const SynctraEmptyState(
                icon: Icons.groups_outlined,
                title: 'No scheduling polls',
                message: 'Create a poll to find a private shared meeting time.',
              )
            else
              ..._polls.map(
                (poll) => Padding(
                  padding: const EdgeInsets.only(bottom: 12),
                  child: _PollCard(
                    poll: poll,
                    currentUserId: _service.currentUserId,
                    onVote: (option, response) => _vote(poll, option, response),
                    onConfirm: (option) => _confirm(poll, option),
                    onCancel: () => _cancel(poll),
                    onSetPreferences: () => _setPreferences(poll),
                  ),
                ),
              ),
          ],
        ),
      ),
      floatingActionButton: FloatingActionButton.extended(
        onPressed: _loading ? null : _createPoll,
        backgroundColor: AppColors.primary,
        elevation: 0,
        icon: const Icon(Icons.add),
        label: const Text('New poll'),
      ),
    );
  }
}

class _PrivacyBanner extends StatelessWidget {
  const _PrivacyBanner({required this.onCreate});

  final VoidCallback onCreate;

  @override
  Widget build(BuildContext context) {
    final brightness = Theme.of(context).brightness;
    return SettingsInsetCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              CircleAvatar(
                backgroundColor: AppColors.collabEvent.withAlpha(30),
                child: const Icon(
                  Icons.lock_outline,
                  color: AppColors.collabEvent,
                ),
              ),
              const SizedBox(width: 14),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      'Busy-only availability',
                      style: CalendarTextStyles.upcomingRow(brightness).copyWith(
                        fontWeight: FontWeight.w600,
                      ),
                    ),
                    const SizedBox(height: 4),
                    Text(
                      'Synctra compares unavailable time ranges without sharing event names. '
                      'Invitees vote before the organizer confirms.',
                      style: CalendarTextStyles.hourLabel(brightness).copyWith(
                        fontSize: 12,
                        height: 1.45,
                      ),
                    ),
                  ],
                ),
              ),
            ],
          ),
          const SizedBox(height: 12),
          Align(
            alignment: Alignment.centerRight,
            child: SynctraPrimaryButton(
              onPressed: onCreate,
              icon: Icons.schedule,
              label: 'Find time',
            ),
          ),
        ],
      ),
    );
  }
}

class _PollCard extends StatelessWidget {
  const _PollCard({
    required this.poll,
    required this.currentUserId,
    required this.onVote,
    required this.onConfirm,
    required this.onCancel,
    required this.onSetPreferences,
  });

  final CollaborationPoll poll;
  final String currentUserId;
  final void Function(CollaborationOption option, String response) onVote;
  final ValueChanged<CollaborationOption> onConfirm;
  final VoidCallback onCancel;
  final VoidCallback onSetPreferences;

  @override
  Widget build(BuildContext context) {
    final brightness = Theme.of(context).brightness;
    final organizer = poll.organizerId == currentUserId;
    return SettingsInsetCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      poll.title,
                      style: CalendarTextStyles.upcomingRow(brightness).copyWith(
                        fontWeight: FontWeight.w600,
                      ),
                    ),
                    const SizedBox(height: 4),
                    Text(
                      '${poll.durationMinutes} min · ${poll.participants.length} participants',
                      style: CalendarTextStyles.hourLabel(brightness).copyWith(
                        fontSize: 12,
                        height: 1.4,
                      ),
                    ),
                  ],
                ),
              ),
              _StatusLabel(status: poll.status),
              if (poll.status == 'open')
                IconButton(
                  tooltip: 'Set preferred meeting times',
                  onPressed: onSetPreferences,
                  icon: const Icon(Icons.tune),
                ),
              if (organizer && poll.status == 'open')
                IconButton(
                  tooltip: 'Cancel poll',
                  onPressed: onCancel,
                  icon: const Icon(Icons.close),
                ),
            ],
          ),
          if (poll.description.isNotEmpty) ...[
            const SizedBox(height: 8),
            Text(
              poll.description,
              style: CalendarTextStyles.upcomingRow(brightness),
            ),
          ],
          const SizedBox(height: 12),
          Wrap(
            spacing: 6,
            runSpacing: 6,
            children: [
              for (final participant in poll.participants)
                Chip(
                  avatar: Icon(
                    participant.responseStatus == 'responded'
                        ? Icons.check_circle_outline
                        : Icons.person_outline,
                    size: 16,
                  ),
                  label: Text(participant.displayName),
                  visualDensity: VisualDensity.compact,
                ),
            ],
          ),
          const Divider(height: 24),
          if (poll.options.isEmpty)
            Text(
              'No shared time was found in this window.',
              style: CalendarTextStyles.hourLabel(brightness).copyWith(fontSize: 12),
            )
          else
            for (var index = 0; index < poll.options.length; index++) ...[
              _OptionRow(
                option: poll.options[index],
                rank: index + 1,
                participantCount: poll.participants.length,
                confirmed: poll.confirmedOptionId == poll.options[index].id,
                open: poll.status == 'open',
                organizer: organizer,
                onVote: (response) => onVote(poll.options[index], response),
                onConfirm: () => onConfirm(poll.options[index]),
              ),
              if (index != poll.options.length - 1) const Divider(height: 20),
            ],
        ],
      ),
    );
  }
}

class _OptionRow extends StatelessWidget {
  const _OptionRow({
    required this.option,
    required this.rank,
    required this.participantCount,
    required this.confirmed,
    required this.open,
    required this.organizer,
    required this.onVote,
    required this.onConfirm,
  });

  final CollaborationOption option;
  final int rank;
  final int participantCount;
  final bool confirmed;
  final bool open;
  final bool organizer;
  final ValueChanged<String> onVote;
  final VoidCallback onConfirm;

  @override
  Widget build(BuildContext context) {
    final localizations = MaterialLocalizations.of(context);
    final scheme = Theme.of(context).colorScheme;
    final unavailable = option.votes['unavailable'] ?? 0;
    final responses = option.votes.values.fold<int>(
      0,
      (total, count) => total + count,
    );
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            SizedBox(
              width: 28,
              child: Text(
                '$rank',
                style: TextStyle(
                  color: scheme.onSurfaceVariant,
                  fontWeight: FontWeight.bold,
                ),
              ),
            ),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    '${localizations.formatMediumDate(option.startTime)} · '
                    '${TimeOfDay.fromDateTime(option.startTime).format(context)} – '
                    '${TimeOfDay.fromDateTime(option.endTime).format(context)}',
                    style: const TextStyle(fontWeight: FontWeight.w600),
                  ),
                  const SizedBox(height: 3),
                  Text(
                    '${option.preferredMatches}/$participantCount preference matches · '
                    '$responses/$participantCount voted · '
                    '$unavailable unavailable',
                    style: Theme.of(context).textTheme.bodySmall?.copyWith(
                          color: unavailable > 0
                              ? scheme.error
                              : scheme.onSurfaceVariant,
                        ),
                  ),
                ],
              ),
            ),
            if (confirmed)
              const Icon(Icons.event_available, color: AppColors.collabEvent),
          ],
        ),
        if (open && !confirmed) ...[
          const SizedBox(height: 6),
          Wrap(
            alignment: WrapAlignment.end,
            crossAxisAlignment: WrapCrossAlignment.center,
            spacing: 4,
            runSpacing: 4,
            children: [
              IconButton(
                tooltip: 'Available',
                onPressed: () => onVote('available'),
                icon: const Icon(Icons.check_circle_outline),
              ),
              IconButton(
                tooltip: 'Preferred',
                onPressed: () => onVote('preferred'),
                icon: const Icon(Icons.star_outline),
              ),
              IconButton(
                tooltip: 'Unavailable',
                onPressed: () => onVote('unavailable'),
                icon: const Icon(Icons.block),
              ),
              if (organizer)
                FilledButton(
                  onPressed: unavailable == 0 && responses == participantCount
                      ? onConfirm
                      : null,
                  child: const Text('Confirm'),
                ),
            ],
          ),
        ],
      ],
    );
  }
}

class _StatusLabel extends StatelessWidget {
  const _StatusLabel({required this.status});

  final String status;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final color = switch (status) {
      'confirmed' => AppColors.collabEvent,
      'cancelled' => scheme.error,
      _ => scheme.primary,
    };
    return Padding(
      padding: const EdgeInsets.only(top: 2),
      child: Text(
        status.toUpperCase(),
        style: TextStyle(
          color: color,
          fontSize: 11,
          fontWeight: FontWeight.bold,
        ),
      ),
    );
  }
}

class _PollDraft {
  final String title;
  final String description;
  final int durationMinutes;
  final DateTime windowStart;
  final DateTime windowEnd;
  final List<String> invitees;
  final List<String> preferredPeriods;

  const _PollDraft({
    required this.title,
    required this.description,
    required this.durationMinutes,
    required this.windowStart,
    required this.windowEnd,
    required this.invitees,
    required this.preferredPeriods,
  });
}

class _CreatePollDialog extends StatefulWidget {
  const _CreatePollDialog();

  @override
  State<_CreatePollDialog> createState() => _CreatePollDialogState();
}

class _CreatePollDialogState extends State<_CreatePollDialog> {
  late final TextEditingController _title;
  late final TextEditingController _description;
  late final TextEditingController _invitees;
  late DateTime _startDay;
  late DateTime _endDay;
  var _durationMinutes = 60;
  final _preferredPeriods = <String>{};
  String? _validation;

  @override
  void initState() {
    super.initState();
    _title = TextEditingController();
    _description = TextEditingController();
    _invitees = TextEditingController();
    final now = DateTime.now();
    _startDay = DateTime(now.year, now.month, now.day);
    _endDay = _startDay.add(const Duration(days: 7));
  }

  @override
  void dispose() {
    _title.dispose();
    _description.dispose();
    _invitees.dispose();
    super.dispose();
  }

  void _submit() {
    final title = _title.text.trim();
    final invitees = _invitees.text
        .split(RegExp(r'[,;\n]+'))
        .map((value) => value.trim())
        .where((value) => value.isNotEmpty)
        .toSet()
        .toList();
    if (title.isEmpty || invitees.isEmpty) {
      setState(() {
        _validation = title.isEmpty
            ? 'Enter an event title.'
            : 'Invite at least one participant.';
      });
      return;
    }
    Navigator.pop(
      context,
      _PollDraft(
        title: title,
        description: _description.text.trim(),
        durationMinutes: _durationMinutes,
        windowStart: DateTime(
          _startDay.year,
          _startDay.month,
          _startDay.day,
          8,
        ),
        windowEnd: DateTime(
          _endDay.year,
          _endDay.month,
          _endDay.day,
          22,
        ),
        invitees: invitees,
        preferredPeriods: _preferredPeriods.toList(),
      ),
    );
  }

  Future<void> _pickDay({required bool start}) async {
    final picked = await showDatePicker(
      context: context,
      initialDate: start ? _startDay : _endDay,
      firstDate: DateTime.now().subtract(const Duration(days: 1)),
      lastDate: DateTime.now().add(const Duration(days: 366)),
    );
    if (picked == null || !mounted) return;
    setState(() {
      if (start) {
        _startDay = picked;
        if (_endDay.isBefore(_startDay)) _endDay = _startDay;
      } else {
        _endDay = picked.isBefore(_startDay) ? _startDay : picked;
      }
    });
  }

  @override
  Widget build(BuildContext context) {
    final localizations = MaterialLocalizations.of(context);
    return AlertDialog(
      title: const Text('Find a group time'),
      content: SizedBox(
        width: 480,
        child: SingleChildScrollView(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              TextField(
                controller: _title,
                autofocus: true,
                textCapitalization: TextCapitalization.sentences,
                decoration: const InputDecoration(
                  labelText: 'Event name',
                  border: OutlineInputBorder(),
                ),
              ),
              const SizedBox(height: 12),
              TextField(
                controller: _invitees,
                decoration: const InputDecoration(
                  labelText: 'Participant names or emails',
                  helperText: 'Separate multiple participants with commas.',
                  border: OutlineInputBorder(),
                ),
              ),
              const SizedBox(height: 12),
              DropdownButtonFormField<int>(
                initialValue: _durationMinutes,
                decoration: const InputDecoration(
                  labelText: 'Duration',
                  border: OutlineInputBorder(),
                ),
                items: const [
                  DropdownMenuItem(value: 30, child: Text('30 minutes')),
                  DropdownMenuItem(value: 60, child: Text('1 hour')),
                  DropdownMenuItem(value: 90, child: Text('1.5 hours')),
                  DropdownMenuItem(value: 120, child: Text('2 hours')),
                  DropdownMenuItem(value: 180, child: Text('3 hours')),
                ],
                onChanged: (value) {
                  if (value != null) setState(() => _durationMinutes = value);
                },
              ),
              const SizedBox(height: 12),
              Align(
                alignment: Alignment.centerLeft,
                child: Text(
                  'Preferred meeting times',
                  style: Theme.of(context).textTheme.labelLarge,
                ),
              ),
              const SizedBox(height: 6),
              Align(
                alignment: Alignment.centerLeft,
                child: Wrap(
                  spacing: 6,
                  runSpacing: 6,
                  children: [
                    for (final period in _productivityPeriods)
                      FilterChip(
                        label: Text(period),
                        selected: _preferredPeriods.contains(period),
                        onSelected: (enabled) {
                          setState(() {
                            if (enabled) {
                              _preferredPeriods.add(period);
                            } else {
                              _preferredPeriods.remove(period);
                            }
                          });
                        },
                      ),
                  ],
                ),
              ),
              const SizedBox(height: 4),
              ListTile(
                contentPadding: EdgeInsets.zero,
                leading: const Icon(Icons.date_range_outlined),
                title: const Text('Date window'),
                subtitle: Text(
                  '${localizations.formatMediumDate(_startDay)} – '
                  '${localizations.formatMediumDate(_endDay)}',
                ),
                onTap: () => _pickDay(start: true),
                trailing: IconButton(
                  tooltip: 'Choose end date',
                  onPressed: () => _pickDay(start: false),
                  icon: const Icon(Icons.last_page),
                ),
              ),
              TextField(
                controller: _description,
                maxLines: 2,
                decoration: const InputDecoration(
                  labelText: 'Notes (optional)',
                  border: OutlineInputBorder(),
                ),
              ),
              if (_validation != null) ...[
                const SizedBox(height: 8),
                Align(
                  alignment: Alignment.centerLeft,
                  child: Text(
                    _validation!,
                    style:
                        TextStyle(color: Theme.of(context).colorScheme.error),
                  ),
                ),
              ],
            ],
          ),
        ),
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.pop(context),
          child: const Text('Cancel'),
        ),
        FilledButton.icon(
          onPressed: _submit,
          icon: const Icon(Icons.search),
          label: const Text('Find times'),
        ),
      ],
    );
  }
}

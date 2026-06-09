import 'package:dio/dio.dart';
import 'package:flutter/foundation.dart';
import 'package:supabase_flutter/supabase_flutter.dart';

import '../../core/constants/api_constants.dart';
import '../../core/constants/preview_flags.dart';
import '../../data/models/event_model.dart';
import '../../data/models/ical_feed.dart';
import 'user_settings_service.dart';

class IcalFeedValidationResult {
  final bool ok;
  final String message;

  const IcalFeedValidationResult({required this.ok, required this.message});
}

/// Validates, stores, and syncs iCal feeds via Supabase + backend preview API.
class IcalFeedService {
  IcalFeedService({Dio? dio, UserSettingsService? settings})
      : _dio = dio ?? Dio(),
        _settings = settings;

  final Dio _dio;
  final UserSettingsService? _settings;

  SupabaseClient get _db => Supabase.instance.client;
  String? get _userId => _db.auth.currentUser?.id;

  UserSettingsService get _userSettings =>
      _settings ?? UserSettingsService();

  static String normalizeUrl(String raw) {
    var url = raw.trim();
    if (url.startsWith('webcal://')) {
      url = url.replaceFirst('webcal://', 'https://');
    }
    return url;
  }

  static IcalFeedValidationResult validateUrlFormat(String raw) {
    final url = normalizeUrl(raw);
    if (url.isEmpty) {
      return const IcalFeedValidationResult(ok: false, message: 'URL is required');
    }
    final uri = Uri.tryParse(url);
    if (uri == null || !uri.hasScheme) {
      return const IcalFeedValidationResult(
        ok: false,
        message: 'Enter a valid http(s) or webcal URL',
      );
    }
    if (uri.scheme != 'http' && uri.scheme != 'https') {
      return const IcalFeedValidationResult(
        ok: false,
        message: 'URL must start with http:// or https://',
      );
    }
    return const IcalFeedValidationResult(ok: true, message: 'Valid URL');
  }

  Future<IcalFeedValidationResult> validateReachable(String raw) async {
    final format = validateUrlFormat(raw);
    if (!format.ok) return format;

    final url = normalizeUrl(raw);
    try {
      final resp = await _dio.head(
        url,
        options: Options(
          followRedirects: true,
          validateStatus: (s) => s != null && s < 500,
          sendTimeout: const Duration(seconds: 10),
          receiveTimeout: const Duration(seconds: 10),
        ),
      );
      if (resp.statusCode != null && resp.statusCode! >= 400) {
        return IcalFeedValidationResult(
          ok: false,
          message: 'Feed returned HTTP ${resp.statusCode}',
        );
      }
      return const IcalFeedValidationResult(ok: true, message: 'Feed reachable');
    } catch (_) {
      // Some servers block HEAD — still allow save per spec.
      return const IcalFeedValidationResult(
        ok: true,
        message: 'Could not verify feed; saved for retry on sync',
      );
    }
  }

  Future<List<IcalFeed>> loadFeeds() async {
    final uid = _userId;
    if (uid == null) return const [];

    try {
      final rows = await _db
          .from('ical_feeds')
          .select()
          .eq('user_id', uid)
          .order('created_at');
      if (rows is! List) return const [];
      return rows
          .whereType<Map>()
          .map((r) => IcalFeed.fromSupabase(Map<String, dynamic>.from(r)))
          .toList();
    } catch (e) {
      debugPrint('IcalFeedService.loadFeeds: $e');
      final settings = await _userSettings.getOrCreate();
      return settings.icalLinks
          .map(
            (url) => IcalFeed(
              id: url.hashCode.toString(),
              userId: uid,
              url: url,
            ),
          )
          .toList();
    }
  }

  Future<IcalFeed?> addFeed(String rawUrl, {String? label}) async {
    final url = normalizeUrl(rawUrl);
    final format = validateUrlFormat(url);
    if (!format.ok) throw ArgumentError(format.message);

    final uid = _userId;
    if (uid == null) {
      if (!PreviewFlags.noAuth) return null;
      final settings = await _userSettings.getOrCreate();
      if (settings.icalLinks.contains(url)) {
        throw StateError('This feed is already connected');
      }
      await validateReachable(url);
      await _userSettings.appendIcalLink(url);
      return IcalFeed(
        id: url.hashCode.toString(),
        userId: 'preview',
        url: url,
        label: label,
      );
    }

    final existing = await loadFeeds();
    if (existing.any((f) => f.url == url)) {
      throw StateError('This feed is already connected');
    }

    final reachable = await validateReachable(url);

    try {
      final row = await _db
          .from('ical_feeds')
          .insert({
            'user_id': uid,
            'url': url,
            'label': label?.trim().isNotEmpty == true ? label!.trim() : null,
          })
          .select()
          .single();
      final feed = IcalFeed.fromSupabase(Map<String, dynamic>.from(row));
      await _userSettings.appendIcalLink(url);
      if (!reachable.ok) {
        debugPrint('Feed saved with warning: ${reachable.message}');
      }
      return feed;
    } catch (e) {
      debugPrint('IcalFeedService.addFeed fallback: $e');
      await _userSettings.appendIcalLink(url);
      return IcalFeed(
        id: url.hashCode.toString(),
        userId: uid,
        url: url,
        label: label,
      );
    }
  }

  Future<void> removeFeed(IcalFeed feed) async {
    try {
      await _db.from('ical_feeds').delete().eq('id', feed.id);
    } catch (e) {
      debugPrint('IcalFeedService.removeFeed: $e');
    }
    await _userSettings.removeIcalLink(feed.url);
  }

  Future<List<EventModel>> syncFeed(IcalFeed feed) async {
    final resp = await _dio.post<Map<String, dynamic>>(
      '${ApiConstants.baseUrl}/events/ical-feeds/preview',
      data: {'url': feed.url, 'name': feed.displayLabel},
    );
    final eventsRaw = resp.data?['events'];
    if (eventsRaw is! List) return const [];

    final now = DateTime.now().toUtc().toIso8601String();
    try {
      await _db.from('ical_feeds').update({'last_synced_at': now}).eq('id', feed.id);
    } catch (_) {}

    return eventsRaw
        .whereType<Map>()
        .map((m) {
          final map = Map<String, dynamic>.from(m);
          return EventModel.fromJson({
            'id': 'ical-${feed.id}-${map['id'] ?? map['start_time']}',
            'title': map['title'] ?? 'Event',
            'start_time': map['start_time'],
            'end_time': map['end_time'],
            'source': 'ical',
            'is_fixed': true,
            'description': map['description'],
          });
        })
        .toList();
  }

  Future<List<EventModel>> syncAllFeeds() async {
    final feeds = await loadFeeds();
    final out = <EventModel>[];
    for (final feed in feeds) {
      try {
        out.addAll(await syncFeed(feed));
      } catch (e) {
        debugPrint('syncFeed failed ${feed.url}: $e');
      }
    }
    return out;
  }
}

void registerIcalFeedService() {
  // Registered alongside UserSettingsService in main.dart
}

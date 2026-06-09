class IcalFeed {
  final String id;
  final String userId;
  final String url;
  final String? label;
  final DateTime? lastSyncedAt;

  const IcalFeed({
    required this.id,
    required this.userId,
    required this.url,
    this.label,
    this.lastSyncedAt,
  });

  factory IcalFeed.fromSupabase(Map<String, dynamic> row) => IcalFeed(
        id: row['id'] as String,
        userId: row['user_id'] as String,
        url: row['url'] as String,
        label: row['label'] as String?,
        lastSyncedAt: row['last_synced_at'] != null
            ? DateTime.parse(row['last_synced_at'] as String)
            : null,
      );

  Map<String, dynamic> toSupabaseMap() => {
        'user_id': userId,
        'url': url,
        if (label != null && label!.isNotEmpty) 'label': label,
        if (lastSyncedAt != null)
          'last_synced_at': lastSyncedAt!.toUtc().toIso8601String(),
      };

  String get displayLabel {
    if (label != null && label!.trim().isNotEmpty) return label!.trim();
    try {
      final host = Uri.parse(url).host;
      return host.isNotEmpty ? host : url;
    } catch (_) {
      return url;
    }
  }
}

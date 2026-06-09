/// Human-readable relative sync timestamps.
String formatRelativeSyncTime(DateTime syncedAt, [DateTime? now]) {
  final clock = now ?? DateTime.now();
  final diff = clock.difference(syncedAt);
  if (diff.inSeconds < 45) return 'just now';
  if (diff.inMinutes < 1) return 'less than a minute ago';
  if (diff.inMinutes < 60) {
    final m = diff.inMinutes;
    return m == 1 ? '1 minute ago' : '$m minutes ago';
  }
  if (diff.inHours < 24) {
    final h = diff.inHours;
    return h == 1 ? '1 hour ago' : '$h hours ago';
  }
  final d = diff.inDays;
  return d == 1 ? '1 day ago' : '$d days ago';
}

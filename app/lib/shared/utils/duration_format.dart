// Parse and display task duration as hours and minutes.
class DurationFormat {
  DurationFormat._();

  static const defaultEstimateMinutes = 180;

  static int parseField(String raw) => int.tryParse(raw.trim()) ?? 0;

  static ({int hours, int minutes}) fromMinutes(int totalMinutes) {
    final clamped = totalMinutes.clamp(0, 365 * 24 * 60);
    return (hours: clamped ~/ 60, minutes: clamped % 60);
  }

  static int toTotalMinutes({int hours = 0, int minutes = 0}) {
    hours = hours.clamp(0, 365 * 24);
    minutes = minutes.clamp(0, 59);
    final total = hours * 60 + minutes;
    if (total <= 0) return 0;
    return total.clamp(1, 365 * 24 * 60);
  }

  /// Readable label, e.g. `3 hr 0 min` or `45 min`.
  static String formatEstimate(int totalMinutes) {
    if (totalMinutes <= 0) return 'No estimate';
    final parts = fromMinutes(totalMinutes);
    if (parts.hours == 0) return '${parts.minutes} min';
    if (parts.minutes == 0) {
      return parts.hours == 1 ? '1 hr' : '${parts.hours} hr';
    }
    final hrLabel = parts.hours == 1 ? '1 hr' : '${parts.hours} hr';
    return '$hrLabel ${parts.minutes} min';
  }

  static ({int? minutes, String? error}) parseHoursMinutes(
    String hoursRaw,
    String minutesRaw,
  ) {
    final total = toTotalMinutes(
      hours: parseField(hoursRaw),
      minutes: parseField(minutesRaw),
    );
    if (total <= 0) {
      return (minutes: null, error: 'Enter at least 1 minute of work.');
    }
    return (minutes: total, error: null);
  }
}

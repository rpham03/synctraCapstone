// 12-hour local time labels for Chat and schedule APIs (device timezone).
import 'package:intl/intl.dart';

class LocalTimeFormat {
  LocalTimeFormat._();

  /// Short label for calendar time gutter — device timezone (e.g. PST, PDT, GMT+1).
  static String timeZoneLabel({bool compact = false}) {
    final now = DateTime.now();
    final name = now.timeZoneName.trim();
    if (name.isNotEmpty && name.length <= 5 && !name.contains(' ')) {
      if (compact && name.length > 3) return name.substring(0, 3);
      return name;
    }
    final offset = _gmtOffsetLabel(now.timeZoneOffset);
    if (compact) {
      return offset.replaceFirst('GMT', '');
    }
    return offset;
  }

  static String _gmtOffsetLabel(Duration offset) {
    final totalMinutes = offset.inMinutes;
    final sign = totalMinutes >= 0 ? '+' : '-';
    final abs = totalMinutes.abs();
    final hours = abs ~/ 60;
    final mins = abs % 60;
    if (mins == 0) return 'GMT$sign$hours';
    return 'GMT$sign$hours:${mins.toString().padLeft(2, '0')}';
  }

  static String time(DateTime dt) => DateFormat('h:mm a').format(dt);

  static String dateShort(DateTime dt) => DateFormat('EEE, MMM d').format(dt);

  static String timeRange(DateTime start, DateTime end) =>
      '${time(start)} – ${time(end)}';

  static String whenTimed(DateTime start, DateTime end) =>
      '${dateShort(start)} · ${timeRange(start, end)}';

  static String whenDateOnly(DateTime day) => dateShort(day);

  static String dueLabel(DateTime due) {
    final atMidnight = due.hour == 0 && due.minute == 0;
    if (atMidnight) return dateShort(due);
    return '${dateShort(due)} · ${time(due)}';
  }
}

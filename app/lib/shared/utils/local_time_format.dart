// 12-hour local time labels for Chat and schedule APIs (device timezone).
import 'package:intl/intl.dart';

class LocalTimeFormat {
  LocalTimeFormat._();

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

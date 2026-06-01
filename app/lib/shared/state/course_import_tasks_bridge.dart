import 'package:flutter/foundation.dart';
import 'package:flutter/scheduler.dart';

class CourseImportTasksBridge extends ChangeNotifier {
  CourseImportTasksBridge._();
  static final CourseImportTasksBridge instance = CourseImportTasksBridge._();

  void refresh() {
    final phase = SchedulerBinding.instance.schedulerPhase;
    if (phase == SchedulerPhase.idle ||
        phase == SchedulerPhase.postFrameCallbacks) {
      notifyListeners();
      return;
    }

    SchedulerBinding.instance.addPostFrameCallback((_) => notifyListeners());
  }
}

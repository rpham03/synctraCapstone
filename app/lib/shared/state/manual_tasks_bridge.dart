import 'package:flutter/foundation.dart';
import 'package:flutter/scheduler.dart';

/// Notifies Calendar + Tasks when manual task rows change (add/edit/delete/complete).
class ManualTasksBridge extends ChangeNotifier {
  ManualTasksBridge._();
  static final ManualTasksBridge instance = ManualTasksBridge._();

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

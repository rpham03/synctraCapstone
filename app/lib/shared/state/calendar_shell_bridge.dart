// Lets [CalendarScreen] inject the month/upcoming planner into [MainShell]'s sidebar.
import 'package:flutter/material.dart';
import 'package:flutter/scheduler.dart';

class CalendarShellBridge extends ChangeNotifier {
  CalendarShellBridge._();
  static final CalendarShellBridge instance = CalendarShellBridge._();

  Widget Function()? _plannerBuilder;
  VoidCallback? openDrawer;

  bool get hasPlanner => _plannerBuilder != null;

  Widget? buildPlanner() => _plannerBuilder?.call();

  void _notifySafely() {
    final phase = SchedulerBinding.instance.schedulerPhase;
    if (phase == SchedulerPhase.idle ||
        phase == SchedulerPhase.postFrameCallbacks) {
      notifyListeners();
      return;
    }

    SchedulerBinding.instance.addPostFrameCallback((_) => notifyListeners());
  }

  void setPlannerBuilder(Widget Function()? builder) {
    _plannerBuilder = builder;
    _notifySafely();
  }

  /// Rebuild sidebar planner without replacing the builder reference.
  void refreshPlanner() => _notifySafely();

  void clearPlanner() => setPlannerBuilder(null);

  void registerOpenDrawer(VoidCallback? callback) {
    openDrawer = callback;
  }
}

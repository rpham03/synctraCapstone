// Lets [CalendarScreen] inject the month/upcoming planner into [MainShell]'s sidebar.
import 'package:flutter/material.dart';

class CalendarShellBridge extends ChangeNotifier {
  CalendarShellBridge._();
  static final CalendarShellBridge instance = CalendarShellBridge._();

  Widget Function()? _plannerBuilder;
  VoidCallback? openDrawer;

  bool get hasPlanner => _plannerBuilder != null;

  Widget? buildPlanner() => _plannerBuilder?.call();

  void setPlannerBuilder(Widget Function()? builder) {
    _plannerBuilder = builder;
    notifyListeners();
  }

  /// Rebuild sidebar planner without replacing the builder reference.
  void refreshPlanner() => notifyListeners();

  void clearPlanner() => setPlannerBuilder(null);

  void registerOpenDrawer(VoidCallback? callback) {
    openDrawer = callback;
  }
}

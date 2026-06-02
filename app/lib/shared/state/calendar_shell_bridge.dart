// Drawer actions and calendar import shortcuts for [MainShell] / sidebar.
import 'package:flutter/foundation.dart';

class CalendarShellBridge {
  CalendarShellBridge._();
  static final CalendarShellBridge instance = CalendarShellBridge._();

  VoidCallback? openDrawer;
  VoidCallback? onOpenIcal;
  VoidCallback? onOpenCourseImport;

  void registerOpenDrawer(VoidCallback? callback) {
    openDrawer = callback;
  }

  void registerImportActions({
    VoidCallback? onIcal,
    VoidCallback? onCourseImport,
  }) {
    onOpenIcal = onIcal;
    onOpenCourseImport = onCourseImport;
  }
}

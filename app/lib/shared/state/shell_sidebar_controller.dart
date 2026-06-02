// Desktop sidebar visibility — toggled from the menu button on Calendar, Tasks, Chat, etc.
import 'package:flutter/foundation.dart';

class ShellSidebarController extends ChangeNotifier {
  ShellSidebarController._();
  static final ShellSidebarController instance = ShellSidebarController._();

  static const double desktopBreakpoint = 1000;

  bool _visible = true;

  bool get visible => _visible;

  void toggle() {
    _visible = !_visible;
    notifyListeners();
  }

  void show() {
    if (_visible) return;
    _visible = true;
    notifyListeners();
  }

  void hide() {
    if (!_visible) return;
    _visible = false;
    notifyListeners();
  }
}

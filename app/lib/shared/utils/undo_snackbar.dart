import 'package:flutter/material.dart';

/// Shows a floating snackbar with a short undo window.
void showUndoSnackBar(
  BuildContext context, {
  required String message,
  required Future<void> Function() onUndo,
  Duration duration = const Duration(seconds: 5),
}) {
  final messenger = ScaffoldMessenger.of(context);
  messenger.hideCurrentSnackBar();
  messenger.showSnackBar(
    SnackBar(
      content: Text(message),
      duration: duration,
      action: SnackBarAction(
        label: 'Undo',
        onPressed: () {
          onUndo();
        },
      ),
    ),
  );
}

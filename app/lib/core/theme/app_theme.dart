// Defines light and dark MaterialApp themes for the Syntra app.
import 'package:flutter/material.dart';

class AppTheme {
  static ThemeData get light => ThemeData(
        useMaterial3: true,
        colorScheme: ColorScheme.fromSeed(seedColor: Colors.deepPurple),
      );

  static ThemeData get dark => ThemeData.dark(useMaterial3: true);
}

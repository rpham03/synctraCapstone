// Defines light and dark MaterialApp themes for the Synctra app.
import 'package:flutter/material.dart';

class AppColors {
  // Brand purple used throughout the app
  static const primary   = Color(0xFF6C63FF);
  static const secondary = Color(0xFF03DAC6);
  static const surface   = Color(0xFFF8F9FE);
  static const error     = Color(0xFFB00020);

  // Event category colors shown on the calendar
  static const fixedEvent    = Color(0xFF4A90D9); // classes, exams — blue
  static const flexibleBlock = Color(0xFF7ED321); // study/work blocks — green
  static const collabEvent   = Color(0xFFF5A623); // group events — orange
  static const deadline      = Color(0xFFD0021B); // due dates — red
}

class AppTheme {
  static ThemeData get light => ThemeData(
        useMaterial3: true,
        colorScheme: ColorScheme.fromSeed(
          seedColor: AppColors.primary,
          surface: AppColors.surface,
        ),
        scaffoldBackgroundColor: AppColors.surface,
        appBarTheme: const AppBarTheme(
          backgroundColor: Colors.white,
          foregroundColor: Color(0xFF1A1A2E),
          elevation: 0,
          centerTitle: true,
        ),
        cardTheme: CardThemeData(
          elevation: 2,
          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
        ),
        inputDecorationTheme: InputDecorationTheme(
          border: OutlineInputBorder(borderRadius: BorderRadius.circular(12)),
          filled: true,
          fillColor: Colors.white,
        ),
        filledButtonTheme: FilledButtonThemeData(
          style: FilledButton.styleFrom(
            minimumSize: const Size.fromHeight(52),
            shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
          ),
        ),
      );

  static ThemeData get dark => ThemeData(
        useMaterial3: true,
        colorScheme: ColorScheme.fromSeed(
          seedColor: AppColors.primary,
          brightness: Brightness.dark,
        ),
      );
}

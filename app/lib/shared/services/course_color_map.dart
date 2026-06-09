import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../../theme.dart';

/// Assigns and persists a stable course color per iCal feed / source id.
class CourseColorMap {
  CourseColorMap._();

  static const _prefsKey = 'synctra_course_color_map_v1';

  static final CourseColorMap instance = CourseColorMap._();

  final Map<String, int> _indexById = {};
  bool _loaded = false;

  Future<void> ensureLoaded() async {
    if (_loaded) return;
    final prefs = await SharedPreferences.getInstance();
    final raw = prefs.getString(_prefsKey);
    if (raw != null) {
      try {
        final map = Map<String, dynamic>.from(jsonDecode(raw) as Map);
        for (final entry in map.entries) {
          final idx = entry.value;
          if (idx is int && idx >= 0 && idx < AppColors.coursePalette.length) {
            _indexById[entry.key] = idx;
          }
        }
      } catch (_) {}
    }
    _loaded = true;
  }

  Future<void> _persist() async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(_prefsKey, jsonEncode(_indexById));
  }

  Color colorFor(String sourceId) {
    final idx = _indexById[sourceId];
    if (idx == null) return AppColors.courseBlue;
    return AppColors.coursePalette[idx];
  }

  Future<Color> assignFor(String sourceId) async {
    await ensureLoaded();
    if (!_indexById.containsKey(sourceId)) {
      final used = _indexById.values.toSet();
      var pick = 0;
      for (var i = 0; i < AppColors.coursePalette.length; i++) {
        if (!used.contains(i)) {
          pick = i;
          break;
        }
      }
      _indexById[sourceId] = pick;
      await _persist();
    }
    return colorFor(sourceId);
  }

  Future<void> remove(String sourceId) async {
    await ensureLoaded();
    if (_indexById.remove(sourceId) != null) {
      await _persist();
    }
  }

  Map<String, Color> asColorMap() {
    return {
      for (final e in _indexById.entries) e.key: AppColors.coursePalette[e.value],
    };
  }
}

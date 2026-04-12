// App entry point — initializes SyntraApp and runs the Flutter widget tree.
import 'package:flutter/material.dart';

void main() {
  runApp(const SyntraApp());
}

class SyntraApp extends StatelessWidget {
  const SyntraApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Syntra',
      theme: ThemeData(
        colorScheme: ColorScheme.fromSeed(seedColor: Colors.deepPurple),
        useMaterial3: true,
      ),
      home: const Placeholder(), // replaced by router
    );
  }
}

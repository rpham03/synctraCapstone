// Task list view — shows Canvas assignments and manually added tasks with due dates.
import 'package:flutter/material.dart';
import 'package:intl/intl.dart';

import '../../../core/theme/app_theme.dart';
import '../../../data/models/task_model.dart';

class TasksScreen extends StatefulWidget {
  const TasksScreen({super.key});

  @override
  State<TasksScreen> createState() => _TasksScreenState();
}

class _TasksScreenState extends State<TasksScreen> {
  // Filter state — which sources to show
  final Set<String> _activeFilters = {'canvas', 'manual'};

  // TODO: replace with real data from repository
  final List<TaskModel> _tasks = [];

  List<TaskModel> get _filtered =>
      _tasks.where((t) => _activeFilters.contains(t.source)).toList()
        ..sort((a, b) => a.dueDate.compareTo(b.dueDate));

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Tasks'),
        actions: [
          IconButton(
            icon: const Icon(Icons.sync),
            tooltip: 'Sync Canvas',
            onPressed: () {/* TODO: trigger Canvas sync */},
          ),
          IconButton(
            icon: const Icon(Icons.filter_list),
            tooltip: 'Filter',
            onPressed: _showFilterSheet,
          ),
        ],
      ),
      body: _filtered.isEmpty
          ? _EmptyTasks(onAdd: _showAddTask)
          : ListView.builder(
              padding: const EdgeInsets.all(16),
              itemCount: _filtered.length,
              itemBuilder: (_, i) => _TaskTile(
                task: _filtered[i],
                onToggle: (done) {
                  // TODO: update task completion in repository
                },
              ),
            ),
      floatingActionButton: FloatingActionButton(
        onPressed: _showAddTask,
        backgroundColor: AppColors.primary,
        child: const Icon(Icons.add),
      ),
    );
  }

  void _showFilterSheet() {
    showModalBottomSheet(
      context: context,
      shape: const RoundedRectangleBorder(
          borderRadius: BorderRadius.vertical(top: Radius.circular(20))),
      builder: (_) => StatefulBuilder(
        builder: (ctx, setModal) => Padding(
          padding: const EdgeInsets.all(24),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const Text('Filter Sources',
                  style: TextStyle(fontWeight: FontWeight.bold, fontSize: 16)),
              const SizedBox(height: 16),
              for (final source in ['canvas', 'manual'])
                CheckboxListTile(
                  value: _activeFilters.contains(source),
                  title: Text(source == 'canvas' ? 'Canvas Assignments' : 'Manual Tasks'),
                  activeColor: AppColors.primary,
                  onChanged: (v) {
                    setModal(() {
                      setState(() {
                        if (v == true) {
                          _activeFilters.add(source);
                        } else {
                          _activeFilters.remove(source);
                        }
                      });
                    });
                  },
                ),
            ],
          ),
        ),
      ),
    );
  }

  void _showAddTask() {
    // TODO: show add task dialog / bottom sheet
    ScaffoldMessenger.of(context).showSnackBar(
      const SnackBar(content: Text('Add task — coming soon')),
    );
  }
}

// ── Sub-widgets ────────────────────────────────────────────────────────────────

class _TaskTile extends StatelessWidget {
  final TaskModel task;
  final ValueChanged<bool> onToggle;
  const _TaskTile({required this.task, required this.onToggle});

  Color _urgencyColor(DateTime due) {
    final daysLeft = due.difference(DateTime.now()).inDays;
    if (daysLeft <= 1) return AppColors.deadline;
    if (daysLeft <= 3) return Colors.orange;
    return Colors.grey;
  }

  @override
  Widget build(BuildContext context) {
    final due = task.dueDate;
    final daysLeft = due.difference(DateTime.now()).inDays;
    final urgency = _urgencyColor(due);

    return Card(
      margin: const EdgeInsets.only(bottom: 10),
      child: ListTile(
        leading: Checkbox(
          value: task.isCompleted,
          activeColor: AppColors.primary,
          onChanged: (v) => onToggle(v ?? false),
        ),
        title: Text(
          task.title,
          style: TextStyle(
            fontWeight: FontWeight.w600,
            decoration: task.isCompleted ? TextDecoration.lineThrough : null,
            color: task.isCompleted ? Colors.grey : null,
          ),
        ),
        subtitle: Row(children: [
          Icon(Icons.schedule, size: 13, color: Colors.grey[500]),
          const SizedBox(width: 4),
          Text(
            '~${task.estimatedMinutes} min',
            style: TextStyle(fontSize: 12, color: Colors.grey[500]),
          ),
          const SizedBox(width: 12),
          if (task.source == 'canvas')
            const Icon(Icons.school_outlined, size: 13, color: Colors.blue),
        ]),
        trailing: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          crossAxisAlignment: CrossAxisAlignment.end,
          children: [
            Text(
              DateFormat('MMM d').format(due),
              style: TextStyle(color: urgency, fontWeight: FontWeight.w600, fontSize: 13),
            ),
            Text(
              daysLeft < 0
                  ? 'Overdue'
                  : daysLeft == 0
                      ? 'Today'
                      : '$daysLeft days',
              style: TextStyle(color: urgency, fontSize: 11),
            ),
          ],
        ),
      ),
    );
  }
}

class _EmptyTasks extends StatelessWidget {
  final VoidCallback onAdd;
  const _EmptyTasks({required this.onAdd});

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(Icons.checklist_outlined, size: 56, color: Colors.grey[300]),
          const SizedBox(height: 12),
          Text('No tasks yet', style: TextStyle(color: Colors.grey[500])),
          const SizedBox(height: 4),
          Text('Sync Canvas or add a task manually.',
              style: TextStyle(color: Colors.grey[400], fontSize: 12)),
          const SizedBox(height: 20),
          FilledButton.icon(
            onPressed: onAdd,
            icon: const Icon(Icons.add),
            label: const Text('Add Task'),
          ),
        ],
      ),
    );
  }
}

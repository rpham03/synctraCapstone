// Full-screen chat tab — same engine as the embedded panel on Tasks week view.
import 'package:flutter/material.dart';

import '../../../core/theme/app_tokens.dart';
import '../../../shared/services/synctra_chat_constants.dart';
import '../../../shared/widgets/synctra_chat_panel.dart';
import '../../../shared/widgets/synctra_page_header.dart';

class ChatScreen extends StatelessWidget {
  const ChatScreen({super.key});

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: AppTokens.calendarGridSurface(context),
      appBar: const SynctraPageHeader(
        title: 'Chat',
        subtitle: 'Ask about your schedule',
        showSettings: true,
      ),
      body: const SynctraChatPanel(
        showHeader: false,
        suggestionChips: SynctraChatConstants.suggestionChips,
      ),
    );
  }
}

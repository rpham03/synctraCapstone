# Supabase Schema

This project uses Supabase Auth plus public tables protected by row level security.

## Apply the Schema

From the repo root, use the Supabase CLI:

```bash
supabase link --project-ref wewuafrajfsqhaajofju
supabase db push
```

Or paste the contents of `supabase/migrations/20260422000000_initial_schema.sql` into the Supabase SQL editor.

## Main Tables

- `profiles`: one row per `auth.users` account. The trigger `on_auth_user_created` fills this from signup metadata such as `full_name`.
- `integrations`: Canvas and Google Calendar account connections.
- `courses`: Canvas/class records used to group tasks and events.
- `tasks`: flexible work such as assignments, studying, and manually added tasks. Matches `TaskModel` fields: `id`, `title`, `due_date`, `estimated_minutes`, `course_id`, `source`, `is_completed`.
- `calendar_events`: fixed events such as classes, meetings, exams, and Google Calendar imports. Matches `EventModel` fields: `id`, `title`, `start_time`, `end_time`, `source`, `is_fixed`.
- `schedule_versions`: AI-generated schedule alternatives, such as balanced or front-loaded plans.
- `schedule_blocks`: scheduled blocks for tasks. Matches `ScheduleBlockModel` fields: `id`, `task_id`, `start_time`, `end_time`, `is_ai_generated`; task title can be read from `tasks.title` or denormalized into `title`.
- `chat_threads` and `chat_messages`: persistent AI chat history.
- `collab_sessions` and `collab_members`: group sessions and invitations for collaboration features.

## Security

RLS is enabled on every public table. Users can only read and write their own rows. Collaboration rows are visible to the owner and accepted members.

Backend jobs that sync Canvas or Google Calendar should use a Supabase service role key, or connect directly to Postgres, so they can write imported rows on behalf of the authenticated user.

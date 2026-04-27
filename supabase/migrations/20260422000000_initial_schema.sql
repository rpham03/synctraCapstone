-- Synctra initial Supabase schema.
-- Apply with: supabase db push
-- Or paste into the Supabase SQL editor for the target project.

create extension if not exists pgcrypto;

do $$
begin
  create type public.task_source as enum ('canvas', 'manual');
exception
  when duplicate_object then null;
end;
$$;

do $$
begin
  create type public.event_source as enum ('google_calendar', 'canvas', 'manual');
exception
  when duplicate_object then null;
end;
$$;

do $$
begin
  create type public.integration_provider as enum ('canvas', 'google_calendar');
exception
  when duplicate_object then null;
end;
$$;

do $$
begin
  create type public.chat_role as enum ('user', 'assistant');
exception
  when duplicate_object then null;
end;
$$;

do $$
begin
  create type public.collab_member_role as enum ('owner', 'editor', 'viewer');
exception
  when duplicate_object then null;
end;
$$;

do $$
begin
  create type public.collab_member_status as enum ('invited', 'accepted', 'declined');
exception
  when duplicate_object then null;
end;
$$;

create or replace function public.set_updated_at()
returns trigger
language plpgsql
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

create table if not exists public.profiles (
  id uuid primary key references auth.users(id) on delete cascade,
  full_name text,
  avatar_url text,
  timezone text not null default 'America/Los_Angeles',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.integrations (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references public.profiles(id) on delete cascade,
  provider public.integration_provider not null,
  external_account_id text,
  display_name text,
  access_token text,
  refresh_token text,
  token_expires_at timestamptz,
  metadata jsonb not null default '{}'::jsonb,
  last_synced_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (user_id, provider, external_account_id)
);

create table if not exists public.courses (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references public.profiles(id) on delete cascade,
  integration_id uuid references public.integrations(id) on delete set null,
  external_id text,
  name text not null,
  code text,
  color text,
  starts_at timestamptz,
  ends_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (user_id, external_id)
);

create table if not exists public.tasks (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references public.profiles(id) on delete cascade,
  course_id uuid references public.courses(id) on delete set null,
  integration_id uuid references public.integrations(id) on delete set null,
  external_id text,
  title text not null,
  notes text,
  due_date timestamptz not null,
  estimated_minutes integer not null default 60 check (estimated_minutes > 0),
  source public.task_source not null default 'manual',
  is_completed boolean not null default false,
  completed_at timestamptz,
  priority integer not null default 0 check (priority between 0 and 5),
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (user_id, source, external_id)
);

create table if not exists public.calendar_events (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references public.profiles(id) on delete cascade,
  integration_id uuid references public.integrations(id) on delete set null,
  course_id uuid references public.courses(id) on delete set null,
  external_id text,
  title text not null,
  description text,
  location text,
  start_time timestamptz not null,
  end_time timestamptz not null,
  source public.event_source not null default 'manual',
  is_fixed boolean not null default true,
  is_all_day boolean not null default false,
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  check (end_time > start_time),
  unique (user_id, source, external_id)
);

create table if not exists public.schedule_versions (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references public.profiles(id) on delete cascade,
  label text not null,
  strategy text,
  is_applied boolean not null default false,
  starts_at timestamptz,
  ends_at timestamptz,
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.schedule_blocks (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references public.profiles(id) on delete cascade,
  version_id uuid references public.schedule_versions(id) on delete cascade,
  task_id uuid not null references public.tasks(id) on delete cascade,
  title text,
  start_time timestamptz not null,
  end_time timestamptz not null,
  is_ai_generated boolean not null default true,
  is_locked boolean not null default false,
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  check (end_time > start_time)
);

create table if not exists public.chat_threads (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references public.profiles(id) on delete cascade,
  title text not null default 'Synctra chat',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.chat_messages (
  id uuid primary key default gen_random_uuid(),
  thread_id uuid not null references public.chat_threads(id) on delete cascade,
  user_id uuid not null references public.profiles(id) on delete cascade,
  role public.chat_role not null,
  content text not null,
  action jsonb,
  created_at timestamptz not null default now()
);

create table if not exists public.collab_sessions (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid not null references public.profiles(id) on delete cascade,
  title text not null,
  description text,
  start_time timestamptz,
  end_time timestamptz,
  location text,
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  check (end_time is null or start_time is null or end_time > start_time)
);

create table if not exists public.collab_members (
  id uuid primary key default gen_random_uuid(),
  session_id uuid not null references public.collab_sessions(id) on delete cascade,
  user_id uuid references public.profiles(id) on delete cascade,
  invited_email text,
  role public.collab_member_role not null default 'viewer',
  status public.collab_member_status not null default 'invited',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  check (user_id is not null or invited_email is not null),
  unique (session_id, user_id),
  unique (session_id, invited_email)
);

create index if not exists idx_courses_user_id on public.courses(user_id);
create index if not exists idx_tasks_user_due_date on public.tasks(user_id, due_date);
create index if not exists idx_tasks_user_completed on public.tasks(user_id, is_completed);
create index if not exists idx_calendar_events_user_start on public.calendar_events(user_id, start_time);
create index if not exists idx_schedule_versions_user_created on public.schedule_versions(user_id, created_at desc);
create index if not exists idx_schedule_blocks_user_start on public.schedule_blocks(user_id, start_time);
create index if not exists idx_schedule_blocks_task_id on public.schedule_blocks(task_id);
create index if not exists idx_chat_messages_thread_created on public.chat_messages(thread_id, created_at);
create index if not exists idx_collab_sessions_owner_id on public.collab_sessions(owner_id);
create index if not exists idx_collab_members_user_id on public.collab_members(user_id);

drop trigger if exists set_profiles_updated_at on public.profiles;
create trigger set_profiles_updated_at
before update on public.profiles
for each row execute function public.set_updated_at();

drop trigger if exists set_integrations_updated_at on public.integrations;
create trigger set_integrations_updated_at
before update on public.integrations
for each row execute function public.set_updated_at();

drop trigger if exists set_courses_updated_at on public.courses;
create trigger set_courses_updated_at
before update on public.courses
for each row execute function public.set_updated_at();

drop trigger if exists set_tasks_updated_at on public.tasks;
create trigger set_tasks_updated_at
before update on public.tasks
for each row execute function public.set_updated_at();

drop trigger if exists set_calendar_events_updated_at on public.calendar_events;
create trigger set_calendar_events_updated_at
before update on public.calendar_events
for each row execute function public.set_updated_at();

drop trigger if exists set_schedule_versions_updated_at on public.schedule_versions;
create trigger set_schedule_versions_updated_at
before update on public.schedule_versions
for each row execute function public.set_updated_at();

drop trigger if exists set_schedule_blocks_updated_at on public.schedule_blocks;
create trigger set_schedule_blocks_updated_at
before update on public.schedule_blocks
for each row execute function public.set_updated_at();

drop trigger if exists set_chat_threads_updated_at on public.chat_threads;
create trigger set_chat_threads_updated_at
before update on public.chat_threads
for each row execute function public.set_updated_at();

drop trigger if exists set_collab_sessions_updated_at on public.collab_sessions;
create trigger set_collab_sessions_updated_at
before update on public.collab_sessions
for each row execute function public.set_updated_at();

drop trigger if exists set_collab_members_updated_at on public.collab_members;
create trigger set_collab_members_updated_at
before update on public.collab_members
for each row execute function public.set_updated_at();

create or replace function public.handle_new_user()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
begin
  insert into public.profiles (id, full_name, avatar_url)
  values (
    new.id,
    coalesce(new.raw_user_meta_data->>'full_name', new.raw_user_meta_data->>'name'),
    new.raw_user_meta_data->>'avatar_url'
  )
  on conflict (id) do update
  set
    full_name = excluded.full_name,
    avatar_url = excluded.avatar_url,
    updated_at = now();

  return new;
end;
$$;

drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created
after insert on auth.users
for each row execute function public.handle_new_user();

create or replace function public.is_collab_session_owner(session_id uuid)
returns boolean
language sql
security definer
set search_path = public
stable
as $$
  select exists (
    select 1
    from public.collab_sessions
    where id = $1
      and owner_id = auth.uid()
  );
$$;

create or replace function public.is_accepted_collab_member(session_id uuid)
returns boolean
language sql
security definer
set search_path = public
stable
as $$
  select exists (
    select 1
    from public.collab_members
    where collab_members.session_id = $1
      and user_id = auth.uid()
      and status = 'accepted'
  );
$$;

alter table public.profiles enable row level security;
alter table public.integrations enable row level security;
alter table public.courses enable row level security;
alter table public.tasks enable row level security;
alter table public.calendar_events enable row level security;
alter table public.schedule_versions enable row level security;
alter table public.schedule_blocks enable row level security;
alter table public.chat_threads enable row level security;
alter table public.chat_messages enable row level security;
alter table public.collab_sessions enable row level security;
alter table public.collab_members enable row level security;

drop policy if exists "profiles_select_own" on public.profiles;
create policy "profiles_select_own"
on public.profiles for select
using (auth.uid() = id);

drop policy if exists "profiles_update_own" on public.profiles;
create policy "profiles_update_own"
on public.profiles for update
using (auth.uid() = id)
with check (auth.uid() = id);

drop policy if exists "integrations_crud_own" on public.integrations;
create policy "integrations_crud_own"
on public.integrations for all
using (auth.uid() = user_id)
with check (auth.uid() = user_id);

drop policy if exists "courses_crud_own" on public.courses;
create policy "courses_crud_own"
on public.courses for all
using (auth.uid() = user_id)
with check (
  auth.uid() = user_id
  and (
    integration_id is null
    or exists (
      select 1 from public.integrations
      where integrations.id = courses.integration_id
        and integrations.user_id = auth.uid()
    )
  )
);

drop policy if exists "tasks_crud_own" on public.tasks;
create policy "tasks_crud_own"
on public.tasks for all
using (auth.uid() = user_id)
with check (
  auth.uid() = user_id
  and (
    course_id is null
    or exists (
      select 1 from public.courses
      where courses.id = tasks.course_id
        and courses.user_id = auth.uid()
    )
  )
  and (
    integration_id is null
    or exists (
      select 1 from public.integrations
      where integrations.id = tasks.integration_id
        and integrations.user_id = auth.uid()
    )
  )
);

drop policy if exists "calendar_events_crud_own" on public.calendar_events;
create policy "calendar_events_crud_own"
on public.calendar_events for all
using (auth.uid() = user_id)
with check (
  auth.uid() = user_id
  and (
    course_id is null
    or exists (
      select 1 from public.courses
      where courses.id = calendar_events.course_id
        and courses.user_id = auth.uid()
    )
  )
  and (
    integration_id is null
    or exists (
      select 1 from public.integrations
      where integrations.id = calendar_events.integration_id
        and integrations.user_id = auth.uid()
    )
  )
);

drop policy if exists "schedule_versions_crud_own" on public.schedule_versions;
create policy "schedule_versions_crud_own"
on public.schedule_versions for all
using (auth.uid() = user_id)
with check (auth.uid() = user_id);

drop policy if exists "schedule_blocks_crud_own" on public.schedule_blocks;
create policy "schedule_blocks_crud_own"
on public.schedule_blocks for all
using (auth.uid() = user_id)
with check (
  auth.uid() = user_id
  and exists (
    select 1 from public.tasks
    where tasks.id = schedule_blocks.task_id
      and tasks.user_id = auth.uid()
  )
  and (
    version_id is null
    or exists (
      select 1 from public.schedule_versions
      where schedule_versions.id = schedule_blocks.version_id
        and schedule_versions.user_id = auth.uid()
    )
  )
);

drop policy if exists "chat_threads_crud_own" on public.chat_threads;
create policy "chat_threads_crud_own"
on public.chat_threads for all
using (auth.uid() = user_id)
with check (auth.uid() = user_id);

drop policy if exists "chat_messages_crud_own" on public.chat_messages;
create policy "chat_messages_crud_own"
on public.chat_messages for all
using (auth.uid() = user_id)
with check (
  auth.uid() = user_id
  and exists (
    select 1 from public.chat_threads
    where chat_threads.id = chat_messages.thread_id
      and chat_threads.user_id = auth.uid()
  )
);

drop policy if exists "collab_sessions_select_member" on public.collab_sessions;
create policy "collab_sessions_select_member"
on public.collab_sessions for select
using (
  auth.uid() = owner_id
  or public.is_accepted_collab_member(id)
);

drop policy if exists "collab_sessions_insert_own" on public.collab_sessions;
create policy "collab_sessions_insert_own"
on public.collab_sessions for insert
with check (auth.uid() = owner_id);

drop policy if exists "collab_sessions_update_owner" on public.collab_sessions;
create policy "collab_sessions_update_owner"
on public.collab_sessions for update
using (auth.uid() = owner_id)
with check (auth.uid() = owner_id);

drop policy if exists "collab_sessions_delete_owner" on public.collab_sessions;
create policy "collab_sessions_delete_owner"
on public.collab_sessions for delete
using (auth.uid() = owner_id);

drop policy if exists "collab_members_select_involved" on public.collab_members;
create policy "collab_members_select_involved"
on public.collab_members for select
using (
  auth.uid() = user_id
  or public.is_collab_session_owner(session_id)
);

drop policy if exists "collab_members_insert_owner" on public.collab_members;
create policy "collab_members_insert_owner"
on public.collab_members for insert
with check (public.is_collab_session_owner(session_id));

drop policy if exists "collab_members_update_involved" on public.collab_members;
create policy "collab_members_update_involved"
on public.collab_members for update
using (
  auth.uid() = user_id
  or public.is_collab_session_owner(session_id)
)
with check (
  auth.uid() = user_id
  or public.is_collab_session_owner(session_id)
);

drop policy if exists "collab_members_delete_owner" on public.collab_members;
create policy "collab_members_delete_owner"
on public.collab_members for delete
using (public.is_collab_session_owner(session_id));

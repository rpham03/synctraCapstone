-- Add iCal feed support: new enum value + user-subscribed feed URLs table.
-- Apply with: supabase db push

-- Extend event_source enum to include iCal-imported events
alter type public.event_source add value if not exists 'ical';

-- Stores the feed URLs a user has subscribed to
create table if not exists public.ical_feeds (
  id            uuid        primary key default gen_random_uuid(),
  user_id       uuid        not null references public.profiles(id) on delete cascade,
  name          text        not null,
  url           text        not null,
  last_synced_at timestamptz,
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now()
);

create trigger set_ical_feeds_updated_at
  before update on public.ical_feeds
  for each row execute function public.set_updated_at();

alter table public.ical_feeds enable row level security;

create policy ical_feeds_crud_own on public.ical_feeds
  for all
  using  (auth.uid() = user_id)
  with check (auth.uid() = user_id);

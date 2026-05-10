-- 001_initial_schema.sql
-- Run this first in Supabase SQL Editor.

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

CREATE TABLE public.profiles (
    id                      UUID        PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
    full_name               TEXT,
    email                   TEXT,
    avatar_url              TEXT,
    canvas_domain           TEXT,
    canvas_token_encrypted  TEXT,
    canvas_token_iv         TEXT,
    study_start_hour        INT         DEFAULT 9,
    study_end_hour          INT         DEFAULT 22,
    min_block_minutes       INT         DEFAULT 30,
    default_break_minutes   INT         DEFAULT 10,
    created_at              TIMESTAMPTZ DEFAULT NOW(),
    updated_at              TIMESTAMPTZ DEFAULT NOW()
);

CREATE OR REPLACE FUNCTION public.handle_new_user()
RETURNS TRIGGER AS $$
BEGIN
    INSERT INTO public.profiles (id, full_name, email)
    VALUES (NEW.id, NEW.raw_user_meta_data->>'full_name', NEW.email);
    RETURN NEW;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

CREATE OR REPLACE TRIGGER on_auth_user_created
    AFTER INSERT ON auth.users
    FOR EACH ROW EXECUTE FUNCTION public.handle_new_user();

CREATE TABLE public.events (
    id              UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id         UUID        NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    title           TEXT        NOT NULL,
    description     TEXT,
    location        TEXT,
    start_time      TIMESTAMPTZ NOT NULL,
    end_time        TIMESTAMPTZ NOT NULL,
    source          TEXT        NOT NULL CHECK (source IN ('canvas', 'google_calendar', 'manual', 'ical', 'course')),
    source_event_id TEXT,
    course_import_id UUID,
    is_fixed        BOOLEAN     DEFAULT TRUE,
    color           TEXT,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (user_id, source, source_event_id)
);

CREATE INDEX idx_events_user_time ON public.events (user_id, start_time);

CREATE TABLE public.tasks (
    id                  UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id             UUID        NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    title               TEXT        NOT NULL,
    description         TEXT,
    due_date            TIMESTAMPTZ NOT NULL,
    estimated_minutes   INT         DEFAULT 60,
    actual_minutes      INT,
    course_id           TEXT,
    course_name         TEXT,
    task_type           TEXT        CHECK (task_type IN ('homework', 'reading', 'project', 'exam_prep', 'quiz', 'lab', 'other')),
    source              TEXT        NOT NULL CHECK (source IN ('canvas', 'manual')),
    source_task_id      TEXT,
    is_completed        BOOLEAN     DEFAULT FALSE,
    priority            INT         DEFAULT 3 CHECK (priority BETWEEN 1 AND 5),
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (user_id, source, source_task_id)
);

CREATE INDEX idx_tasks_user_due       ON public.tasks (user_id, due_date);
CREATE INDEX idx_tasks_user_completed ON public.tasks (user_id, is_completed);

CREATE TABLE public.schedule_blocks (
    id              UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id         UUID        NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    task_id         UUID        REFERENCES public.tasks(id) ON DELETE SET NULL,
    task_title      TEXT        NOT NULL,
    start_time      TIMESTAMPTZ NOT NULL,
    end_time        TIMESTAMPTZ NOT NULL,
    is_ai_generated BOOLEAN     DEFAULT TRUE,
    is_completed    BOOLEAN     DEFAULT FALSE,
    is_active       BOOLEAN     DEFAULT TRUE,
    version         INT         DEFAULT 1 CHECK (version BETWEEN 1 AND 3),
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_blocks_user_time   ON public.schedule_blocks (user_id, start_time);
CREATE INDEX idx_blocks_user_active ON public.schedule_blocks (user_id, is_active);

CREATE TABLE public.chat_messages (
    id          UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id     UUID        NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    content     TEXT        NOT NULL,
    role        TEXT        NOT NULL CHECK (role IN ('user', 'assistant')),
    intent      TEXT,
    confidence  FLOAT,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_chat_user_time ON public.chat_messages (user_id, created_at DESC);

CREATE TABLE public.collab_groups (
    id          UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    name        TEXT        NOT NULL,
    description TEXT,
    created_by  UUID        NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE public.collab_members (
    id          UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    group_id    UUID        NOT NULL REFERENCES public.collab_groups(id) ON DELETE CASCADE,
    user_id     UUID        NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    role        TEXT        DEFAULT 'member' CHECK (role IN ('owner', 'member')),
    joined_at   TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (group_id, user_id)
);

CREATE INDEX idx_collab_members_user ON public.collab_members (user_id);

CREATE OR REPLACE FUNCTION public.update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER set_updated_at_profiles BEFORE UPDATE ON public.profiles
    FOR EACH ROW EXECUTE FUNCTION public.update_updated_at();
CREATE TRIGGER set_updated_at_events BEFORE UPDATE ON public.events
    FOR EACH ROW EXECUTE FUNCTION public.update_updated_at();
CREATE TRIGGER set_updated_at_tasks BEFORE UPDATE ON public.tasks
    FOR EACH ROW EXECUTE FUNCTION public.update_updated_at();
CREATE TRIGGER set_updated_at_blocks BEFORE UPDATE ON public.schedule_blocks
    FOR EACH ROW EXECUTE FUNCTION public.update_updated_at();

-- 001_initial_schema.sql
-- Full Synctra database schema — run this first in Supabase SQL editor.
-- Tables: profiles, events, tasks, schedule_blocks, chat_messages,
--         collab_groups, collab_members

-- ─────────────────────────────────────────────────────────────────────────────
-- EXTENSIONS
-- ─────────────────────────────────────────────────────────────────────────────

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";


-- ─────────────────────────────────────────────────────────────────────────────
-- PROFILES
-- Extends Supabase auth.users with app-specific user data.
-- Auto-created when a new user signs up via the trigger below.
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE public.profiles (
    id                      UUID        PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
    full_name               TEXT,
    email                   TEXT,
    avatar_url              TEXT,

    -- Canvas integration
    canvas_domain           TEXT,                        -- e.g. canvas.uw.edu
    canvas_token_encrypted  TEXT,                        -- AES-256 encrypted token
    canvas_token_iv         TEXT,                        -- IV for decryption

    -- Scheduling preferences
    study_start_hour        INT         DEFAULT 9,       -- preferred start (24hr)
    study_end_hour          INT         DEFAULT 22,      -- preferred end (24hr)
    min_block_minutes       INT         DEFAULT 30,      -- shortest block to create
    default_break_minutes   INT         DEFAULT 10,      -- break between blocks

    created_at              TIMESTAMPTZ DEFAULT NOW(),
    updated_at              TIMESTAMPTZ DEFAULT NOW()
);

-- Auto-create profile when user signs up
CREATE OR REPLACE FUNCTION public.handle_new_user()
RETURNS TRIGGER AS $$
BEGIN
    INSERT INTO public.profiles (id, full_name, email)
    VALUES (
        NEW.id,
        NEW.raw_user_meta_data->>'full_name',
        NEW.email
    );
    RETURN NEW;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

CREATE OR REPLACE TRIGGER on_auth_user_created
    AFTER INSERT ON auth.users
    FOR EACH ROW EXECUTE FUNCTION public.handle_new_user();


-- ─────────────────────────────────────────────────────────────────────────────
-- EVENTS
-- Fixed calendar events that cannot be moved (classes, exams, meetings).
-- Sourced from Canvas or Google Calendar.
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE public.events (
    id              UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id         UUID        NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,

    title           TEXT        NOT NULL,
    description     TEXT,
    location        TEXT,
    start_time      TIMESTAMPTZ NOT NULL,
    end_time        TIMESTAMPTZ NOT NULL,

    -- Where this event came from
    source          TEXT        NOT NULL CHECK (source IN ('canvas', 'google_calendar', 'manual')),
    source_event_id TEXT,                               -- external ID for deduplication

    is_fixed        BOOLEAN     DEFAULT TRUE,           -- fixed = cannot be rescheduled
    color           TEXT,                               -- optional hex color override

    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW(),

    -- Prevent duplicate imports from same source
    UNIQUE (user_id, source, source_event_id)
);

CREATE INDEX idx_events_user_time ON public.events (user_id, start_time);


-- ─────────────────────────────────────────────────────────────────────────────
-- TASKS
-- Flexible tasks that can be scheduled around fixed events.
-- Sourced from Canvas assignments or added manually.
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE public.tasks (
    id                  UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id             UUID        NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,

    title               TEXT        NOT NULL,
    description         TEXT,

    due_date            TIMESTAMPTZ NOT NULL,
    estimated_minutes   INT         DEFAULT 60,          -- XGBoost prediction stored here
    actual_minutes      INT,                             -- filled when user marks done

    -- Canvas metadata
    course_id           TEXT,                            -- Canvas course ID
    course_name         TEXT,
    task_type           TEXT        CHECK (task_type IN (
                            'homework', 'reading', 'project',
                            'exam_prep', 'quiz', 'lab', 'other'
                        )),

    source              TEXT        NOT NULL CHECK (source IN ('canvas', 'manual')),
    source_task_id      TEXT,                            -- Canvas assignment ID

    is_completed        BOOLEAN     DEFAULT FALSE,
    priority            INT         DEFAULT 3 CHECK (priority BETWEEN 1 AND 5),

    created_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW(),

    UNIQUE (user_id, source, source_task_id)
);

CREATE INDEX idx_tasks_user_due ON public.tasks (user_id, due_date);
CREATE INDEX idx_tasks_user_completed ON public.tasks (user_id, is_completed);


-- ─────────────────────────────────────────────────────────────────────────────
-- SCHEDULE BLOCKS
-- AI-generated study/work blocks placed around fixed events.
-- Multiple versions (1, 2, 3) can exist — only the active version shows.
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE public.schedule_blocks (
    id              UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id         UUID        NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,

    -- Link to the task this block is for (nullable for general blocks)
    task_id         UUID        REFERENCES public.tasks(id) ON DELETE SET NULL,
    task_title      TEXT        NOT NULL,               -- denormalized for fast display

    start_time      TIMESTAMPTZ NOT NULL,
    end_time        TIMESTAMPTZ NOT NULL,

    is_ai_generated BOOLEAN     DEFAULT TRUE,
    is_completed    BOOLEAN     DEFAULT FALSE,
    is_active       BOOLEAN     DEFAULT TRUE,           -- false = belongs to unused version

    -- Which AI schedule version this block belongs to (1, 2, or 3)
    version         INT         DEFAULT 1 CHECK (version BETWEEN 1 AND 3),

    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_blocks_user_time    ON public.schedule_blocks (user_id, start_time);
CREATE INDEX idx_blocks_user_active  ON public.schedule_blocks (user_id, is_active);


-- ─────────────────────────────────────────────────────────────────────────────
-- CHAT MESSAGES
-- Conversation history between user and the AI scheduling assistant.
-- Auto-deleted after 90 days to protect privacy.
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE public.chat_messages (
    id          UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id     UUID        NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,

    content     TEXT        NOT NULL,
    role        TEXT        NOT NULL CHECK (role IN ('user', 'assistant')),

    -- Which intent DistilBERT classified (stored for model improvement)
    intent      TEXT,
    -- Confidence score from the classifier (0.0 - 1.0)
    confidence  FLOAT,

    created_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_chat_user_time ON public.chat_messages (user_id, created_at DESC);


-- ─────────────────────────────────────────────────────────────────────────────
-- COLLAB GROUPS
-- Groups for collaborative scheduling (study groups, team meetings).
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE public.collab_groups (
    id          UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    name        TEXT        NOT NULL,
    description TEXT,
    created_by  UUID        NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);


-- ─────────────────────────────────────────────────────────────────────────────
-- COLLAB MEMBERS
-- Membership table linking users to collab groups.
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE public.collab_members (
    id          UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    group_id    UUID        NOT NULL REFERENCES public.collab_groups(id) ON DELETE CASCADE,
    user_id     UUID        NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    role        TEXT        DEFAULT 'member' CHECK (role IN ('owner', 'member')),
    joined_at   TIMESTAMPTZ DEFAULT NOW(),

    UNIQUE (group_id, user_id)
);

CREATE INDEX idx_collab_members_user ON public.collab_members (user_id);


-- ─────────────────────────────────────────────────────────────────────────────
-- AUTO-UPDATE updated_at TIMESTAMPS
-- ─────────────────────────────────────────────────────────────────────────────

CREATE OR REPLACE FUNCTION public.update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER set_updated_at_profiles
    BEFORE UPDATE ON public.profiles
    FOR EACH ROW EXECUTE FUNCTION public.update_updated_at();

CREATE TRIGGER set_updated_at_events
    BEFORE UPDATE ON public.events
    FOR EACH ROW EXECUTE FUNCTION public.update_updated_at();

CREATE TRIGGER set_updated_at_tasks
    BEFORE UPDATE ON public.tasks
    FOR EACH ROW EXECUTE FUNCTION public.update_updated_at();

CREATE TRIGGER set_updated_at_blocks
    BEFORE UPDATE ON public.schedule_blocks
    FOR EACH ROW EXECUTE FUNCTION public.update_updated_at();

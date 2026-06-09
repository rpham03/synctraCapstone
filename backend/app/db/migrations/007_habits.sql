-- 007_habits.sql — Reclaim-style habit definitions and scheduled instances.

CREATE TABLE IF NOT EXISTS public.habits (
    id                  UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id             UUID        NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    title               TEXT        NOT NULL,
    duration_minutes    INT         NOT NULL CHECK (duration_minutes BETWEEN 5 AND 480),
    frequency_per_week  INT         NOT NULL CHECK (frequency_per_week BETWEEN 1 AND 14),
    preferred_days      INT[]       NOT NULL DEFAULT '{}',
    preferred_time_ranges JSONB     NOT NULL DEFAULT '{}',
    priority            INT         NOT NULL DEFAULT 5 CHECK (priority BETWEEN 1 AND 10),
    is_active           BOOLEAN     NOT NULL DEFAULT TRUE,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_habits_user_active
    ON public.habits (user_id, is_active);

CREATE TABLE IF NOT EXISTS public.habit_sessions (
    id              UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id         UUID        NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    habit_id        UUID        NOT NULL REFERENCES public.habits(id) ON DELETE CASCADE,
    start_time      TIMESTAMPTZ NOT NULL,
    end_time        TIMESTAMPTZ NOT NULL,
    explanation     TEXT,
    score           NUMERIC(8,2),
    week_start      DATE        NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT habit_sessions_time_order CHECK (end_time > start_time)
);

CREATE INDEX IF NOT EXISTS idx_habit_sessions_user_week
    ON public.habit_sessions (user_id, week_start, start_time);

ALTER TABLE public.habits ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.habit_sessions ENABLE ROW LEVEL SECURITY;

CREATE POLICY habits_select_own ON public.habits
    FOR SELECT USING (auth.uid() = user_id);
CREATE POLICY habits_insert_own ON public.habits
    FOR INSERT WITH CHECK (auth.uid() = user_id);
CREATE POLICY habits_update_own ON public.habits
    FOR UPDATE USING (auth.uid() = user_id);
CREATE POLICY habits_delete_own ON public.habits
    FOR DELETE USING (auth.uid() = user_id);

CREATE POLICY habit_sessions_select_own ON public.habit_sessions
    FOR SELECT USING (auth.uid() = user_id);
CREATE POLICY habit_sessions_insert_own ON public.habit_sessions
    FOR INSERT WITH CHECK (auth.uid() = user_id);
CREATE POLICY habit_sessions_update_own ON public.habit_sessions
    FOR UPDATE USING (auth.uid() = user_id);
CREATE POLICY habit_sessions_delete_own ON public.habit_sessions
    FOR DELETE USING (auth.uid() = user_id);

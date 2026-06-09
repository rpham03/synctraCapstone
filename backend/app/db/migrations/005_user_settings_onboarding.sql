-- 005_user_settings_onboarding.sql
-- Run AFTER 004_course_imports.sql

CREATE TABLE public.user_settings (
    id                          UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id                     UUID        NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE UNIQUE,
    schedule_type               TEXT        NOT NULL DEFAULT 'flexible'
                                CHECK (schedule_type IN ('early_bird', 'night_owl', 'flexible')),
    work_start_time             TIME        NOT NULL DEFAULT '09:00',
    work_end_time               TIME        NOT NULL DEFAULT '22:00',
    preferred_session_minutes   INT         NOT NULL DEFAULT 60,
    break_minutes               INT         NOT NULL DEFAULT 10,
    ical_links                  TEXT[]      NOT NULL DEFAULT '{}',
    course_urls                 TEXT[]      NOT NULL DEFAULT '{}',
    onboarding_complete         BOOLEAN     NOT NULL DEFAULT FALSE,
    created_at                  TIMESTAMPTZ DEFAULT NOW(),
    updated_at                  TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE public.ical_feeds (
    id              UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id         UUID        NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    url             TEXT        NOT NULL,
    label           TEXT,
    last_synced_at  TIMESTAMPTZ,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (user_id, url)
);

CREATE INDEX idx_user_settings_user ON public.user_settings (user_id);
CREATE INDEX idx_ical_feeds_user ON public.ical_feeds (user_id);

ALTER TABLE public.user_settings ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.ical_feeds ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users manage own settings"
    ON public.user_settings FOR ALL
    USING  (auth.uid() = user_id)
    WITH CHECK (auth.uid() = user_id);

CREATE POLICY "Users manage own ical feeds"
    ON public.ical_feeds FOR ALL
    USING  (auth.uid() = user_id)
    WITH CHECK (auth.uid() = user_id);

CREATE TRIGGER set_updated_at_user_settings
    BEFORE UPDATE ON public.user_settings
    FOR EACH ROW EXECUTE FUNCTION public.update_updated_at();

ALTER TABLE public.course_imports
    ADD COLUMN IF NOT EXISTS source_url TEXT;

UPDATE public.course_imports
SET source_url = course_url
WHERE source_url IS NULL;

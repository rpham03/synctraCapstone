-- 004_course_imports.sql
-- Run this AFTER 002_rls_policies.sql

CREATE TABLE public.course_imports (
    id              UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id         UUID        NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    course_url      TEXT        NOT NULL,
    course_name     TEXT        NOT NULL DEFAULT '',
    best_source     TEXT,
    event_count     INT         DEFAULT 0,
    last_synced_at  TIMESTAMPTZ DEFAULT NOW(),
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (user_id, course_url)
);

CREATE INDEX idx_course_imports_user ON public.course_imports (user_id);

ALTER TABLE public.course_imports ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users manage own course imports"
    ON public.course_imports FOR ALL
    USING  (auth.uid() = user_id)
    WITH CHECK (auth.uid() = user_id);

ALTER TABLE public.events
    ADD CONSTRAINT fk_events_course_import
    FOREIGN KEY (course_import_id) REFERENCES public.course_imports(id) ON DELETE CASCADE;

CREATE INDEX idx_events_course_import ON public.events (course_import_id);

-- 006_collaborative_scheduling.sql
-- Scheduling polls, privacy-safe availability, voting, and confirmed group events.

ALTER TABLE public.events DROP CONSTRAINT IF EXISTS events_source_check;
ALTER TABLE public.events ADD CONSTRAINT events_source_check
    CHECK (source IN (
        'canvas', 'google_calendar', 'manual', 'ical', 'course', 'collab'
    ));

CREATE TABLE public.collab_scheduling_requests (
    id                UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    group_id          UUID        REFERENCES public.collab_groups(id) ON DELETE SET NULL,
    organizer_id      UUID        NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    title             TEXT        NOT NULL,
    description       TEXT,
    location          TEXT,
    duration_minutes  INT         NOT NULL CHECK (duration_minutes BETWEEN 15 AND 480),
    window_start      TIMESTAMPTZ NOT NULL,
    window_end        TIMESTAMPTZ NOT NULL,
    status            TEXT        NOT NULL DEFAULT 'open'
                      CHECK (status IN ('open', 'confirmed', 'cancelled')),
    confirmed_option_id UUID,
    created_at        TIMESTAMPTZ DEFAULT NOW(),
    updated_at        TIMESTAMPTZ DEFAULT NOW(),
    CHECK (window_end > window_start)
);

CREATE TABLE public.collab_scheduling_participants (
    id                  UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    request_id          UUID        NOT NULL REFERENCES public.collab_scheduling_requests(id) ON DELETE CASCADE,
    user_id             UUID        REFERENCES auth.users(id) ON DELETE CASCADE,
    email               TEXT,
    display_name        TEXT,
    timezone_offset_minutes INT     DEFAULT 0 CHECK (timezone_offset_minutes BETWEEN -840 AND 840),
    preferred_periods   TEXT[]      DEFAULT '{}',
    response_status     TEXT        NOT NULL DEFAULT 'invited'
                        CHECK (response_status IN ('invited', 'accepted', 'responded', 'declined')),
    joined_at           TIMESTAMPTZ,
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    CHECK (user_id IS NOT NULL OR email IS NOT NULL)
);

CREATE TABLE public.collab_schedule_options (
    id                UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    request_id        UUID        NOT NULL REFERENCES public.collab_scheduling_requests(id) ON DELETE CASCADE,
    start_time        TIMESTAMPTZ NOT NULL,
    end_time          TIMESTAMPTZ NOT NULL,
    rank_score        INT         DEFAULT 0,
    preferred_matches INT         DEFAULT 0,
    created_at        TIMESTAMPTZ DEFAULT NOW(),
    CHECK (end_time > start_time)
);

ALTER TABLE public.collab_scheduling_requests
    ADD CONSTRAINT collab_confirmed_option_fk
    FOREIGN KEY (confirmed_option_id) REFERENCES public.collab_schedule_options(id) ON DELETE SET NULL;

CREATE TABLE public.collab_schedule_votes (
    id              UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    request_id      UUID        NOT NULL REFERENCES public.collab_scheduling_requests(id) ON DELETE CASCADE,
    option_id       UUID        NOT NULL REFERENCES public.collab_schedule_options(id) ON DELETE CASCADE,
    participant_id  UUID        NOT NULL REFERENCES public.collab_scheduling_participants(id) ON DELETE CASCADE,
    response        TEXT        NOT NULL CHECK (response IN ('available', 'preferred', 'unavailable')),
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (option_id, participant_id)
);

CREATE TABLE public.collab_activity_log (
    id          UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    request_id  UUID        NOT NULL REFERENCES public.collab_scheduling_requests(id) ON DELETE CASCADE,
    actor_id    UUID        REFERENCES auth.users(id) ON DELETE SET NULL,
    action      TEXT        NOT NULL,
    metadata    JSONB       DEFAULT '{}'::jsonb,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_collab_requests_organizer
    ON public.collab_scheduling_requests (organizer_id, created_at DESC);
CREATE INDEX idx_collab_participants_user
    ON public.collab_scheduling_participants (user_id, request_id);
CREATE INDEX idx_collab_options_request
    ON public.collab_schedule_options (request_id, start_time);
CREATE INDEX idx_collab_votes_request
    ON public.collab_schedule_votes (request_id, option_id);

CREATE TRIGGER set_updated_at_collab_requests
    BEFORE UPDATE ON public.collab_scheduling_requests
    FOR EACH ROW EXECUTE FUNCTION public.update_updated_at();
CREATE TRIGGER set_updated_at_collab_votes
    BEFORE UPDATE ON public.collab_schedule_votes
    FOR EACH ROW EXECUTE FUNCTION public.update_updated_at();

ALTER TABLE public.collab_scheduling_requests ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.collab_scheduling_participants ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.collab_schedule_options ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.collab_schedule_votes ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.collab_activity_log ENABLE ROW LEVEL SECURITY;

CREATE OR REPLACE FUNCTION public.is_collab_request_participant(request_uuid UUID)
RETURNS BOOLEAN AS $$
BEGIN
    RETURN EXISTS (
        SELECT 1
        FROM public.collab_scheduling_requests request
        LEFT JOIN public.collab_scheduling_participants participant
            ON participant.request_id = request.id
        WHERE request.id = request_uuid
          AND (
              request.organizer_id = auth.uid()
              OR participant.user_id = auth.uid()
          )
    );
END;
$$ LANGUAGE plpgsql SECURITY DEFINER SET search_path = public;

CREATE POLICY "Participants can view scheduling requests"
    ON public.collab_scheduling_requests FOR SELECT
    USING (public.is_collab_request_participant(id));
CREATE POLICY "Organizers can create scheduling requests"
    ON public.collab_scheduling_requests FOR INSERT
    WITH CHECK (organizer_id = auth.uid());
CREATE POLICY "Organizers can update scheduling requests"
    ON public.collab_scheduling_requests FOR UPDATE
    USING (organizer_id = auth.uid());

CREATE POLICY "Participants can view poll participants"
    ON public.collab_scheduling_participants FOR SELECT
    USING (public.is_collab_request_participant(request_id));
CREATE POLICY "Organizers can add poll participants"
    ON public.collab_scheduling_participants FOR INSERT
    WITH CHECK (
        EXISTS (
            SELECT 1 FROM public.collab_scheduling_requests request
            WHERE request.id = request_id AND request.organizer_id = auth.uid()
        )
    );
CREATE POLICY "Users can update own poll participant"
    ON public.collab_scheduling_participants FOR UPDATE
    USING (user_id = auth.uid());

CREATE POLICY "Participants can view schedule options"
    ON public.collab_schedule_options FOR SELECT
    USING (public.is_collab_request_participant(request_id));
CREATE POLICY "Organizers can create schedule options"
    ON public.collab_schedule_options FOR INSERT
    WITH CHECK (
        EXISTS (
            SELECT 1 FROM public.collab_scheduling_requests request
            WHERE request.id = request_id AND request.organizer_id = auth.uid()
        )
    );

CREATE POLICY "Participants can view votes"
    ON public.collab_schedule_votes FOR SELECT
    USING (public.is_collab_request_participant(request_id));
CREATE POLICY "Participants can cast own votes"
    ON public.collab_schedule_votes FOR INSERT
    WITH CHECK (
        EXISTS (
            SELECT 1 FROM public.collab_scheduling_participants participant
            WHERE participant.id = participant_id
              AND participant.request_id = request_id
              AND participant.user_id = auth.uid()
        )
    );
CREATE POLICY "Participants can update own votes"
    ON public.collab_schedule_votes FOR UPDATE
    USING (
        EXISTS (
            SELECT 1 FROM public.collab_scheduling_participants participant
            WHERE participant.id = participant_id
              AND participant.user_id = auth.uid()
        )
    );

CREATE POLICY "Participants can view collaboration activity"
    ON public.collab_activity_log FOR SELECT
    USING (public.is_collab_request_participant(request_id));

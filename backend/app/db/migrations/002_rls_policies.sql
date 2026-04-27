-- 002_rls_policies.sql
-- Row Level Security — every user can only access their own data.
-- Run this AFTER 001_initial_schema.sql

-- ─────────────────────────────────────────────────────────────────────────────
-- ENABLE RLS ON ALL TABLES
-- ─────────────────────────────────────────────────────────────────────────────

ALTER TABLE public.profiles        ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.events          ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.tasks           ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.schedule_blocks ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.chat_messages   ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.collab_groups   ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.collab_members  ENABLE ROW LEVEL SECURITY;


-- ─────────────────────────────────────────────────────────────────────────────
-- PROFILES
-- ─────────────────────────────────────────────────────────────────────────────

CREATE POLICY "Users can view own profile"
    ON public.profiles FOR SELECT
    USING (auth.uid() = id);

CREATE POLICY "Users can update own profile"
    ON public.profiles FOR UPDATE
    USING (auth.uid() = id);


-- ─────────────────────────────────────────────────────────────────────────────
-- EVENTS
-- ─────────────────────────────────────────────────────────────────────────────

CREATE POLICY "Users can view own events"
    ON public.events FOR SELECT
    USING (auth.uid() = user_id);

CREATE POLICY "Users can insert own events"
    ON public.events FOR INSERT
    WITH CHECK (auth.uid() = user_id);

CREATE POLICY "Users can update own events"
    ON public.events FOR UPDATE
    USING (auth.uid() = user_id);

CREATE POLICY "Users can delete own events"
    ON public.events FOR DELETE
    USING (auth.uid() = user_id);


-- ─────────────────────────────────────────────────────────────────────────────
-- TASKS
-- ─────────────────────────────────────────────────────────────────────────────

CREATE POLICY "Users can view own tasks"
    ON public.tasks FOR SELECT
    USING (auth.uid() = user_id);

CREATE POLICY "Users can insert own tasks"
    ON public.tasks FOR INSERT
    WITH CHECK (auth.uid() = user_id);

CREATE POLICY "Users can update own tasks"
    ON public.tasks FOR UPDATE
    USING (auth.uid() = user_id);

CREATE POLICY "Users can delete own tasks"
    ON public.tasks FOR DELETE
    USING (auth.uid() = user_id);


-- ─────────────────────────────────────────────────────────────────────────────
-- SCHEDULE BLOCKS
-- ─────────────────────────────────────────────────────────────────────────────

CREATE POLICY "Users can view own blocks"
    ON public.schedule_blocks FOR SELECT
    USING (auth.uid() = user_id);

CREATE POLICY "Users can insert own blocks"
    ON public.schedule_blocks FOR INSERT
    WITH CHECK (auth.uid() = user_id);

CREATE POLICY "Users can update own blocks"
    ON public.schedule_blocks FOR UPDATE
    USING (auth.uid() = user_id);

CREATE POLICY "Users can delete own blocks"
    ON public.schedule_blocks FOR DELETE
    USING (auth.uid() = user_id);


-- ─────────────────────────────────────────────────────────────────────────────
-- CHAT MESSAGES
-- ─────────────────────────────────────────────────────────────────────────────

CREATE POLICY "Users can view own messages"
    ON public.chat_messages FOR SELECT
    USING (auth.uid() = user_id);

CREATE POLICY "Users can insert own messages"
    ON public.chat_messages FOR INSERT
    WITH CHECK (auth.uid() = user_id);

-- Users cannot edit or delete chat history (integrity)


-- ─────────────────────────────────────────────────────────────────────────────
-- COLLAB GROUPS
-- Group is visible to all members, editable only by owner.
-- ─────────────────────────────────────────────────────────────────────────────

CREATE POLICY "Group members can view group"
    ON public.collab_groups FOR SELECT
    USING (
        auth.uid() = created_by
        OR
        EXISTS (
            SELECT 1 FROM public.collab_members
            WHERE group_id = collab_groups.id
            AND   user_id  = auth.uid()
        )
    );

CREATE POLICY "Users can create groups"
    ON public.collab_groups FOR INSERT
    WITH CHECK (auth.uid() = created_by);

CREATE POLICY "Only owner can update group"
    ON public.collab_groups FOR UPDATE
    USING (auth.uid() = created_by);

CREATE POLICY "Only owner can delete group"
    ON public.collab_groups FOR DELETE
    USING (auth.uid() = created_by);


-- ─────────────────────────────────────────────────────────────────────────────
-- COLLAB MEMBERS
-- Members can see others in the same group (for free/busy lookup).
-- Free/busy only — event details are never exposed to other users.
-- ─────────────────────────────────────────────────────────────────────────────

CREATE POLICY "Members can view group membership"
    ON public.collab_members FOR SELECT
    USING (
        EXISTS (
            SELECT 1 FROM public.collab_members AS cm
            WHERE cm.group_id = collab_members.group_id
            AND   cm.user_id  = auth.uid()
        )
    );

CREATE POLICY "Group owner can add members"
    ON public.collab_members FOR INSERT
    WITH CHECK (
        EXISTS (
            SELECT 1 FROM public.collab_groups
            WHERE id         = group_id
            AND   created_by = auth.uid()
        )
    );

CREATE POLICY "Members can leave group"
    ON public.collab_members FOR DELETE
    USING (auth.uid() = user_id);

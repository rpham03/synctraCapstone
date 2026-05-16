-- 005_add_event_type.sql
-- Add event_type column to events table for course imports

ALTER TABLE public.events
ADD COLUMN IF NOT EXISTS event_type TEXT CHECK (event_type IN ('lecture', 'lab', 'section', 'discussion', 'exam', 'office_hours'));

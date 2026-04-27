-- 003_seed_dev_data.sql
-- Sample data for development and demo — DO NOT run in production.
-- Replace 'YOUR_USER_ID' with your actual Supabase user ID after signing up.
-- Find it in Supabase → Authentication → Users → copy the UUID.

-- ─────────────────────────────────────────────────────────────────────────────
-- HOW TO USE
-- 1. Sign up in the app first to create your auth.users row
-- 2. Go to Supabase → Authentication → Users → copy your UUID
-- 3. Replace every occurrence of 'YOUR_USER_ID' below with that UUID
-- 4. Run in Supabase SQL editor
-- ─────────────────────────────────────────────────────────────────────────────

DO $$
DECLARE
    uid UUID := '0a8e1007-b928-40fd-b1cd-c1b50519a9be';   -- ← replace this
BEGIN

-- ── Fixed Events (classes, exams) ────────────────────────────────────────────

INSERT INTO public.events (user_id, title, start_time, end_time, source, is_fixed) VALUES
(uid, 'CSE 444 Lecture',   NOW() + INTERVAL '1 day 10 hours',  NOW() + INTERVAL '1 day 11 hours 20 min', 'canvas', TRUE),
(uid, 'Bio 220 Lecture',   NOW() + INTERVAL '1 day 13 hours',  NOW() + INTERVAL '1 day 14 hours',          'canvas', TRUE),
(uid, 'Math 308 Lecture',  NOW() + INTERVAL '2 days 9 hours',  NOW() + INTERVAL '2 days 10 hours 20 min',  'canvas', TRUE),
(uid, 'CSE 444 Lab',       NOW() + INTERVAL '3 days 14 hours', NOW() + INTERVAL '3 days 16 hours',          'canvas', TRUE),
(uid, 'Bio Midterm Exam',  NOW() + INTERVAL '5 days 9 hours',  NOW() + INTERVAL '5 days 11 hours',          'canvas', TRUE),
(uid, 'Team Standup',      NOW() + INTERVAL '1 day 15 hours',  NOW() + INTERVAL '1 day 15 hours 30 min',   'google_calendar', TRUE);

-- ── Tasks (homework, studying) ────────────────────────────────────────────────

INSERT INTO public.tasks
    (user_id, title, due_date, estimated_minutes, course_name, task_type, source) VALUES
(uid, 'CSE 444 HW 3 — Query Optimization',  NOW() + INTERVAL '3 days',  120, 'CSE 444', 'homework',  'canvas'),
(uid, 'Bio Reading — Chapter 12 & 13',       NOW() + INTERVAL '2 days',   60, 'Bio 220',  'reading',   'canvas'),
(uid, 'Math 308 Problem Set 5',              NOW() + INTERVAL '4 days',   90, 'Math 308', 'homework',  'canvas'),
(uid, 'Bio Exam Study Guide',                NOW() + INTERVAL '5 days',  150, 'Bio 220',  'exam_prep', 'canvas'),
(uid, 'CSE 444 Lab Report',                  NOW() + INTERVAL '6 days',  180, 'CSE 444',  'lab',       'canvas'),
(uid, 'Synctra Capstone Slides',             NOW() + INTERVAL '7 days',   90, 'CSE Capstone', 'project', 'manual');

END $$;

# Synctra Architecture

**One slide — copy everything below the line.**

---

## Synctra System Architecture

```
                         ┌─────────────────────────────────────┐
                         │     Flutter App (iOS · Android)      │
                         │  Planner │ Habits │ Tasks │ Chat │ Collab │
                         └──────────────────┬──────────────────┘
                                            │
              ┌─────────────────────────────┼─────────────────────────────┐
              │                             │                             │
              ▼                             ▼                             ▼
     ┌─────────────────┐         ┌─────────────────┐         ┌─────────────────┐
     │    Supabase     │         │  FastAPI Backend │         │   On-device     │
     │  Auth · Settings│         │    /api/v1       │         │     cache       │
     │  Tasks · Events │         │                  │         │                 │
     └─────────────────┘         └────────┬────────┘         └─────────────────┘
                                          │
                    ┌─────────────────────┼─────────────────────┐
                    │                     │                     │
                    ▼                     ▼                     ▼
            ┌──────────────┐    ┌──────────────┐    ┌──────────────┐
            │ Canvas LMS   │    │  iCal feeds  │    │Course import │
            │ assignments  │    │  calendars   │    │  (schedule)  │
            └──────────────┘    └──────────────┘    └──────────────┘
                                          │
                                          ▼
                              ┌───────────────────────┐
                              │  Scheduling engine    │
                              │  Chat · Habits · Tasks│
                              │  Collab polls         │
                              └───────────────────────┘
```

**Fixed** classes & calendars → **Flexible** tasks, habits & AI blocks → **One Planner**

Flutter · FastAPI · Supabase · NLP tool router · Canvas · iCal

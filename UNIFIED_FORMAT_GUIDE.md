# Unified Course Format Guide

This guide explains the new unified format workflow that eliminates duplicates and works with all course websites.

## Overview

**One unified workflow for all courses:**

```
Course Website (any format)
    ↓
Ollama AI Parser (intelligent parsing)
    ↓
UNIFIED FORMAT (standardized structure)
    ├─ UnifiedAssignment (all assignments)
    └─ UnifiedClassEvent (all class events)
    ↓
DEDUPLICATION (remove duplicates)
    ↓
Calendar Import (one function for all)
    ↓
Supabase (saved to database)
```

---

## Key Features

✅ **No Duplicates** — Automatic deduplication based on course + name + date  
✅ **One Format** — All assignments and events use same structure  
✅ **One Import** — Single calendar import function handles everything  
✅ **Any Website** — Works with any course website format  
✅ **AI-Powered** — Uses Ollama for intelligent parsing  

---

## Unified Data Models

### UnifiedAssignment (for HW, Projects, Exams, etc.)

```python
class UnifiedAssignment:
    assignment_name: str       # "HW1", "Midterm", "Project 2"
    assignment_type: str       # "homework", "project", "exam", "quiz", "lab"
    due_date: str              # "2026-04-10" (ISO format)
    due_time: str              # "23:59" (24h format), null if not specified
    points: int                # 10, null if not specified
    description: str           # Full description
    submission_method: str     # "Canvas", "email", "in-person"
    requirements: list[str]    # ["Requirement 1", "Requirement 2"]
    is_individual: bool        # Can submit individually?
    is_group: bool             # Can submit as group?
    late_policy: str           # "10% per day", null if none
    course_name: str           # "CSE 331"
    source_url: str            # Where parsed from
```

### UnifiedClassEvent (for Lectures, Labs, Sections, etc.)

```python
class UnifiedClassEvent:
    event_name: str            # "Lecture 5", "Lab A", "Discussion Section"
    event_type: str            # "lecture", "lab", "section", "discussion", "office_hours"
    date: str                  # "2026-04-10" (ISO format)
    start_time: str            # "10:30" (24h format)
    end_time: str              # "11:20" (24h format), null if not specified
    location: str              # "CSE2 B215", "Zoom", null if online
    description: str           # "Introduction to algorithms", etc.
    course_name: str           # "CSE 331"
    source_url: str            # Where parsed from
```

---

## Main Endpoint

**Endpoint:** `POST /api/v1/course-import/import-to-calendar`

This is the endpoint you should use. It does everything:

### Request

```bash
curl -X POST "http://localhost:8000/api/v1/course-import/import-to-calendar" \
  -G \
  --data-urlencode "course_url=https://courses.cs.washington.edu/courses/cse331" \
  --data-urlencode "user_id=user_12345" \
  --data-urlencode "ollama_model=mistral" \
  --data-urlencode "ollama_host=http://localhost:11434"
```

### Parameters

- `course_url` (required) — Course website URL
- `user_id` (required) — User ID for calendar (Supabase auth)
- `ollama_model` (optional) — Model to use (default: "mistral")
- `ollama_host` (optional) — Ollama server URL (default: "http://localhost:11434")

### Response

```json
{
  "course_url": "https://courses.cs.washington.edu/courses/cse331",
  "course_name": "CSE 331",
  "parsing_method": "hybrid",
  "confidence": 0.95,
  "calendar_import": {
    "assignments_imported": 5,
    "assignments_failed": 0,
    "class_events_imported": 20,
    "class_events_failed": 0,
    "summary": {
      "total_imported": 25,
      "total_failed": 0,
      "success_rate": 100.0
    },
    "details": [
      "✅ Assignment: HW1 (CSE 331)",
      "✅ Assignment: HW2 (CSE 331)",
      "✅ Event: Lecture 1 (CSE 331)",
      "✅ Event: Lecture 2 (CSE 331)",
      "..."
    ]
  },
  "summary": {
    "assignments_parsed": 5,
    "class_events_parsed": 20,
    "total_imported": 25,
    "total_failed": 0
  },
  "warnings": []
}
```

---

## How It Works (Step by Step)

### Step 1: Parse Course Website
```
Input: Course URL
↓
HTML scraping + Ollama AI parsing
↓
Output: Raw assignments and events
```

### Step 2: Convert to Unified Format
```
Raw data
↓
convert_to_unified_assignment() / convert_to_unified_class_event()
↓
UnifiedAssignment and UnifiedClassEvent objects
```

### Step 3: Deduplicate
```
Unified objects
↓
deduplicate_assignments() / deduplicate_class_events()
↓
Remove duplicates based on: course_name + name + date + time
```

### Step 4: Import to Calendar
```
Deduplicated unified objects
↓
import_to_calendar(user_id, assignments, class_events)
↓
Supabase: tasks + events tables
```

---

## Deduplication Logic

### For Assignments

Duplicates are identified by:
```python
key = (course_name, assignment_name, due_date)
```

**Example:**
```
HW1 from CSE 331 due 2026-04-10 (scraped)
HW1 from CSE 331 due 2026-04-10 (AI parsed) ← DUPLICATE, REMOVED
```

### For Class Events

Duplicates are identified by:
```python
key = (course_name, event_name, date, start_time)
```

**Example:**
```
Lecture 1 in CSE 331 on 2026-04-01 at 10:30 (scraped)
Lecture 1 in CSE 331 on 2026-04-01 at 10:30 (AI parsed) ← DUPLICATE, REMOVED
```

---

## Batch Import (Multiple Courses)

Import multiple courses at once:

```python
import httpx

async def import_multiple_courses(courses: list[tuple[str, str]]):
    """
    courses: list of (course_url, user_id) tuples
    """
    async with httpx.AsyncClient() as client:
        for course_url, user_id in courses:
            response = await client.post(
                "http://localhost:8000/api/v1/course-import/import-to-calendar",
                params={
                    "course_url": course_url,
                    "user_id": user_id,
                    "ollama_model": "mistral",
                    "ollama_host": "http://localhost:11434"
                }
            )
            result = response.json()
            print(f"{course_url}: {result['summary']['total_imported']} events imported")
```

---

## Example Response Breakdown

```json
{
  "course_url": "https://courses.cs.washington.edu/courses/cse331",
  "course_name": "CSE 331",
  
  "parsing_method": "hybrid",     ← 80% regex, 20% AI
  "confidence": 0.95,             ← High confidence in results
  
  "calendar_import": {
    "assignments_imported": 5,    ← 5 assignments added to calendar
    "assignments_failed": 0,      ← 0 assignments failed
    "class_events_imported": 20,  ← 20 lectures/labs added to calendar
    "class_events_failed": 0,     ← 0 events failed
    "success_rate": 100.0         ← All events imported successfully
  },
  
  "summary": {
    "assignments_parsed": 5,      ← Total unique assignments found
    "class_events_parsed": 20,    ← Total unique class events found
    "total_imported": 25,         ← All events successfully imported
    "total_failed": 0             ← No failures
  },
  
  "warnings": []                  ← Any parsing warnings
}
```

---

## No More Duplicates!

### Before (Old System)
```
Course Website
  ↓
Scraper only ("Course") + AI parser ("Lecture 20")
  ↓
BOTH added to calendar
  ↓
DUPLICATE EVENTS! ❌
```

### After (New Unified System)
```
Course Website
  ↓
Scraper + AI parser → Unified Format
  ↓
Deduplication (remove duplicates)
  ↓
One "Lecture 20" added to calendar ✅
```

---

## Integration Example

### Python Backend

```python
from httpx import AsyncClient

async def import_cse331(user_id: str):
    """Import CSE 331 course to user's calendar."""
    async with AsyncClient() as client:
        response = await client.post(
            "http://localhost:8000/api/v1/course-import/import-to-calendar",
            params={
                "course_url": "https://courses.cs.washington.edu/courses/cse331",
                "user_id": user_id,
            }
        )
        
        result = response.json()
        
        if result["calendar_import"]["total_failed"] == 0:
            print(f"✅ Imported {result['summary']['total_imported']} events")
        else:
            print(f"⚠️ {result['calendar_import']['total_failed']} events failed")
        
        return result
```

### JavaScript Frontend

```typescript
async function importCourse(courseUrl: string, userId: string) {
  const params = new URLSearchParams({
    course_url: courseUrl,
    user_id: userId,
  });
  
  const response = await fetch(
    `http://localhost:8000/api/v1/course-import/import-to-calendar?${params}`,
    { method: "POST" }
  );
  
  const result = await response.json();
  
  if (result.calendar_import.total_failed === 0) {
    console.log(`✅ Imported ${result.summary.total_imported} events`);
  } else {
    console.warn(`⚠️ ${result.calendar_import.total_failed} events failed`);
  }
  
  return result;
}
```

---

## Troubleshooting

### Duplicates Still Appearing?

1. Check if using old `/import` endpoint (don't use it!)
2. Make sure using `/import-to-calendar` (new unified endpoint)
3. Verify deduplication is working: check `summary.total_imported` vs raw count

### Events Not Importing?

1. Check `calendar_import.total_failed` count
2. Look at `details` array for error messages
3. Verify `user_id` is valid
4. Check Supabase tables have correct schema

### Missing Events?

1. Check parsing confidence
2. Look at `warnings` array
3. Try lowering `confidence_threshold` if some events were skipped
4. Check Ollama is running: `ollama serve`

---

## Files

- **Unified Format Module**: [unified_course_format.py](backend/app/api/v1/routes/unified_course_format.py)
- **Course Import Route**: [course_import.py](backend/app/api/v1/routes/course_import.py)
- **Ollama Parser**: [ollama_assignment_parser.py](backend/app/api/v1/routes/ollama_assignment_parser.py)
- **Hybrid Parser**: [hybrid_parser.py](backend/app/api/v1/routes/hybrid_parser.py)

---

## Summary

| Feature | Before | After |
|---------|--------|-------|
| **Duplicates** | ❌ Yes | ✅ No |
| **One Format** | ❌ Multiple | ✅ Unified |
| **One Import Function** | ❌ Different endpoints | ✅ One endpoint |
| **Works with Any Site** | ❌ Limited | ✅ All formats |
| **Automatic Dedup** | ❌ Manual | ✅ Automatic |

**Use endpoint:** `POST /api/v1/course-import/import-to-calendar`

That's it! 🚀


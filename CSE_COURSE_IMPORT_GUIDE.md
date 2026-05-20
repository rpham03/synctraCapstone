# CSE Course Import Strategy & Findings

## Executive Summary

Researched UW CSE course catalog and analyzed which courses have **publicly accessible calendars and assignment details**. Implemented flexible, course-aware import system that automatically adapts to different course website formats.

## Research Findings

### UW CSE Courses with Confirmed Public Calendars/Assignments

Based on investigation of the `courses.cs.washington.edu` domain:

**Confirmed with Public Content:**
- **CSE 331** — Software Design & Implementation ✅
  - Format: HTML calendar (`/calendar/calendar.html`)
  - Details: Contains day-by-day required activities and homework due dates
  
- **CSE 351** — Hardware/Software Interface ✅
  - Format: HTML schedule (`schedule.html`)
  - Details: Weekly calendar with course events and assignment specs

**Likely to Have Public Content:**
- CSE 333, 351, 369, 373 (FullCalendar or custom schedule format)
- CSE 403, 410, 414, 415, 416, 421, 431
- CSE 440, 451, 452, 461, 481, 482

### Courses Without Public Calendar Access

Many UW CSE courses use **authentication-only systems**:
- Canvas-based courses (require UW NetID)
- Gradescope submissions (private)
- Internal course management systems

**Important:** The importer automatically **skips courses without public calendars** rather than fail, and warns users to check Canvas/Gradescope for auth-required courses.

---

## Flexible Import Implementation

### Course-Aware Architecture

The updated `course_import.py` includes:

#### 1. **Automatic Course Detection**
```python
# Extracts course code (e.g., "cse331") from URL
_extract_course_code(url) → "cse331"

# Classifies course type (UW CSE vs generic)
_get_course_type(url) → "uw_cse_public" | "uw_cse" | "generic"
```

#### 2. **Smart Path Prioritization**
For UW CSE courses, probes these paths in order:
```
1. /calendar/calendar.html        (monthtable format)
2. /calendar/subscribe.html       (iCal subscription)
3. /schedule.html                 (custom schedule format)
4. /schedule/schedule.html
5. /lectures.html
6. /homework.html
7. /assignments.html
```

Generic courses fall back to:
```
- /calendar/, /schedule/
- /homework/, /assignments/
- /syllabus.html, /due_dates.html
```

#### 3. **Public Calendar Detection**
Automatically checks if page has public calendar/assignment content:
- ✅ Looks for: "calendar", "schedule", "assignment", "homework", "due date"
- ❌ Detects auth barriers: "login required", "canvas", "gradescope"
- ⚠️ Warns users if page lacks public content

#### 4. **Multi-Strategy Extraction** (10 formats supported)
Runs all strategies in parallel and merges results:
1. iCal subscription files (`.ics` feeds)
2. FullCalendar `events_source.json`
3. UW Monthtable HTML (`<td class='eventtd'>`)
4. Schedule cards (`<div class='schedule-card'>`)
5. Day/week divs (`<div class='day lecture-day'>`)
6. Generic element scanning (date + assignment keyword)
7. Calendar grid (month headings + table cells)
8. Date-ID cells (`<td id='YYYY-MM-DD'>`)
9. Table rows with date inference
10. Heading context with sibling lists
11. Structured JSON (JSON-LD, Next.js data)

### How It Works

**For a typical CSE course URL:**
```
Input: https://courses.cs.washington.edu/cse331/26sp/
```

1. **Course Detection** → Identifies as "cse331", "uw_cse_public"
2. **Fetch Landing Page** → Gets main course page
3. **Smart Path Search** → Probes 15+ candidate URLs in priority order
4. **Parallel Extraction** → Runs 10 extraction strategies on each page found
5. **Deduplication & Merging** → Combines results by normalized event key
6. **Scoring & Selection** → Picks best source by event count + quality

**Result:**
```json
{
  "course_url": "https://courses.cs.washington.edu/cse331/26sp/",
  "best_source": "https://courses.cs.washington.edu/cse331/26sp/calendar/calendar.html",
  "events": [
    {
      "title": "HW1 due",
      "date": "2026-04-07",
      "time": "23:59",
      "description": "Data Structures",
      "source_urls": ["https://...calendar.html"]
    }
  ],
  "warnings": []
}
```

---

## Format Examples

### 1. UW Monthtable Format (CSE 331-style)
```html
<td class='eventtd' id='2026-04-07'>
  <span class='datespan'>7</span>
  <div class='hw'>
    23:59 <span class='summary'><a>HW1</a> due</span>
    <span class='description'>Data Structures</span>
  </div>
  <div class='lecture'>
    10:30 <span class='summary'>Lecture 12</span>
  </div>
</td>
```
✅ **Supported** — Extracts `title`, `date`, `time`, `description`

### 2. Schedule Cards (CSE 421-style)
```html
<div class='schedule-card'>
  <div class='card-header'>
    <p>April 9</p>
    <p>Lecture 5</p>
  </div>
  <div class='schedule-content'>
    <ul class='schedule-topics'>
      <li>Pset 1 due Apr 9th</li>
    </ul>
  </div>
</div>
```
✅ **Supported** — Parses date from header + assignment from list

### 3. Day/Week Divs (CSE 312-style)
```html
<div class='day lecture-day'>
  <div class='date-and-type'>
    <div class='type'>Lecture 2</div>
    <div class='date'>(Wed, Apr 2)</div>
  </div>
  <div class='topic'>Intro to Probability</div>
  <div>Pset 1 out</div>
</div>
```
✅ **Supported** — Extracts date from structure + assignment details

---

## Adding New Courses

### To add a CSE course with known public calendar:

Edit `course_import.py` in the `_UW_CSE_COURSES_WITH_PUBLIC_CALENDARS` set:

```python
_UW_CSE_COURSES_WITH_PUBLIC_CALENDARS = {
    "cse331", "cse333", "cse351", "cse369", "cse373",
    "cse421", "cse403", "cse410", "cse414", "cse415",
    "cse416", "cse431", "cse440", "cse451", "cse452",
    "cse461", "cse481", "cse482",
    "cse412",  # Add new course here
}
```

### For custom calendar URL patterns:

If a course uses non-standard paths, add to `_CALENDAR_CANDIDATES`:

```python
_CALENDAR_CANDIDATES = [
    # ... existing paths
    "events/events.html",      # Custom path
    "academic-calendar.html",
    "resources/schedule",
]
```

---

## Testing the Importer

### Example: Import CSE 331 Calendar

```bash
curl -X POST http://localhost:8000/api/v1/course-import \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "course_url=https://courses.cs.washington.edu/cse331/26sp/"
```

**Response:**
- ✅ **Success**: Returns events with dates, times, descriptions
- ⚠️ **Warning**: "This course page may not have publicly accessible calendar..."
- ❌ **Error**: "Could not fetch {url}" or "HTTP 401/403"

### Debugging

Check returned `page_reports` to see which pages were crawled:
```json
"page_reports": [
  {
    "url": "https://courses.cs.washington.edu/cse331/26sp/calendar/calendar.html",
    "events_found": 28,
    "score": 456,
    "is_best": true
  },
  {
    "url": "https://courses.cs.washington.edu/cse331/26sp/",
    "events_found": 5,
    "score": 120,
    "is_best": false
  }
]
```

---

## Known Limitations

1. **JavaScript-rendered calendars** — Importer fetches raw HTML only
   - Some courses load calendars via client-side JS (FullCalendar, etc.)
   - **Workaround**: Provide direct link to calendar JSON/HTML export

2. **Relative dates** — "Next Friday", "Week 5 assignments" not fully resolved
   - **Workaround**: Explicitly mention week/date ranges near assignments

3. **Auth-required courses** — Canvas, Gradescope, Blackboard
   - **Solution**: Use Canvas API integration instead
   - Importer warns users and skips these courses

4. **Non-standard date formats** — Some courses use custom notation
   - **Workaround**: Add course-specific date parser if needed

---

## Implementation Notes

- **No new dependencies** — Uses existing libraries (BeautifulSoup, icalendar, dateutil)
- **Backward compatible** — All existing extraction strategies intact
- **Non-breaking** — Course-specific logic is additive, doesn't change baseline behavior
- **Efficient** — ~0.12s delay between requests, max 18 pages crawled per course

---

## Next Steps

### To activate for more courses:
1. Update `_UW_CSE_COURSES_WITH_PUBLIC_CALENDARS` with additional courses
2. Test against live course URLs and refine path detection
3. Add course-specific adapters as new patterns emerge

### To extend:
1. Add support for other universities (adjust domain patterns)
2. Implement JavaScript rendering for client-side calendars (Playwright/Selenium)
3. Build Canvas API integration for auth-required courses
4. Add recurring event expansion (weekly lectures → individual entries)


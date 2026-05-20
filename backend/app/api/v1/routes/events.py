# API routes for fetching and managing fixed calendar events (classes, meetings, exams).
from datetime import date, datetime, timezone, timedelta
import re as _re
import uuid as _uuid

import httpx
import recurring_ical_events
from bs4 import BeautifulSoup
from dateutil import parser as _dateutil
from fastapi import APIRouter, HTTPException
from icalendar import Calendar
from pydantic import BaseModel

router = APIRouter()


class IcalFeedIn(BaseModel):
    url: str
    name: str = ""


@router.post("/ical-feeds/preview")
async def preview_ical_feed(body: IcalFeedIn) -> dict:
    """Fetch an iCal URL and return its events as JSON.

    Recurring events (RRULE) are fully expanded — e.g. a Canvas lecture
    that repeats every Monday/Wednesday for 16 weeks becomes 32 individual
    events. Covers a window of 90 days in the past to 365 days in the future.
    """
    url = body.url
    if url.startswith("webcal://"):
        url = url.replace("webcal://", "https://", 1)

    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=15) as client:
            resp = await client.get(url)
            resp.raise_for_status()
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=400, detail=f"Could not fetch iCal URL: {exc}")

    try:
        cal = Calendar.from_ical(resp.content)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Invalid iCal data: {exc}")

    # Extract calendar display name
    feed_name = body.name
    if not feed_name:
        for comp in cal.walk():
            if comp.name == "VCALENDAR":
                feed_name = str(comp.get("X-WR-CALNAME", "")) or "iCal Feed"
                break

    # Expand recurrences over a ~15-month window (past semester + next year)
    now = datetime.now(tz=timezone.utc)
    start_dt = now - timedelta(days=90)
    end_dt   = now + timedelta(days=365)

    try:
        expanded = recurring_ical_events.of(cal).between(start_dt, end_dt)
    except Exception:
        expanded = [c for c in cal.walk() if c.name == "VEVENT"]

    events: list[dict] = []
    for component in expanded:
        dtstart = component.get("DTSTART")
        if dtstart is None:
            continue

        dtend = component.get("DTEND")
        start = dtstart.dt
        end   = dtend.dt if dtend else start

        # Normalise all-day date → midnight datetime
        if isinstance(start, date) and not isinstance(start, datetime):
            start = datetime(start.year, start.month, start.day, 0, 0, 0)
        if isinstance(end, date) and not isinstance(end, datetime):
            end = datetime(end.year, end.month, end.day, 23, 59, 59)

        # Strip tz info for uniform ISO strings
        if getattr(start, "tzinfo", None):
            start = start.replace(tzinfo=None)
        if getattr(end, "tzinfo", None):
            end = end.replace(tzinfo=None)

        uid = str(component.get("UID", _uuid.uuid4()))
        unique_id = f"{uid}_{start.isoformat()}"

        events.append({
            "id":         unique_id,
            "title":      str(component.get("SUMMARY", "Untitled")),
            "start_time": start.isoformat(),
            "end_time":   end.isoformat(),
            "source":     "ical",
            "is_fixed":   True,
        })

    return {
        "feed_name":   feed_name or "iCal Feed",
        "event_count": len(events),
        "events":      events,
    }


# ── Course URL import ──────────────────────────────────────────────────────────
#
# Detection order for any given URL:
#   1. events_source.json   — UW FullCalendar JSON (CSE 333, 351, 369, …)
#   2. monthtable HTML      — UW static monthly calendar (CSE 331, 340, 341, …)
#      Checked at several candidate paths (calendar/calendar.html, schedule/, …)
#   3. Generic HTML fallback — tables, lists, headings with date + keyword patterns
#
# Event types always skipped: office hours ("oh")
# ──────────────────────────────────────────────────────────────────────────────

_SKIP_TYPES: set[str] = {"oh"}

# "14:30-15:20"
_TIME_RANGE_RE = _re.compile(r'(\d{1,2}:\d{2})\s*[-–]\s*(\d{1,2}:\d{2})')
# "23:59"  or  "17:00"  (single due-time, no dash)
_SINGLE_TIME_RE = _re.compile(r'\b(\d{1,2}:\d{2})\b')

# Common date text patterns
_DATE_RE = _re.compile(
    r'\b(?:'
    r'(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|'
    r'jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)'
    r'\.?\s+\d{1,2}(?:st|nd|rd|th)?(?:,?\s*\d{4})?'
    r'|'
    r'(?:0?[1-9]|1[0-2])/(?:0?[1-9]|[12]\d|3[01])(?:/\d{2,4})?'
    r'|'
    r'(?:mon|tue|wed|thu|fri|sat|sun)(?:day)?\.?,?\s+'
    r'(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|'
    r'jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)'
    r'\.?\s+\d{1,2}(?:st|nd|rd|th)?'
    r')',
    _re.IGNORECASE,
)

_ASSIGNMENT_RE = _re.compile(
    r'\b(?:hw\d*|homework|assignment|project|quiz|exam|midterm|final|lab|'
    r'due|reading|problem\s*set|ps\s*\d|exercise|writeup|write-up)\b',
    _re.IGNORECASE,
)

# Candidate sub-paths to look for a monthtable calendar page
_CALENDAR_CANDIDATES = [
    "calendar/calendar.html",
    "calendar.html",
    "schedule/schedule.html",
    "schedule.html",
    "schedule/",
    "calendar/",
]


# ── helpers ────────────────────────────────────────────────────────────────────

def _make_event(title: str, start_dt: datetime, end_dt: datetime) -> dict:
    return {
        "id":         str(_uuid.uuid4()),
        "title":      title[:120],
        "start_time": start_dt.isoformat(),
        "end_time":   end_dt.isoformat(),
        "source":     "course",
        "is_fixed":   True,
    }


def _try_parse_date(text: str, default_year: int) -> datetime | None:
    m = _DATE_RE.search(text)
    if not m:
        return None
    try:
        dt = _dateutil.parse(
            m.group(),
            default=datetime(default_year, 6, 1),
            dayfirst=False,
        )
        if abs((dt - datetime.now()).days) > 730:
            return None
        return dt
    except Exception:
        return None


def _resolve_times(div_text: str, base_date: datetime) -> tuple[datetime, datetime]:
    """Extract start/end datetimes from event text.

    Handles three formats:
      "14:30-15:20 ..."   → timed range
      "23:59 ..."         → single due-time (end = due time, start = due - 0)
      (no time)           → all-day (00:00 → 23:59)
    """
    range_m = _TIME_RANGE_RE.search(div_text)
    if range_m:
        sh, sm = map(int, range_m.group(1).split(":"))
        eh, em = map(int, range_m.group(2).split(":"))
        return base_date.replace(hour=sh, minute=sm), base_date.replace(hour=eh, minute=em)

    single_m = _SINGLE_TIME_RE.search(div_text)
    if single_m:
        h, m = map(int, single_m.group(1).split(":"))
        due = base_date.replace(hour=h, minute=m)
        return due, due + timedelta(hours=1)

    return base_date, base_date.replace(hour=23, minute=59, second=59)


# ── Strategy 1: FullCalendar events_source.json ────────────────────────────────

def _parse_events_source_json(data: dict) -> list[dict]:
    events: list[dict] = []
    for source in data.get("eventSources", []):
        for ev in source.get("events", []):
            if ev.get("eventType") in _SKIP_TYPES:
                continue
            try:
                start_dt = _dateutil.parse(ev["start"]).replace(tzinfo=None)
                end_raw  = ev.get("end", "")
                end_dt   = _dateutil.parse(end_raw).replace(tzinfo=None) if end_raw else start_dt + timedelta(hours=1)

                title = ev.get("title", "Untitled")
                desc  = BeautifulSoup(ev.get("description", ""), "html.parser").get_text(strip=True)
                if desc:
                    title = f"{title} — {desc}"

                events.append(_make_event(title, start_dt, end_dt))
            except Exception:
                continue
    return events


# ── Strategy 2: monthtable HTML calendar ──────────────────────────────────────

def _parse_monthtable(soup) -> list[dict]:
    """Parse UW CSE monthtable-format HTML calendars.

    Works for any page using:
      <td class='eventtd' id='YYYY-MM-DD'>
        <div aria-label='lecture|section|hw|exam|…'>
          [HH:MM[-HH:MM]] <span class='summary'>…</span>
          [<span class='description'>…</span>]
        </div>
      </td>
    """
    events: list[dict] = []
    for td in soup.find_all("td", class_="eventtd"):
        date_str = td.get("id", "")
        if len(date_str) != 10:
            continue
        try:
            base_date = datetime.strptime(date_str, "%Y-%m-%d")
        except ValueError:
            continue

        for div in td.find_all("div", recursive=False):
            etype = div.get("aria-label") or (div.get("class") or ["other"])[0]
            if etype in _SKIP_TYPES:
                continue

            div_text = div.get_text(" ", strip=True)
            start_dt, end_dt = _resolve_times(div_text, base_date)

            summary = div.find("span", class_="summary")
            desc    = div.find("span", class_="description")
            title   = summary.get_text(strip=True) if summary else etype.capitalize()
            if desc:
                desc_text = desc.get_text(strip=True)
                if desc_text:
                    title = f"{title} — {desc_text}"

            events.append(_make_event(title, start_dt, end_dt))
    return events


def _has_monthtable(soup) -> bool:
    return bool(soup.find("td", class_="eventtd"))


# ── Strategy 3: Generic HTML fallback ─────────────────────────────────────────

def _parse_tables(soup, default_year: int) -> list[dict]:
    events = []
    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        if len(rows) < 2:
            continue

        headers = [c.get_text(" ", strip=True).lower()
                   for c in rows[0].find_all(["th", "td"])]
        date_col = next(
            (i for i, h in enumerate(headers)
             if any(kw in h for kw in ["date", "week", "due", "when", "day"])),
            None,
        )

        for row in rows[1:]:
            cells = [c.get_text(" ", strip=True) for c in row.find_all(["td", "th"])]
            if not cells:
                continue

            dt = None
            date_idx = None
            search_order = (
                ([date_col] if date_col is not None and date_col < len(cells) else [])
                + [i for i in range(len(cells)) if i != date_col]
            )
            for i in search_order:
                if i >= len(cells):
                    continue
                dt = _try_parse_date(cells[i], default_year)
                if dt:
                    date_idx = i
                    break

            if dt is None:
                continue

            parts = [c for i, c in enumerate(cells) if i != date_idx and c]
            title = " — ".join(parts[:2])
            if not title.strip():
                continue
            events.append(_make_event(title, dt, dt.replace(hour=23, minute=59, second=59) if dt.hour == 0 else dt + timedelta(hours=1)))
    return events


def _parse_lists(soup, default_year: int) -> list[dict]:
    events = []
    for li in soup.find_all("li"):
        text = li.get_text(" ", strip=True)
        if not (5 < len(text) < 300):
            continue
        if not (_ASSIGNMENT_RE.search(text) or _DATE_RE.search(text)):
            continue
        dt = _try_parse_date(text, default_year)
        if dt is None:
            continue
        end_dt = dt + timedelta(hours=1) if (dt.hour or dt.minute) else dt.replace(hour=23, minute=59, second=59)
        events.append(_make_event(text, dt, end_dt))
    return events


def _parse_headings(soup, default_year: int) -> list[dict]:
    events = []
    for heading in soup.find_all(["h2", "h3", "h4"]):
        text = heading.get_text(" ", strip=True)
        dt = _try_parse_date(text, default_year)
        if dt is None:
            continue
        sibling = heading.find_next_sibling()
        extra = sibling.get_text(" ", strip=True)[:80] if sibling else ""
        title = f"{text} — {extra}" if extra else text
        end_dt = dt + timedelta(hours=1) if (dt.hour or dt.minute) else dt.replace(hour=23, minute=59, second=59)
        events.append(_make_event(title, dt, end_dt))
    return events


def _html_fallback(soup, default_year: int) -> list[dict]:
    for tag in soup(["script", "style", "nav", "footer", "header", "noscript"]):
        tag.decompose()
    raw = (
        _parse_tables(soup, default_year)
        + _parse_lists(soup, default_year)
        + _parse_headings(soup, default_year)
    )
    seen: set[tuple] = set()
    events: list[dict] = []
    for ev in raw:
        key = (ev["title"], ev["start_time"][:10])
        if key not in seen:
            seen.add(key)
            events.append(ev)
    return events


# ── Endpoint ───────────────────────────────────────────────────────────────────

class CourseImportIn(BaseModel):
    url: str
    name: str = ""


@router.post("/course-import")
async def import_course_url(body: CourseImportIn) -> dict:
    """Extract calendar events from any public course page.

    Detection order:
      1. events_source.json  — UW FullCalendar JSON (cse333/351/369 …)
      2. monthtable HTML     — UW static calendar (cse331/340/341/373 …)
         Tried at several candidate paths automatically.
      3. Generic HTML        — schedule tables, assignment lists, headings.
    """
    base_url = body.url.rstrip("/") + "/"

    async with httpx.AsyncClient(
        follow_redirects=True,
        timeout=20,
        headers={"User-Agent": "Mozilla/5.0 (compatible; Synctra/1.0)"},
    ) as client:

        # Fetch main page (always needed for the course name)
        try:
            page_resp = await client.get(base_url)
            page_resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=400, detail=f"Could not fetch URL: {exc}")

        main_soup = BeautifulSoup(page_resp.text, "html.parser")
        course_name = body.name or (
            (main_soup.find("title") or {}).get_text(strip=True)
            if main_soup.find("title") else "Course"
        )

        def _ret(events: list[dict]) -> dict:
            return {"feed_name": course_name, "event_count": len(events), "events": events}

        # ── 1. events_source.json ────────────────────────────────────────────
        try:
            r = await client.get(base_url + "events_source.json")
            if r.status_code == 200:
                data = r.json()
                if "eventSources" in data:
                    evs = _parse_events_source_json(data)
                    if evs:
                        return _ret(evs)
        except Exception:
            pass

        # ── 2. monthtable calendar — try main page first, then sub-paths ────
        if _has_monthtable(main_soup):
            evs = _parse_monthtable(main_soup)
            if evs:
                return _ret(evs)

        for path in _CALENDAR_CANDIDATES:
            try:
                r = await client.get(base_url + path)
                if r.status_code != 200:
                    continue
                cal_soup = BeautifulSoup(r.text, "html.parser")
                if _has_monthtable(cal_soup):
                    evs = _parse_monthtable(cal_soup)
                    if evs:
                        return _ret(evs)
            except Exception:
                continue

        # ── 3. Generic HTML fallback ─────────────────────────────────────────
        return _ret(_html_fallback(main_soup, datetime.now().year))

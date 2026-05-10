"""
Course URL importer — multi-strategy scraper for public course websites.

Supports course-specific adapters for UW CSE courses with intelligent path detection.
Automatically detects course type (UW CSE vs generic) and prioritizes paths accordingly.

Detection priority (most → least accurate):
  0. iCal subscription  — /calendar/subscribe.html → .ics files (createcal system)
  1. events_source.json — FullCalendar JSON (CSE 333/351/369 etc.)
  2. Monthtable HTML    — <td class='eventtd' id='YYYY-MM-DD'> with div/span structure
  3. Schedule cards     — <div class='schedule-card'> (CSE 421-style)
  4. Day/week divs      — <div class='day lecture-day'> (CSE 312-style)
  5. Generic scanning   — date + assignment keyword in the same element
  6. Calendar grid      — month heading above table, day number in cell
  7. Date-id cells      — <td id='YYYY-MM-DD'> with inner divs (aria-label)
  8. Table rows         — date/header inference across schedule tables
  9. Heading context    — week/date headings with sibling lists/cards
 10. Structured JSON    — JSON-LD / Next-style embedded event data

Course-specific features:
- Recognizes UW CSE courses and applies optimized path search
- Auto-detects calendar availability and skips courses without public access
- Extends candidate paths based on course patterns

A lightweight feature-scoring classifier picks the best strategy per page.
All strategies run; results are deduplicated and merged by normalised key.
"""

import json
import re
from dataclasses import dataclass
from datetime import date as _date
from datetime import datetime, timedelta
from time import sleep
from urllib.parse import urljoin, urlparse, urlunparse

import httpx
from bs4 import BeautifulSoup
from dateutil import parser as dateparser
from fastapi import APIRouter, HTTPException, Query
from icalendar import Calendar as ICalendar
from pydantic import BaseModel, Field

# Import hybrid parser for AI-enhanced parsing (ChatGPT only)
from .hybrid_parser import (
    parse_with_hybrid_approach,
    ParsingResult,
)

router = APIRouter(tags=["course-import"])

# ────────────────────────────────────────────────────────────────────────────
# Constants
# ────────────────────────────────────────────────────────────────────────────

SKIP_EXTENSIONS = {
    ".pdf", ".zip", ".tar", ".gz", ".png", ".jpg", ".jpeg", ".gif",
    ".webp", ".svg", ".css", ".js", ".ico", ".mp4", ".mov",
}
SKIP_KEYWORDS   = {"staff", "contact", "people", "piazza", "edstem", "gradescope",
                   "canvas", "login", "logout", "account"}
MAX_CRAWL_PAGES = 18
REQUEST_DELAY_SECONDS = 0.12

LINK_POSITIVE_TERMS = {
    "assignment", "assignments", "calendar", "deadline", "deadlines", "due",
    "exam", "exams", "final", "homework", "hw", "lab", "labs", "lecture",
    "lectures", "midterm", "project", "projects", "quiz", "quizzes",
    "reading", "readings", "schedule", "syllabus", "week", "weeks",
}
LINK_NEGATIVE_TERMS = {
    "about", "admission", "archive", "blog", "contact", "directory",
    "faculty", "login", "news", "people", "policy", "privacy", "research",
    "staff", "student-life",
}
AUTH_URL_TERMS = {"canvas", "gradescope", "login", "sso", "signin", "oauth", "saml"}
AUTH_TEXT_RE = re.compile(
    r"\b(sign in|log in|login|single sign-on|sso|authentication required|"
    r"unauthorized|forbidden|netid|duo)\b",
    re.IGNORECASE,
)
NOISE_TEXT_RE = re.compile(
    r"\b(copyright|privacy|cookie|all rights reserved|office hours|"
    r"instructor|teaching assistant|staff|navbar|navigation|late policy|"
    r"academic integrity|grading policy)\b",
    re.IGNORECASE,
)

# Event types / div classes to skip entirely
_SKIP_EVENT_TYPES: frozenset[str] = frozenset({"oh"})
_SKIP_DIV_CLASSES: frozenset[str] = frozenset({
    "oh", "holiday", "nothing", "notinquarter", "noevent",
})

# Known event class / aria-label values that indicate a real assignment/class event
_COURSE_EVENT_TYPES: frozenset[str] = frozenset({
    "hw", "homework", "quiz", "midterm", "final", "exam",
    "lecture", "section", "lab", "project", "assignment", "due", "reading",
})

# Sub-paths to probe even when not discoverable via HTML links
_CALENDAR_CANDIDATES = [
    "calendar/calendar.html",
    "calendar.html",
    "schedule/schedule.html",
    "schedule.html",
    "schedule/",
    "calendar/",
    "calendar/subscribe.html",
    "lectures.html",
    "homework.html",
    "assignments.html",
    "lectures/",
    "homework/",
    "assignments/",
    "due_dates.html",
    "syllabus.html",
]

# UW CSE courses known to have public calendars/assignments
_UW_CSE_COURSES_WITH_PUBLIC_CALENDARS = {
    # Courses that definitely have public calendars/assignments
    "cse331", "cse333", "cse351", "cse369", "cse373",
    "cse421", "cse403", "cse410", "cse414", "cse415",
    "cse416", "cse431", "cse440", "cse451", "cse452",
    "cse461", "cse481", "cse482",
    # Add more as we confirm them
}

# Courses known to require authentication
_COURSES_REQUIRING_AUTH = {
    "canvas", "gradescope", "canvas-based", "gradescope-based",
}

# Known course domain patterns
_COURSE_DOMAIN_PATTERNS = {
    "courses.cs.washington.edu": "uw_cse",
    "www.cs.washington.edu": "uw_cse",
    "cs.washington.edu": "uw_cse",
}

# ── Regex patterns ────────────────────────────────────────────────────────────

ASSIGNMENT_RE = re.compile(
    r"\b(hw|homework|assignment|project|lab|quiz|midterm|final|exam|"
    r"lecture|section|due|pset|problem\s*set|reading|program)\s*\d*\b",
    re.IGNORECASE,
)

NORM_RE = re.compile(
    r"\b(hw|homework|assignment|project|lab|quiz|midterm|final|exam|pset|problem\s*set|program)\s*(\d+)?\b",
    re.IGNORECASE,
)

DATE_PATTERNS = [
    # "2026-04-15"
    r"\b\d{4}-\d{1,2}-\d{1,2}\b",
    # "April 15", "Apr 15, 2026", "15th April"
    r"\b(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?"
    r"|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
    r"\.?\s+\d{1,2}(?:st|nd|rd|th)?(?:,?\s*\d{4})?\b",
    # "15 April", "15th Apr 2026"
    r"\b\d{1,2}(?:st|nd|rd|th)?\s+"
    r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?"
    r"|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
    r"\.?(?:,?\s*\d{4})?\b",
    # "4/15" or "4/15/26"
    r"\b\d{1,2}/\d{1,2}(?:/\d{2,4})?\b",
    # "4-15" / "4.15" without a year
    r"\b\d{1,2}[-.]\d{1,2}(?:[-.]\d{2,4})?\b",
    # "Mon, Apr 15" / "Monday April 15"
    r"\b(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)(?:day)?\.?,?\s+"
    r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?"
    r"|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
    r"\.?\s+\d{1,2}(?:st|nd|rd|th)?\b",
    # "Apr 15th" with ordinal suffix
    r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{1,2}(?:st|nd|rd|th)\b",
]

MONTH_YEAR_RE = re.compile(
    r"\b(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?"
    r"|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
    r"\s+(\d{4})\b",
    re.IGNORECASE,
)

MONTH_ONLY_RE = re.compile(
    r"^(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?"
    r"|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)$",
    re.IGNORECASE,
)

MONTH_MAP = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}

TIME_RE      = re.compile(r"(?<!\d)(\d{1,2}):(\d{2})(?!\d)")
AMPM_TIME_RE = re.compile(r"\b(\d{1,2})(?::(\d{2}))?\s*([ap])\.?m\.?\b", re.IGNORECASE)
EOD_RE       = re.compile(r"\b(eod|end of day|end-of-day|11:59\s*p\.?m\.?)\b", re.IGNORECASE)
NOON_RE      = re.compile(r"\b(noon|12\s*p\.?m\.?)\b", re.IGNORECASE)
MIDNIGHT_RE  = re.compile(r"\b(midnight|12\s*a\.?m\.?)\b", re.IGNORECASE)
WEEKDAY_RE   = re.compile(r"\b(mon|tue|wed|thu|fri|sat|sun)(?:day)?\b", re.IGNORECASE)
UNRESOLVED_RELATIVE_DATE_RE = re.compile(
    r"\b(next|this)\s+(mon|tue|wed|thu|fri|sat|sun)(?:day)?\b|"
    r"\b(today|tomorrow|tonight)\b|"
    r"\b(mon|tue|wed|thu|fri|sat|sun)(?:day)?\s+of\s+week\s+\d+\b",
    re.IGNORECASE,
)
WEEKDAY_INDEX = {
    "mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6,
}
DAY_START_RE = re.compile(r"^(\d{1,2})\b")
FILLER       = re.compile(r"\b(due|deadline|submit|submission|part|section|a|b|c)\b", re.IGNORECASE)
DATE_ID_RE   = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# ────────────────────────────────────────────────────────────────────────────
# Models
# ────────────────────────────────────────────────────────────────────────────

class RawEvent(BaseModel):
    title: str
    date: str
    time: str | None = None
    description: str | None = None
    source_url: str
    norm_key: str


class CourseEvent(BaseModel):
    title: str
    date: str
    time: str | None = None
    end_time: str | None = None  # For events with duration (e.g., "7:59 AM - 8:29 AM")
    description: str | None = None  # Full context and requirements
    full_text: str | None = None  # Complete original text if available
    event_type: str | None = None  # 'assignment', 'lecture', 'exam', etc.
    source_urls: list[str]


class PageReport(BaseModel):
    url: str
    events_found: int
    score: int
    is_best: bool


class CourseImportResult(BaseModel):
    course_url: str
    best_source: str | None
    events: list[CourseEvent]
    page_reports: list[PageReport]
    warnings: list[str] = Field(default_factory=list)


@dataclass(frozen=True)
class FetchOutcome:
    requested_url: str
    final_url: str
    status_code: int | None
    html: str | None
    content_type: str | None = None
    warning: str | None = None


# ────────────────────────────────────────────────────────────────────────────
# HTTP helpers
# ────────────────────────────────────────────────────────────────────────────

def _headers() -> dict[str, str]:
    return {
        "User-Agent": "Mozilla/5.0 (compatible; SyntraCourseImporter/1.0)",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,text/calendar;q=0.8,*/*;q=0.7",
    }


def _diagnose_html(url: str, html: str, status_code: int | None = None) -> str | None:
    lower_url = url.lower()
    lower_html = html.lower()
    soup = BeautifulSoup(html, "html.parser")
    body_text = soup.get_text(" ", strip=True)

    if status_code in {401, 403}:
        return "The page requires authentication or blocked anonymous access."
    if status_code == 429:
        return "The server rate-limited the importer."
    if any(term in lower_url for term in AUTH_URL_TERMS) and AUTH_TEXT_RE.search(body_text):
        return "The fetched page appears to be a login or SSO page."
    if soup.find("form") and AUTH_TEXT_RE.search(body_text):
        return "The fetched page appears to require login before course content is visible."

    script_count = len(soup.find_all("script"))
    app_shell = bool(soup.find(id=re.compile(r"^(app|root|__next)$", re.IGNORECASE)))
    if script_count >= 3 and app_shell and len(body_text) < 250:
        return "The page looks JavaScript-rendered; raw HTML contains little course content."
    if "__next_data__" in lower_html or "window.__initial_state__" in lower_html:
        return "The page is JavaScript-rendered; importer will inspect embedded JSON only."

    return None


def _relative_date_warning(html: str) -> str | None:
    text = _clean_soup(html).get_text(" ", strip=True)
    if UNRESOLVED_RELATIVE_DATE_RE.search(text):
        return (
            "Found relative date wording such as 'next Friday', 'Friday of Week 5', or 'tomorrow'; "
            "those entries are only imported when an explicit week/date range is nearby."
        )
    return None


def _fetch_page(url: str) -> FetchOutcome:
    for attempt in range(2):
        try:
            r = httpx.get(url, follow_redirects=True, timeout=12, headers=_headers())
        except Exception as exc:
            return FetchOutcome(
                requested_url=url,
                final_url=url,
                status_code=None,
                html=None,
                warning=f"Could not fetch {url}: {exc}",
            )

        content_type = r.headers.get("content-type", "")
        if r.status_code in {429, 503} and attempt == 0:
            sleep(0.5)
            continue
        if r.status_code >= 400:
            warning = _diagnose_html(str(r.url), r.text, r.status_code)
            return FetchOutcome(
                requested_url=url,
                final_url=str(r.url),
                status_code=r.status_code,
                html=None,
                content_type=content_type,
                warning=warning or f"HTTP {r.status_code} while fetching {url}.",
            )

        html = r.text
        warning = _diagnose_html(str(r.url), html, r.status_code)
        if warning and "login" in warning.lower():
            return FetchOutcome(
                requested_url=url,
                final_url=str(r.url),
                status_code=r.status_code,
                html=None,
                content_type=content_type,
                warning=warning,
            )
        return FetchOutcome(
            requested_url=url,
            final_url=str(r.url),
            status_code=r.status_code,
            html=html,
            content_type=content_type,
            warning=warning,
        )

    return FetchOutcome(
        requested_url=url,
        final_url=url,
        status_code=None,
        html=None,
        warning=f"Could not fetch {url}.",
    )


def _fetch(url: str) -> str | None:
    return _fetch_page(url).html


def _fetch_bytes(url: str) -> bytes | None:
    try:
        r = httpx.get(url, follow_redirects=True, timeout=12, headers=_headers())
        r.raise_for_status()
        return r.content
    except Exception:
        return None


def _same_domain(base: str, url: str) -> bool:
    return urlparse(url).netloc == urlparse(base).netloc


def _skip_url(url: str) -> bool:
    lower = url.lower()
    return (
        any(lower.endswith(ext) for ext in SKIP_EXTENSIONS)
        or any(kw in lower for kw in SKIP_KEYWORDS)
    )


def _extract_course_code(url: str) -> str | None:
    """Extract CSE course code (e.g., 'cse331') from a URL."""
    match = re.search(r"(?:^|/)(?:cse)(\d{3})", url.lower())
    if match:
        return f"cse{match.group(1)}"
    return None


def _get_course_type(url: str) -> str:
    """Determine course type from URL patterns."""
    course_code = _extract_course_code(url)
    if course_code and course_code in _UW_CSE_COURSES_WITH_PUBLIC_CALENDARS:
        return "uw_cse_public"
    if any(domain in url.lower() for domain in _COURSE_DOMAIN_PATTERNS):
        return "uw_cse"
    return "generic"


def _prioritize_candidate_paths(base_url: str, course_type: str) -> list[str]:
    """Generate prioritized candidate paths based on course type."""
    base = base_url.rstrip("/") + "/"
    candidates = []

    # Course-specific paths first
    if course_type in {"uw_cse", "uw_cse_public"}:
        candidates.extend([
            base + "calendar/calendar.html",
            base + "calendar/subscribe.html",
            base + "schedule.html",
            base + "schedule/schedule.html",
            base + "lectures.html",
            base + "homework.html",
            base + "assignments.html",
        ])

    # General paths
    candidates.extend(_CALENDAR_CANDIDATES)
    return candidates


def _canonical_url(url: str) -> str:
    parsed = urlparse(url)
    return urlunparse(parsed._replace(fragment="")).rstrip("/")


def _base_path_prefix(page_url: str) -> str:
    parsed = urlparse(page_url)
    path = parsed.path
    if not path or path == "/":
        return "/"
    return path if path.endswith("/") else path.rsplit("/", 1)[0] + "/"


def _link_score(page_url: str, abs_url: str, link_text: str) -> int:
    parsed = urlparse(abs_url)
    text = f"{parsed.path} {parsed.query} {link_text}".lower()
    score = 0
    score += sum(4 for term in LINK_POSITIVE_TERMS if term in text)
    score -= sum(8 for term in LINK_NEGATIVE_TERMS if term in text)

    base_prefix = _base_path_prefix(page_url)
    if parsed.path.startswith(base_prefix):
        score += 5
    elif score < 8:
        score -= 6

    if parsed.query:
        score -= 1
    return score


def _all_internal_links(html: str, page_url: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    seen: set[str] = {_canonical_url(page_url)}
    scored_links: list[tuple[int, str]] = []
    for tag in soup.find_all("a", href=True):
        href: str = tag["href"].strip()
        if href.startswith("#") or href.startswith(("mailto:", "tel:", "javascript:")):
            continue
        abs_url = urljoin(page_url, href).split("#")[0]
        canonical = _canonical_url(abs_url)
        if canonical in seen:
            continue
        if not _same_domain(page_url, abs_url) or _skip_url(abs_url):
            continue
        score = _link_score(page_url, abs_url, tag.get_text(" ", strip=True))
        if score <= 0:
            continue
        seen.add(canonical)
        scored_links.append((score, canonical))

    scored_links.sort(key=lambda item: (-item[0], item[1]))
    return [url for _, url in scored_links[:MAX_CRAWL_PAGES]]


# ────────────────────────────────────────────────────────────────────────────
# Extraction utilities (shared)
# ────────────────────────────────────────────────────────────────────────────

def _default_year(default_year: int | None = None) -> int:
    return default_year or datetime.now().year


def _strip_ordinal_suffixes(text: str) -> str:
    return re.sub(r"\b(\d{1,2})(st|nd|rd|th)\b", r"\1", text, flags=re.IGNORECASE)


def _parse_date_text(candidate: str, default_year: int | None = None) -> datetime | None:
    cleaned = _strip_ordinal_suffixes(candidate.strip())
    if not cleaned:
        return None
    try:
        return dateparser.parse(cleaned, default=datetime(_default_year(default_year), 1, 1))
    except Exception:
        return None


def _parse_date_range(text: str, default_year: int | None = None) -> tuple[datetime, datetime] | None:
    year = _default_year(default_year)

    # "4/14-4/18", "4/14 - 18", "4/14/26-4/18/26"
    numeric = re.search(
        r"\b(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?\s*[-–—]\s*"
        r"(?:(\d{1,2})/)?(\d{1,2})(?:/(\d{2,4}))?\b",
        text,
    )
    if numeric:
        start_month = int(numeric.group(1))
        start_day = int(numeric.group(2))
        start_year = int(numeric.group(3)) if numeric.group(3) else year
        end_month = int(numeric.group(4)) if numeric.group(4) else start_month
        end_day = int(numeric.group(5))
        end_year = int(numeric.group(6)) if numeric.group(6) else start_year
        if start_year < 100:
            start_year += 2000
        if end_year < 100:
            end_year += 2000
        try:
            return datetime(start_year, start_month, start_day), datetime(end_year, end_month, end_day)
        except ValueError:
            pass

    # "Apr 14-18", "April 14 - Apr 18", "April 14 to April 18"
    month_name = re.search(
        r"\b(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?"
        r"|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
        r"\.?\s+(\d{1,2})(?:st|nd|rd|th)?(?:,?\s*(\d{4}))?\s*(?:[-–—]|to)\s*"
        r"(?:(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?"
        r"|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
        r"\.?\s+)?(\d{1,2})(?:st|nd|rd|th)?(?:,?\s*(\d{4}))?\b",
        text,
        re.IGNORECASE,
    )
    if month_name:
        start_month = MONTH_MAP[month_name.group(1).lower()[:3]]
        end_month = MONTH_MAP[(month_name.group(4) or month_name.group(1)).lower()[:3]]
        start_year = int(month_name.group(3) or year)
        end_year = int(month_name.group(6) or start_year)
        try:
            return (
                datetime(start_year, start_month, int(month_name.group(2))),
                datetime(end_year, end_month, int(month_name.group(5))),
            )
        except ValueError:
            pass

    return None


def _weekday_date_in_range(text: str, start: datetime, end: datetime) -> datetime | None:
    match = WEEKDAY_RE.search(text)
    if not match:
        return None
    target = WEEKDAY_INDEX[match.group(1).lower()[:3]]
    current = start
    while current.date() <= end.date():
        if current.weekday() == target:
            return current
        current += timedelta(days=1)
    return None


def _parse_date(text: str, default_year: int | None = None) -> datetime | None:
    range_pair = _parse_date_range(text, default_year)
    if range_pair:
        start, end = range_pair
        weekday_dt = _weekday_date_in_range(text, start, end)
        if weekday_dt:
            return weekday_dt
        if re.search(r"\b(due|deadline|submit|submission|eod|end of day)\b", text, re.IGNORECASE):
            return end
        return start

    for pat in DATE_PATTERNS:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            parsed = _parse_date_text(m.group(), default_year)
            if parsed:
                return parsed
    return None


def _infer_default_year(course_url: str, html: str) -> int:
    url_lower = course_url.lower()
    term_code = re.search(r"(?:^|[/_-])(\d{2})(?:wi|sp|su|au|fa)(?:[/_-]|$)", url_lower)
    if term_code:
        return 2000 + int(term_code.group(1))

    four_digit = re.search(r"(?:^|[/_-])(20\d{2})(?:[/_-]|$)", url_lower)
    if four_digit:
        return int(four_digit.group(1))

    month_year = MONTH_YEAR_RE.search(BeautifulSoup(html, "html.parser").get_text(" ", strip=True)[:5000])
    if month_year:
        return int(month_year.group(2))

    return datetime.now().year


def _normalize_key(text: str) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    m = NORM_RE.search(text)
    if not m:
        compact = FILLER.sub("", text).lower().strip()
        compact = re.sub(r"\b\d{4}-\d{1,2}-\d{1,2}\b", "", compact)
        compact = re.sub(r"\b\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?\b", "", compact)
        compact = re.sub(r"\s+", " ", compact)
        return compact[:100]
    base = m.group(1).lower()
    base = base.replace("homework", "hw").replace("assignment", "hw").replace("pset", "hw")
    base = base.replace("problem set", "hw")
    num = m.group(2) or ""
    return f"{base}{num}"


def _extract_title(text: str) -> str:
    """Extract assignment name, not just the due date clause."""
    # Look for patterns like "Homework 1", "Project X", "Quiz Y" first
    m = ASSIGNMENT_RE.search(text)
    if m:
        # Extract context around the match to get full assignment name
        start = max(0, m.start() - 30)
        end = min(len(text), m.end() + 50)
        snippet = text[start:end].strip()

        # Find the assignment name part (before "due" if present)
        due_idx = snippet.lower().find("due")
        if due_idx > 0:
            snippet = snippet[:due_idx].strip()
        else:
            # Split by common delimiters
            snippet = re.split(r"[|\n•–—()]", snippet)[0].strip()

        return snippet[:100]
    return text[:100]


def _extract_description(container_text: str, title: str) -> str | None:
    """Extract full description, preserving all details and context."""
    desc = container_text.replace(title, "").strip()
    desc = re.sub(r"\s+", " ", desc)
    # Increased from 200 to 500 chars to preserve more context
    return desc[:500] if len(desc) > 10 else None


def _dt_with_time(base: datetime, text: str) -> datetime:
    """Apply explicit due/class time words in text to base datetime."""
    if EOD_RE.search(text):
        return base.replace(hour=23, minute=59)
    if NOON_RE.search(text):
        return base.replace(hour=12, minute=0)
    if MIDNIGHT_RE.search(text):
        return base.replace(hour=0, minute=0)

    ampm = AMPM_TIME_RE.search(text)
    if ampm:
        hour = int(ampm.group(1))
        minute = int(ampm.group(2) or "0")
        marker = ampm.group(3).lower()
        if marker == "p" and hour != 12:
            hour += 12
        if marker == "a" and hour == 12:
            hour = 0
        try:
            return base.replace(hour=hour, minute=minute)
        except ValueError:
            pass

    m = TIME_RE.search(text)
    if m:
        try:
            return base.replace(hour=int(m.group(1)), minute=int(m.group(2)))
        except ValueError:
            pass
    return base


def _parse_multiple_assignments(text: str, base_date: datetime) -> list[tuple[str, datetime]]:
    """Parse multiple assignments from a single text block.

    Returns list of (assignment_name, due_datetime) tuples.
    Handles cases like:
    - "Homework 1 due today" + "Project 2 due Friday"
    - "Due today by 11:59pm ) Beta release ( due Tues 02/17/26"
    """
    results = []

    # Split by common separators that might indicate multiple items
    parts = re.split(r'\)\s*\(|\)(?=\s*[A-Z])|;\s+|,\s+(?=(?:hw|homework|project|quiz|lab|exam|assignment|due))', text, flags=re.IGNORECASE)

    for part in parts:
        part = part.strip().strip('()').strip()
        if not part or len(part) < 5:
            continue

        # Extract assignment name and due date
        if ASSIGNMENT_RE.search(part):
            # Find where "due" is mentioned
            due_match = re.search(r'\bdue\b', part, re.IGNORECASE)
            if due_match:
                # Assignment name is before "due"
                assignment_name = part[:due_match.start()].strip()
                due_clause = part[due_match.start():].strip()

                # Clean up parentheses and extra text
                assignment_name = re.sub(r'[()]+', '', assignment_name).strip()
                if not assignment_name or len(assignment_name) > 200:
                    continue

                # Parse the due date from the clause
                due_dt = _parse_date(due_clause, base_date.year)
                if due_dt:
                    due_dt = _dt_with_time(due_dt, due_clause)
                    results.append((assignment_name, due_dt))
            else:
                # No explicit "due", assume entire part is the event
                results.append((part[:100], base_date))

    return results if results else [(text[:100], base_date)]


def _event_kind(text: str) -> str:
    lower = text.lower()
    if re.search(r"\b(final|midterm|exam|quiz)\b", lower):
        return "exam"
    if re.search(r"\b(due|deadline|submit|submission|eod|end of day)\b", lower):
        return "deadline"
    if re.search(r"\b(out|released|assigned|posted|available)\b", lower):
        return "release"
    if re.search(r"\b(lecture|section|lab|meeting)\b", lower):
        return "meeting"
    return "event"


def _event_rank(ev: RawEvent) -> tuple[int, int, int, int]:
    text = f"{ev.title} {ev.description or ''}"
    kind_weight = {
        "deadline": 5,
        "exam": 5,
        "meeting": 3,
        "event": 2,
        "release": 1,
    }.get(_event_kind(text), 2)
    source_weight = 4 if ev.source_url.endswith((".ics", "events_source.json")) else 0
    return (
        kind_weight,
        source_weight + (2 if ev.time else 0),
        len(ev.description or ""),
        len(ev.title),
    )


def _is_noisy_container(container, text: str) -> bool:
    if len(text) > 500:
        return True
    if container.name in {"nav", "footer", "header", "aside", "form"}:
        return True
    if NOISE_TEXT_RE.search(text) and _event_kind(text) not in {"deadline", "exam"}:
        return True
    if len(container.find_all("a")) > 8 and _event_kind(text) == "event":
        return True
    return False


def _clean_soup(html: str) -> BeautifulSoup:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header", "aside", "form", "noscript"]):
        tag.decompose()
    return soup


def _append_raw_event(
    events: list[RawEvent],
    seen: set[str],
    *,
    title: str,
    dt: datetime,
    text: str,
    source_url: str,
) -> None:
    title = re.sub(r"\s+", " ", title).strip()
    if not title:
        return
    title = title[:80]
    norm_key = _normalize_key(title) or _normalize_key(text)
    if not norm_key:
        return
    key = f"{dt.date().isoformat()}|{norm_key}"
    if key in seen:
        return
    seen.add(key)
    events.append(RawEvent(
        title=title,
        date=dt.date().isoformat(),
        time=dt.strftime("%H:%M") if (dt.hour or dt.minute) else None,
        description=_extract_description(text, title),
        source_url=source_url,
        norm_key=norm_key,
    ))


# ────────────────────────────────────────────────────────────────────────────
# Page-type classifier (lightweight ML-style feature scorer)
#
# Scores each page for which calendar format it contains.
# Returns the format name with the highest score so the pipeline can
# prioritise the most precise extraction strategy.
# ────────────────────────────────────────────────────────────────────────────

_PAGE_TYPES = ("monthtable", "schedule_cards", "day_divs", "generic")

def _has_likely_public_calendar(html: str, course_url: str) -> bool:
    """Check if page indicates public calendar/assignment availability."""
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text(" ", strip=True).lower()

    # Positive signals for public calendars
    positive_signals = [
        "calendar", "schedule", "assignment", "homework", "due date",
        "lecture", "syllabus", "course outline", "weekly schedule",
    ]

    # Negative signals indicating auth-only or no calendar
    negative_signals = [
        "canvas", "gradescope", "login required", "authentication required",
        "sign in", "access restricted", "course closed",
    ]

    found_positive = sum(1 for sig in positive_signals if sig in text)
    found_negative = sum(1 for sig in negative_signals if sig in text)

    # If we see negative signals and no positive, likely needs auth
    if found_negative > 0 and found_positive < 2:
        return False

    # UW CSE courses usually have public pages
    if "cs.washington.edu" in course_url.lower():
        return True

    # Otherwise, positive signals indicate public access
    return found_positive >= 2


def _classify_page(html: str) -> str:
    """Score the page against known UW CSE format signals."""
    soup = BeautifulSoup(html, "html.parser")
    raw = html.lower()

    scores: dict[str, int] = {t: 0 for t in _PAGE_TYPES}
    scores["generic"] = 1  # baseline

    # ── Monthtable signals ────────────────────────────────────────────────
    if soup.find("td", class_="eventtd"):
        scores["monthtable"] += 20
    if soup.find("table", class_="monthtable"):
        scores["monthtable"] += 10
    if soup.find("span", class_="summary"):
        scores["monthtable"] += 5
    if "eventtd" in raw:
        scores["monthtable"] += 5
    if soup.find("td", id=DATE_ID_RE):
        scores["monthtable"] += 8

    # ── Schedule-card signals (CSE 421-style) ─────────────────────────────
    if soup.find("div", class_="schedule-card"):
        scores["schedule_cards"] += 20
    if soup.find("div", class_="schedule-cards"):
        scores["schedule_cards"] += 10
    if soup.find("div", class_="card-header"):
        scores["schedule_cards"] += 10
    if soup.find("div", class_="schedule-content"):
        scores["schedule_cards"] += 5
    if soup.find("a", class_="schedule-link"):
        scores["schedule_cards"] += 5

    # ── Day/week-div signals (CSE 312-style) ──────────────────────────────
    if soup.find("div", class_=lambda c: c and "lecture-day" in c):
        scores["day_divs"] += 20
    if soup.find("div", class_=lambda c: c and "section-day" in c):
        scores["day_divs"] += 10
    if soup.find("div", class_="date-and-type"):
        scores["day_divs"] += 10
    if soup.find("div", class_="schedule-container"):
        scores["day_divs"] += 5

    return max(scores, key=lambda k: scores[k])


# ────────────────────────────────────────────────────────────────────────────
# Strategy 0 — iCal subscription files
#
# All UW CSE createcal courses publish .ics feeds at:
#   /calendar/subscribe.html  →  links to .ics files per event type
# Parsing these gives exact DTSTART/DTEND with event type labels.
# ────────────────────────────────────────────────────────────────────────────

def _parse_ical_bytes(content: bytes, source_url: str) -> list[RawEvent]:
    """Parse raw iCal bytes into RawEvents, skipping office hours."""
    try:
        cal = ICalendar.from_ical(content)
    except Exception:
        return []

    events: list[RawEvent] = []
    seen: set[str] = set()

    for component in cal.walk():
        if component.name != "VEVENT":
            continue

        event_type = str(component.get("X-CREATECAL-EVENTTYPE", "")).lower().strip()
        if event_type in _SKIP_EVENT_TYPES:
            continue

        dtstart = component.get("DTSTART")
        if dtstart is None:
            continue
        start = dtstart.dt
        if isinstance(start, _date) and not isinstance(start, datetime):
            start = datetime(start.year, start.month, start.day)
        if getattr(start, "tzinfo", None):
            start = start.replace(tzinfo=None)

        summary = str(component.get("SUMMARY", "")).strip()
        description = str(component.get("DESCRIPTION", "")).strip()
        if not summary:
            continue

        # UW iCal often prefixes summary with course number ("331 HW1 due")
        # Strip leading "NNN " prefix so titles are clean
        summary = re.sub(r"^\d{3}\s+", "", summary).strip()

        # HW events with no time (or placeholder morning time) → treat as 23:59 deadline
        if event_type == "hw" and start.hour < 12 and start.minute == 0:
            start = start.replace(hour=23, minute=59)

        title = summary
        norm_key = _normalize_key(summary)
        key = f"{start.date().isoformat()}|{norm_key}"
        if key in seen:
            continue
        seen.add(key)

        events.append(RawEvent(
            title=title[:80],
            date=start.date().isoformat(),
            time=start.strftime("%H:%M") if (start.hour or start.minute) else None,
            description=description or None,
            source_url=source_url,
            norm_key=norm_key,
        ))

    return events


def _discover_ical_urls(html: str, page_url: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    urls: list[str] = []
    seen: set[str] = set()
    for tag in soup.find_all(["a", "link"], href=True):
        href = tag["href"].strip()
        text = tag.get_text(" ", strip=True).lower()
        rel_attr = tag.get("rel") or []
        rel_values = rel_attr if isinstance(rel_attr, list) else [str(rel_attr)]
        rel = " ".join(rel_values).lower()
        content_type = (tag.get("type") or "").lower()
        looks_like_calendar = (
            href.lower().endswith((".ics", ".ical"))
            or href.lower().startswith("webcal://")
            or "text/calendar" in content_type
            or "ical" in text
            or "calendar" in rel
        )
        if not looks_like_calendar or any(kw in href.lower() for kw in ("oh", "office")):
            continue
        abs_url = urljoin(page_url, href)
        if abs_url.startswith("webcal://"):
            abs_url = abs_url.replace("webcal://", "https://", 1)
        if abs_url not in seen:
            seen.add(abs_url)
            urls.append(abs_url)
    return urls


def _try_ical_sources(course_url: str, landing_html: str | None = None) -> tuple[str, list[RawEvent]] | None:
    """Find linked .ics feeds and createcal /calendar/subscribe.html feeds."""
    ical_urls: list[str] = []
    seen_urls: set[str] = set()

    if landing_html:
        for url in _discover_ical_urls(landing_html, course_url):
            if url not in seen_urls:
                seen_urls.add(url)
                ical_urls.append(url)

    subscribe_url = course_url.rstrip("/") + "/calendar/subscribe.html"
    html = _fetch(subscribe_url)
    if html:
        for url in _discover_ical_urls(html, subscribe_url):
            if url not in seen_urls:
                seen_urls.add(url)
                ical_urls.append(url)

    if not ical_urls:
        return None

    all_events: list[RawEvent] = []
    seen: set[str] = set()
    for url in ical_urls:
        raw = _fetch_bytes(url)
        if not raw:
            continue
        for ev in _parse_ical_bytes(raw, url):
            key = f"{ev.date}|{ev.norm_key}"
            if key not in seen:
                seen.add(key)
                all_events.append(ev)

    source = subscribe_url if html else ical_urls[0]
    return (source, all_events) if all_events else None


# ────────────────────────────────────────────────────────────────────────────
# Strategy 1 — FullCalendar events_source.json
# ────────────────────────────────────────────────────────────────────────────

def _parse_events_source(course_url: str) -> list[RawEvent] | None:
    json_url = course_url.rstrip("/") + "/events_source.json"
    raw = _fetch(json_url)
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except Exception:
        return None
    if not isinstance(data.get("eventSources"), list):
        return None

    events: list[RawEvent] = []
    seen: set[str] = set()
    for source in data["eventSources"]:
        for ev in source.get("events", []):
            if ev.get("eventType") in _SKIP_EVENT_TYPES:
                continue
            try:
                start_dt = dateparser.parse(ev["start"]).replace(tzinfo=None)
            except Exception:
                continue

            title_raw = ev.get("title") or ev.get("eventType") or "Event"
            desc_html = ev.get("description") or ""
            if desc_html:
                desc_text = BeautifulSoup(desc_html, "html.parser").get_text(strip=True)
                if desc_text:
                    title_raw = f"{title_raw} — {desc_text}"

            title = _extract_title(title_raw) or title_raw[:80]
            norm_key = _normalize_key(title)
            key = f"{start_dt.date().isoformat()}|{norm_key}"
            if key in seen:
                continue
            seen.add(key)

            events.append(RawEvent(
                title=title[:80],
                date=start_dt.date().isoformat(),
                time=start_dt.strftime("%H:%M") if (start_dt.hour or start_dt.minute) else None,
                description=None,
                source_url=json_url,
                norm_key=norm_key,
            ))

    return events or None


# ────────────────────────────────────────────────────────────────────────────
# Strategy 2 — UW Monthtable HTML
#
# Format:
#   <td class='eventtd' id='2026-04-07'>
#     <span class='datespan'>7</span>
#     <div class='hw'>
#       23:59 <span class='summary'><a href='...'>HW1</a> due</span>
#       <span class='description'>Data Structures</span>
#     </div>
#     <div class='lecture'>
#       10:30 <span class='summary'>Lecture 12</span>
#       <span class='description'>Hashing</span>
#     </div>
#   </td>
# ────────────────────────────────────────────────────────────────────────────

def _extract_monthtable(html: str, source_url: str) -> list[RawEvent]:
    soup = BeautifulSoup(html, "html.parser")
    events: list[RawEvent] = []
    seen: set[str] = set()

    for td in soup.find_all("td", class_="eventtd"):
        date_str = td.get("id", "")
        if not DATE_ID_RE.match(date_str):
            continue
        try:
            base_dt = datetime.fromisoformat(date_str)
        except ValueError:
            continue

        for div in td.find_all("div", recursive=False):
            classes = set(div.get("class") or [])
            aria    = (div.get("aria-label") or "").lower().strip()

            # Determine event type from class or aria-label
            event_type = next(iter(classes - _SKIP_DIV_CLASSES), None) or aria
            if not event_type or event_type in _SKIP_DIV_CLASSES:
                continue
            if classes & _SKIP_DIV_CLASSES or aria in _SKIP_DIV_CLASSES:
                continue

            # Build title from summary + description spans
            summary_span = div.find("span", class_="summary")
            desc_span    = div.find("span", class_="description")

            if summary_span:
                title = summary_span.get_text(" ", strip=True)
            else:
                raw_text = div.get_text(" ", strip=True)
                title = _extract_title(raw_text) or event_type.capitalize()

            if desc_span:
                desc_text = desc_span.get_text(" ", strip=True)
                if desc_text:
                    title = f"{title} — {desc_text}"

            title = title[:80]
            if not title:
                continue

            div_text = div.get_text(" ", strip=True)
            dt = _dt_with_time(base_dt, div_text)

            norm_key = _normalize_key(title)
            key = f"{date_str}|{norm_key}"
            if key in seen:
                continue
            seen.add(key)

            events.append(RawEvent(
                title=title,
                date=date_str,
                time=dt.strftime("%H:%M") if (dt.hour or dt.minute) else None,
                description=desc_span.get_text(" ", strip=True) if desc_span else None,
                source_url=source_url,
                norm_key=norm_key,
            ))

    return events


# ────────────────────────────────────────────────────────────────────────────
# Strategy 3 — Schedule cards  (CSE 421-style)
#
# Format:
#   <div class='schedule-card'>
#     <div class='card-header'>
#       <p>April 9</p>
#       <p>Lecture 5</p>
#     </div>
#     <div class='schedule-content'>
#       <ul class='schedule-topics'><li>Pset 1 due Apr 9th</li></ul>
#       <div class='schedule-links'>
#         <a class='schedule-link' href='psets/pset1.pdf'>Pset 1 due</a>
#       </div>
#     </div>
#   </div>
# ────────────────────────────────────────────────────────────────────────────

def _extract_schedule_cards(html: str, source_url: str, default_year: int | None = None) -> list[RawEvent]:
    soup = BeautifulSoup(html, "html.parser")
    events: list[RawEvent] = []
    seen: set[str] = set()

    for card in soup.find_all("div", class_="schedule-card"):
        header = card.find("div", class_="card-header")
        if not header:
            continue

        # Date is the first <p> that contains a parseable date
        card_dt: datetime | None = None
        for p in header.find_all(["p", "span", "div"]):
            card_dt = _parse_date(p.get_text(" ", strip=True), default_year)
            if card_dt:
                break
        if card_dt is None:
            card_dt = _parse_date(header.get_text(" ", strip=True), default_year)
        if card_dt is None:
            continue

        date_str = card_dt.date().isoformat()

        content = card.find("div", class_="schedule-content") or card

        # Assignment links with "due" in text
        for a in content.find_all("a"):
            link_text = a.get_text(" ", strip=True)
            if ASSIGNMENT_RE.search(link_text) or "due" in link_text.lower():
                norm_key = _normalize_key(link_text)
                key = f"{date_str}|{norm_key}"
                if key not in seen:
                    seen.add(key)
                    events.append(RawEvent(
                        title=link_text[:80],
                        date=date_str,
                        time=None,
                        description=None,
                        source_url=source_url,
                        norm_key=norm_key,
                    ))

        # List items mentioning assignments or due dates
        for li in content.find_all("li"):
            text = li.get_text(" ", strip=True)
            if not text or len(text) > 500:  # Allow up to 500 chars for full context
                continue
            if ASSIGNMENT_RE.search(text) or "due" in text.lower():
                # Try to extract an inline due date (e.g. "Pset 1 due Apr 9th")
                li_dt = _parse_date(text, default_year)
                effective_date = li_dt.date().isoformat() if li_dt else date_str
                norm_key = _normalize_key(text)
                key = f"{effective_date}|{norm_key}"
                if key not in seen:
                    seen.add(key)
                    title = _extract_title(text)
                    description = _extract_description(text, title)
                    events.append(RawEvent(
                        title=title,
                        date=effective_date,
                        time=None,
                        description=description,  # Preserve full context
                        source_url=source_url,
                        norm_key=norm_key,
                    ))

    return events


# ────────────────────────────────────────────────────────────────────────────
# Strategy 4 — Day/week divs  (CSE 312-style)
#
# Format:
#   <div class='day lecture-day odd'>
#     <div class='date-and-type'>
#       <div class='type'>Lecture 2</div>
#       <div class='date'>(Wed, Apr 2)</div>
#     </div>
#     <div class='topic'>Introduction to Probability</div>
#     <div>Pset 1 out</div>
#   </div>
# ────────────────────────────────────────────────────────────────────────────

def _extract_day_divs(html: str, source_url: str, default_year: int | None = None) -> list[RawEvent]:
    soup = BeautifulSoup(html, "html.parser")
    events: list[RawEvent] = []
    seen: set[str] = set()

    for day_div in soup.find_all("div", class_=lambda c: c and "day" in c):
        # Must also have a date indicator
        date_type = day_div.find("div", class_="date-and-type")
        if not date_type:
            continue

        # Parse date from the date-and-type block
        day_dt: datetime | None = _parse_date(date_type.get_text(" ", strip=True), default_year)
        if day_dt is None:
            continue
        date_str = day_dt.date().isoformat()

        # Scan every child div/p for assignment mentions
        for child in day_div.find_all(["div", "p", "li", "span"]):
            if child == date_type or date_type in child.parents:
                continue
            text = child.get_text(" ", strip=True)
            if not text or len(text) > 300:
                continue
            if ASSIGNMENT_RE.search(text) or "due" in text.lower():
                norm_key = _normalize_key(text)
                key = f"{date_str}|{norm_key}"
                if key not in seen:
                    seen.add(key)
                    events.append(RawEvent(
                        title=text[:80],
                        date=date_str,
                        time=None,
                        description=None,
                        source_url=source_url,
                        norm_key=norm_key,
                    ))

    return events


# ────────────────────────────────────────────────────────────────────────────
# Strategy 5 — General element scanning
# Finds date + assignment keyword in the SAME element.
# Catches tables, lists, paragraphs, definition lists, etc.
# ────────────────────────────────────────────────────────────────────────────

def _extract_events(html: str, source_url: str, default_year: int | None = None) -> list[RawEvent]:
    soup = _clean_soup(html)
    events: list[RawEvent] = []
    seen: set[str] = set()

    for container in soup.find_all(["main", "section", "article", "tr", "li", "div", "p", "td", "dt", "dd"]):
        text = container.get_text(" ", strip=True)
        # Allow longer text to capture full context (up to 1000 chars instead of filtering out 500+)
        if len(text) < 5 or len(text) > 1000 or _is_noisy_container(container, text):
            continue
        if not ASSIGNMENT_RE.search(text):
            continue

        base_date = _parse_date(text, default_year)
        if base_date is None:
            continue

        # Try to parse multiple assignments from the same text block
        assignments = _parse_multiple_assignments(text, base_date)

        for title, date_obj in assignments:
            title = title.strip()
            if not title or len(title) < 3:
                continue

            norm_key = _normalize_key(title)
            page_key = f"{date_obj.date()}|{norm_key}"
            if page_key in seen:
                continue
            seen.add(page_key)

            # Capture full description with all context
            description = _extract_description(text, title)
            events.append(RawEvent(
                title=title,
                date=date_obj.date().isoformat(),
                time=date_obj.strftime("%H:%M") if (date_obj.hour or date_obj.minute) else None,
                description=description,
                source_url=source_url,
                norm_key=norm_key,
            ))

    return events


# ────────────────────────────────────────────────────────────────────────────
# Strategy 6 — Calendar grid
# Month heading above a table; day number + event inside each <td>.
# Also handles split-cell rows (day in one <td>, event in adjacent <td>).
# ────────────────────────────────────────────────────────────────────────────

def _extract_calendar_grid(html: str, source_url: str, default_year: int | None = None) -> list[RawEvent]:
    soup = BeautifulSoup(html, "html.parser")
    events: list[RawEvent] = []
    seen: set[str] = set()

    current_month: int | None = None
    current_year: int = _default_year(default_year)

    for elem in soup.descendants:
        if not hasattr(elem, "name") or elem.name is None:
            continue
        text = elem.get_text(" ", strip=True)
        if not text:
            continue

        # Detect month/year heading
        if len(text) < 60 and elem.name in ("h1","h2","h3","h4","caption","th","b","strong","span","div"):
            m = MONTH_YEAR_RE.search(text)
            if m:
                key = m.group(1).lower()[:3]
                if key in MONTH_MAP:
                    current_month = MONTH_MAP[key]
                    current_year  = int(m.group(2))
                    continue
            m2 = MONTH_ONLY_RE.match(text.strip())
            if m2:
                key = m2.group(1).lower()[:3]
                if key in MONTH_MAP:
                    current_month = MONTH_MAP[key]
                    continue

        # Split-cell row: day number in one <td>, event in adjacent <td>
        if elem.name == "tr" and current_month is not None:
            cells = [
                td for td in elem.find_all("td", recursive=False)
                if not DATE_ID_RE.match(td.get("id", ""))
            ]
            if len(cells) >= 2:
                day = None
                for cell in cells:
                    raw = cell.get_text(" ", strip=True)
                    if re.fullmatch(r"\d{1,2}", raw):
                        d = int(raw)
                        if 1 <= d <= 31:
                            day = d
                            break
                if day is not None:
                    try:
                        base_dt = datetime(current_year, current_month, day)
                    except ValueError:
                        base_dt = None
                    if base_dt is not None:
                        for cell in cells:
                            ctext = cell.get_text(" ", strip=True)
                            if len(ctext) < 3 or len(ctext) > 400:
                                continue
                            if not ASSIGNMENT_RE.search(ctext):
                                continue
                            cell_dt = _dt_with_time(base_dt, ctext)
                            title    = _extract_title(ctext)
                            norm_key = _normalize_key(title)
                            key      = f"{cell_dt.date()}|{norm_key}"
                            if key not in seen:
                                seen.add(key)
                                events.append(RawEvent(
                                    title=title,
                                    date=cell_dt.date().isoformat(),
                                    time=cell_dt.strftime("%H:%M") if (cell_dt.hour or cell_dt.minute) else None,
                                    description=_extract_description(ctext, title),
                                    source_url=source_url,
                                    norm_key=norm_key,
                                ))

        # Single <td> with day number at start and assignment keyword
        if elem.name != "td":
            continue
        if DATE_ID_RE.match(elem.get("id", "")):
            continue
        if current_month is None:
            continue
        if len(text) < 3 or len(text) > 400:
            continue
        if not ASSIGNMENT_RE.search(text):
            continue

        day_m = DAY_START_RE.match(text)
        if not day_m:
            continue
        day = int(day_m.group(1))
        if not 1 <= day <= 31:
            continue

        try:
            dt = datetime(current_year, current_month, day)
        except ValueError:
            continue

        dt = _dt_with_time(dt, text)
        title    = _extract_title(text)
        norm_key = _normalize_key(title)
        key      = f"{dt.date()}|{norm_key}"
        if key in seen:
            continue
        seen.add(key)

        events.append(RawEvent(
            title=title,
            date=dt.date().isoformat(),
            time=dt.strftime("%H:%M") if (dt.hour or dt.minute) else None,
            description=_extract_description(text, title),
            source_url=source_url,
            norm_key=norm_key,
        ))

    return events


# ────────────────────────────────────────────────────────────────────────────
# Strategy 7 — Date-id TD cells  (<td id='YYYY-MM-DD'> with aria-label divs)
# ────────────────────────────────────────────────────────────────────────────

def _extract_by_date_id(html: str, source_url: str) -> list[RawEvent]:
    soup = BeautifulSoup(html, "html.parser")
    events: list[RawEvent] = []
    seen: set[str] = set()

    for td in soup.find_all("td", id=DATE_ID_RE):
        date_str: str = td["id"]
        try:
            dt = datetime.fromisoformat(date_str)
        except ValueError:
            continue

        for inner in td.find_all(["div", "li", "p"]):
            classes = set(inner.get("class") or [])
            aria    = (inner.get("aria-label") or "").lower().strip()

            if classes & _SKIP_DIV_CLASSES or aria in _SKIP_DIV_CLASSES:
                continue

            text = inner.get_text(" ", strip=True)
            if not text or len(text) > 300:
                continue

            is_event = (
                bool(classes & _COURSE_EVENT_TYPES)
                or (aria in _COURSE_EVENT_TYPES)
                or bool(ASSIGNMENT_RE.search(text))
            )
            if not is_event:
                continue

            inner_dt = _dt_with_time(dt, text)
            title    = _extract_title(text)
            if not title:
                continue
            norm_key = _normalize_key(title)
            key      = f"{date_str}|{norm_key}"
            if key in seen:
                continue
            seen.add(key)

            events.append(RawEvent(
                title=title,
                date=date_str,
                time=inner_dt.strftime("%H:%M") if (inner_dt.hour or inner_dt.minute) else None,
                description=_extract_description(text, title),
                source_url=source_url,
                norm_key=norm_key,
            ))

    return events


# ────────────────────────────────────────────────────────────────────────────
# Strategy 8 — Generic table rows with date/header inference
# ────────────────────────────────────────────────────────────────────────────

def _extract_table_rows(html: str, source_url: str, default_year: int | None = None) -> list[RawEvent]:
    soup = _clean_soup(html)
    events: list[RawEvent] = []
    seen: set[str] = set()

    for table in soup.find_all("table"):
        headers = [
            cell.get_text(" ", strip=True).lower()
            for cell in table.find_all("th")
        ]
        date_col: int | None = None
        if headers:
            for idx, header in enumerate(headers):
                if re.search(r"\b(date|day|week|due)\b", header):
                    date_col = idx
                    break

        for tr in table.find_all("tr"):
            cells = [cell.get_text(" ", strip=True) for cell in tr.find_all(["td", "th"], recursive=False)]
            if len(cells) < 2:
                continue
            row_text = " ".join(c for c in cells if c)
            if len(row_text) < 5 or _is_noisy_container(tr, row_text):
                continue
            if not (ASSIGNMENT_RE.search(row_text) or re.search(r"\b(due|deadline|exam|quiz)\b", row_text, re.IGNORECASE)):
                continue

            dt: datetime | None = None
            date_idx: int | None = None
            search_order = (
                ([date_col] if date_col is not None and date_col < len(cells) else [])
                + [idx for idx in range(len(cells)) if idx != date_col]
            )
            for idx in search_order:
                parsed = _parse_date(cells[idx], default_year)
                if parsed:
                    dt = _dt_with_time(parsed, row_text)
                    date_idx = idx
                    break
            if dt is None:
                dt = _parse_date(row_text, default_year)
                if dt:
                    dt = _dt_with_time(dt, row_text)
            if dt is None:
                continue

            title_cells = [cell for idx, cell in enumerate(cells) if idx != date_idx and cell]
            title_source = " - ".join(title_cells[:2]) if title_cells else row_text
            title = _extract_title(title_source if ASSIGNMENT_RE.search(title_source) else row_text)
            _append_raw_event(events, seen, title=title, dt=dt, text=row_text, source_url=source_url)

    return events


# ────────────────────────────────────────────────────────────────────────────
# Strategy 9 — Heading context, week ranges, and sibling list items
# ────────────────────────────────────────────────────────────────────────────

def _heading_level(tag_name: str) -> int:
    return int(tag_name[1]) if tag_name and re.fullmatch(r"h[1-6]", tag_name) else 7


def _extract_heading_context(html: str, source_url: str, default_year: int | None = None) -> list[RawEvent]:
    soup = _clean_soup(html)
    events: list[RawEvent] = []
    seen: set[str] = set()

    for heading in soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6"]):
        heading_text = heading.get_text(" ", strip=True)
        if not heading_text:
            continue
        heading_date = _parse_date(heading_text, default_year)
        heading_range = _parse_date_range(heading_text, default_year)
        if not heading_date and not heading_range:
            continue

        level = _heading_level(heading.name)
        sibling = heading.find_next_sibling()
        scanned = 0
        while sibling is not None and scanned < 40:
            if sibling.name and re.fullmatch(r"h[1-6]", sibling.name) and _heading_level(sibling.name) <= level:
                break

            candidates = sibling.find_all(["li", "p", "td", "div"], recursive=True) if hasattr(sibling, "find_all") else []
            if getattr(sibling, "name", None) in {"li", "p", "td", "div"}:
                candidates = [sibling] + candidates

            for node in candidates:
                if node.find_parent("table"):
                    continue
                text = node.get_text(" ", strip=True)
                if len(text) < 4 or _is_noisy_container(node, text):
                    continue
                if not ASSIGNMENT_RE.search(text):
                    continue

                dt = _parse_date(text, default_year)
                if dt is None and heading_range:
                    dt = _weekday_date_in_range(text, heading_range[0], heading_range[1])
                if dt is None:
                    dt = heading_date
                if dt is None:
                    continue
                dt = _dt_with_time(dt, text)

                title = _extract_title(text)
                _append_raw_event(events, seen, title=title, dt=dt, text=text, source_url=source_url)

            scanned += 1
            sibling = sibling.find_next_sibling()

    return events


# ────────────────────────────────────────────────────────────────────────────
# Strategy 10 — Structured data embedded in JavaScript/JSON script tags
# ────────────────────────────────────────────────────────────────────────────

def _iter_json_values(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _iter_json_values(child)
    elif isinstance(value, list):
        for child in value:
            yield from _iter_json_values(child)


def _extract_structured_data(html: str, source_url: str, default_year: int | None = None) -> list[RawEvent]:
    soup = BeautifulSoup(html, "html.parser")
    events: list[RawEvent] = []
    seen: set[str] = set()

    for script in soup.find_all("script"):
        script_type = (script.get("type") or "").lower()
        script_id = (script.get("id") or "").lower()
        if script_type not in {"application/ld+json", "application/json"} and script_id not in {"__next_data__"}:
            continue

        raw = script.string or script.get_text()
        if not raw or len(raw) > 1_000_000:
            continue
        try:
            data = json.loads(raw)
        except Exception:
            continue

        for item in _iter_json_values(data):
            title = (
                item.get("title")
                or item.get("name")
                or item.get("summary")
                or item.get("label")
            )
            date_value = (
                item.get("startDate")
                or item.get("start")
                or item.get("dueDate")
                or item.get("due_date")
                or item.get("dueAt")
                or item.get("due_at")
                or item.get("date")
            )
            description = item.get("description") or item.get("body") or ""
            if not isinstance(title, str):
                continue
            if isinstance(description, dict):
                description = json.dumps(description)
            if not isinstance(description, str):
                description = ""

            combined = f"{title} {date_value or ''} {description}"
            if not (ASSIGNMENT_RE.search(combined) or item.get("@type") == "Event"):
                continue

            dt = None
            if isinstance(date_value, str):
                dt = _parse_date(date_value, default_year) or _parse_date_text(date_value, default_year)
                if dt:
                    dt = _dt_with_time(dt, date_value)
            if dt is None:
                dt = _parse_date(combined, default_year)
            if dt is None:
                continue
            dt = _dt_with_time(dt, combined)

            _append_raw_event(events, seen, title=_extract_title(title), dt=dt, text=combined, source_url=source_url)

    return events


# ────────────────────────────────────────────────────────────────────────────
# Combined extraction — classifier routes, then all strategies deduplicate
# ────────────────────────────────────────────────────────────────────────────

def _extract_all(html: str, source_url: str, default_year: int | None = None) -> list[RawEvent]:
    page_type = _classify_page(html)

    # Format-specific strategies first (higher precision)
    specific: list[RawEvent] = []
    if page_type == "monthtable":
        specific = _extract_monthtable(html, source_url)
    elif page_type == "schedule_cards":
        specific = _extract_schedule_cards(html, source_url, default_year)
    elif page_type == "day_divs":
        specific = _extract_day_divs(html, source_url, default_year)

    # General strategies always run (fill gaps / non-standard pages)
    general = (
        _extract_events(html, source_url, default_year)
        + _extract_calendar_grid(html, source_url, default_year)
        + _extract_by_date_id(html, source_url)
        + _extract_table_rows(html, source_url, default_year)
        + _extract_heading_context(html, source_url, default_year)
        + _extract_structured_data(html, source_url, default_year)
    )

    seen: set[str] = set()
    combined: list[RawEvent] = []
    for ev in specific + general:
        key = f"{ev.date}|{ev.norm_key}"
        if key not in seen:
            seen.add(key)
            combined.append(ev)

    return combined


def _score_page(events: list[RawEvent]) -> int:
    return sum(8 + sum(_event_rank(e)[:2]) for e in events)


# ────────────────────────────────────────────────────────────────────────────
# Merge page buckets into final event list
# ────────────────────────────────────────────────────────────────────────────

def _build_course_event(group: list[RawEvent]) -> CourseEvent:
    best = max(group, key=_event_rank)
    best_kind = _event_kind(f"{best.title} {best.description or ''}")
    same_kind_date = [
        e for e in group
        if e.date == best.date and _event_kind(f"{e.title} {e.description or ''}") == best_kind
    ]
    title_candidates = same_kind_date or [e for e in group if e.date == best.date] or group
    title = max((e.title for e in title_candidates), key=len)

    # Collect all unique descriptions and context
    seen_desc: set[str] = set()
    desc_parts: list[str] = []
    for e in sorted(group, key=_event_rank, reverse=True):
        if e.description and e.description not in seen_desc:
            seen_desc.add(e.description)
            desc_parts.append(e.description)

    # Collect all source URLs
    seen_urls: set[str] = set()
    source_urls: list[str] = []
    for e in sorted(group, key=_event_rank, reverse=True):
        if e.source_url not in seen_urls:
            seen_urls.add(e.source_url)
            source_urls.append(e.source_url)

    # Determine event type
    event_type = _event_kind(f"{title} {' | '.join(desc_parts)}")

    return CourseEvent(
        title=title,
        date=best.date,
        time=best.time,
        end_time=None,  # Could be enhanced to extract from description
        description=" | ".join(desc_parts) if desc_parts else None,
        full_text=title + (" — " + " | ".join(desc_parts) if desc_parts else ""),
        event_type=event_type,
        source_urls=source_urls,
    )


def _merge_all(page_buckets: dict[str, list[RawEvent]], warnings: list[str] | None = None) -> list[CourseEvent]:
    groups: dict[str, list[RawEvent]] = {}
    for events in page_buckets.values():
        for ev in events:
            groups.setdefault(ev.norm_key, []).append(ev)

    merged: list[CourseEvent] = []
    for norm_key, group in groups.items():
        dates = {e.date for e in group}
        if len(dates) > 1:
            priority = [
                e for e in group
                if _event_kind(f"{e.title} {e.description or ''}") in {"deadline", "exam"}
            ]
            if priority:
                if warnings is not None:
                    warnings.append(
                        f"Resolved conflicting dates for '{norm_key}' by preferring explicit deadline/exam entries."
                    )
                group = priority
            else:
                by_date: dict[str, list[RawEvent]] = {}
                for e in group:
                    by_date.setdefault(e.date, []).append(e)
                if len(by_date) <= 4:
                    if warnings is not None:
                        warnings.append(
                            f"Kept separate entries for '{norm_key}' because matching pages used different dates."
                        )
                    for date_group in by_date.values():
                        merged.append(_build_course_event(date_group))
                    continue

        merged.append(_build_course_event(group))

    return sorted(merged, key=lambda e: e.date)


def _dedupe_warnings(warnings: list[str]) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for warning in warnings:
        if warning and warning not in seen:
            seen.add(warning)
            unique.append(warning)
    return unique


# ────────────────────────────────────────────────────────────────────────────
# Endpoint
# ────────────────────────────────────────────────────────────────────────────

@router.post("/", response_model=CourseImportResult)
async def import_course(course_url: str) -> CourseImportResult:
    warnings: list[str] = []
    main_fetch = _fetch_page(course_url)
    if main_fetch.warning:
        warnings.append(main_fetch.warning)
    main_html = main_fetch.html
    if main_html is None:
        detail = main_fetch.warning or f"Could not fetch {course_url}"
        if any(term in course_url.lower() for term in {"canvas", "gradescope"}):
            detail = f"{detail} Use the Canvas or iCal integration for authenticated course systems."
        raise HTTPException(status_code=400, detail=detail)

    # Check if course appears to have public calendar/assignments
    if not _has_likely_public_calendar(main_html, course_url):
        warnings.append(
            "This course page may not have publicly accessible calendar or assignment information. "
            "Check if the course uses Canvas, Gradescope, or another auth-required system."
        )

    if relative_warning := _relative_date_warning(main_html):
        warnings.append(relative_warning)

    default_year = _infer_default_year(course_url, main_html)

    # ── Priority 0: iCal subscription files (most accurate) ────────────────
    # UW CSE createcal courses expose .ics feeds at /calendar/subscribe.html.
    # These have exact DTSTART/DTEND and an event-type label per entry.
    is_direct_ical = (
        course_url.lower().endswith((".ics", ".ical"))
        or "text/calendar" in (main_fetch.content_type or "")
    )
    if is_direct_ical:
        direct_ical_events = _parse_ical_bytes(main_html.encode("utf-8"), course_url)
        if direct_ical_events:
            merged = _merge_all({course_url: direct_ical_events}, warnings)
            score = _score_page(direct_ical_events)
            return CourseImportResult(
                course_url=course_url,
                best_source=course_url,
                events=merged,
                page_reports=[PageReport(url=course_url, events_found=len(direct_ical_events),
                                         score=score, is_best=True)],
                warnings=_dedupe_warnings(warnings),
            )

    ical_result = _try_ical_sources(course_url, main_html)
    if ical_result:
        ical_source, ical_events = ical_result
        merged  = _merge_all({ical_source: ical_events}, warnings)
        score   = _score_page(ical_events)
        return CourseImportResult(
            course_url=course_url,
            best_source=ical_source,
            events=merged,
            page_reports=[PageReport(url=ical_source, events_found=len(ical_events),
                                     score=score, is_best=True)],
            warnings=_dedupe_warnings(warnings),
        )

    # ── Priority 1: FullCalendar events_source.json ─────────────────────────
    json_events = _parse_events_source(course_url)
    if json_events:
        json_url = course_url.rstrip("/") + "/events_source.json"
        merged   = _merge_all({json_url: json_events}, warnings)
        score    = _score_page(json_events)
        return CourseImportResult(
            course_url=course_url,
            best_source=json_url,
            events=merged,
            page_reports=[PageReport(url=json_url, events_found=len(json_events),
                                     score=score, is_best=True)],
            warnings=_dedupe_warnings(warnings),
        )

    # ── Priority 2+: HTML crawl + candidate paths ───────────────────────────
    # Build link list: discovered HTML links + known UW CSE sub-paths that are
    # often NOT linked in the main HTML (calendar pages loaded via JS nav).
    all_links  = [course_url] + _all_internal_links(main_html, course_url)
    seen_links = {_canonical_url(url) for url in all_links}

    # Use course-aware candidate paths based on course type
    course_type = _get_course_type(course_url)
    candidate_paths = _prioritize_candidate_paths(course_url, course_type)
    for candidate in candidate_paths:
        canonical = _canonical_url(candidate)
        if canonical not in seen_links:
            all_links.append(candidate)
            seen_links.add(canonical)

    page_buckets: dict[str, list[RawEvent]] = {}
    for idx, url in enumerate(all_links[:MAX_CRAWL_PAGES + len(_CALENDAR_CANDIDATES) + 1]):
        if _canonical_url(url) == _canonical_url(course_url):
            html = main_html
        else:
            if idx > 0:
                sleep(REQUEST_DELAY_SECONDS)
            fetched = _fetch_page(url)
            if fetched.warning and fetched.status_code != 404:
                warnings.append(f"{url}: {fetched.warning}")
            html = fetched.html
        if html is None:
            continue
        if url != course_url:
            if relative_warning := _relative_date_warning(html):
                warnings.append(relative_warning)
        evs = _extract_all(html, url, default_year)
        if evs:
            page_buckets[url] = evs

    if not page_buckets:
        return CourseImportResult(
            course_url=course_url,
            best_source=None,
            events=[],
            page_reports=[],
            warnings=_dedupe_warnings(warnings),
        )

    scored = sorted(
        [(url, _score_page(evs)) for url, evs in page_buckets.items()],
        key=lambda x: -x[1],
    )
    best_url, best_score = scored[0]
    merged_events = _merge_all(page_buckets, warnings)

    reports = [
        PageReport(
            url=url,
            events_found=len(page_buckets[url]),
            score=sc,
            is_best=(url == best_url and best_score > 0),
        )
        for url, sc in scored
    ]

    return CourseImportResult(
        course_url=course_url,
        best_source=best_url if best_score > 0 else None,
        events=merged_events,
        page_reports=reports,
        warnings=_dedupe_warnings(warnings),
    )


# ────────────────────────────────────────────────────────────────────────────
# NEW: AI-Enhanced Parsing Endpoints (Hybrid Regex + ChatGPT)
# ────────────────────────────────────────────────────────────────────────────


class AIParsingRequest(BaseModel):
    """Request for AI-enhanced assignment parsing (ChatGPT)."""
    raw_text: str
    course_name: str = "Unknown Course"
    confidence_threshold: float = 0.75  # Threshold for using ChatGPT vs regex only


class AIParsingResponse(BaseModel):
    """Response from AI-enhanced parsing."""
    method: str  # "regex_only" or "hybrid"
    confidence: float
    assignments: list[dict]
    class_events: list[dict]
    tokens_used: int
    processing_time_ms: int
    warnings: list[str] = Field(default_factory=list)


@router.post("/parse-text", response_model=AIParsingResponse)
async def parse_course_text(
    request: AIParsingRequest,
) -> AIParsingResponse:
    """
    Parse raw course website text using hybrid approach (Regex + ChatGPT).

    - Simple assignments (80% of cases): Uses fast regex only (free, instant)
    - Complex assignments (20% of cases): Uses ChatGPT for accuracy

    Args:
        request: AIParsingRequest containing raw_text and course_name

    Returns:
        AIParsingResponse with structured assignments and class events

    Example:
        POST /api/v1/course-import/parse-text
        {
            "raw_text": "HW1 due Friday 4/10...",
            "course_name": "CSE 331"
        }
    """
    warnings: list[str] = []

    if not request.raw_text or len(request.raw_text.strip()) == 0:
        raise HTTPException(status_code=400, detail="raw_text cannot be empty")

    try:
        result: ParsingResult = await parse_with_hybrid_approach(
            text=request.raw_text,
            course_name=request.course_name,
            ai_threshold=request.confidence_threshold,
            use_cache=True,
        )

        return AIParsingResponse(
            method=result.method,
            confidence=result.confidence,
            assignments=result.assignments,
            class_events=result.class_events,
            tokens_used=result.tokens_used,
            processing_time_ms=result.processing_time_ms,
            warnings=warnings,
        )
    except Exception as e:
        warnings.append(f"Parsing error: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to parse course text: {str(e)}"
        )


@router.post("/parse-url-enhanced")
async def parse_course_url_enhanced(
    course_url: str = Query(..., description="Course website URL"),
) -> dict:
    """
    Scrape course URL and enhance parsing with hybrid regex+ChatGPT approach.

    Combines the existing scraper with AI-enhanced parsing for better accuracy.

    Args:
        course_url: URL of course website

    Returns:
        CourseImportResult with enhanced AI parsing

    Example:
        POST /api/v1/course-import/parse-url-enhanced?course_url=https://courses.cs.washington.edu/courses/cse331
    """
    warnings: list[str] = []

    # First, use the existing scraper to get raw text
    main_fetch = _fetch_page(course_url)
    if main_fetch.warning:
        warnings.append(main_fetch.warning)

    main_html = main_fetch.html
    if main_html is None:
        raise HTTPException(
            status_code=400,
            detail=f"Could not fetch {course_url}"
        )

    # Extract plain text from HTML for AI parsing
    soup = BeautifulSoup(main_html, "html.parser")
    raw_text = soup.get_text(separator="\n", strip=True)

    if not raw_text or len(raw_text.strip()) < 50:
        raise HTTPException(
            status_code=400,
            detail="Course page contains no extractable text"
        )

    # Extract course name from URL
    course_code = _extract_course_code(course_url)
    course_name = course_code or "Course"

    try:
        # Parse with hybrid approach (ChatGPT only)
        result: ParsingResult = await parse_with_hybrid_approach(
            text=raw_text,
            course_name=course_name,
            use_cache=True,
        )

        # Convert assignments to CourseEvent format
        events: list[CourseEvent] = []
        for assignment in result.assignments:
            event = CourseEvent(
                title=assignment.get("assignment_name", "Unknown"),
                date=assignment.get("due_date", ""),
                time=assignment.get("due_time"),
                description=assignment.get("description", ""),
                event_type=assignment.get("assignment_type", "assignment"),
                source_urls=[course_url],
            )
            events.append(event)

        for event in result.class_events:
            course_event = CourseEvent(
                title=event.get("event_name", "Class Event"),
                date=event.get("date", ""),
                time=event.get("start_time"),
                end_time=event.get("end_time"),
                description=event.get("description", ""),
                event_type=event.get("event_type", "lecture"),
                source_urls=[course_url],
            )
            events.append(course_event)

        return {
            "course_url": course_url,
            "parsing_method": result.method,
            "confidence": result.confidence,
            "events": [e.model_dump() for e in events],
            "tokens_used": result.tokens_used,
            "processing_time_ms": result.processing_time_ms,
            "warnings": warnings,
        }

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to parse course: {str(e)}"
        )


@router.get("/cost-estimate")
async def estimate_costs(
    num_courses: int = Query(100, description="Number of courses to estimate"),
) -> dict:
    """
    Estimate costs for hybrid parsing with ChatGPT.

    Shows savings using:
    - Regex only (80% of simple courses) - FREE
    - ChatGPT (20% of complex courses) - $0.003 per call

    Args:
        num_courses: Number of courses to parse

    Returns:
        Cost breakdown and savings estimate

    Example:
        GET /api/v1/course-import/cost-estimate?num_courses=100
    """
    if num_courses < 1 or num_courses > 10000:
        raise HTTPException(
            status_code=400,
            detail="num_courses must be between 1 and 10000"
        )

    regex_ratio = 0.80
    ai_ratio = 1 - regex_ratio
    cost_per_call = 0.003

    ai_calls = int(num_courses * ai_ratio)
    total_cost = ai_calls * cost_per_call

    return {
        "num_courses": num_courses,
        "regex_only_courses": int(num_courses * regex_ratio),
        "ai_courses": ai_calls,
        "total_api_calls": ai_calls,
        "cost_per_call": f"${cost_per_call}",
        "total_cost": f"${total_cost:.2f}",
        "cost_per_import": f"${total_cost / num_courses:.4f}",
        "savings_vs_all_ai": f"${(num_courses * cost_per_call) - total_cost:.2f}",
        "savings_percentage": "80%",
    }

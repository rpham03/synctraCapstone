"""Simplified course import using Ollama AI and unified format."""
import asyncio
import httpx
import json
import re
from datetime import date, datetime, timedelta
from urllib.parse import urldefrag, urljoin, urlparse
from bs4 import BeautifulSoup, NavigableString, Tag
from fastapi import APIRouter, HTTPException
from icalendar import Calendar
from pydantic import BaseModel

from app.api.v1.routes.events import (
    _CALENDAR_CANDIDATES,
    _html_fallback,
    _has_monthtable,
    _parse_events_source_json,
    _parse_monthtable,
)
from app.api.v1.routes.unified_course_format import (
    UnifiedAssignment,
    UnifiedClassEvent,
    deduplicate_assignments,
    deduplicate_class_events,
)
from app.core.config.settings import settings
from app.services.assignment_estimate import (
    ESTIMATE_AI_GUIDANCE,
    coerce_estimated_minutes,
    estimate_assignment_minutes,
    infer_assignment_type,
    round_estimate_minutes as _round_minutes,
)

router = APIRouter(tags=["course-import"])

ASSIGNMENT_DUE_RE = re.compile(r"\b(?:due|deadline)\b", re.IGNORECASE)
CALENDAR_LINK_RE = re.compile(r"\b(?:calendar|schedule)\b", re.IGNORECASE)
ASSIGNMENT_LINK_RE = re.compile(r"\b(?:assignments?|homework|hw)\b", re.IGNORECASE)
COURSE_DETAIL_LINK_RE = re.compile(
    r"\b(?:calendar|schedule|syllabus|assignments?|homework|hw|projects?|"
    r"lectures?|sections?|discussion|labs?|exams?|deadlines?|readings?|office\s*hours?)\b",
    re.IGNORECASE,
)
LOW_VALUE_LINK_RE = re.compile(
    r"\b(?:subscribe|rss|atom|mailto|login|privacy|policy|staff|people|contact)\b",
    re.IGNORECASE,
)
PLACEHOLDER_TITLE_RE = re.compile(
    r"(?:^|[\s:—–-]+)(?:tbd|tba|to\s+be\s+(?:determined|announced)|unknown|n/?a)(?:$|[\s:—–-]+)",
    re.IGNORECASE,
)
TABLE_DATE_RE = re.compile(r"\b(0?[1-9]|1[0-2])/(0?[1-9]|[12]\d|3[01])/(\d{2}|\d{4})\b")
MONTH_DAY_RE = re.compile(
    r"\b(?:mon(?:day)?|tue(?:s(?:day)?)?|wed(?:nesday)?|thu(?:rs(?:day)?)?|"
    r"fri(?:day)?|sat(?:urday)?|sun(?:day)?)?\.?,?\s*"
    r"(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|"
    r"jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
    r"\.?\s+(\d{1,2})(?:st|nd|rd|th)?(?:,?\s*(\d{2}|\d{4})(?!:))?\b",
    re.IGNORECASE,
)
NUMERIC_MONTH_DAY_RE = re.compile(
    r"\b(?:mon(?:day)?|tue(?:s(?:day)?)?|wed(?:nesday)?|thu(?:rs(?:day)?)?|"
    r"fri(?:day)?|sat(?:urday)?|sun(?:day)?)?\.?,?\s*\(?"
    r"(0?[1-9]|1[0-2])/(0?[1-9]|[12]\d|3[01])(?:/(\d{2}|\d{4}))?\)?\b",
    re.IGNORECASE,
)
DUE_PHRASE_RE = re.compile(r"\b(?:due|deadline)\b[^)]*", re.IGNORECASE)
DUE_OR_INITIAL_SUBMISSION_RE = re.compile(
    r"\b(?:due|deadline)\b|\bI\.?\s*S\.?(?:\s+by)?\b",
    re.IGNORECASE,
)
DUE_TIME_RE = re.compile(r"\b(\d{1,2})(?::(\d{2}))?\s*(a\.?m\.?|p\.?m\.?)\b", re.IGNORECASE)
DEFAULT_DUE_TIME_RE = re.compile(
    r"\bdue\s+(?:at|by)\s+(\d{1,2})(?::(\d{2}))?\s*(a\.?m\.?|p\.?m\.?)\b",
    re.IGNORECASE,
)
TIME_RANGE_RE = re.compile(
    r"\b(?P<start>\d{1,2}(?::\d{2})?)\s*(?P<start_ampm>a\.?m\.?|p\.?m\.?)?\s*"
    r"(?:-|–|—|to)\s*"
    r"(?P<end>\d{1,2}(?::\d{2})?)\s*(?P<end_ampm>a\.?m\.?|p\.?m\.?)?\b",
    re.IGNORECASE,
)
INLINE_DUE_ASSIGNMENT_RE = re.compile(
    r"\b(?P<title>(?:Homework|HW|Pset|Assignment\s+\d+|Project|Lab|A\d+|P\d+|C\d+|R\d+)"
    r"[^.;]{0,140}?)\s*(?:\(|,)?\s*\bdue\b:?\s*"
    r"(?P<due>.*?)(?=[.;)]|\b(?:Homework|HW|Pset|Assignment\s+\d+|Project|Lab|A\d+|P\d+|C\d+|R\d+)\b|$)",
    re.IGNORECASE,
)
ASSIGNMENT_LIKE_RE = re.compile(
    r"\b(?:assignment|homework|hw\d*|pset|problem\s*set|project|lab\d*|quiz|exam|"
    r"reflection|resub|artifact|survey|c\d+|p\d+|r\d+|wa\d+|tha\d+)\b",
    re.IGNORECASE,
)
MONTHS = {
    "jan": 1,
    "january": 1,
    "feb": 2,
    "february": 2,
    "mar": 3,
    "march": 3,
    "apr": 4,
    "april": 4,
    "may": 5,
    "jun": 6,
    "june": 6,
    "jul": 7,
    "july": 7,
    "aug": 8,
    "august": 8,
    "sep": 9,
    "september": 9,
    "oct": 10,
    "october": 10,
    "nov": 11,
    "november": 11,
    "dec": 12,
    "december": 12,
}
ASSIGNMENT_PAGE_CANDIDATES = [
    "assignments/index.html",
    "assignments/",
    "homework/index.html",
    "homework/",
    "hw/index.html",
    "hw/",
    "exercises/index.html",
    "exercises/",
    "labs/index.html",
    "labs/",
    "projects/index.html",
    "projects/",
    "psets/",
    "psets/index.html",
]
MAX_RELATED_PAGES = 10
COURSE_REQUEST_HEADERS = {
    "ngrok-skip-browser-warning": "true",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) SyntraCourseImport/1.0"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}
COURSE_FETCH_TIMEOUT = httpx.Timeout(45.0, connect=15.0)
RELATED_PAGE_FETCH_DELAY_S = 0.25
COURSE_FETCH_RETRY_DELAY_S = 1.5
OLLAMA_COURSE_IMPORT_TIMEOUT_S = 120
UW_COURSE_ROOT_RE = re.compile(
    r"^(https://courses\.cs\.washington\.edu/courses/cse\d{3,4})/?$",
    re.IGNORECASE,
)
UW_QUARTER_PATH_RE = re.compile(r"/\d{2}(?:wi|sp|su|au|fa)/?$", re.IGNORECASE)


class CourseImportResponse(BaseModel):
    """Response from course import."""
    course_url: str
    course_name: str
    assignments_imported: int
    class_events_imported: int
    total_imported: int
    warnings: list[str] = []
    class_events: list[dict] = []  # UnifiedClassEvent as dict
    assignments: list[dict] = []   # UnifiedAssignment as dict


def infer_current_uw_quarter(now: datetime | None = None) -> str:
    """Return UW-style current quarter fragments such as 26sp."""
    now = now or datetime.now()
    if now.month <= 3:
        quarter = "wi"
    elif now.month <= 6:
        quarter = "sp"
    elif now.month <= 8:
        quarter = "su"
    else:
        quarter = "au"
    return f"{now.year % 100:02d}{quarter}"


def normalize_course_url(course_url: str, now: datetime | None = None) -> str:
    """Turn a UW course root URL into a specific current-quarter course URL."""
    course_url = course_url.strip()
    if UW_QUARTER_PATH_RE.search(urlparse(course_url).path):
        return course_url

    match = UW_COURSE_ROOT_RE.match(course_url.rstrip("/"))
    if not match:
        return course_url

    return f"{match.group(1)}/{infer_current_uw_quarter(now)}/"


def extract_json_object(response_text: str) -> str | None:
    """Extract the first balanced JSON object from an LLM response."""
    text = response_text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)

    start = text.find("{")
    if start == -1:
        return None

    depth = 0
    in_string = False
    escaped = False

    for index in range(start, len(text)):
        char = text[index]

        if escaped:
            escaped = False
            continue

        if char == "\\" and in_string:
            escaped = True
            continue

        if char == '"':
            in_string = not in_string
            continue

        if in_string:
            continue

        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start:index + 1]

    return text[start:]


def parse_ollama_json(response_text: str) -> dict:
    """Parse Ollama JSON and turn invalid model output into a controlled API error."""
    json_str = extract_json_object(response_text)
    if not json_str:
        raise HTTPException(status_code=502, detail="Ollama response did not contain a JSON object")

    try:
        parsed = json.loads(json_str)
    except json.JSONDecodeError as original_error:
        # LLMs commonly add trailing commas even when asked for strict JSON.
        repaired_json = re.sub(r",\s*([}\]])", r"\1", json_str)
        if repaired_json != json_str:
            try:
                parsed = json.loads(repaired_json)
            except json.JSONDecodeError:
                parsed = None
        else:
            parsed = None

        if parsed is None:
            start = max(original_error.pos - 120, 0)
            end = min(original_error.pos + 120, len(json_str))
            snippet = json_str[start:end].replace("\n", "\\n")
            raise HTTPException(
                status_code=502,
                detail=(
                    "Ollama returned invalid JSON "
                    f"at line {original_error.lineno}, column {original_error.colno}: "
                    f"{original_error.msg}. Snippet: {snippet}"
                ),
            )

    if not isinstance(parsed, dict):
        raise HTTPException(status_code=502, detail="Ollama JSON response must be an object")

    parsed.setdefault("class_events", [])
    parsed.setdefault("assignments", [])
    return parsed


def is_valid_iso_date(value: object) -> bool:
    """Return True when value is a real YYYY-MM-DD date."""
    if not isinstance(value, str):
        return False

    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        return False

    return True


def infer_event_type(title: str) -> str:
    """Infer a constrained event type from a calendar title."""
    lower_title = title.lower()
    if any(term in lower_title for term in ("exam", "midterm", "final")):
        return "exam"
    if "section" in lower_title:
        return "section"
    if "lab" in lower_title:
        return "lab"
    if "discussion" in lower_title:
        return "discussion"
    if "office hour" in lower_title:
        return "office_hours"
    return "lecture"


def clean_calendar_text(text: str) -> str:
    """Normalize whitespace in scraped calendar labels."""
    return re.sub(r"\s+", " ", text).strip()


_COURSE_CODE_RE = re.compile(r"\b([A-Z]{2,5})\s*[-_]?\s*(\d{3,4}[A-Z]?)\b", re.IGNORECASE)


def extract_course_code(course_name: str | None) -> str:
    """Return a short course code like 'CSE403' from a course name or URL fragment."""
    if not course_name:
        return ""
    match = _COURSE_CODE_RE.search(course_name)
    if match:
        return f"{match.group(1).upper()}{match.group(2).upper()}"
    cleaned = re.sub(r"[^A-Za-z0-9]", "", course_name)
    return cleaned.upper()[:10]


def clean_event_title(
    title: str,
    event_type: str = "lecture",
    course_name: str | None = None,
) -> str:
    """Remove placeholder fragments like TBD without losing event type.

    When a course_name is available, TBD-style placeholders are swapped for
    the course code so chips like "Lecture — TBD" become "Lecture — CSE403".
    """
    title = clean_calendar_text(title)
    course_code = extract_course_code(course_name)

    if course_code and PLACEHOLDER_TITLE_RE.search(title):
        title = PLACEHOLDER_TITLE_RE.sub(f" {course_code} ", title)
    else:
        title = PLACEHOLDER_TITLE_RE.sub(" ", title)

    title = re.sub(r"\s+[—–-]\s*$", "", title)
    title = re.sub(r"^[\s:—–-]+|[\s:—–-]+$", "", title)
    title = clean_calendar_text(title)
    if course_code:
        title = re.sub(rf"\s+{re.escape(course_code)}$", f" — {course_code}", title)
        title = re.sub(
            rf"(?:\s+[—–\-])+\s+{re.escape(course_code)}$",
            f" — {course_code}",
            title,
        )
    title = re.sub(r"(?:\s+[—–\-]){2,}\s+", " — ", title)
    generic_title = {
        "lecture",
        "section",
        "discussion",
        "lab",
        "office hours",
        "exam",
    }
    if course_code and title.lower() in generic_title:
        title = f"{title} — {course_code}"
    if title:
        return title

    fallback = {
        "office_hours": "Office Hours",
        "discussion": "Discussion",
    }.get(event_type, event_type.replace("_", " ").title())
    if course_code:
        return f"{fallback} — {course_code}"
    return fallback or "Class Event"


def clean_assignment_name(title: str) -> str:
    """Remove placeholder fragments from assignment labels."""
    title = clean_schedule_assignment_title(title)
    title = re.sub(
        r"^(?:(?:mon|tue|wed|thu|fri|sat|sun)(?:day)?\.?,?\s+)?"
        r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|"
        r"jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
        r"\.?\s+\d{1,2}(?:st|nd|rd|th)?(?:,?\s*\d{2,4})?\s+",
        "",
        title,
        count=1,
        flags=re.IGNORECASE,
    )
    title = re.sub(
        r"^(?:(?:mon|tue|wed|thu|fri|sat|sun)(?:day)?\.?,?\s+)?"
        r"\d{1,2}/\d{1,2}(?:/\d{2,4})?\s+",
        "",
        title,
        count=1,
        flags=re.IGNORECASE,
    )
    title = PLACEHOLDER_TITLE_RE.sub(" ", title)
    title = re.sub(r"^[\s:—–-]+|[\s:—–-]+$", "", title)
    return clean_calendar_text(title)


def infer_default_year(course_url: str) -> int:
    """Infer academic year from UW quarter fragments like 26sp."""
    match = re.search(r"/(\d{2})(?:wi|sp|su|au|fa)\b", course_url, re.IGNORECASE)
    if match:
        return 2000 + int(match.group(1))

    return datetime.now().year


def normalize_two_digit_year(year: int) -> int:
    """Convert two-digit course years into 2000-based years."""
    return year + 2000 if year < 100 else year


def parse_numeric_course_date(text: str) -> datetime | None:
    """Parse course schedule dates like 01/12/26 or 01/12/2026."""
    match = TABLE_DATE_RE.search(text)
    if not match:
        return None

    month, day, year = (int(part) for part in match.groups())
    year = normalize_two_digit_year(year)

    try:
        return datetime(year, month, day)
    except ValueError:
        return None


def parse_course_date(text: str, default_year: int) -> datetime | None:
    """Parse course dates with or without an explicit year."""
    if not text:
        return None

    numeric_with_year = parse_numeric_course_date(text)
    if numeric_with_year:
        return numeric_with_year

    numeric_match = NUMERIC_MONTH_DAY_RE.search(text)
    if numeric_match:
        month, day = int(numeric_match.group(1)), int(numeric_match.group(2))
        raw_year = numeric_match.group(3)
        year = normalize_two_digit_year(int(raw_year)) if raw_year else default_year
        try:
            return datetime(year, month, day)
        except ValueError:
            return None

    month_match = MONTH_DAY_RE.search(text)
    if month_match:
        month_name = month_match.group(1).lower().rstrip(".")
        month = MONTHS.get(month_name[:3], MONTHS.get(month_name))
        day = int(month_match.group(2))
        raw_year = month_match.group(3)
        year = normalize_two_digit_year(int(raw_year)) if raw_year else default_year
        if month:
            try:
                return datetime(year, month, day)
            except ValueError:
                return None

    return None


def parse_due_time(text: str) -> tuple[int, int] | None:
    """Parse due-time text such as 11:59pm into 24-hour clock values."""
    match = DUE_TIME_RE.search(text)
    if not match:
        return None

    hour = int(match.group(1))
    minute = int(match.group(2) or "0")
    meridiem = match.group(3).lower()

    if hour < 1 or hour > 12 or minute > 59:
        return None

    if meridiem.startswith("p") and hour != 12:
        hour += 12
    elif meridiem.startswith("a") and hour == 12:
        hour = 0

    return hour, minute


def _normalize_ampm(value: str | None) -> str | None:
    if not value:
        return None
    return "pm" if value.lower().startswith("p") else "am"


def _parse_clock_value(value: str, ampm: str | None) -> tuple[int, int] | None:
    try:
        if ":" in value:
            hour_text, minute_text = value.split(":", 1)
            hour = int(hour_text)
            minute = int(minute_text)
        else:
            hour = int(value)
            minute = 0
    except ValueError:
        return None

    if hour < 1 or hour > 23 or minute < 0 or minute > 59:
        return None
    if ampm:
        if hour > 12:
            return None
        if ampm == "pm" and hour != 12:
            hour += 12
        elif ampm == "am" and hour == 12:
            hour = 0
    return hour, minute


def parse_time_range(text: str) -> tuple[tuple[int, int], tuple[int, int]] | None:
    """Parse meeting ranges like '12:30 PM - 1:20 PM'."""
    match = TIME_RANGE_RE.search(text)
    if not match:
        return None

    start_ampm = _normalize_ampm(match.group("start_ampm"))
    end_ampm = _normalize_ampm(match.group("end_ampm"))
    if start_ampm is None and end_ampm is not None:
        start_hour_text = match.group("start").split(":", 1)[0]
        end_hour_text = match.group("end").split(":", 1)[0]
        try:
            start_hour = int(start_hour_text)
            end_hour = int(end_hour_text)
        except ValueError:
            return None
        start_ampm = "am" if end_ampm == "pm" and start_hour > end_hour else end_ampm

    start = _parse_clock_value(match.group("start"), start_ampm)
    end = _parse_clock_value(match.group("end"), end_ampm)
    if start is None or end is None:
        return None
    if start_ampm is None and end_ampm is None:
        start_hour, start_minute = start
        end_hour, end_minute = end
        if start_hour <= 7:
            start_hour += 12
        if end_hour <= 7:
            end_hour += 12
        if (end_hour, end_minute) <= (start_hour, start_minute):
            end_hour += 12
        start = (start_hour, start_minute)
        end = (end_hour, end_minute)
    return start, end


def find_default_due_time(soup) -> tuple[int, int] | None:
    """Find a page-level default due time such as 'due at 11pm'."""
    page_text = clean_calendar_text(soup.get_text(" ", strip=True))
    match = DEFAULT_DUE_TIME_RE.search(page_text)
    if not match:
        return None

    return parse_due_time(match.group(0))


def extract_due_datetime(
    due_text: str,
    context_date: datetime | None,
    default_year: int,
    default_due_time: tuple[int, int] | None = None,
) -> tuple[datetime, bool] | None:
    """Resolve a due date/time from a cell using row date as context."""
    due_date = parse_course_date(due_text, default_year)
    if due_date is None and (
        context_date is not None
        and (
            re.search(r"\btoday\b", due_text, re.IGNORECASE)
            or DUE_OR_INITIAL_SUBMISSION_RE.search(due_text)
            or parse_due_time(due_text)
        )
    ):
        due_date = context_date

    if due_date is None:
        return None

    due_time = parse_due_time(due_text) or default_due_time
    if due_time:
        hour, minute = due_time
        return due_date.replace(hour=hour, minute=minute), False

    return due_date, True


def clean_due_assignment_title(title: str) -> str:
    """Remove leftover punctuation around assignment titles from schedule cells."""
    title = re.sub(r"\s*\($", "", title)
    title = re.sub(r"\s*\([^)]*$", "", title)
    title = re.sub(r"^\W+", "", title)
    title = re.sub(r"\W+$", "", title)
    title = clean_calendar_text(title)

    # CSE 403 sometimes puts informational links before the real due item.
    if " posted in ed " in title.lower():
        title = re.split(r"\bposted in ed\b", title, flags=re.IGNORECASE)[-1]
        title = clean_calendar_text(title)

    return title


def clean_schedule_assignment_title(title: str) -> str:
    """Clean common schedule-table prefixes from an assignment title."""
    title = clean_calendar_text(title)
    title_matches = list(re.finditer(
        r"\b(?:Homework\s*\d+|HW\s*\d+|Pset\s*\d+|Assignment\s+\d+|Lab\s*\d+|"
        r"A\d+|P\d+|C\d+|R\d+|WA\d+|THA\d+)",
        title,
        flags=re.IGNORECASE,
    ))
    if title_matches:
        first_match = title_matches[0]
        last_match = title_matches[-1]
        if first_match.start() > 0:
            title = title[first_match.start():]
        elif len(title_matches) > 1 and re.search(
            r"\b(?:here|turn in|output comparison|tool)\b",
            title[:last_match.start()],
            re.IGNORECASE,
        ):
            title = title[last_match.start():]

    title = re.sub(r"\([^)]*\b[Dd]ue\b[^)]*\)", "", title)
    title = re.split(
        r"\b(?:due|deadline)\b|\bI\.?\s*S\.?(?:\s+by)?\b|\bby\s+\d{1,2}(?::\d{2})?\s*(?:a\.?m\.?|p\.?m\.?)",
        title,
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0]
    title = re.sub(r"^\s*(?:Released|Out|Assigned:|Assignment:)\s+", "", title, flags=re.IGNORECASE)
    title = re.sub(r"\s*\((?:pdf|html)\)\s*", " ", title, flags=re.IGNORECASE)
    title = re.sub(r"\b(?:Specification|template|pdf|html)\b", " ", title, flags=re.IGNORECASE)
    title = re.sub(r"\]\([^)]*$", "", title)
    title = re.sub(r"^[\s,;:()\\[\\]-]+|[\s,;:()\\[\\]-]+$", "", title)
    return clean_calendar_text(title)


def build_assignment_event(
    title: str,
    due_dt: datetime,
    all_day: bool,
    description: str,
    index: int,
) -> dict | None:
    """Build a deterministic assignment event if the title is usable."""
    clean_title = clean_assignment_name(title)
    if not clean_title or clean_title.lower() in {"assignment", "assignments", "due", "deadline"}:
        return None

    return {
        "id": f"{due_dt.isoformat()}_assignment_{index}",
        "title": clean_title,
        "start_time": due_dt.isoformat(),
        "end_time": due_dt.isoformat(),
        "source": "course",
        "is_fixed": True,
        "event_kind": "assignment",
        "event_type": infer_assignment_type(clean_title),
        "description": description,
        "all_day": all_day,
    }


def parse_due_table_assignments(soup) -> list[dict]:
    """Parse assignment due dates from schedule table assignment columns.

    Some UW course pages, including CSE 403, store assignments in a table
    column like: "Project proposal (due Mon 01/12/26 11:59pm)".
    """
    events = []

    for row in soup.find_all("tr"):
        cells = row.find_all(["td", "th"], recursive=False)
        if not cells:
            continue

        row_date = parse_numeric_course_date(cells[0].get_text(" ", strip=True))
        due_cells = [
            cell for cell in cells
            if "due" in {class_name.lower() for class_name in cell.get("class", [])}
        ]

        if not due_cells:
            continue

        for cell in due_cells:
            cell_text = clean_calendar_text(cell.get_text(" ", strip=True))
            if not ASSIGNMENT_DUE_RE.search(cell_text):
                continue

            previous_end = 0
            for match in DUE_PHRASE_RE.finditer(cell_text):
                due_text = match.group(0)
                due_date = parse_numeric_course_date(due_text)

                if due_date is None and re.search(r"\btoday\b", due_text, re.IGNORECASE):
                    due_date = row_date
                elif due_date is None and re.search(r"\bduring class\b", due_text, re.IGNORECASE):
                    due_date = row_date

                if due_date is None:
                    continue

                title_text = cell_text[previous_end:match.start()]
                title = clean_due_assignment_title(title_text)
                if not title:
                    continue

                due_time = parse_due_time(due_text)
                all_day = due_time is None
                if due_time:
                    hour, minute = due_time
                    due_dt = due_date.replace(hour=hour, minute=minute)
                else:
                    due_dt = due_date

                events.append({
                    "id": f"{due_dt.isoformat()}_table_assignment_{len(events)}",
                    "title": title,
                    "start_time": due_dt.isoformat(),
                    "end_time": due_dt.isoformat(),
                    "source": "course",
                    "is_fixed": True,
                    "event_kind": "assignment",
                    "event_type": infer_assignment_type(title),
                    "description": cell_text,
                    "all_day": all_day,
                })

                previous_end = match.end()
                while previous_end < len(cell_text) and cell_text[previous_end] in " )":
                    previous_end += 1

    return events


def get_header_indices(headers: list[str]) -> tuple[int | None, int | None, int | None]:
    """Find date, due-date, and assignment columns in table headers."""
    date_col = None
    due_col = None
    assignment_col = None

    for index, header in enumerate(headers):
        normalized = header.lower()
        if due_col is None and "due" in normalized:
            due_col = index
        if date_col is None and any(term in normalized for term in ("date", "day", "when")):
            date_col = index
        if assignment_col is None and any(
            term in normalized
            for term in ("assignment", "homework", "hw", "lab", "pset", "project")
        ):
            assignment_col = index

    return date_col, due_col, assignment_col


def append_assignment_event(
    events: list[dict],
    title: str,
    due_result: tuple[datetime, bool] | None,
    description: str,
) -> None:
    """Append a normalized assignment event when due parsing succeeded."""
    if due_result is None:
        return

    due_dt, all_day = due_result
    event = build_assignment_event(title, due_dt, all_day, description, len(events))
    if event:
        events.append(event)


def parse_schedule_table_assignments(soup, default_year: int) -> list[dict]:
    """Parse assignments from common course schedule/assignment tables."""
    events = []
    default_due_time = find_default_due_time(soup)

    for table in soup.find_all("table"):
        headers: list[str] = []
        current_date = None

        for row in table.find_all("tr"):
            cells_el = row.find_all(["td", "th"], recursive=False)
            cells = [clean_calendar_text(cell.get_text(" ", strip=True)) for cell in cells_el]
            if not any(cells):
                continue

            combined_header = " ".join(cells).lower()
            header_like = (
                row.find("th") is not None
                or (
                    not parse_course_date(cells[0], default_year)
                    and not any(parse_course_date(cell, default_year) for cell in cells)
                    and any(term in combined_header for term in ("date", "assignment", "homework", "due"))
                    and not any(term in combined_header for term in ("released", "out ", " due "))
                )
            )
            if header_like:
                headers = [cell.lower() for cell in cells]
                continue

            first_cell_date = parse_course_date(cells[0], default_year)
            if first_cell_date:
                current_date = first_cell_date

            date_col, due_col, assignment_col = get_header_indices(headers)
            handled_header_assignment = False

            if due_col is not None and due_col < len(cells):
                due_text = cells[due_col]
                if due_text:
                    due_result = extract_due_datetime(
                        due_text,
                        current_date,
                        default_year,
                        default_due_time,
                    )
                    if due_result is None and current_date and ASSIGNMENT_LIKE_RE.search(due_text):
                        due_result = (current_date, True)

                    title = ""
                    if assignment_col is not None and assignment_col < len(cells):
                        title = cells[assignment_col]
                    if not title:
                        title = due_text
                    append_assignment_event(
                        events,
                        title,
                        due_result,
                        " | ".join(cells),
                    )
                    handled_header_assignment = True

            if (
                due_col is None
                and date_col is not None
                and assignment_col is not None
                and date_col < len(cells)
                and assignment_col < len(cells)
                and cells[assignment_col]
            ):
                append_assignment_event(
                    events,
                    cells[assignment_col],
                    extract_due_datetime(cells[date_col], current_date, default_year, default_due_time),
                    " | ".join(cells),
                )
                handled_header_assignment = True

            if handled_header_assignment:
                continue

            row_text = " ".join(cells)
            if not ASSIGNMENT_LIKE_RE.search(row_text):
                continue

            due_marked_indices = [
                index for index, cell in enumerate(cells)
                if DUE_OR_INITIAL_SUBMISSION_RE.search(cell)
                or re.search(
                    r"\bby\s+\d{1,2}(?::\d{2})?\s*(?:a\.?m\.?|p\.?m\.?)\b",
                    cell,
                    re.IGNORECASE,
                )
            ]

            if not due_marked_indices and due_col is not None and due_col < len(cells) and cells[due_col]:
                due_marked_indices = [due_col]

            for due_index in due_marked_indices:
                due_text = cells[due_index]
                due_result = extract_due_datetime(
                    due_text,
                    current_date,
                    default_year,
                    default_due_time,
                )
                if due_result is None:
                    continue

                title = clean_schedule_assignment_title(due_text)
                if not title or not ASSIGNMENT_LIKE_RE.search(title):
                    previous_parts = [
                        cell for index, cell in enumerate(cells[:due_index])
                        if cell and not parse_course_date(cell, default_year)
                    ]
                    title = " ".join(previous_parts[-2:] + ([title] if title else []))
                if not title:
                    title = due_text

                append_assignment_event(events, title, due_result, " | ".join(cells))

    return events


def parse_inline_due_assignments(soup, default_year: int) -> list[dict]:
    """Parse prose snippets like 'Homework 1 ... Due Monday, May 25, 11pm'."""
    events = []
    default_due_time = find_default_due_time(soup)
    text_soup = BeautifulSoup(str(soup), "html.parser")
    for table in text_soup.find_all("table"):
        table.decompose()
    text = clean_calendar_text(text_soup.get_text(" ", strip=True))

    for match in INLINE_DUE_ASSIGNMENT_RE.finditer(text):
        title = match.group("title")
        due_text = match.group("due")
        if re.fullmatch(r"[ACPR]\d+", clean_schedule_assignment_title(title), re.IGNORECASE):
            continue
        due_result = extract_due_datetime(due_text, None, default_year, default_due_time)
        append_assignment_event(events, title, due_result, match.group(0))

    return events


def parse_assignment_cards_with_date_context(soup, default_year: int) -> list[dict]:
    """Parse card/list layouts where a date heading contains assignment labels."""
    events = []
    default_due_time = find_default_due_time(soup)

    for card in soup.select(".MuiPaper-root"):
        text = clean_calendar_text(card.get_text(" ", strip=True))
        if "Assignment Due" not in text or "Assignment:" not in text:
            continue

        date = parse_course_date(text[:80], default_year)
        if date is None:
            continue

        for title in re.split(r"\bAssignment:\s*", text, flags=re.IGNORECASE)[1:]:
            title = re.split(r"\bAssignment\s+Due\b|\bReadings?\b|\b\d{1,2}:\d{2}\b", title)[0]
            if default_due_time:
                hour, minute = default_due_time
                due_result = (date.replace(hour=hour, minute=minute), False)
            else:
                due_result = (date, True)
            append_assignment_event(
                events,
                title,
                due_result,
                text,
            )

    current_date = None
    root = soup.select_one("#calendar") or soup.select_one(".main-content") or soup.body
    if root:
        for node in root.descendants:
            if isinstance(node, NavigableString):
                text = clean_calendar_text(str(node))
                if 3 <= len(text) <= 30:
                    parsed_date = parse_course_date(text, default_year)
                    if parsed_date:
                        current_date = parsed_date
                continue

            if not isinstance(node, Tag):
                continue

            if node.name in {"strong", "span"}:
                label = clean_calendar_text(
                    " ".join(str(text) for text in node.find_all(string=True, recursive=False))
                )
                if "due" in label.lower() and ASSIGNMENT_LIKE_RE.search(label):
                    append_assignment_event(
                        events,
                        label,
                        extract_due_datetime(label, current_date, default_year, default_due_time),
                        label,
                    )

    return events


_DT_DATE_PREFIX_RE = re.compile(
    r"^(?:mon|tue|wed|thu|fri|sat|sun)\.?,?\s*"
    r"(?:0?[1-9]|1[0-2])/(?:0?[1-9]|[12]\d|3[01])(?:/(?:\d{2}|\d{4}))?\s*",
    re.IGNORECASE,
)
_HW_LIKE_INLINE_RE = re.compile(
    r"\b(?:HW|Hw|Homework|Pset|Lab|Project|Exercise|Assignment)\s*\d+[A-Za-z]?\b"
    r"[^.;\n]{0,160}",
)


def parse_definition_list_schedule(soup, default_year: int) -> list[dict]:
    """Parse <dl>/<dt>/<dd> schedule layouts (e.g. CSE 391).

    Each <dt> starts with a date like "Tue 03/31" plus a lecture title.
    The following <dd> often contains "Released HWn ... Due TIME" snippets
    where the due date isn't explicit — assumed to be the next <dt> date.
    """
    events: list[dict] = []

    for dl in soup.find_all("dl"):
        items: list[tuple[str, str, datetime | None]] = []
        for child in dl.children:
            if not isinstance(child, Tag) or child.name not in ("dt", "dd"):
                continue
            text = clean_calendar_text(child.get_text(" ", strip=True))
            if not text:
                continue
            lec_date = parse_course_date(text, default_year) if child.name == "dt" else None
            items.append((child.name, text, lec_date))

        last_date: datetime | None = None
        for index, (tag, text, date) in enumerate(items):
            if tag == "dt":
                if date is None:
                    continue
                last_date = date
                title_text = _DT_DATE_PREFIX_RE.sub("", text).strip(" -—–:")
                if not title_text:
                    title_text = "Lecture"
                events.append({
                    "id": f"{date.isoformat()}_dt_{len(events)}",
                    "title": title_text,
                    "start_time": date.isoformat(),
                    "end_time": date.isoformat(),
                    "source": "course",
                    "is_fixed": True,
                    "event_kind": "class_event",
                    "event_type": infer_event_type(title_text),
                    "description": text,
                    "all_day": True,
                })
                continue

            if last_date is None:
                continue

            for hw_match in _HW_LIKE_INLINE_RE.finditer(text):
                snippet = hw_match.group(0)
                if not ASSIGNMENT_LIKE_RE.search(snippet):
                    continue

                # Prefer explicit due date in snippet; else next <dt>; else this row's date.
                due_pair = extract_due_datetime(snippet, None, default_year, None)
                if due_pair is None:
                    fallback_date = None
                    # Look ahead for the next <dt> date after this <dd>
                    for look_index in range(index + 1, len(items)):
                        if items[look_index][0] == "dt" and items[look_index][2]:
                            fallback_date = items[look_index][2]
                            break
                    if fallback_date is None:
                        fallback_date = last_date
                    due_time = parse_due_time(snippet)
                    if due_time:
                        hour, minute = due_time
                        due_pair = (fallback_date.replace(hour=hour, minute=minute), False)
                    else:
                        due_pair = (fallback_date, True)

                due_dt, all_day = due_pair
                event = build_assignment_event(
                    snippet, due_dt, all_day, snippet, len(events),
                )
                if event:
                    events.append(event)

    return events


def parse_course_assignments(soup, default_year: int) -> list[dict]:
    """Run all deterministic assignment extractors for a course page."""
    events = []
    events.extend(parse_assignment_cards(soup))
    events.extend(parse_due_table_assignments(soup))
    events.extend(parse_schedule_table_assignments(soup, default_year))
    events.extend(parse_assignment_cards_with_date_context(soup, default_year))
    events.extend(parse_inline_due_assignments(soup, default_year))
    events.extend(parse_definition_list_schedule(soup, default_year))

    by_clean_title_and_date: dict[tuple[str, str], dict] = {}
    ordered_keys: list[tuple[str, str]] = []
    for event in events:
        title = clean_assignment_name(event.get("title", ""))
        if not title:
            continue
        event = {**event, "title": title}
        event_date = event.get("start_time", "")[:10]
        if not event_date:
            continue

        key = (title.lower(), event_date)
        existing = by_clean_title_and_date.get(key)
        if existing is None:
            ordered_keys.append(key)
            by_clean_title_and_date[key] = event
            continue

        existing_is_all_day = bool(existing.get("all_day"))
        event_is_all_day = bool(event.get("all_day"))
        if existing_is_all_day and not event_is_all_day:
            by_clean_title_and_date[key] = event

    deduped = [by_clean_title_and_date[key] for key in ordered_keys]

    return deduped


def infer_grid_item_type(class_names: set[str], title: str) -> str:
    """Infer event type from CSE grid-calendar CSS classes and title."""
    lower_classes = {class_name.lower() for class_name in class_names}
    if "exam" in lower_classes or any(term in title.lower() for term in ("exam", "midterm", "final")):
        return "exam"
    if "lab" in lower_classes:
        return "lab"
    if "section" in lower_classes:
        return "section"
    if "discussion" in lower_classes:
        return "discussion"
    if "office_hours" in lower_classes or "office-hours" in lower_classes:
        return "office_hours"
    return "lecture"


DAY_ALIASES = {
    "m": 0,
    "mon": 0,
    "monday": 0,
    "mondays": 0,
    "tu": 1,
    "tue": 1,
    "tues": 1,
    "tuesday": 1,
    "tuesdays": 1,
    "w": 2,
    "wed": 2,
    "wednesday": 2,
    "wednesdays": 2,
    "th": 3,
    "thu": 3,
    "thur": 3,
    "thurs": 3,
    "thursday": 3,
    "thursdays": 3,
    "f": 4,
    "fri": 4,
    "friday": 4,
    "fridays": 4,
}


def weekday_from_date_label(text: str) -> int | None:
    match = re.match(r"\s*(mon|monday|tue|tues|tuesday|wed|wednesday|thu|thur|thurs|thursday|fri|friday)\b", text, re.IGNORECASE)
    if not match:
        return None
    return DAY_ALIASES.get(match.group(1).lower())


def parse_meeting_days(text: str) -> set[int]:
    """Parse compact course day strings like MWF, TTh, or Mon/Wed/Fri."""
    compact = re.sub(r"[^A-Za-z]", "", text).lower()
    if compact in {"mwf", "mwfri"}:
        return {0, 2, 4}
    if compact in {"mw", "mwed"}:
        return {0, 2}
    if compact in {"tth", "tuth", "tueth", "tuesdaythursday"}:
        return {1, 3}

    days: set[int] = set()
    for token in re.findall(
        r"\b(?:mondays?|mon|tuesdays?|tues|tue|tu|wednesdays?|wed|thursdays?|thurs|thur|thu|th|fridays?|fri)\b",
        text,
        re.IGNORECASE,
    ):
        weekday = DAY_ALIASES.get(token.lower())
        if weekday is not None:
            days.add(weekday)

    if not days and re.fullmatch(r"[MTWThF]+", text.replace(" ", ""), re.IGNORECASE):
        token = text.replace(" ", "")
        index = 0
        while index < len(token):
            two = token[index:index + 2].lower()
            one = token[index:index + 1].lower()
            if two == "th":
                days.add(3)
                index += 2
            elif one in DAY_ALIASES:
                days.add(DAY_ALIASES[one])
                index += 1
            else:
                index += 1

    return days


def _format_hhmm(clock: tuple[int, int]) -> str:
    return f"{clock[0]:02d}:{clock[1]:02d}"


def _clean_meeting_location(text: str) -> str | None:
    text = clean_calendar_text(text)
    text = re.sub(r"^(?:PT|PST|PDT),?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"^(?:in|at|@|room|location)\s*:?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\b(?:lectures?|classes?|will be recorded|recorded using panopto)\b.*$", "", text, flags=re.IGNORECASE)
    text = re.sub(r",?\s*additional\s*$", "", text, flags=re.IGNORECASE)
    text = text.strip(" .,:;-()")
    return text or None


def meeting_pattern_from_line(
    line: str,
    event_type: str,
    fallback_location: str | None = None,
) -> dict | None:
    """Parse one line of recurring meeting text into an event pattern."""
    line = clean_calendar_text(line)
    time_range = parse_time_range(line)
    if time_range is None:
        return None
    time_match = TIME_RANGE_RE.search(line)
    if not time_match:
        return None

    before_time = line[:time_match.start()].strip(" :,-")
    before_time = re.sub(
        r"^(?:class|classes|lecture|lectures|course\s+time|time|meeting)\s*:?\s*",
        "",
        before_time,
        flags=re.IGNORECASE,
    )
    section_label = None
    label_match = re.search(r"\b([A-Z]{1,3})\s*:\s*", before_time)
    if label_match:
        section_label = label_match.group(1)
        before_time = before_time[label_match.end():].strip(" :,-")

    weekdays = parse_meeting_days(before_time)
    if not weekdays:
        return None

    after_time = line[time_match.end():].strip(" ,;-")
    location = _clean_meeting_location(after_time) or fallback_location
    start_clock, end_clock = time_range
    return {
        "event_type": event_type,
        "section_label": section_label,
        "weekdays": weekdays,
        "start_time": _format_hhmm(start_clock),
        "end_time": _format_hhmm(end_clock),
        "location": location,
    }


def _append_unique_pattern(patterns: list[dict], pattern: dict | None) -> None:
    if pattern is None:
        return
    key = (
        pattern.get("event_type"),
        tuple(sorted(pattern.get("weekdays", set()))),
        pattern.get("start_time"),
        pattern.get("end_time"),
        pattern.get("location"),
    )
    for existing in patterns:
        existing_key = (
            existing.get("event_type"),
            tuple(sorted(existing.get("weekdays", set()))),
            existing.get("start_time"),
            existing.get("end_time"),
            existing.get("location"),
        )
        if existing_key == key:
            return
    patterns.append(pattern)


def extract_meeting_patterns(soup) -> list[dict]:
    """Extract recurring meeting time/location rules from a course home page."""
    patterns: list[dict] = []

    for heading in soup.find_all(re.compile(r"^h[1-6]$")):
        heading_text = clean_calendar_text(heading.get_text(" ", strip=True)).lower()
        if "lecture" in heading_text:
            event_type = "lecture"
        elif "section" in heading_text or "discussion" in heading_text:
            event_type = "section"
        elif "lab" in heading_text:
            event_type = "lab"
        else:
            continue

        parts: list[str] = []
        for sibling in heading.find_next_siblings():
            if isinstance(sibling, Tag) and re.fullmatch(r"h[1-6]", sibling.name or ""):
                break
            if isinstance(sibling, Tag):
                parts.append(sibling.get_text("\n", strip=True))
        block_text = "\n".join(parts)

        for line in [clean_calendar_text(line) for line in block_text.splitlines()]:
            _append_unique_pattern(patterns, meeting_pattern_from_line(line, event_type))

    lines = [clean_calendar_text(line) for line in soup.get_text("\n", strip=True).splitlines()]
    lines = [line for line in lines if line]
    context_event_type: str | None = None
    context_location: str | None = None
    for index, line in enumerate(lines):
        lower = line.lower()
        if re.search(r"\b(?:office\s*hours?|oh|midterm|final\s+exam|exam)\b", lower):
            context_event_type = None
            continue
        if re.search(r"\b(?:lecture|lectures|class|classes|course\s+time|meeting\s+time)\b", lower):
            context_event_type = "lecture"
        elif re.search(r"\b(?:section|sections|discussion)\b", lower):
            context_event_type = "section"

        if lower.startswith("location:") or lower.startswith("room "):
            context_location = _clean_meeting_location(line)

        event_type = context_event_type
        if re.search(r"\b(?:lecture|lectures|class|classes|course\s+time|meeting\s+time)\b", lower):
            event_type = "lecture"
        elif re.search(r"\b(?:section|sections|discussion)\b", lower):
            event_type = "section"
        elif lower.startswith("time:") and context_location:
            event_type = "lecture"

        if event_type and parse_time_range(line):
            nearby_location = context_location
            for nearby in lines[max(0, index - 2):index + 3]:
                if nearby.lower().startswith("location:") or nearby.lower().startswith("room "):
                    nearby_location = _clean_meeting_location(nearby)
            _append_unique_pattern(
                patterns,
                meeting_pattern_from_line(line, event_type, nearby_location),
            )

    return patterns


def _meeting_pattern_for_event(
    event_type: str,
    event_date: datetime,
    patterns: list[dict],
    weekday_override: int | None = None,
) -> dict | None:
    weekdays_to_match = {event_date.weekday()}
    if weekday_override is not None:
        weekdays_to_match.add(weekday_override)

    candidates = [
        pattern for pattern in patterns
        if pattern.get("event_type") == event_type
        and pattern.get("weekdays", set()).intersection(weekdays_to_match)
    ]
    if len(candidates) == 1:
        return candidates[0]
    return None


def _datetime_with_hhmm(date_value: datetime, hhmm: str) -> datetime:
    hour, minute = [int(part) for part in hhmm.split(":", 1)]
    return date_value.replace(hour=hour, minute=minute)


def expand_recurring_meeting_patterns(course_url: str, patterns: list[dict]) -> list[dict]:
    """Expand recurring lecture/section meeting rules across the quarter."""
    quarter = infer_quarter_dates(course_url)
    if not quarter:
        return []

    start_date = datetime.fromisoformat(quarter[0])
    end_date = datetime.fromisoformat(quarter[1])
    events: list[dict] = []
    current = start_date
    while current <= end_date:
        for pattern in patterns:
            if current.weekday() not in pattern.get("weekdays", set()):
                continue
            event_type = pattern.get("event_type", "lecture")
            section_label = pattern.get("section_label")
            title = event_type.replace("_", " ").title()
            if section_label:
                title = f"{title} {section_label}"
            start_dt = _datetime_with_hhmm(current, pattern["start_time"])
            end_dt = _datetime_with_hhmm(current, pattern["end_time"])
            events.append({
                "id": f"{current.date().isoformat()}_{event_type}_{len(events)}",
                "title": title,
                "start_time": start_dt.isoformat(),
                "end_time": end_dt.isoformat(),
                "source": "course",
                "is_fixed": True,
                "event_kind": "class_event",
                "event_type": event_type,
                "location": pattern.get("location"),
                "description": None,
                "all_day": False,
            })
        current += timedelta(days=1)

    return events


def parse_calendar_table_events(
    soup,
    default_year: int,
    meeting_patterns: list[dict] | None = None,
) -> list[dict]:
    """Parse generic calendar tables with Date / Type / Description columns."""
    events: list[dict] = []
    meeting_patterns = meeting_patterns or []

    for table in soup.find_all("table"):
        headers: list[str] = []
        for row in table.find_all("tr"):
            cells_el = row.find_all(["td", "th"], recursive=False)
            cells = [clean_calendar_text(cell.get_text(" ", strip=True)) for cell in cells_el]
            if not any(cells):
                continue

            if row.find("th") is not None:
                headers = [cell.lower() for cell in cells]
                continue

            date_col, _due_col, assignment_col = get_header_indices(headers)
            type_col = next(
                (index for index, header in enumerate(headers) if "type" in header or "kind" in header),
                None,
            )
            description_col = next(
                (index for index, header in enumerate(headers) if "description" in header or "topic" in header),
                None,
            )
            if date_col is None or type_col is None or date_col >= len(cells) or type_col >= len(cells):
                continue

            effective_date_col = date_col
            date_label = cells[effective_date_col]
            event_date = parse_course_date(date_label, default_year)
            if event_date is None and effective_date_col > 0:
                shifted_date_col = effective_date_col - 1
                shifted_date_label = cells[shifted_date_col]
                shifted_date = parse_course_date(shifted_date_label, default_year)
                if shifted_date is not None:
                    effective_date_col = shifted_date_col
                    date_label = shifted_date_label
                    event_date = shifted_date
            if event_date is None:
                for index, cell in enumerate(cells):
                    parsed_date = parse_course_date(cell, default_year)
                    if parsed_date is not None:
                        effective_date_col = index
                        date_label = cell
                        event_date = parsed_date
                        break

            index_shift = effective_date_col - date_col
            effective_type_col = type_col + index_shift
            effective_description_col = (
                description_col + index_shift if description_col is not None else None
            )
            if (
                event_date is None
                or effective_type_col < 0
                or effective_type_col >= len(cells)
            ):
                continue

            raw_type = cells[effective_type_col]
            if event_date is None or not raw_type:
                continue

            event_type = infer_event_type(raw_type)
            if event_type == "lecture" and "lecture" not in raw_type.lower():
                continue

            event_kind = "assignment" if ASSIGNMENT_LIKE_RE.search(raw_type) else "class_event"
            if event_kind == "assignment":
                continue

            description = (
                cells[effective_description_col]
                if effective_description_col is not None
                and 0 <= effective_description_col < len(cells)
                else ""
            )
            title = raw_type if not description else f"{raw_type} — {description}"
            pattern = _meeting_pattern_for_event(
                event_type,
                event_date,
                meeting_patterns,
                weekday_from_date_label(date_label),
            )
            if pattern:
                start_dt = _datetime_with_hhmm(event_date, pattern["start_time"])
                end_dt = _datetime_with_hhmm(event_date, pattern["end_time"])
                all_day = False
                location = pattern.get("location")
            else:
                start_dt = event_date
                end_dt = event_date
                all_day = True
                location = None

            events.append({
                "id": f"{event_date.date().isoformat()}_{event_type}_{len(events)}",
                "title": title,
                "start_time": start_dt.isoformat(),
                "end_time": end_dt.isoformat(),
                "source": "course",
                "is_fixed": True,
                "event_kind": "class_event",
                "event_type": event_type,
                "description": description,
                "location": location,
                "all_day": all_day,
            })

    return events


def parse_grid_calendar(soup) -> list[dict]:
    """Parse CSE calendar pages that use div.day[date] grid markup."""
    events = []
    for day in soup.select("#schedule.calendar .day[date], .calendar .day[date]"):
        date_str = day.get("date", "")
        if not is_valid_iso_date(date_str):
            continue

        events_container = day.find("div", class_="events")
        if not events_container:
            continue

        for item in events_container.find_all(["details", "div"], recursive=False):
            class_names = set(item.get("class", []))
            lower_classes = {class_name.lower() for class_name in class_names}
            if {"no", "meeting"}.issubset(lower_classes):
                continue

            if item.name == "details":
                summary = item.find("summary")
                title = clean_calendar_text(summary.get_text(" ", strip=True) if summary else "")
            else:
                title = clean_calendar_text(item.get_text(" ", strip=True))

            if not title:
                continue

            event_type = infer_grid_item_type(class_names, title)
            event_kind = "assignment" if "assignment" in lower_classes else "class_event"
            start_dt = datetime.fromisoformat(f"{date_str}T00:00:00")
            end_dt = datetime.fromisoformat(f"{date_str}T23:59:59")

            events.append({
                "id": f"{date_str}_{event_kind}_{len(events)}",
                "title": title,
                "start_time": start_dt.isoformat(),
                "end_time": end_dt.isoformat(),
                "source": "course",
                "is_fixed": True,
                "event_kind": event_kind,
                "event_type": event_type,
                "all_day": True,
            })

    return events


def parse_assignment_cards(soup) -> list[dict]:
    """Parse assignment-card pages such as CSE446 assignments/index.html."""
    events = []
    for card in soup.select(".hw-card[data-date], .assignment-card[data-date], .assignment[data-date]"):
        raw_date = card.get("data-date", "").strip()
        if not raw_date:
            continue

        try:
            due_dt = datetime.fromisoformat(raw_date)
        except ValueError:
            try:
                due_dt = datetime.fromisoformat(f"{raw_date}T00:00:00")
            except ValueError:
                continue

        title_el = (
            card.select_one(".hw-title")
            or card.select_one(".assignment-title")
            or card.find(["h2", "h3", "h4"])
        )
        title = clean_calendar_text(
            title_el.get_text(" ", strip=True) if title_el else card.get_text(" ", strip=True)
        )
        if not title:
            continue

        due_text_el = card.select_one(".hw-date") or card.select_one(".assignment-date")
        due_text = clean_calendar_text(due_text_el.get_text(" ", strip=True) if due_text_el else "")
        description = due_text

        events.append({
            "id": f"{due_dt.isoformat()}_assignment_{len(events)}",
            "title": title,
            "start_time": due_dt.isoformat(),
            "end_time": due_dt.isoformat(),
            "source": "course",
            "is_fixed": True,
            "event_kind": "assignment",
            "event_type": infer_assignment_type(title),
            "description": description,
            "all_day": "T" not in raw_date,
        })

    return events


def parse_supported_calendar_soup(
    soup,
    default_year: int | None = None,
    meeting_patterns: list[dict] | None = None,
) -> list[dict]:
    """Parse known deterministic calendar formats from a BeautifulSoup document."""
    if _has_monthtable(soup):
        return _parse_monthtable(soup)

    grid_events = parse_grid_calendar(soup)
    if grid_events:
        return grid_events

    if default_year is not None:
        return parse_calendar_table_events(soup, default_year, meeting_patterns)

    return []


def _ical_dt_to_datetime(value: object) -> tuple[datetime, bool] | None:
    """Convert an iCalendar DTSTART/DTEND value into a datetime."""
    if isinstance(value, datetime):
        return value.replace(tzinfo=None), False
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day), True
    return None


def infer_ical_event_type(summary: str, event_type_value: str, url: str) -> str:
    label = f"{summary} {event_type_value} {url}".lower()
    if "office" in label or re.search(r"\boh\b", label):
        return "office_hours"
    if "section" in label:
        return "section"
    if "lab" in label:
        return "lab"
    if "exam" in label or "midterm" in label or "final" in label:
        return "exam"
    return "lecture"


def parse_ical_calendar_events(ical_content: bytes | str, source_url: str) -> list[dict]:
    """Parse explicit VEVENT rows from a course .ics file."""
    try:
        calendar = Calendar.from_ical(ical_content)
    except Exception:
        return []

    events: list[dict] = []
    for component in calendar.walk():
        if getattr(component, "name", None) != "VEVENT":
            continue
        dtstart = component.get("DTSTART")
        if dtstart is None:
            continue
        start_pair = _ical_dt_to_datetime(dtstart.dt)
        if start_pair is None:
            continue

        start_dt, all_day = start_pair
        dtend = component.get("DTEND")
        end_pair = _ical_dt_to_datetime(dtend.dt) if dtend is not None else None
        end_dt = end_pair[0] if end_pair else start_dt
        summary = clean_calendar_text(str(component.get("SUMMARY", ""))) or "Class Event"
        description = clean_calendar_text(str(component.get("DESCRIPTION", ""))) or None
        location = clean_calendar_text(str(component.get("LOCATION", ""))) or None
        event_type_value = clean_calendar_text(str(component.get("X-CREATECAL-EVENTTYPE", "")))
        event_type = infer_ical_event_type(summary, event_type_value, source_url)
        events.append({
            "id": str(component.get("UID", f"{source_url}_{len(events)}")),
            "title": summary,
            "start_time": start_dt.isoformat(),
            "end_time": end_dt.isoformat(),
            "source": "course",
            "is_fixed": True,
            "event_kind": "class_event",
            "event_type": event_type,
            "description": description,
            "location": location,
            "all_day": all_day,
        })

    return events


async def fetch_ical_events_from_soup(
    client: httpx.AsyncClient,
    soup,
    page_url: str,
    *,
    max_files: int = 12,
) -> list[dict]:
    """Fetch .ics links from a related calendar directory/page."""
    events: list[dict] = []
    seen: set[str] = set()
    for link in soup.find_all("a", href=True):
        href = link["href"]
        if not href.lower().endswith(".ics"):
            continue
        ical_url = _canonical_url(urljoin(page_url, href))
        if ical_url in seen:
            continue
        seen.add(ical_url)
        if len(seen) > max_files:
            break
        try:
            response = await get_course_html(client, ical_url)
            events.extend(parse_ical_calendar_events(response.content, ical_url))
        except Exception:
            continue
    return events


def _canonical_url(url: str) -> str:
    """Normalize URL for duplicate detection."""
    return urldefrag(url)[0].rstrip("/")


def _is_same_course_url(candidate_url: str, course_url: str) -> bool:
    """Keep crawling scoped to the imported course website."""
    candidate = urlparse(candidate_url)
    root = urlparse(course_url)
    if candidate.scheme not in {"http", "https"}:
        return False
    if candidate.netloc != root.netloc:
        return False

    root_path = root.path.rstrip("/")
    if not root_path:
        return True
    return candidate.path.startswith(root_path)


def _link_score(url: str, text: str) -> int:
    """Rank links by how likely they are to contain course calendar data."""
    lower_url = url.lower()
    label = f"{text} {lower_url}"
    if LOW_VALUE_LINK_RE.search(label):
        return 0
    if re.search(r"\.(?:pdf|png|jpg|jpeg|gif|zip|tar|gz|pptx?|docx?|mp4|mov|avi|mp3|wav)$", lower_url):
        return 0

    score = 0
    if CALENDAR_LINK_RE.search(label):
        score += 90
    if ASSIGNMENT_LINK_RE.search(label):
        score += 120
    if re.search(r"\b(?:syllabus|overview|course)\b", label, re.IGNORECASE):
        score += 100
    if re.search(r"\b(?:lectures?|sections?|discussion|labs?|exams?|deadlines?|readings?)\b", label, re.IGNORECASE):
        score += 50
    if COURSE_DETAIL_LINK_RE.search(label):
        score += 25
    if lower_url.endswith((".html", ".htm")) or lower_url.endswith("/"):
        score += 5
    return score


def discover_related_course_links(
    soup,
    course_url: str,
    *,
    max_links: int = MAX_RELATED_PAGES,
    include_common_paths: bool = False,
) -> list[str]:
    """Return high-value same-course links from the imported page."""
    scored: dict[str, int] = {}

    def add(url: str, label: str = "") -> None:
        absolute = _canonical_url(urljoin(course_url, url))
        if absolute == _canonical_url(course_url):
            return
        if not _is_same_course_url(absolute, course_url):
            return
        score = _link_score(absolute, label)
        if score <= 0:
            return
        scored[absolute] = max(score, scored.get(absolute, 0))

    for link in soup.find_all("a", href=True):
        add(link["href"], link.get_text(" ", strip=True))

    if include_common_paths:
        base_url = urljoin(course_url, ".")
        for path in [*_CALENDAR_CANDIDATES, *ASSIGNMENT_PAGE_CANDIDATES]:
            add(urljoin(base_url, path), path)

    return [
        url
        for url, _score in sorted(scored.items(), key=lambda item: (-item[1], item[0]))[:max_links]
    ]


def should_probe_common_course_paths(soup, course_url: str) -> bool:
    """Probe common paths when JS-generated nav hides calendar/assignment links."""
    links = discover_related_course_links(soup, course_url, max_links=MAX_RELATED_PAGES)
    return not any(
        CALENDAR_LINK_RE.search(link) or ASSIGNMENT_LINK_RE.search(link)
        for link in links
    )


async def fetch_related_course_pages(
    client: httpx.AsyncClient,
    soup,
    course_url: str,
    *,
    max_pages: int = MAX_RELATED_PAGES,
    include_common_paths: bool = False,
) -> list[tuple[str, str]]:
    """Fetch selected same-course links with bounded network cost."""
    pages: list[tuple[str, str]] = []
    links = discover_related_course_links(
        soup,
        course_url,
        max_links=max_pages,
        include_common_paths=include_common_paths,
    )
    for index, url in enumerate(links):
        if index:
            await asyncio.sleep(RELATED_PAGE_FETCH_DELAY_S)
        try:
            response = await get_course_html(client, url)
            content_type = response.headers.get("content-type", "")
            if "text/html" not in content_type:
                continue
            pages.append((url, response.text))
        except Exception:
            continue
    return pages


async def get_course_html(
    client: httpx.AsyncClient,
    url: str,
    *,
    attempts: int = 2,
) -> httpx.Response:
    """Fetch a course HTML page with one retry for slow/disconnected UW pages."""
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            response = await client.get(url)
            response.raise_for_status()
            return response
        except (httpx.TimeoutException, httpx.RemoteProtocolError, httpx.ConnectError) as exc:
            last_error = exc
            if attempt + 1 >= attempts:
                break
            await asyncio.sleep(COURSE_FETCH_RETRY_DELAY_S)
            continue
    assert last_error is not None
    raise last_error


def calendar_event_to_unified(
    event: dict,
    course_name: str,
    course_url: str,
) -> tuple[dict | None, dict | None]:
    """Convert a deterministic calendar event into assignment or class-event dicts."""
    raw_title = event.get("title", "Class Event")

    try:
        start_dt = datetime.fromisoformat(event["start_time"])
        end_dt = datetime.fromisoformat(event.get("end_time", event["start_time"]))
    except (KeyError, TypeError, ValueError):
        return None, None

    all_day = event.get("all_day") is True
    start_time = start_dt.strftime("%H:%M")
    end_time = end_dt.strftime("%H:%M")

    if event.get("event_kind") == "assignment" or ASSIGNMENT_DUE_RE.search(raw_title):
        title = clean_assignment_name(raw_title)
        if not title:
            return None, None
        assignment_type = infer_assignment_type(title)
        description = event.get("description", "") or ""
        return {
            "assignment_name": title,
            "assignment_type": assignment_type,
            "due_date": start_dt.date().isoformat(),
            "due_time": None if all_day else start_time,
            "points": None,
            "description": description,
            "submission_method": None,
            "requirements": [],
            "is_individual": True,
            "is_group": False,
            "late_policy": None,
            "estimated_minutes": estimate_assignment_minutes(
                title,
                assignment_type,
                description,
            ),
            "course_name": course_name,
            "source_url": course_url,
        }, None

    event_type = event.get("event_type") or infer_event_type(raw_title)
    title = clean_event_title(raw_title, event_type, course_name)
    return None, {
        "event_name": title,
        "event_type": event_type,
        "date": start_dt.date().isoformat(),
        "start_time": None if all_day else start_time,
        "end_time": None if all_day else end_time,
        "location": event.get("location"),
        "description": event.get("description"),
        "course_name": course_name,
        "source_url": course_url,
    }


def convert_calendar_events_to_unified(
    events: list[dict],
    course_name: str,
    course_url: str,
) -> dict:
    """Convert deterministic calendar parser output into the route response schema."""
    assignments = []
    class_events = []
    seen_assignments = set()
    seen_class_events = set()

    for event in events:
        assignment, class_event = calendar_event_to_unified(event, course_name, course_url)
        if assignment:
            key = (
                assignment["assignment_name"],
                assignment["due_date"],
                assignment.get("due_time"),
            )
            if key in seen_assignments:
                continue
            seen_assignments.add(key)
            assignments.append(assignment)
        if class_event:
            key = (
                class_event["event_name"],
                class_event["date"],
                class_event.get("start_time"),
            )
            if key in seen_class_events:
                continue
            seen_class_events.add(key)
            class_events.append(class_event)

    return {
        "course_name": course_name,
        "class_events": class_events,
        "assignments": assignments,
    }


def _canonical_assignment_name_key(name: str) -> str:
    """Collapse common aliases like HW1/Homework 1 for matching rows."""
    name = clean_assignment_name(name).lower()
    name = re.sub(r"\bstarter\s+code\b", " ", name)
    name = re.sub(r"\bhomework\s*(\d+)\b", r"hw\1", name)
    name = re.sub(r"\bassignment\s*(\d+)\b", r"a\1", name)
    return re.sub(r"[^a-z0-9]+", "", name)


def _parsed_assignment_key(assignment: dict) -> tuple[str, str]:
    """Key assignment rows by cleaned name and date, ignoring missing time."""
    return (
        _canonical_assignment_name_key(assignment.get("assignment_name", "")),
        assignment.get("due_date", ""),
    )


def _parsed_event_key(event: dict) -> tuple[str, str, str, str]:
    """Key class rows by type/date/time so AI can improve generic titles."""
    return (
        (event.get("event_type") or infer_event_type(event.get("event_name", ""))).lower(),
        event.get("date", ""),
        event.get("start_time") or "",
        event.get("end_time") or "",
    )


def _is_generic_event_name(name: str) -> bool:
    normalized = re.sub(r"\s+", " ", name).strip().lower()
    return bool(re.fullmatch(
        r"(?:lecture|section|discussion|lab|office hours|exam)(?:\s+[a-z])?(?:\s+[—–-]\s+cse\d{3})?",
        normalized,
    ))


def merge_parsed_course_data(primary: dict, secondary: dict) -> dict:
    """Merge AI output into deterministic output without duplicating rows."""
    merged = {
        "course_name": primary.get("course_name") or secondary.get("course_name") or "Course",
        "class_events": list(primary.get("class_events", [])),
        "assignments": list(primary.get("assignments", [])),
    }

    assignment_index = {
        _parsed_assignment_key(assignment): index
        for index, assignment in enumerate(merged["assignments"])
        if _parsed_assignment_key(assignment)[0] and _parsed_assignment_key(assignment)[1]
    }
    for assignment in secondary.get("assignments", []):
        key = _parsed_assignment_key(assignment)
        if not key[0] or not key[1]:
            continue
        existing_index = assignment_index.get(key)
        if existing_index is None:
            assignment_index[key] = len(merged["assignments"])
            merged["assignments"].append(assignment)
            continue
        existing = merged["assignments"][existing_index]
        improved = {**existing}
        ai_estimate = coerce_estimated_minutes(
            assignment.get("estimated_minutes"),
            assignment_type=assignment.get("assignment_type")
            or infer_assignment_type(str(assignment.get("assignment_name", ""))),
        )
        if ai_estimate is not None:
            improved["estimated_minutes"] = ai_estimate
        if not improved.get("due_time") and assignment.get("due_time"):
            improved["due_time"] = assignment["due_time"]
        for field in (
            "assignment_type",
            "description",
            "points",
            "submission_method",
            "requirements",
            "is_individual",
            "is_group",
            "late_policy",
        ):
            value = assignment.get(field)
            if not improved.get(field) and value not in (None, "", []):
                improved[field] = value
        merged["assignments"][existing_index] = improved

    event_index = {
        _parsed_event_key(event): index
        for index, event in enumerate(merged["class_events"])
        if _parsed_event_key(event)[1]
    }
    for event in secondary.get("class_events", []):
        key = _parsed_event_key(event)
        if not key[1]:
            continue
        existing_index = event_index.get(key)
        if existing_index is None:
            event_index[key] = len(merged["class_events"])
            merged["class_events"].append(event)
            continue

        existing = merged["class_events"][existing_index]
        existing_name = existing.get("event_name", "")
        event_name = event.get("event_name", "")
        if _is_generic_event_name(existing_name) and not _is_generic_event_name(event_name):
            merged["class_events"][existing_index] = event

    return merged


_LAB_ASSIGNMENT_NUMBER_RE = re.compile(r"\blab\s*0*(\d+[a-z]?)\b", re.IGNORECASE)


def canonical_assignment_import_key(assignment: UnifiedAssignment) -> tuple[str, ...]:
    """Collapse equivalent names like HW1 and Homework 1 for final imports."""
    assignment_type = assignment.assignment_type.lower()
    lab_match = _LAB_ASSIGNMENT_NUMBER_RE.search(assignment.assignment_name)
    if lab_match and assignment_type == "lab":
        return (
            "lab-number",
            assignment.course_name.lower(),
            assignment_type,
            assignment.due_date,
            lab_match.group(1).lower(),
        )

    return (
        "name",
        assignment.course_name.lower(),
        _canonical_assignment_name_key(assignment.assignment_name),
        assignment.due_date,
        assignment.due_time or "",
    )


def assignment_import_quality_score(assignment: UnifiedAssignment) -> int:
    """Prefer richer duplicate assignment rows when import sources disagree."""
    score = 0
    description = (assignment.description or "").strip()
    score += min(len(description), 400)
    score += len(assignment.requirements or []) * 50
    if assignment.due_time:
        score += 20
    if assignment.points:
        score += 20
    if assignment.submission_method:
        score += 10
    score += assignment.estimated_minutes or 0
    return score


def deduplicate_course_import_assignments(
    assignments: list[UnifiedAssignment],
) -> list[UnifiedAssignment]:
    """Remove duplicate assignment rows after cross-page course imports."""
    index_by_key: dict[tuple[str, ...], int] = {}
    unique: list[UnifiedAssignment] = []
    for assignment in assignments:
        key = canonical_assignment_import_key(assignment)
        existing_index = index_by_key.get(key)
        if existing_index is None:
            index_by_key[key] = len(unique)
            unique.append(assignment)
            continue

        existing = unique[existing_index]
        if assignment_import_quality_score(assignment) > assignment_import_quality_score(existing):
            unique[existing_index] = assignment

    return unique


def canonical_class_event_import_key(event: UnifiedClassEvent) -> tuple[str, ...]:
    """Collapse duplicate timed lectures found from both HTML and .ics sources."""
    base = (
        event.course_name.lower(),
        event.event_type.lower(),
        event.date,
        event.start_time or "",
        event.end_time or "",
    )
    if event.event_type == "lecture" and event.start_time and event.end_time:
        return base

    normalized_name = re.sub(r"[^a-z0-9]+", "", event.event_name.lower())
    return (*base, normalized_name)


def class_event_quality_score(event: UnifiedClassEvent) -> int:
    """Prefer rows with real topics/details over generic duplicate rows."""
    score = 0
    if not _is_generic_event_name(event.event_name):
        score += 100
    if event.description:
        score += 20
    if event.location:
        score += 10
    score += min(len(event.event_name), 80)
    return score


def deduplicate_course_import_class_events(
    events: list[UnifiedClassEvent],
) -> list[UnifiedClassEvent]:
    """Remove duplicate class rows after cross-page course imports."""
    index_by_key: dict[tuple[str, ...], int] = {}
    unique: list[UnifiedClassEvent] = []

    for event in events:
        key = canonical_class_event_import_key(event)
        existing_index = index_by_key.get(key)
        if existing_index is None:
            index_by_key[key] = len(unique)
            unique.append(event)
            continue

        existing = unique[existing_index]
        if class_event_quality_score(event) > class_event_quality_score(existing):
            unique[existing_index] = event

    return unique


def should_augment_with_ai(parsed_data: dict | None) -> bool:
    """Use Ollama when deterministic parsing is likely incomplete."""
    if parsed_data is None:
        return True
    assignments = parsed_data.get("assignments", [])
    class_events = parsed_data.get("class_events", [])
    return not assignments or not class_events


def should_augment_assignment_estimates_with_ai(parsed_data: dict | None) -> bool:
    """Use the course AI pass to improve duration estimates for due items."""
    if parsed_data is None:
        return True
    return any(
        (assignment.get("assignment_type") or "").lower()
        in {"assignment", "homework", "lab", "project", "reading", "quiz", "exam"}
        for assignment in parsed_data.get("assignments", [])
        if isinstance(assignment, dict)
    )


async def parse_static_course_calendar(
    course_url: str,
    html: str,
    fallback_course_name: str,
    resolved_course_url: str | None = None,
) -> dict | None:
    """Try the deterministic UW/generic course calendar parser before using AI."""
    related_course_url = resolved_course_url or course_url
    base_url = urljoin(related_course_url, ".")
    main_soup = BeautifulSoup(html, "html.parser")
    title_tag = main_soup.find("title")
    course_name = title_tag.get_text(strip=True) if title_tag else fallback_course_name
    default_year = infer_default_year(course_url)
    meeting_patterns = extract_meeting_patterns(main_soup)
    calendar_events = []
    assignment_events = parse_course_assignments(main_soup, default_year)
    include_common_paths = should_probe_common_course_paths(main_soup, related_course_url)

    async with httpx.AsyncClient(
        follow_redirects=True,
        timeout=COURSE_FETCH_TIMEOUT,
        headers=COURSE_REQUEST_HEADERS,
    ) as client:
        try:
            response = await get_course_html(client, urljoin(base_url, "events_source.json"))
            if response.status_code == 200:
                data = response.json()
                if "eventSources" in data:
                    calendar_events = _parse_events_source_json(data)
        except Exception:
            pass

        if not calendar_events:
            calendar_events = parse_supported_calendar_soup(
                main_soup,
                default_year,
                meeting_patterns,
            )
            calendar_events.extend(
                await fetch_ical_events_from_soup(client, main_soup, related_course_url)
            )

        for related_url, related_html in await fetch_related_course_pages(
            client,
            main_soup,
            related_course_url,
            include_common_paths=include_common_paths,
        ):
            related_soup = BeautifulSoup(related_html, "html.parser")
            assignment_events.extend(parse_course_assignments(related_soup, default_year))
            found_calendar_events = parse_supported_calendar_soup(
                related_soup,
                default_year,
                meeting_patterns,
            )
            found_calendar_events.extend(
                await fetch_ical_events_from_soup(client, related_soup, related_url)
            )
            if found_calendar_events:
                calendar_events.extend(found_calendar_events)
                candidate_title = related_soup.find("title")
                if candidate_title and course_name == fallback_course_name:
                    course_name = candidate_title.get_text(strip=True)

    has_timed_class_events = any(
        event.get("event_kind") == "class_event" and event.get("all_day") is not True
        for event in calendar_events
    )
    if not has_timed_class_events and meeting_patterns:
        calendar_events.extend(expand_recurring_meeting_patterns(course_url, meeting_patterns))

    if not calendar_events:
        calendar_events = _html_fallback(main_soup, datetime.now().year)

    calendar_events.extend(assignment_events)

    if not calendar_events:
        return None

    parsed_data = convert_calendar_events_to_unified(calendar_events, course_name, course_url)
    if not parsed_data["class_events"] and not parsed_data["assignments"]:
        return None

    return parsed_data


async def fetch_course_page_with_url(course_url: str) -> tuple[str, str]:
    """Fetch course page HTML and return the final URL after redirects."""
    try:
        async with httpx.AsyncClient(
            follow_redirects=True,
            timeout=COURSE_FETCH_TIMEOUT,
            headers=COURSE_REQUEST_HEADERS,
        ) as client:
            response = await get_course_html(client, course_url)
            return response.text, str(response.url)
    except httpx.TimeoutException as e:
        message = str(e) or type(e).__name__
        raise HTTPException(
            status_code=504,
            detail=(
                f"Timed out connecting to {course_url}. "
                "The UW course site did not respond; wait a few minutes and try again. "
                f"({message})"
            ),
        )
    except httpx.ConnectError as e:
        message = str(e) or type(e).__name__
        raise HTTPException(
            status_code=504,
            detail=(
                f"Could not connect to {course_url}. "
                "Check your network or try again later. "
                f"({message})"
            ),
        )
    except Exception as e:
        message = str(e) or type(e).__name__
        raise HTTPException(status_code=400, detail=f"Could not fetch {course_url}: {message}")


async def fetch_course_page(course_url: str) -> str:
    """Fetch course page HTML."""
    html, _resolved_url = await fetch_course_page_with_url(course_url)
    return html


async def fetch_course_context_for_llm(
    course_url: str,
    html: str,
    resolved_course_url: str | None = None,
) -> str:
    """Build a compact multi-page context for LLM fallback parsing."""
    main_soup = BeautifulSoup(html, "html.parser")
    related_course_url = resolved_course_url or course_url
    sections = [
        f"Source URL: {course_url}\n{preprocess_html_for_llm(html, max_chars=7000)}"
    ]

    async with httpx.AsyncClient(
        follow_redirects=True,
        timeout=COURSE_FETCH_TIMEOUT,
        headers=COURSE_REQUEST_HEADERS,
    ) as client:
        related_pages = await fetch_related_course_pages(
            client,
            main_soup,
            related_course_url,
            max_pages=MAX_RELATED_PAGES,
        )

    for related_url, related_html in related_pages:
        page_text = preprocess_html_for_llm(related_html, max_chars=5000)
        if page_text:
            sections.append(f"Source URL: {related_url}\n{page_text}")

    return "\n\n---\n\n".join(sections)


# JSON schema for Ollama structured outputs. Passed as the `format` field
# so the model is constrained to emit valid unified-format JSON at decode
# time, not just instructed to via prompt.
LLM_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "class_events": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "event_name": {"type": "string"},
                    "event_type": {
                        "type": "string",
                        "enum": [
                            "lecture",
                            "lab",
                            "section",
                            "discussion",
                            "exam",
                            "office_hours",
                        ],
                    },
                    "date": {"type": "string"},
                    "start_time": {"type": ["string", "null"]},
                    "end_time": {"type": ["string", "null"]},
                    "location": {"type": ["string", "null"]},
                    "description": {"type": ["string", "null"]},
                },
                "required": ["event_name", "event_type", "date"],
            },
        },
        "assignments": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "assignment_name": {"type": "string"},
                    "assignment_type": {
                        "type": "string",
                        "enum": [
                            "homework",
                            "project",
                            "exam",
                            "quiz",
                            "lab",
                            "reading",
                        ],
                    },
                    "due_date": {"type": "string"},
                    "due_time": {"type": ["string", "null"]},
                    "points": {"type": ["integer", "null"]},
                    "description": {"type": "string"},
                    "submission_method": {"type": ["string", "null"]},
                    "requirements": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "is_individual": {"type": "boolean"},
                    "is_group": {"type": "boolean"},
                    "late_policy": {"type": ["string", "null"]},
                    "estimated_minutes": {"type": ["integer", "null"]},
                },
                "required": [
                    "assignment_name",
                    "assignment_type",
                    "due_date",
                    "description",
                ],
            },
        },
    },
    "required": ["class_events", "assignments"],
}

# Tags that never contain schedule data and just add token cost.
_HTML_NOISE_TAGS = (
    "script", "style", "nav", "footer", "header",
    "noscript", "iframe", "svg", "form",
)
_HTML_NOISE_CLASS_RE = re.compile(
    r"\b(nav|menu|sidebar|footer|header|breadcrumb)\b",
    re.IGNORECASE,
)


def preprocess_html_for_llm(html: str, max_chars: int = 16000) -> str:
    """Prune navigation/script noise from HTML before sending to the LLM.

    NEXT-EVAL benchmarks show extraction accuracy jumps sharply when
    the input is pruned rather than raw HTML or naive tag-stripped text.
    Block-level newlines preserve table/list structure the model uses
    to associate dates with assignment titles.
    """
    soup = BeautifulSoup(html, "html.parser")

    for tag_name in _HTML_NOISE_TAGS:
        for element in soup.find_all(tag_name):
            element.decompose()

    for element in soup.find_all(class_=_HTML_NOISE_CLASS_RE):
        element.decompose()

    text = soup.get_text("\n", strip=True)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]+", " ", text)

    return text[:max_chars]


def infer_quarter_dates(course_url: str) -> tuple[str, str] | None:
    """Infer (start_date, end_date) for the academic quarter from URL fragments
    like /26sp/ (Spring 2026), /25au/ (Autumn 2025).

    UW quarters approximate:
      - Winter (wi): early Jan -> mid March
      - Spring (sp): late March -> early June
      - Summer (su): mid June -> mid August
      - Autumn (au): late September -> early December
    """
    match = re.search(r"/(\d{2})(wi|sp|su|au|fa)\b", course_url, re.IGNORECASE)
    if not match:
        return None
    year = 2000 + int(match.group(1))
    season = match.group(2).lower()
    ranges = {
        "wi": ((1, 6), (3, 18)),
        "sp": ((3, 28), (6, 7)),
        "su": ((6, 20), (8, 22)),
        "au": ((9, 24), (12, 12)),
        "fa": ((9, 24), (12, 12)),
    }
    (sm, sd), (em, ed) = ranges[season]
    return f"{year}-{sm:02d}-{sd:02d}", f"{year}-{em:02d}-{ed:02d}"


async def parse_with_ollama(html: str, course_name: str, course_url: str = "") -> dict:
    """Parse course HTML with Hermes 3 via schema-enforced structured outputs."""
    text = preprocess_html_for_llm(html, max_chars=24000)
    today = datetime.now().strftime("%Y-%m-%d")
    quarter = infer_quarter_dates(course_url)
    quarter_line = (
        f"Academic quarter runs from {quarter[0]} to {quarter[1]}.\n"
        if quarter else ""
    )

    prompt = f"""Extract every course event from this page into the schema.

Today is {today}. Course: {course_name}.
{quarter_line}
Rules:
- Times must use 24h HH:MM (e.g. "23:59"). Use null when no time is given.
- Never output TBD, TBA, unknown, or "to be determined" as a name.
- If a lecture/section/lab has no listed topic, name it only by type ("Lecture", "Section").
- Use every Source URL section; schedule and assignment details may be on linked pages.
- assignment_type must be one of: homework, project, exam, quiz, lab, reading.
- event_type must be one of: lecture, lab, section, discussion, exam, office_hours.
{ESTIMATE_AI_GUIDANCE}

Recurring schedules:
- If the page only describes a recurring pattern like "MWF 10:30-11:20" or
  "Tue/Thu 1:30-3:20" without specific dates, EXPAND it into one entry per
  occurrence between the quarter start and end above.
- Skip US federal holidays and Thanksgiving/Veterans Day breaks if mentioned.
- Use 24h start_time and end_time exactly as written; do not invent times.

Example input snippet:
  "Lectures: MWF 10:30-11:20am, GUG 220
   HW1 due Friday 04/10/26 by 11:59pm
   Midterm: Wednesday May 13"

Example correct extraction (abbreviated):
  class_events: [
    {{"event_name":"Lecture","event_type":"lecture","date":"2026-03-30",
      "start_time":"10:30","end_time":"11:20","location":"GUG 220","description":null}},
    {{"event_name":"Lecture","event_type":"lecture","date":"2026-04-01",
      "start_time":"10:30","end_time":"11:20","location":"GUG 220","description":null}},
    {{"event_name":"Midterm","event_type":"exam","date":"2026-05-13",
      "start_time":null,"end_time":null,"location":null,"description":null}}
  ]
  assignments: [
    {{"assignment_name":"HW1","assignment_type":"homework","due_date":"2026-04-10",
      "due_time":"23:59","points":null,"description":"HW1 due Friday 04/10/26 by 11:59pm",
      "submission_method":null,"requirements":[],"is_individual":true,"is_group":false,
      "late_policy":null,"estimated_minutes":300}}
  ]

Page content:
{text}
"""

    try:
        host = (settings.ollama_host or "http://localhost:11434").rstrip("/")
        # Course extraction needs strict JSON output, not tool calling, so use
        # the course-import model instead of the chat-service default.
        model = (settings.course_import_model or "hermes3").strip()
        async with httpx.AsyncClient(timeout=180) as client:
            response = await client.post(
                f"{host}/api/generate",
                json={
                    "model": model,
                    "prompt": prompt,
                    "stream": False,
                    "format": LLM_RESPONSE_SCHEMA,
                    "options": {"temperature": 0},
                },
            )

        if response.status_code != 200:
            raise HTTPException(status_code=500, detail=f"Ollama error: {response.text}")

        result = response.json()
        response_text = result.get("response", "")
        return parse_ollama_json(response_text)

    except httpx.ConnectError:
        raise HTTPException(
            status_code=503,
            detail=(
                "Ollama server not reachable at "
                f"{settings.ollama_host}. "
                "Start local Ollama (ollama serve) or point OLLAMA_HOST to a Colab tunnel."
            ),
        )
    except httpx.TimeoutException:
        raise HTTPException(
            status_code=504,
            detail=(
                "Course AI parsing timed out. Try a specific quarter URL like "
                "https://courses.cs.washington.edu/courses/cse391/26sp/ "
                "or retry after Ollama is idle."
            ),
        )


def convert_to_unified_format(
    parsed_data: dict,
    course_url: str,
) -> tuple[list[UnifiedAssignment], list[UnifiedClassEvent], list[str]]:
    """Convert Ollama's unified format to our models."""
    course_name = parsed_data.get("course_name", "Unknown Course")
    assignments = []
    class_events = []
    warnings = []

    # Create UnifiedAssignment objects from Ollama's output
    for raw_assignment in parsed_data.get("assignments", []):
        try:
            if not isinstance(raw_assignment, dict):
                warnings.append(f"Skipped malformed assignment: {raw_assignment}")
                continue

            if not is_valid_iso_date(raw_assignment.get("due_date")):
                warnings.append(
                    f"Skipped assignment with invalid due_date: {raw_assignment.get('assignment_name', 'Unknown')}"
                )
                continue

            # Ensure required fields are set
            raw_assignment["source_url"] = course_url
            raw_assignment["course_name"] = raw_assignment.get("course_name", course_name)
            raw_assignment["assignment_name"] = clean_assignment_name(
                raw_assignment.get("assignment_name", "")
            )
            if not raw_assignment["assignment_name"]:
                warnings.append("Skipped assignment with placeholder title")
                continue
            raw_assignment["assignment_type"] = raw_assignment.get(
                "assignment_type"
            ) or infer_assignment_type(raw_assignment["assignment_name"])
            raw_assignment["requirements"] = raw_assignment.get("requirements") or []
            estimated_minutes = coerce_estimated_minutes(
                raw_assignment.get("estimated_minutes"),
                assignment_type=raw_assignment.get("assignment_type"),
            )
            raw_assignment["estimated_minutes"] = estimated_minutes or estimate_assignment_minutes(
                raw_assignment["assignment_name"],
                raw_assignment["assignment_type"],
                raw_assignment.get("description", ""),
                raw_assignment["requirements"],
                raw_assignment.get("points"),
            )
            assignment = UnifiedAssignment(**raw_assignment)
            assignments.append(assignment)
        except Exception as e:
            warnings.append(
                f"Skipped assignment {raw_assignment.get('assignment_name', 'Unknown')}: {e}"
            )
            print(f"Error parsing assignment: {raw_assignment} - {e}")

    # Create UnifiedClassEvent objects from Ollama's output
    for raw_event in parsed_data.get("class_events", []):
        try:
            if not isinstance(raw_event, dict):
                warnings.append(f"Skipped malformed event: {raw_event}")
                continue

            if not is_valid_iso_date(raw_event.get("date")):
                warnings.append(
                    f"Skipped event with invalid date: {raw_event.get('event_name', 'Class Event')}"
                )
                continue

            # Ensure required fields are set
            raw_event["source_url"] = course_url
            raw_event["course_name"] = raw_event.get("course_name", course_name)
            raw_event["event_type"] = raw_event.get("event_type") or infer_event_type(
                raw_event.get("event_name", "")
            )
            raw_event["event_name"] = clean_event_title(
                raw_event.get("event_name", ""),
                raw_event["event_type"],
                raw_event.get("course_name"),
            )
            event = UnifiedClassEvent(**raw_event)
            class_events.append(event)
        except Exception as e:
            warnings.append(f"Skipped event {raw_event.get('event_name', 'Class Event')}: {e}")
            print(f"Error parsing event: {raw_event} - {e}")

    return assignments, class_events, warnings


async def save_to_calendar(
    user_id: str,
    assignments: list[UnifiedAssignment],
    class_events: list[UnifiedClassEvent],
) -> dict:
    """Save unified format events to calendar (Supabase).

    This function extracts information from unified events and saves to database.
    Currently a placeholder - will be connected to Supabase.
    """
    result = {
        "assignments_imported": 0,
        "assignments_failed": 0,
        "class_events_imported": 0,
        "class_events_failed": 0,
        "details": [],
    }

    # Save assignments
    for assignment in assignments:
        try:
            # TODO: Save to Supabase tasks table
            # supabase.table("tasks").insert({
            #     "user_id": user_id,
            #     "title": assignment.assignment_name,
            #     "due_date": assignment.due_date,
            #     "description": assignment.description,
            #     ...
            # }).execute()

            result["assignments_imported"] += 1
            result["details"].append(f"✅ {assignment.assignment_name} ({assignment.course_name})")
        except Exception as e:
            result["assignments_failed"] += 1
            result["details"].append(f"❌ {assignment.assignment_name}: {str(e)}")

    # Save class events
    for event in class_events:
        try:
            # TODO: Save to Supabase events table
            # supabase.table("events").insert({
            #     "user_id": user_id,
            #     "title": event.event_name,
            #     "start_time": f"{event.date}T{event.start_time}",
            #     "end_time": f"{event.date}T{event.end_time}",
            #     ...
            # }).execute()

            result["class_events_imported"] += 1
            result["details"].append(f"✅ {event.event_name} ({event.course_name})")
        except Exception as e:
            result["class_events_failed"] += 1
            result["details"].append(f"❌ {event.event_name}: {str(e)}")

    result["total_imported"] = result["assignments_imported"] + result["class_events_imported"]
    return result


@router.post("/", response_model=CourseImportResponse)
async def import_course(course_url: str) -> CourseImportResponse:
    """Import course using AI parsing and unified format."""
    parse_warnings: list[str] = []
    requested_course_url = course_url
    course_url = normalize_course_url(course_url)
    if course_url != requested_course_url:
        parse_warnings.append(f"Using current UW quarter URL: {course_url}")

    # 1. Fetch course page
    html, resolved_course_url = await fetch_course_page_with_url(course_url)

    # 2. Extract course name from URL
    course_name = course_url.rstrip("/").split("/")[-2]

    # 3. Prefer deterministic calendar parsing, then fall back to Ollama AI
    parsed_data = await parse_static_course_calendar(
        course_url,
        html,
        course_name,
        resolved_course_url,
    )
    if parsed_data is None:
        context_text = await fetch_course_context_for_llm(course_url, html, resolved_course_url)
        parsed_data = await parse_with_ollama(context_text, course_name, course_url)
    elif (
        settings.course_import_ai_augment
        or should_augment_with_ai(parsed_data)
        or should_augment_assignment_estimates_with_ai(parsed_data)
    ):
        context_text = await fetch_course_context_for_llm(course_url, html, resolved_course_url)
        try:
            ai_data = await parse_with_ollama(context_text, course_name, course_url)
            parsed_data = merge_parsed_course_data(parsed_data, ai_data)
        except HTTPException as exc:
            parse_warnings.append(f"AI augmentation skipped: {exc.detail}")

    # 4. Convert to unified format
    assignments, class_events, warnings = convert_to_unified_format(parsed_data, course_url)
    warnings = [*parse_warnings, *warnings]

    # 5. Deduplicate
    unique_assignments = deduplicate_course_import_assignments(
        deduplicate_assignments(assignments)
    )
    unique_class_events = deduplicate_course_import_class_events(
        deduplicate_class_events(class_events)
    )

    # 6. Convert to dict for response
    class_events_dict = [ev.model_dump() for ev in unique_class_events]
    assignments_dict = [asn.model_dump() for asn in unique_assignments]

    return CourseImportResponse(
        course_url=course_url,
        course_name=parsed_data.get("course_name", course_name),
        assignments_imported=len(unique_assignments),
        class_events_imported=len(unique_class_events),
        total_imported=len(unique_assignments) + len(unique_class_events),
        class_events=class_events_dict,
        assignments=assignments_dict,
        warnings=warnings,
    )

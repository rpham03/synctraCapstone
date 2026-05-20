"""Simplified course import using Ollama AI and unified format."""
import httpx
import json
import re
from datetime import datetime
from urllib.parse import urljoin
from bs4 import BeautifulSoup, NavigableString, Tag
from fastapi import APIRouter, HTTPException
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

router = APIRouter(tags=["course-import"])

ASSIGNMENT_DUE_RE = re.compile(r"\b(?:due|deadline)\b", re.IGNORECASE)
CALENDAR_LINK_RE = re.compile(r"\b(?:calendar|schedule)\b", re.IGNORECASE)
ASSIGNMENT_LINK_RE = re.compile(r"\b(?:assignments?|homework|hw)\b", re.IGNORECASE)
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
]


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


def infer_assignment_type(title: str) -> str:
    """Infer assignment type from a calendar title."""
    lower_title = title.lower()
    if "project" in lower_title:
        return "project"
    if "quiz" in lower_title:
        return "quiz"
    if "lab" in lower_title:
        return "lab"
    if "reading" in lower_title:
        return "reading"
    if any(term in lower_title for term in ("exam", "midterm", "final")):
        return "exam"
    return "homework"


def clean_calendar_text(text: str) -> str:
    """Normalize whitespace in scraped calendar labels."""
    return re.sub(r"\s+", " ", text).strip()


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
    clean_title = clean_schedule_assignment_title(title)
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


def parse_course_assignments(soup, default_year: int) -> list[dict]:
    """Run all deterministic assignment extractors for a course page."""
    events = []
    events.extend(parse_assignment_cards(soup))
    events.extend(parse_due_table_assignments(soup))
    events.extend(parse_schedule_table_assignments(soup, default_year))
    events.extend(parse_assignment_cards_with_date_context(soup, default_year))
    events.extend(parse_inline_due_assignments(soup, default_year))

    deduped = []
    seen = set()
    for event in events:
        key = (event["title"], event["start_time"], event.get("all_day"))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(event)

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


def parse_supported_calendar_soup(soup) -> list[dict]:
    """Parse known deterministic calendar formats from a BeautifulSoup document."""
    if _has_monthtable(soup):
        return _parse_monthtable(soup)

    return parse_grid_calendar(soup)


def calendar_event_to_unified(
    event: dict,
    course_name: str,
    course_url: str,
) -> tuple[dict | None, dict | None]:
    """Convert a deterministic calendar event into assignment or class-event dicts."""
    title = event.get("title", "Class Event")

    try:
        start_dt = datetime.fromisoformat(event["start_time"])
        end_dt = datetime.fromisoformat(event.get("end_time", event["start_time"]))
    except (KeyError, TypeError, ValueError):
        return None, None

    all_day = event.get("all_day") is True
    start_time = start_dt.strftime("%H:%M")
    end_time = end_dt.strftime("%H:%M")

    if event.get("event_kind") == "assignment" or ASSIGNMENT_DUE_RE.search(title):
        return {
            "assignment_name": title,
            "assignment_type": infer_assignment_type(title),
            "due_date": start_dt.date().isoformat(),
            "due_time": None if all_day else start_time,
            "points": None,
            "description": event.get("description", ""),
            "submission_method": None,
            "requirements": [],
            "is_individual": True,
            "is_group": False,
            "late_policy": None,
            "course_name": course_name,
            "source_url": course_url,
        }, None

    return None, {
        "event_name": title,
        "event_type": event.get("event_type") or infer_event_type(title),
        "date": start_dt.date().isoformat(),
        "start_time": None if all_day else start_time,
        "end_time": None if all_day else end_time,
        "location": None,
        "description": None,
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


async def parse_static_course_calendar(
    course_url: str,
    html: str,
    fallback_course_name: str,
) -> dict | None:
    """Try the deterministic UW/generic course calendar parser before using AI."""
    base_url = urljoin(course_url, ".")
    main_soup = BeautifulSoup(html, "html.parser")
    title_tag = main_soup.find("title")
    course_name = title_tag.get_text(strip=True) if title_tag else fallback_course_name
    default_year = infer_default_year(course_url)
    calendar_events = []
    assignment_events = parse_course_assignments(main_soup, default_year)

    async with httpx.AsyncClient(
        follow_redirects=True,
        timeout=20,
        headers={"User-Agent": "Mozilla/5.0 (compatible; Syntra/1.0)"},
    ) as client:
        try:
            response = await client.get(urljoin(base_url, "events_source.json"))
            if response.status_code == 200:
                data = response.json()
                if "eventSources" in data:
                    calendar_events = _parse_events_source_json(data)
        except Exception:
            pass

        if not calendar_events:
            calendar_events = parse_supported_calendar_soup(main_soup)

        if not calendar_events:
            candidate_urls = []
            seen_urls = set()

            def add_candidate(url: str) -> None:
                if url not in seen_urls:
                    seen_urls.add(url)
                    candidate_urls.append(url)

            for link in main_soup.find_all("a", href=True):
                href = link["href"]
                text = link.get_text(" ", strip=True)
                if CALENDAR_LINK_RE.search(href) or CALENDAR_LINK_RE.search(text):
                    add_candidate(urljoin(course_url, href))

            for path in _CALENDAR_CANDIDATES:
                add_candidate(urljoin(base_url, path))

            for candidate_url in candidate_urls:
                try:
                    response = await client.get(candidate_url)
                    if response.status_code != 200:
                        continue

                    calendar_soup = BeautifulSoup(response.text, "html.parser")
                    assignment_events.extend(parse_course_assignments(calendar_soup, default_year))
                    calendar_events = parse_supported_calendar_soup(calendar_soup)
                    if calendar_events:
                        candidate_title = calendar_soup.find("title")
                        if candidate_title:
                            course_name = candidate_title.get_text(strip=True)
                        break
                except Exception:
                    continue

        assignment_candidate_urls = []
        seen_assignment_urls = set()

        def add_assignment_candidate(url: str) -> None:
            if url not in seen_assignment_urls:
                seen_assignment_urls.add(url)
                assignment_candidate_urls.append(url)

        for link in main_soup.find_all("a", href=True):
            href = link["href"]
            text = link.get_text(" ", strip=True)
            if ASSIGNMENT_LINK_RE.search(href) or ASSIGNMENT_LINK_RE.search(text):
                add_assignment_candidate(urljoin(course_url, href))

        for path in ASSIGNMENT_PAGE_CANDIDATES:
            add_assignment_candidate(urljoin(base_url, path))

        for candidate_url in assignment_candidate_urls:
            try:
                response = await client.get(candidate_url)
                if response.status_code != 200:
                    continue

                assignment_soup = BeautifulSoup(response.text, "html.parser")
                found_assignments = parse_course_assignments(assignment_soup, default_year)
                if found_assignments:
                    assignment_events.extend(found_assignments)
                    break
            except Exception:
                continue

    if not calendar_events:
        calendar_events = _html_fallback(main_soup, datetime.now().year)

    calendar_events.extend(assignment_events)

    if not calendar_events:
        return None

    parsed_data = convert_calendar_events_to_unified(calendar_events, course_name, course_url)
    if not parsed_data["class_events"] and not parsed_data["assignments"]:
        return None

    return parsed_data


async def fetch_course_page(course_url: str) -> str:
    """Fetch course page HTML."""
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=15) as client:
            response = await client.get(course_url)
            response.raise_for_status()
            return response.text
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Could not fetch {course_url}: {str(e)}")


async def parse_with_ollama(html: str, course_name: str) -> dict:
    """Parse course HTML with Ollama AI."""
    # Extract text from HTML (remove tags)
    text = re.sub(r'<[^>]+>', ' ', html)
    text = re.sub(r'\s+', ' ', text)[:8000]  # Limit to 8000 chars

    prompt = f"""Extract ALL course events from this course page and return in UNIFIED FORMAT.

IMPORTANT: Extract ACTUAL CALENDAR DATES from the page, not URL fragments.
Only include events or assignments with explicit dates in YYYY-MM-DD format.
If an item only has a quarter code like 26sp, a day of week, or a recurring time, omit it.

Course: {course_name}
Text:
{text}

Return ONLY valid JSON (no markdown, no code blocks) with UnifiedClassEvent and UnifiedAssignment format:

For class_events (lectures, labs, sections, exams, etc.):
{{
  "event_name": "Lecture 1" or "Lab A" or "Midterm Exam",
  "event_type": "lecture|lab|section|discussion|exam|office_hours",
  "date": "YYYY-MM-DD",
  "start_time": "HH:MM" (24h format) or null when no start time is shown,
  "end_time": "HH:MM" (24h format) or null when no end time is shown,
  "location": "room name" or "Online" or null,
  "description": "brief description" or null,
  "course_name": "{course_name}",
  "source_url": "the course url"
}}

For assignments (homework, projects, quizzes, etc.):
{{
  "assignment_name": "HW1" or "Project 2",
  "assignment_type": "homework|project|exam|quiz|lab|reading",
  "due_date": "YYYY-MM-DD",
  "due_time": "HH:MM" (24h format) or null when no due time is shown,
  "points": integer or null,
  "description": "full description",
  "submission_method": "Canvas|email|in-person" or null,
  "requirements": ["requirement 1", "requirement 2"],
  "is_individual": true or false,
  "is_group": true or false,
  "late_policy": "10% per day" or null,
  "course_name": "{course_name}",
  "source_url": "the course url"
}}

Return JSON with arrays of actual extracted items. Use empty arrays when no items are found.
Do not include placeholders, ellipses, comments, or trailing commas.
Do not invent midnight or 00:00 for missing times. Use null for missing times.
When a lecture/lab/section row includes both a start and an end time, include both times exactly.
{{
  "course_name": "{course_name}",
  "class_events": [],
  "assignments": []
}}
"""

    try:
        async with httpx.AsyncClient(timeout=180) as client:
            response = await client.post(
                "http://localhost:11434/api/generate",
                json={
                    "model": "mistral",
                    "prompt": prompt,
                    "stream": False,
                    "format": "json",
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
            detail="Ollama server not running. Start with: ollama serve",
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

    # 1. Fetch course page
    html = await fetch_course_page(course_url)

    # 2. Extract course name from URL
    course_name = course_url.rstrip("/").split("/")[-2]

    # 3. Prefer deterministic calendar parsing, then fall back to Ollama AI
    parsed_data = await parse_static_course_calendar(course_url, html, course_name)
    if parsed_data is None:
        parsed_data = await parse_with_ollama(html, course_name)

    # 4. Convert to unified format
    assignments, class_events, warnings = convert_to_unified_format(parsed_data, course_url)

    # 5. Deduplicate
    unique_assignments = deduplicate_assignments(assignments)
    unique_class_events = deduplicate_class_events(class_events)

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

"""
Hybrid parser: Regex + ChatGPT with intelligent caching.

Strategy:
1. Try fast regex parsing first (free, instant)
2. Score confidence level
3. Only use ChatGPT for low-confidence cases
4. Cache results to avoid re-parsing
"""

import json
import hashlib
import re
import time
from datetime import datetime
from typing import Optional
from pydantic import BaseModel

from .openai_assignment_parser import parse_course_events_with_chatgpt


class ParsingResult(BaseModel):
    """Result with metadata about which method was used."""
    method: str  # "regex_only", "chatgpt", "hybrid"
    confidence: float  # 0.0-1.0
    assignments: list[dict]
    class_events: list[dict]
    tokens_used: int
    processing_time_ms: int


class SimpleAssignment(BaseModel):
    """Simple assignment extracted by regex."""
    name: str
    type: str
    due_date: str
    due_time: Optional[str]
    confidence: float


_parse_cache: dict[str, ParsingResult] = {}


def cache_key(text: str) -> str:
    """Generate cache key from text hash."""
    return hashlib.md5(text.encode()).hexdigest()


def _extract_simple_assignments(text: str) -> list[SimpleAssignment]:
    """Extract high-confidence assignments using regex only."""
    assignments = []
    pattern = r'((?:HW|Homework|Assignment|Project|Quiz|Lab|Exam|Midterm|Final)\s*\d+)\s+due\s+([A-Za-z\d\s\-,]+?)(?:\s+by\s+(\d{1,2}:\d{2}\s*[AP]M))?(?:\s*$|[;\n])'

    for match in re.finditer(pattern, text, re.IGNORECASE | re.MULTILINE):
        name = match.group(1).strip()
        date_str = match.group(2).strip()
        time_str = match.group(3)

        try:
            from dateutil import parser as dateparser
            parsed_date = dateparser.parse(date_str)
            if parsed_date:
                assignments.append(SimpleAssignment(
                    name=name,
                    type=_classify_assignment_type(name),
                    due_date=parsed_date.strftime("%Y-%m-%d"),
                    due_time=_parse_time_string(time_str),
                    confidence=0.95,
                ))
        except:
            pass

    return assignments


def _classify_assignment_type(name: str) -> str:
    """Classify assignment type from name."""
    lower = name.lower()
    if 'hw' in lower or 'homework' in lower:
        return 'homework'
    elif 'project' in lower:
        return 'project'
    elif 'quiz' in lower:
        return 'quiz'
    elif 'exam' in lower or 'midterm' in lower or 'final' in lower:
        return 'exam'
    elif 'lab' in lower:
        return 'lab'
    else:
        return 'assignment'


def _parse_time_string(time_str: Optional[str]) -> Optional[str]:
    """Convert time string to 24h format."""
    if not time_str:
        return None

    try:
        from datetime import datetime as dt
        parsed = dt.strptime(time_str.strip(), "%I:%M %p")
        return parsed.strftime("%H:%M")
    except:
        return None


def _score_confidence(text: str, regex_results: list[SimpleAssignment]) -> float:
    """Score how confident we are that regex alone is sufficient."""
    confidence = 0.5

    if regex_results and all(r.confidence > 0.85 for r in regex_results):
        confidence += 0.3

    if re.search(r'\d{1,2}:\d{2}\s*(?:AM|PM|am|pm)', text):
        confidence -= 0.2

    if len(re.findall(r'\(.*?due.*?\)', text, re.IGNORECASE)) > 1:
        confidence -= 0.3

    if re.search(r'\b(next|this|last)\s+(monday|tuesday|wednesday|thursday|friday|week)', text, re.IGNORECASE):
        confidence -= 0.15

    return max(0.0, min(1.0, confidence))


async def parse_with_hybrid_approach(
    text: str,
    course_name: str = "Course",
    ai_threshold: float = 0.75,
    use_cache: bool = True,
) -> ParsingResult:
    """
    Hybrid parsing: Fast regex first, ChatGPT only if needed.

    Args:
        text: Course website text
        course_name: Course name for context
        ai_threshold: Confidence threshold for using ChatGPT
        use_cache: Whether to use cache for repeated parsing

    Returns:
        ParsingResult with method used and results
    """
    start_time = time.time()

    # Check cache
    key = cache_key(text)
    if use_cache and key in _parse_cache:
        return _parse_cache[key]

    # Phase 1: Try fast regex parsing
    regex_assignments = _extract_simple_assignments(text)
    regex_confidence = _score_confidence(text, regex_assignments)

    # Phase 2: Decide if we need ChatGPT
    if regex_confidence < ai_threshold:
        # Use ChatGPT for complex cases
        ai_result = parse_course_events_with_chatgpt(text, course_name)
        tokens_used = 800

        result = ParsingResult(
            method="hybrid",
            confidence=0.95,
            assignments=[a.model_dump() for a in ai_result.assignments],
            class_events=[e.model_dump() for e in ai_result.class_events],
            tokens_used=tokens_used,
            processing_time_ms=int((time.time() - start_time) * 1000),
        )
    else:
        # Regex is sufficient
        result = ParsingResult(
            method="regex_only",
            confidence=regex_confidence,
            assignments=[
                {
                    "assignment_name": a.name,
                    "assignment_type": a.type,
                    "due_date": a.due_date,
                    "due_time": a.due_time,
                    "confidence": a.confidence,
                }
                for a in regex_assignments
            ],
            class_events=[],
            tokens_used=0,
            processing_time_ms=int((time.time() - start_time) * 1000),
        )

    # Cache result
    if use_cache:
        _parse_cache[key] = result

    return result

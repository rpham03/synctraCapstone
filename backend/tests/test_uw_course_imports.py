"""End-to-end import validation across the UW CSE course list.

Run with the backend already running on http://localhost:8000 and Ollama
serving hermes3:

    cd backend
    python tests/test_uw_course_imports.py [QUARTER]

QUARTER defaults to "26sp". Examples: 26sp, 25au, 26wi.

The script POSTs each course URL through /api/v1/course-import/ and prints
a per-course summary plus an overall success rate. A course is considered
"successful" when at least one class_event OR one assignment is returned.

This is a runner, not a pytest test, because it hits a live backend + LLM.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
import time
from dataclasses import dataclass

import httpx


COURSE_NUMBERS = [
    "121", "122", "123", "163",
    "311", "312", "331", "332", "333", "341", "344", "351", "369",
    "371", "373", "391",
    "401", "413", "415", "421", "444", "455", "457", "478", "484",
    "510", "512", "525",
]

BACKEND_BASE = "http://localhost:8000"
IMPORT_ENDPOINT = f"{BACKEND_BASE}/api/v1/course-import/"
DEFAULT_QUARTER = "26sp"
PER_COURSE_TIMEOUT_S = 300
DEFAULT_DELAY_S = 2.5


@dataclass
class Result:
    course: str
    url: str
    success: bool
    class_events: int
    assignments: int
    warnings: int
    elapsed_s: float
    error: str | None = None


def course_url(number: str, quarter: str) -> str:
    return f"https://courses.cs.washington.edu/courses/cse{number}/{quarter}/"


async def import_one(client: httpx.AsyncClient, number: str, quarter: str) -> Result:
    url = course_url(number, quarter)
    start = time.monotonic()
    try:
        resp = await client.post(
            IMPORT_ENDPOINT,
            params={"course_url": url},
            timeout=PER_COURSE_TIMEOUT_S,
        )
        elapsed = time.monotonic() - start
        if resp.status_code != 200:
            return Result(
                course=f"CSE {number}",
                url=url,
                success=False,
                class_events=0,
                assignments=0,
                warnings=0,
                elapsed_s=elapsed,
                error=f"HTTP {resp.status_code}: {resp.text[:160]}",
            )
        data = resp.json()
        class_events = int(data.get("class_events_imported", 0))
        assignments = int(data.get("assignments_imported", 0))
        warnings = len(data.get("warnings", []))
        success = (class_events + assignments) > 0
        return Result(
            course=f"CSE {number}",
            url=url,
            success=success,
            class_events=class_events,
            assignments=assignments,
            warnings=warnings,
            elapsed_s=elapsed,
        )
    except Exception as exc:
        return Result(
            course=f"CSE {number}",
            url=url,
            success=False,
            class_events=0,
            assignments=0,
            warnings=0,
            elapsed_s=time.monotonic() - start,
            error=f"{type(exc).__name__}: {exc}",
        )


def print_row(result: Result) -> None:
    status = "OK " if result.success else "FAIL"
    base = (
        f"[{status}] {result.course:<8} "
        f"events={result.class_events:<3} "
        f"assn={result.assignments:<3} "
        f"warn={result.warnings:<2} "
        f"{result.elapsed_s:5.1f}s"
    )
    if result.error:
        base += f"  -> {result.error}"
    print(base, flush=True)


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("quarter", nargs="?", default=DEFAULT_QUARTER)
    parser.add_argument(
        "--concurrency", type=int, default=1,
        help="Parallel import requests. Keep at 1 for UW/Ollama-friendly validation.",
    )
    parser.add_argument(
        "--delay", type=float, default=DEFAULT_DELAY_S,
        help="Seconds to wait after each import request.",
    )
    parser.add_argument(
        "--filter", default=None,
        help="Only run courses whose number contains this substring (e.g. 333).",
    )
    args = parser.parse_args()

    numbers = [n for n in COURSE_NUMBERS if args.filter is None or args.filter in n]
    print(f"Importing {len(numbers)} courses for quarter {args.quarter} "
          f"via {IMPORT_ENDPOINT}")
    print("-" * 80)

    semaphore = asyncio.Semaphore(args.concurrency)
    results: list[Result] = []

    async with httpx.AsyncClient() as client:
        async def runner(num: str) -> None:
            async with semaphore:
                result = await import_one(client, num, args.quarter)
                results.append(result)
                print_row(result)
                if args.delay > 0:
                    await asyncio.sleep(args.delay)

        await asyncio.gather(*(runner(n) for n in numbers))

    print("-" * 80)
    total = len(results)
    succeeded = sum(1 for r in results if r.success)
    rate = (succeeded / total * 100) if total else 0.0
    total_events = sum(r.class_events for r in results)
    total_assn = sum(r.assignments for r in results)

    print(f"\nSummary: {succeeded}/{total} succeeded ({rate:.1f}%)")
    print(f"Total class events: {total_events}   Total assignments: {total_assn}")

    failures = [r for r in results if not r.success]
    if failures:
        print(f"\nFailures ({len(failures)}):")
        for r in failures:
            err = r.error or "0 items extracted"
            print(f"  - {r.course:<8} {err}")

    target = 85.0
    print(f"\nTarget: {target}%   Actual: {rate:.1f}%   "
          f"{'PASS' if rate >= target else 'NEEDS REFINEMENT'}")
    return 0 if rate >= target else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

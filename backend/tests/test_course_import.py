from datetime import datetime

from bs4 import BeautifulSoup

from app.api.v1.routes.course_import import (
    calendar_event_to_unified,
    clean_event_title,
    deduplicate_course_import_class_events,
    deduplicate_course_import_assignments,
    estimate_assignment_minutes,
    discover_related_course_links,
    extract_meeting_patterns,
    infer_current_uw_quarter,
    merge_parsed_course_data,
    normalize_course_url,
    parse_ical_calendar_events,
    parse_calendar_table_events,
    parse_course_assignments,
    parse_due_table_assignments,
    parse_time_range,
    should_augment_assignment_estimates_with_ai,
    should_probe_common_course_paths,
)
from app.api.v1.routes.unified_course_format import UnifiedAssignment, UnifiedClassEvent


def test_parse_due_table_assignments_uses_direct_row_date_for_today():
    soup = BeautifulSoup(
        """
        <table>
          <tr>
            <td>02/06/2026</td>
            <td>In-class exercise</td>
            <td></td>
            <td class="due">git-bisect in-class exercise (<b>due today by 11:59pm</b>)</td>
          <tr>
            <td>02/11/2026</td>
            <td>Guest speaker</td>
            <td></td>
            <td class="due">
              Attendance required to individually submit your guest speaker learning
              (<b>due today by 11:59pm</b>)
              <br><br>
              <a>Beta release</a> (<b>due Tues 02/17/26 by 11:59pm</b>)
            </td>
          </tr>
        </table>
        """,
        "html.parser",
    )

    events = parse_due_table_assignments(soup)

    assert [(event["title"], event["start_time"]) for event in events] == [
        ("git-bisect in-class exercise", "2026-02-06T23:59:00"),
        (
            "Attendance required to individually submit your guest speaker learning",
            "2026-02-11T23:59:00",
        ),
        ("Beta release", "2026-02-17T23:59:00"),
    ]


def test_parse_due_table_assignments_preserves_empty_due_time():
    soup = BeautifulSoup(
        """
        <table>
          <tr>
            <td>03/01/2026</td>
            <td></td>
            <td></td>
            <td class="due">Reading report (<b>due 03/01/26</b>)</td>
          </tr>
        </table>
        """,
        "html.parser",
    )

    event = parse_due_table_assignments(soup)[0]
    assignment, class_event = calendar_event_to_unified(
        event,
        "CSE 403",
        "https://courses.cs.washington.edu/courses/cse403/26wi/",
    )

    assert class_event is None
    assert assignment["assignment_name"] == "Reading report"
    assert assignment["due_date"] == "2026-03-01"
    assert assignment["due_time"] is None


def test_parse_course_assignments_uses_previous_schedule_row_date():
    soup = BeautifulSoup(
        """
        <table class="course-calendar">
          <tr><th>Date</th><th>Topic</th><th>Assignment</th></tr>
          <tr><td>Tue 03/31</td><td>Lecture</td><td></td></tr>
          <tr><td></td><td>Released C0 Hello Bugs I.S. by 11:59pm PT</td><td></td></tr>
          <tr><td>Fri 04/17</td><td>Lecture</td><td></td></tr>
          <tr><td></td><td>Released R0 Resub 0 C0, P0 Due 11:59pm PT</td></tr>
        </table>
        """,
        "html.parser",
    )

    events = parse_course_assignments(soup, 2026)

    assert [(event["title"], event["start_time"]) for event in events] == [
        ("C0 Hello Bugs", "2026-03-31T23:59:00"),
        ("R0 Resub 0 C0, P0", "2026-04-17T23:59:00"),
    ]


def test_parse_course_assignments_supports_assignment_tables():
    soup = BeautifulSoup(
        """
        <table>
          <tr><th>Pset (pdf)</th><th>Release date</th><th>Due date</th></tr>
          <tr><td>Pset 1(pdf)</td><td>April 1</td><td>Wed Apr 8, 11:59 pm</td></tr>
        </table>
        <table>
          <tr><th>Date</th><th>Assignment</th></tr>
          <tr><td>April 10</td><td>HW1 - RA, HeapFiles, Buffer Manager</td></tr>
        </table>
        """,
        "html.parser",
    )

    events = parse_course_assignments(soup, 2026)

    assert [(event["title"], event["start_time"], event["all_day"]) for event in events] == [
        ("Pset 1", "2026-04-08T23:59:00", False),
        ("HW1 - RA, HeapFiles, Buffer Manager", "2026-04-10T00:00:00", True),
    ]


def test_parse_course_assignments_supports_assignment_due_date_headers():
    soup = BeautifulSoup(
        """
        <table>
          <tr><th>Assignment</th><th>Due Date</th></tr>
          <tr><td>Homework 1</td><td>Wed Apr. 8 at 11:59 PM</td></tr>
          <tr><td>Homework 2</td><td>Wed Apr. 15 at 11:59 PM</td></tr>
        </table>
        """,
        "html.parser",
    )

    events = parse_course_assignments(soup, 2026)

    assert [(event["title"], event["start_time"], event["all_day"]) for event in events] == [
        ("Homework 1", "2026-04-08T23:59:00", False),
        ("Homework 2", "2026-04-15T23:59:00", False),
    ]


def test_parse_course_assignments_supports_schedule_due_rows():
    soup = BeautifulSoup(
        """
        <table>
          <tr><td>Mon, Mar 30</td><td>Lecture</td><td>Welcome</td><td></td></tr>
          <tr><td>Project</td><td>Deques</td><td>due Apr 15</td></tr>
        </table>
        <table>
          <tr><th>DATE</th><th>LECTURE TITLE</th><th>HW DUE DATES</th></tr>
          <tr><td>04/01/2026</td><td>Anatomy</td><td>Knowledge Survey</td></tr>
          <tr><td>04/27/2026</td><td>Control</td><td>Localization Project Due (April 28th)</td></tr>
        </table>
        """,
        "html.parser",
    )

    events = parse_course_assignments(soup, 2026)

    assert [(event["title"], event["start_time"], event["all_day"]) for event in events] == [
        ("Project Deques", "2026-04-15T00:00:00", True),
        ("Knowledge Survey", "2026-04-01T00:00:00", True),
        ("Localization Project", "2026-04-28T00:00:00", True),
    ]


def test_parse_course_assignments_supports_inline_homework_due_text():
    soup = BeautifulSoup(
        """
        <main>
          Homework Output Comparison Tool
          Homework 7 (mini-Idle) Due Monday, May 25, 11:00pm.
          Homework 6 (relations, random art) Due Thursday, May 14, 11:00pm.
        </main>
        """,
        "html.parser",
    )

    events = parse_course_assignments(soup, 2026)

    assert [(event["title"], event["start_time"]) for event in events] == [
        ("Homework 7 (mini-Idle)", "2026-05-25T23:00:00"),
        ("Homework 6 (relations, random art)", "2026-05-14T23:00:00"),
    ]


def test_parse_course_assignments_supports_calendar_assignment_due_cards():
    soup = BeautifulSoup(
        """
        <main>
          <div class="MuiPaper-root">
            <h2>Sun Apr 19</h2>
            <h2>Assignment Due</h2>
            <p>Assignment: Project Proposal</p>
          </div>
          <div class="MuiPaper-root">
            <h2>Fri May 15</h2>
            <h2>Assignment Due</h2>
            <p>Assignment: Contribution Reflection</p>
            <p>Assignment: Method Reflection</p>
          </div>
        </main>
        """,
        "html.parser",
    )

    events = parse_course_assignments(soup, 2026)

    assert [(event["title"], event["start_time"], event["all_day"]) for event in events] == [
        ("Project Proposal", "2026-04-19T00:00:00", True),
        ("Contribution Reflection", "2026-05-15T00:00:00", True),
        ("Method Reflection", "2026-05-15T00:00:00", True),
    ]


def test_parse_course_assignments_supports_label_due_calendar():
    soup = BeautifulSoup(
        """
        <main id="calendar">
          <p>All assignments are <strong>due at 11pm</strong> on the specified date.</p>
          <div><dl><dt>Apr 7<dd><strong class="label label-red">P1 Due</strong></dd></dt></dl></div>
          <div><dl><dt>May 16<dd><strong class="label label-red">Artifact Pitch Due</strong></dd></dt></dl></div>
        </main>
        """,
        "html.parser",
    )

    events = parse_course_assignments(soup, 2026)

    assert [(event["title"], event["start_time"]) for event in events] == [
        ("P1", "2026-04-07T23:00:00"),
        ("Artifact Pitch", "2026-05-16T23:00:00"),
    ]


def test_clean_event_title_removes_tbd_placeholder():
    assert clean_event_title("Lecture — TBD", "lecture") == "Lecture"
    assert clean_event_title("TBD", "section") == "Section"
    assert clean_event_title("Lecture", "lecture", "CSE 446") == "Lecture — CSE446"
    assert clean_event_title("Lecture — TBD", "lecture", "CSE 333") == "Lecture — CSE333"
    assert clean_event_title("Lecture — — TBD", "lecture", "CSE 446") == "Lecture — CSE446"
    assert clean_event_title("Lecture — — CSE446", "lecture", "CSE 446") == "Lecture — CSE446"


def test_calendar_event_to_unified_removes_tbd_placeholder():
    assignment, class_event = calendar_event_to_unified(
        {
            "title": "Lecture — TBD",
            "event_kind": "class_event",
            "event_type": "lecture",
            "start_time": "2026-05-20T11:30:00",
            "end_time": "2026-05-20T12:20:00",
            "all_day": False,
        },
        "CSE 333",
        "https://courses.cs.washington.edu/courses/cse333/26sp/",
    )

    assert assignment is None
    assert class_event["event_name"] == "Lecture — CSE333"


def test_discover_related_course_links_scores_same_course_pages():
    soup = BeautifulSoup(
        """
        <a href="calendar.html">Weekly Calendar</a>
        <a href="assignments/">Assignments</a>
        <a href="syllabus.html">Syllabus</a>
        <a href="https://example.com/calendar.html">External calendar</a>
        <a href="staff.html">Staff</a>
        <a href="files/spec.pdf">Spec PDF</a>
        """,
        "html.parser",
    )

    links = discover_related_course_links(
        soup,
        "https://courses.cs.washington.edu/courses/cse333/26sp/",
        max_links=10,
    )

    assert "https://courses.cs.washington.edu/courses/cse333/26sp/calendar.html" in links
    assert "https://courses.cs.washington.edu/courses/cse333/26sp/assignments" in links
    assert "https://courses.cs.washington.edu/courses/cse333/26sp/syllabus.html" in links
    assert all("example.com" not in link for link in links)
    assert all(not link.endswith(".pdf") for link in links)


def test_should_probe_common_course_paths_when_nav_is_js_generated():
    soup = BeautifulSoup(
        """
        <script src="site/js/config.js"></script>
        <a href="./resources/syllabus.html">Syllabus</a>
        <a href="./resources/styleguide.html">Style Guide</a>
        """,
        "html.parser",
    )

    assert should_probe_common_course_paths(
        soup,
        "https://courses.cs.washington.edu/courses/cse421/26sp/",
    )


def test_parse_ical_calendar_events_extracts_course_calendar_rows():
    events = parse_ical_calendar_events(
        b"""BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
SUMMARY:421 Lecture
DESCRIPTION:Logistics\\, Stable Matching
DTSTART:20260330T133000
DTEND:20260330T142000
LOCATION:CSE2 G20
UID:test-lecture
X-CREATECAL-EVENTTYPE:lecture
END:VEVENT
END:VCALENDAR
""",
        "https://courses.cs.washington.edu/courses/cse421/26sp/calendar/calendar-lecture-A.ics",
    )

    assert events == [{
        "id": "test-lecture",
        "title": "421 Lecture",
        "start_time": "2026-03-30T13:30:00",
        "end_time": "2026-03-30T14:20:00",
        "source": "course",
        "is_fixed": True,
        "event_kind": "class_event",
        "event_type": "lecture",
        "description": "Logistics, Stable Matching",
        "location": "CSE2 G20",
        "all_day": False,
    }]


def test_deduplicate_course_import_assignments_collapses_hw_aliases():
    base = {
        "assignment_type": "homework",
        "due_date": "2026-04-08",
        "due_time": "23:59",
        "points": None,
        "description": "",
        "submission_method": None,
        "requirements": [],
        "is_individual": True,
        "is_group": False,
        "late_policy": None,
        "course_name": "cse421",
        "source_url": "https://courses.cs.washington.edu/courses/cse421/26sp/",
    }

    assignments = [
        UnifiedAssignment(**base, assignment_name="HW1"),
        UnifiedAssignment(**base, assignment_name="Homework 1"),
    ]

    unique = deduplicate_course_import_assignments(assignments)

    assert [assignment.assignment_name for assignment in unique] == ["HW1"]


def test_deduplicate_course_import_assignments_collapses_lab_demo_variants():
    base = {
        "assignment_type": "lab",
        "due_date": "2026-05-22",
        "points": None,
        "submission_method": None,
        "requirements": [],
        "is_individual": True,
        "is_group": False,
        "late_policy": None,
        "course_name": "CSE 331",
        "source_url": "https://courses.cs.washington.edu/courses/cse331/26sp/",
    }

    assignments = [
        UnifiedAssignment(
            **base,
            assignment_name="Lab 7 Demo",
            due_time=None,
            description="",
            estimated_minutes=120,
        ),
        UnifiedAssignment(
            **base,
            assignment_name="Lab 7 Demos",
            due_time="23:59",
            description="Demo Lab 7 functionality to course staff.",
            estimated_minutes=240,
        ),
    ]

    unique = deduplicate_course_import_assignments(assignments)

    assert len(unique) == 1
    assert unique[0].assignment_name == "Lab 7 Demos"
    assert unique[0].estimated_minutes == 240
    assert unique[0].due_time == "23:59"


def test_deduplicate_course_import_class_events_collapses_duplicate_lectures():
    base = {
        "event_type": "lecture",
        "date": "2026-05-18",
        "start_time": "09:30",
        "end_time": "10:20",
        "location": None,
        "description": None,
        "course_name": "CSE 333",
        "source_url": "https://courses.cs.washington.edu/courses/cse333/26sp/",
    }

    events = [
        UnifiedClassEvent(**base, event_name="Lecture"),
        UnifiedClassEvent(
            **{**base, "description": "Virtual Memory"},
            event_name="Lecture — Virtual Memory",
        ),
    ]

    unique = deduplicate_course_import_class_events(events)

    assert [event.event_name for event in unique] == ["Lecture — Virtual Memory"]


def test_estimate_assignment_minutes_uses_assignment_complexity():
    assert estimate_assignment_minutes("Reading 4", "reading") == 90
    assert estimate_assignment_minutes("HW3", "homework") == 240
    assert estimate_assignment_minutes("Lab 2", "lab") == 180
    assert estimate_assignment_minutes(
        "Final Project Report",
        "project",
        "Implement model, run experiments, and write report.",
        ["code", "experiments", "writeup"],
    ) == 720


def test_merge_parsed_course_data_uses_ai_assignment_estimate():
    primary = {
        "course_name": "CSE 331",
        "class_events": [],
        "assignments": [{
            "assignment_name": "HW1",
            "assignment_type": "homework",
            "due_date": "2026-04-10",
            "due_time": None,
            "description": "",
            "estimated_minutes": 180,
        }],
    }
    secondary = {
        "course_name": "CSE 331",
        "class_events": [],
        "assignments": [{
            "assignment_name": "Homework 1",
            "assignment_type": "homework",
            "due_date": "2026-04-10",
            "due_time": "23:59",
            "description": "Problems 1-8 plus written reflection.",
            "requirements": ["Problems 1-8", "reflection"],
            "estimated_minutes": 240,
        }],
    }

    merged = merge_parsed_course_data(primary, secondary)

    assert merged["assignments"][0]["estimated_minutes"] == 240
    assert merged["assignments"][0]["due_time"] == "23:59"
    assert merged["assignments"][0]["description"] == "Problems 1-8 plus written reflection."
    assert merged["assignments"][0]["requirements"] == ["Problems 1-8", "reflection"]


def test_should_augment_assignment_estimates_with_ai_for_homework_and_labs():
    assert should_augment_assignment_estimates_with_ai({
        "assignments": [
            {"assignment_name": "Lab 2", "assignment_type": "lab", "due_date": "2026-04-10"}
        ],
        "class_events": [],
    })
    assert not should_augment_assignment_estimates_with_ai({
        "assignments": [],
        "class_events": [],
    })


def test_parse_calendar_table_events_applies_homepage_lecture_meeting_time():
    home_soup = BeautifulSoup(
        """
        <main>
          <h3>Lectures</h3>
          <p>MWF 12:30 PM - 1:20 PM, AND 205</p>
        </main>
        """,
        "html.parser",
    )
    calendar_soup = BeautifulSoup(
        """
        <table>
          <tr><th>Week</th><th>Date</th><th>Type</th><th>Description</th></tr>
          <tr><td rowspan="3">1</td><td>Mon, Mar 30</td><td>Lecture</td><td>Introduction</td></tr>
          <tr><td>Wed, Apr 1</td><td>Lecture</td><td>SQL</td></tr>
          <tr><td>Fri, Apr 18</td><td>Lecture</td><td>Typo weekday still gets lecture time</td></tr>
        </table>
        """,
        "html.parser",
    )

    events = parse_calendar_table_events(
        calendar_soup,
        2026,
        extract_meeting_patterns(home_soup),
    )

    assert [(event["title"], event["start_time"], event["end_time"], event["location"]) for event in events] == [
        ("Lecture — Introduction", "2026-03-30T12:30:00", "2026-03-30T13:20:00", "AND 205"),
        ("Lecture — SQL", "2026-04-01T12:30:00", "2026-04-01T13:20:00", "AND 205"),
        (
            "Lecture — Typo weekday still gets lecture time",
            "2026-04-18T12:30:00",
            "2026-04-18T13:20:00",
            "AND 205",
        ),
    ]


def test_extract_meeting_patterns_handles_generic_400_level_homepage_formats():
    soup = BeautifulSoup(
        """
        <main>
          <p>Lectures:</p>
          <p>MWF 2:30-3:20 in CSE2 G10. Lectures will be recorded.</p>
          <p>Class: Tue/Thu 11:30am-12:50pm, CSE2 G01</p>
          <p>Course Time & Location</p>
          <p>Tuesdays & Thursdays, 10:00-11:20.</p>
          <p>Room G04.</p>
          <p>Location: Gates G20</p>
          <p>Time: Tu/Th 11:30-12:50</p>
        </main>
        """,
        "html.parser",
    )

    patterns = extract_meeting_patterns(soup)

    assert {
        (tuple(sorted(pattern["weekdays"])), pattern["start_time"], pattern["end_time"], pattern["location"])
        for pattern in patterns
    } >= {
        ((0, 2, 4), "14:30", "15:20", "CSE2 G10"),
        ((1, 3), "11:30", "12:50", "CSE2 G01"),
        ((1, 3), "10:00", "11:20", "Gates G20"),
        ((1, 3), "11:30", "12:50", "Gates G20"),
    }
    assert parse_time_range("12:30-1:20") == ((12, 30), (13, 20))


def test_normalize_course_url_adds_current_quarter_for_uw_course_root():
    spring_2026 = datetime(2026, 5, 25)
    assert infer_current_uw_quarter(spring_2026) == "26sp"
    assert normalize_course_url("https://courses.cs.washington.edu/courses/cse391/", spring_2026) == (
        "https://courses.cs.washington.edu/courses/cse391/26sp/"
    )
    assert normalize_course_url("https://courses.cs.washington.edu/courses/cse391/26sp/", spring_2026) == (
        "https://courses.cs.washington.edu/courses/cse391/26sp/"
    )

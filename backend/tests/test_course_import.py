from bs4 import BeautifulSoup

from app.api.v1.routes.course_import import (
    calendar_event_to_unified,
    parse_course_assignments,
    parse_due_table_assignments,
)


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

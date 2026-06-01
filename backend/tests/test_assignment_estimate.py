"""Tests for below-average student assignment time estimates."""

from app.services.assignment_estimate import (
    coerce_estimated_minutes,
    estimate_assignment_minutes,
    estimate_canvas_assignment_minutes,
)


def test_coerce_enforces_type_floor_for_low_ai_estimates():
    # AI returned 90 min for homework — bump to homework floor (300).
    assert coerce_estimated_minutes(90, assignment_type="homework") == 300


def test_canvas_estimate_uses_generous_points_formula():
    minutes = estimate_canvas_assignment_minutes(
        {"name": "Problem Set 2", "points_possible": 50, "description": ""}
    )
    assert minutes >= 300


def test_homework_default_not_short():
    assert estimate_assignment_minutes("Homework 1") >= 300

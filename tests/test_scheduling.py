"""Scheduling correctness must not depend on the model, so it is tested directly."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from psok.db.repositories import CalendarRepository, TaskRepository
from psok.scheduling.engine import AmbiguousDate, find_conflicts, find_free_slot, resolve_date_hint
from psok.security.confirmation import ConfirmationService, auto_approve
from psok.tools.base import ToolContext
from psok.tools.builtin import tasks as task_tools

NOW = datetime(2026, 3, 10, 11, 0)  # a Tuesday


@pytest.mark.parametrize(
    "hint,expected_date",
    [
        ("today", "2026-03-10"),
        ("tomorrow", "2026-03-11"),
        ("in 3 days", "2026-03-13"),
        ("in 2 weeks", "2026-03-24"),
        ("friday", "2026-03-13"),
        ("next monday", "2026-03-16"),
    ],
)
def test_relative_hints_resolve_deterministically(hint, expected_date):
    assert resolve_date_hint(hint, now=NOW).strftime("%Y-%m-%d") == expected_date


def test_explicit_time_is_honoured():
    resolved = resolve_date_hint("tomorrow at 3pm", now=NOW)
    assert (resolved.hour, resolved.minute) == (15, 0)
    assert resolved.strftime("%Y-%m-%d") == "2026-03-11"


def test_same_weekday_means_next_week_not_today():
    assert resolve_date_hint("tuesday", now=NOW).strftime("%Y-%m-%d") == "2026-03-17"


def test_unresolvable_hint_raises_rather_than_guessing():
    with pytest.raises(AmbiguousDate):
        resolve_date_hint("sometime whenever", now=NOW)


def test_conflict_detection(db):
    repo = CalendarRepository()
    repo.create("standup", "2026-03-11T10:00:00", "2026-03-11T10:30:00")

    overlapping = find_conflicts(
        datetime(2026, 3, 11, 10, 15), datetime(2026, 3, 11, 11, 0), repo=repo
    )
    assert len(overlapping) == 1 and overlapping[0].title == "standup"

    assert not find_conflicts(datetime(2026, 3, 11, 11, 0), datetime(2026, 3, 11, 12, 0), repo=repo)


def test_free_slot_skips_busy_time(db):
    repo = CalendarRepository()
    day = datetime(2026, 3, 11, 9, 0)
    repo.create("blocked", day.isoformat(), (day + timedelta(hours=2)).isoformat())

    slot = find_free_slot(60, search_from=day, repo=repo)
    assert slot is not None and slot.starts_at >= day + timedelta(hours=2)


async def test_create_task_resolves_the_brief_example(db):
    """'Finish my ML assignment tomorrow' end to end."""
    result = await task_tools.create_task(
        {"title": "Finish ML assignment", "due_date_hint": "tomorrow"}, ToolContext()
    )
    assert not result.is_error

    row = TaskRepository().upcoming()[0]
    assert row["title"] == "Finish ML assignment"
    expected = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
    assert row["due_at"].startswith(expected)


async def test_create_task_reports_conflicts_instead_of_guessing(db):
    start = datetime.now().replace(hour=14, minute=0, second=0, microsecond=0) + timedelta(days=1)
    CalendarRepository().create(
        "existing", start.isoformat(), (start + timedelta(hours=1)).isoformat()
    )

    result = await task_tools.create_task(
        {
            "title": "Deep work",
            "scheduled_hint": start.strftime("%Y-%m-%d %H:%M"),
            "duration_estimate_minutes": 60,
        },
        ToolContext(),
    )
    assert result.is_error and "conflicts with" in result.content
    assert "existing" in result.content


async def test_ambiguous_date_asks_rather_than_inventing(db):
    result = await task_tools.create_task(
        {"title": "Something", "due_date_hint": "qwerty nonsense"}, ToolContext()
    )
    assert result.is_error and "Ask the user" in result.content


async def test_task_tools_go_through_the_permission_gate(db):
    """Scheduling is not special-cased: create_task confirms like any medium-risk write."""
    from psok.tools.registry import build_default_registry

    denied = []

    async def deny(request):
        denied.append(request.tool_name)
        return False

    registry = build_default_registry(ConfirmationService(deny))
    result = await registry.dispatch("create_task", {"title": "x"}, ToolContext())
    assert result.is_error and denied == ["create_task"]

    registry = build_default_registry(ConfirmationService(auto_approve))
    assert not (await registry.dispatch("list_upcoming", {}, ToolContext())).is_error

"""Schedule read model for assessment items."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass


@dataclass
class ScheduleWeek:
    """The scheduled assessment items for one numbered teaching week."""

    week: int
    items: list


@dataclass
class Schedule:
    """Owns schedule weeks and detached assessment display items."""

    project_id: str
    week_count: int
    weeks: list[ScheduleWeek]
    unscheduled: list

    @classmethod
    def empty(cls, project_id: str, week_count: int) -> Schedule:
        """Create an empty schedule with one container per teaching week."""
        if week_count < 1:
            raise ValueError("A schedule must contain at least one week.")
        return cls(
            project_id=project_id,
            week_count=week_count,
            weeks=[ScheduleWeek(number, []) for number in range(1, week_count + 1)],
            unscheduled=[],
        )

    def add_unscheduled(self, item: dict) -> None:
        """Append an item whose timing is not yet known."""
        self.unscheduled.append(deepcopy(item))

    def add_in_weeks(self, item: dict, start: int, end: int) -> None:
        """Place a detached item in every inclusive week of its timing range."""
        if not 1 <= start <= end <= self.week_count:
            raise ValueError("Assessment weeks are outside this schedule.")
        for number in range(start, end + 1):
            self.weeks[number - 1].items.append(deepcopy(item))

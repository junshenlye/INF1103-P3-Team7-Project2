from __future__ import annotations
from dataclasses import dataclass, field
from copy import deepcopy


@dataclass(eq=False)
class Schedule:
    """Owns primitive calendar values; never receives another domain object."""

    project_id: str
    week_count: int
    _weeks: dict = field(init=False, repr=False)
    _undated: list = field(default_factory=list, init=False, repr=False)

    def __post_init__(self):
        if type(self.week_count) is not int or self.week_count < 1:
            raise ValueError('A schedule needs a positive integer week count.')
        self._weeks = {number: [] for number in range(1, self.week_count + 1)}

    def add_undated(self, record):
        self._undated.append(deepcopy(record))

    def add_item(self, record, start, end):
        if type(start) is not int or type(end) is not int or not 1 <= start <= end <= self.week_count:
            raise ValueError("Assessment weeks are outside this schedule.")
        for number in range(start, end + 1):
            self._weeks[number].append(deepcopy(record))

    def to_record(self):
        return {
            'project_id': self.project_id,
            'week_count': self.week_count,
            'weeks': [{'week': number, 'items': deepcopy(items)} for number, items in self._weeks.items()],
            'unscheduled': deepcopy(self._undated),
        }

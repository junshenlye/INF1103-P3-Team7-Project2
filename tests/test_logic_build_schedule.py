"""Tests for building a project schedule from stored assessment rows."""

from types import SimpleNamespace
import unittest

from src.managers import LogicManager
from src.models.assessments import Schedule


def row(id, key, week=None, end_week=None, kind="assessment", module_id="m", **extra):
    return {
        "id": id,
        "result_id": "r",
        "module_id": module_id,
        "facts": {"key": key, "name": key.title(), "kind": kind, "week": week, "end_week": end_week},
        "evidence": {"name": ["source"]},
        **extra,
    }


def module(id="m", title="INF1103", position=0):
    return SimpleNamespace(id=id, module_title=title, position=position)


class BuildScheduleTests(unittest.TestCase):
    def setUp(self):
        self.logic = LogicManager()

    def test_places_rows_by_their_timing(self):
        rows = [
            row("a1", "quiz", week=3, end_week=4),
            row("a2", "exam", week=14),
            row("a3", "essay"),
            row("g1", "coursework", kind="group"),
        ]
        schedule = self.logic.build_schedule([module()], rows, 14, "p")

        self.assertIsInstance(schedule, Schedule)
        self.assertEqual(schedule.project_id, "p")
        self.assertEqual(len(schedule.weeks), 14)
        placed = {w.week: [i["assessment_id"] for i in w.items] for w in schedule.weeks if w.items}
        self.assertEqual(placed, {3: ["a1"], 4: ["a1"], 14: ["a2"]})
        self.assertEqual([i["assessment_id"] for i in schedule.unscheduled], ["a3"])

    def test_optional_parent_is_accepted_and_revision_is_carried(self):
        rows = [
            row("a1", "quiz", week=2),
            row("a2", "lab", week=2, parent_assessment_id="g1", revision=3),
        ]
        items = self.logic.build_schedule([module()], rows, 14, "p").weeks[1].items
        by_id = {item["assessment_id"]: item for item in items}
        self.assertEqual(by_id["a1"]["revision"], 0)
        self.assertEqual(by_id["a2"]["revision"], 3)

    def test_orders_by_module_position_then_key(self):
        rows = [
            row("a3", "alpha", week=5, module_id="m2"),
            row("a2", "zeta", week=5, module_id="m1"),
            row("a1", "beta", week=5, module_id="m1"),
        ]
        modules = [module("m2", "Second", 1), module("m1", "First", 0)]
        items = self.logic.build_schedule(modules, rows, 14, "p").weeks[4].items
        self.assertEqual([i["assessment_id"] for i in items], ["a1", "a2", "a3"])
        self.assertEqual([i["module_title"] for i in items], ["First", "First", "Second"])

    def test_rows_are_not_modified(self):
        rows = [row("a1", "quiz", week=3)]
        schedule = self.logic.build_schedule([module()], rows, 14, "p")
        schedule.weeks[2].items[0]["evidence"]["name"].append("changed")
        self.assertEqual(rows[0]["evidence"], {"name": ["source"]})

    def test_empty_rows_give_an_empty_schedule(self):
        schedule = self.logic.build_schedule([module()], [], 3, "p")
        self.assertEqual([w.items for w in schedule.weeks], [[], [], []])
        self.assertEqual(schedule.unscheduled, [])

    def test_unknown_kind_is_rejected(self):
        with self.assertRaises(ValueError):
            self.logic.build_schedule([module()], [row("a1", "quiz", kind="exam")], 14, "p")


if __name__ == "__main__":
    unittest.main()

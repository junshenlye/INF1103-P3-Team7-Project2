"""Tests for the assessment hierarchy and schedule building."""

from dataclasses import FrozenInstanceError, asdict
from types import SimpleNamespace
import unittest

from src.models.assessments import (
    Assessment,
    AssessmentCollection,
    AssessmentGroup,
    IndividualAssessment,
    Schedule,
)


def make_assessment(kind="assessment", week=3, end_week=5, id="a", module_id="m", key="quiz"):
    return Assessment.create(
        id,
        "r",
        module_id,
        {"key": key, "name": key.title(), "kind": kind, "week": week, "end_week": end_week},
        {"name": ["source"]},
    )


def module(id="m", title="INF1103", position=0):
    """Provide the module fields that schedule building reads."""
    return SimpleNamespace(id=id, module_title=title, position=position)


class AssessmentCreationTests(unittest.TestCase):
    def test_base_requires_a_concrete_scheduling_behaviour(self):
        with self.assertRaises(TypeError):
            Assessment("a", "r", "m", {}, {})

    def test_create_chooses_type_from_kind(self):
        self.assertIsInstance(make_assessment("assessment"), IndividualAssessment)
        self.assertIsInstance(make_assessment("group"), AssessmentGroup)

    def test_create_rejects_unknown_or_missing_kind(self):
        for facts in ({"kind": "exam"}, {}, None):
            with self.subTest(facts=facts):
                with self.assertRaises(ValueError):
                    Assessment.create("a", "r", "m", facts, {})

    def test_create_copies_caller_data_and_is_immutable(self):
        facts = {"key": "quiz", "name": "Quiz", "kind": "assessment", "week": 2, "end_week": None}
        evidence = {"name": ["source"]}
        assessment = Assessment.create("a", "r", "m", facts, evidence)
        facts["name"] = "Changed"
        evidence["name"].append("changed")
        self.assertEqual(assessment.facts["name"], "Quiz")
        self.assertEqual(assessment.evidence, {"name": ["source"]})
        with self.assertRaises(FrozenInstanceError):
            assessment.revision = 1


class AddToScheduleTests(unittest.TestCase):
    def test_tasks_unknown_timing_and_group_totals(self):
        cases = (
            ("assessment", 3, 5, [3, 4, 5], 0),
            ("assessment", 7, None, [7], 0),
            ("assessment", None, None, [], 1),
            ("group", None, None, [], 0),
        )
        for kind, week, end, weeks, unknown in cases:
            with self.subTest(kind=kind, week=week, end=end):
                assessment = make_assessment(kind, week, end)
                schedule = Schedule.empty("p", 14)
                before = asdict(assessment)
                assessment.add_to_schedule(schedule, "INF1103")
                self.assertEqual([w.week for w in schedule.weeks if w.items], weeks)
                self.assertEqual(len(schedule.unscheduled), unknown)
                self.assertEqual(asdict(assessment), before)

    def test_schedule_item_carries_identity_facts_and_evidence(self):
        item = make_assessment().schedule_item("INF1103")
        self.assertEqual(item["assessment_id"], "a")
        self.assertEqual(item["module_title"], "INF1103")
        self.assertEqual(item["name"], "Quiz")
        self.assertEqual(item["evidence"], {"name": ["source"]})
        self.assertEqual(item["revision"], 0)


class AssessmentCollectionTests(unittest.TestCase):
    def test_schedule_owns_copies_of_assessment_data(self):
        assessment = make_assessment()
        schedule = AssessmentCollection([assessment]).build_schedule([module()], 14, "p")
        schedule.weeks[2].items[0]["evidence"]["name"].append("changed")
        self.assertEqual(assessment.evidence, {"name": ["source"]})
        self.assertEqual(schedule.weeks[3].items[0]["evidence"], {"name": ["source"]})

    def test_orders_by_module_position_then_key(self):
        first = module("m1", "First", 0)
        second = module("m2", "Second", 1)
        assessments = [
            make_assessment(id="a3", module_id="m2", key="alpha", end_week=None),
            make_assessment(id="a2", module_id="m1", key="zeta", end_week=None),
            make_assessment(id="a1", module_id="m1", key="beta", end_week=None),
        ]
        schedule = AssessmentCollection(assessments).build_schedule([second, first], 14, "p")
        self.assertEqual(
            [item["assessment_id"] for item in schedule.weeks[2].items], ["a1", "a2", "a3"]
        )

    def test_out_of_range_weeks_are_rejected(self):
        collection = AssessmentCollection([make_assessment(week=12, end_week=15)])
        with self.assertRaises(ValueError):
            collection.build_schedule([module()], 14, "p")


if __name__ == "__main__":
    unittest.main()

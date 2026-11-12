"""Tests for the assessment schedule read model."""

import unittest

from src.models.assessments import Schedule


class ScheduleTests(unittest.TestCase):
    def test_empty_schedule_numbers_each_teaching_week(self):
        schedule = Schedule.empty("project-7", 3)

        self.assertEqual(schedule.project_id, "project-7")
        self.assertEqual([week.week for week in schedule.weeks], [1, 2, 3])
        self.assertEqual([week.items for week in schedule.weeks], [[], [], []])
        self.assertEqual(schedule.unscheduled, [])

    def test_add_in_weeks_copies_item_to_each_inclusive_week(self):
        schedule = Schedule.empty("project-7", 4)
        item = {"title": "Report", "evidence": {"page": 2}}

        schedule.add_in_weeks(item, 2, 3)
        item["evidence"]["page"] = 9

        self.assertEqual(schedule.weeks[1].items, [{"title": "Report", "evidence": {"page": 2}}])
        self.assertEqual(schedule.weeks[2].items, [{"title": "Report", "evidence": {"page": 2}}])
        self.assertEqual(schedule.weeks[0].items, [])
        self.assertEqual(schedule.weeks[3].items, [])

    def test_unscheduled_items_are_detached_from_caller_data(self):
        schedule = Schedule.empty("project-7", 2)
        item = {"title": "Presentation", "evidence": {"page": 5}}

        schedule.add_unscheduled(item)
        item["evidence"]["page"] = 8

        self.assertEqual(schedule.unscheduled, [{"title": "Presentation", "evidence": {"page": 5}}])

    def test_rejects_invalid_week_counts_and_ranges(self):
        with self.assertRaises(ValueError):
            Schedule.empty("project-7", 0)

        schedule = Schedule.empty("project-7", 2)
        for start, end in ((0, 1), (2, 1), (1, 3)):
            with self.subTest(start=start, end=end):
                with self.assertRaises(ValueError):
                    schedule.add_in_weeks({"title": "Report"}, start, end)


if __name__ == "__main__":
    unittest.main()

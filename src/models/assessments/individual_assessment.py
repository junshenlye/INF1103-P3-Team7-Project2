"""A single scheduled assessment task."""

from src.models.assessments.assessment import Assessment


class IndividualAssessment(Assessment):
    """A task appears in its stated weeks, or in the unknown-timing list."""

    def add_to_schedule(self, schedule, module_title):
        item = self.schedule_item(module_title)
        start = self.facts["week"]
        if start is None:
            schedule.add_unscheduled(item)
        else:
            end = self.facts.get("end_week") or start
            schedule.add_in_weeks(item, start, end)

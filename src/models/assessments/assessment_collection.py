"""A view over independently existing assessments, without owning their lifetime."""

from src.models.assessments.schedule import Schedule


class AssessmentCollection:
    """Build a project schedule from published assessments."""

    def __init__(self, assessments):
        self._assessments = tuple(assessments)

    def build_schedule(self, modules, week_count, project_id):
        """Return a new schedule with every assessment placed by its own rules.

        Assessments are added in module submission order, then by assessment
        key and id, so the same inputs always produce the same schedule.
        """
        by_module = {module.id: module for module in modules}
        schedule = Schedule.empty(project_id, week_count)
        ordered = sorted(
            self._assessments,
            key=lambda assessment: (
                by_module[assessment.module_id].position,
                assessment.facts["key"],
                assessment.id,
            ),
        )
        for assessment in ordered:
            assessment.add_to_schedule(schedule, by_module[assessment.module_id].module_title)
        return schedule

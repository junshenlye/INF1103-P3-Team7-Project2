"""A parent total that groups individual assessments."""

from src.models.assessments.assessment import Assessment


class AssessmentGroup(Assessment):
    """A parent total is kept for validation, but is never a scheduled task."""

    def add_to_schedule(self, schedule, module_title):
        # Scheduling the total would duplicate its individual child assessments.
        return None

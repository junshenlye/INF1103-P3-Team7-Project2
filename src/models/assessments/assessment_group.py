from src.models.assessments.assessment import Assessment


class AssessmentGroup(Assessment):
    """A parent total is persisted for validation, but is never a scheduled task."""

    def scheduling_span(self):
        # Scheduling the total would duplicate its individual child assessments.
        return None

from src.models.assessments.assessment import Assessment


class IndividualAssessment(Assessment):
    """A task appears in its stated weeks, or in the unknown-timing list."""

    def scheduling_span(self):
        start = self._facts['week']
        return (None, None) if start is None else (start, self._facts['end_week'] or start)

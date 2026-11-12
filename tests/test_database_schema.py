"""Keep the initial database schema consistent with the Python domain rules.

These checks read the SQL text, so they run without a database server.
"""

from pathlib import Path
import re
import unittest

from src.config import limits
from src.models.processing import lifecycle

SCHEMA = (
    Path(__file__).resolve().parents[1] / "database" / "migrations" / "001_initial.sql"
).read_text(encoding="utf-8")


def table(name):
    match = re.search(rf"CREATE TABLE {name} \((.*?)\n\);", SCHEMA, re.S)
    if match is None:
        raise AssertionError(f"Table {name} is not defined.")
    return match.group(1)


def column(table_name, column_name):
    for line in table(table_name).splitlines():
        if line.strip().startswith(f"{column_name} "):
            return line
    raise AssertionError(f"Column {table_name}.{column_name} is not defined.")


def allowed_values(table_name, column_name):
    match = re.search(r"IN\s*\(([^)]*)\)", column(table_name, column_name))
    return {value.strip().strip("'") for value in match.group(1).split(",")}


def between(table_name, column_name):
    match = re.search(r"BETWEEN (\d+) AND (\d+)", column(table_name, column_name))
    return int(match.group(1)), int(match.group(2))


class DatabaseSchemaTests(unittest.TestCase):
    def test_project_statuses_match_the_lifecycle(self):
        expected = {lifecycle.CREATED, lifecycle.PROCESSING, *lifecycle.TERMINAL_STATES}
        self.assertEqual(allowed_values("projects", "status"), expected)
        self.assertIn(f"DEFAULT '{lifecycle.CREATED}'", column("projects", "status"))

    def test_job_statuses_include_every_terminal_outcome(self):
        statuses = allowed_values("processing_jobs", "status")
        self.assertEqual(statuses - lifecycle.TERMINAL_STATES, {"queued", "running"})
        self.assertLessEqual(lifecycle.TERMINAL_STATES, statuses)

    def test_text_and_count_bounds_match_limits(self):
        cases = {
            ("projects", "name"): (1, limits.PROJECT_NAME_LENGTH),
            ("projects", "week_count"): (1, limits.WEEK_COUNT),
            ("modules", "module_title"): (1, limits.MODULE_TITLE_LENGTH),
            ("modules", "normalized_title"): (1, limits.MODULE_TITLE_LENGTH),
            ("modules", "credit"): (1, limits.CREDIT),
            ("modules", "position"): (0, limits.MODULE_COUNT - 1),
            ("documents", "filename"): (1, limits.DOCUMENT_NAME_LENGTH),
            ("documents", "size"): (1, limits.DOCUMENT_BYTES),
            ("parse_snapshots", "chunk_count"): (1, limits.MAX_CHUNK_COUNT),
            ("source_elements", "text"): (1, limits.MAX_CHUNK_BYTES),
        }
        for (table_name, column_name), expected in cases.items():
            with self.subTest(column=f"{table_name}.{column_name}"):
                self.assertEqual(between(table_name, column_name), expected)

    def test_submission_key_length_matches_its_pattern(self):
        low, high = re.search(r"\{(\d+),(\d+)\}$", limits.SUBMISSION_KEY_PATTERN).groups()
        self.assertEqual(between("processing_jobs", "submission_key"), (int(low), int(high)))

    def test_media_types_and_evidence_fields_match_limits(self):
        self.assertEqual(allowed_values("documents", "media_type"), set(limits.MEDIA_TYPES))
        self.assertEqual(allowed_values("assessment_evidence", "field"), set(limits.FACT_FIELDS))

    def test_published_records_are_append_only(self):
        for name in (
            "documents",
            "assessments",
            "assessment_evidence",
            "parse_snapshots",
            "source_elements",
            "review_revisions",
        ):
            with self.subTest(table=name):
                self.assertRegex(
                    SCHEMA,
                    rf"BEFORE UPDATE OR DELETE ON {name} FOR EACH ROW "
                    r"EXECUTE FUNCTION reject_mutation\(\);",
                )


if __name__ == "__main__":
    unittest.main()

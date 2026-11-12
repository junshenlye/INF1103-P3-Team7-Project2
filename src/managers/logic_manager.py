"""Deterministic validation rules for project submissions and extracted facts."""

from __future__ import annotations

import math
import re

from src.config import limits
from src.errors import error_codes
from src.errors.processing_error import ProcessingError
from src.schemas.create_project_request import CreateProjectRequest
from src.schemas.submit_module_request import SubmitModuleRequest


class LogicManager:
    """Validate user input without depending on HTTP, storage, or providers."""

    @staticmethod
    def _normalize_title(value: str) -> tuple[str, str]:
        display = " ".join(value.split())
        return display, display.casefold()

    def validate_project(self, raw: object) -> CreateProjectRequest:
        if not isinstance(raw, dict) or set(raw) != {"name", "week_count"}:
            raise ProcessingError(error_codes.INVALID_REQUEST, "Project metadata is incomplete.")
        name, weeks = raw["name"], raw["week_count"]
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= limits.PROJECT_NAME_LENGTH or type(weeks) is not int or not 1 <= weeks <= limits.WEEK_COUNT:
            raise ProcessingError(error_codes.INVALID_REQUEST, "Project name or week count is invalid.")
        return CreateProjectRequest(name.strip(), weeks)

    def validate_submission(self, raw: object, file_fields: object) -> tuple[SubmitModuleRequest, ...]:
        if not isinstance(raw, list) or not 1 <= len(raw) <= limits.MODULE_COUNT:
            raise ProcessingError(error_codes.INVALID_REQUEST, "Submit between one and the supported number of modules.")
        modules, titles, registered = [], set(), []
        for item in raw:
            if not isinstance(item, dict) or set(item) != {"module_title", "credit", "file_fields"}:
                raise ProcessingError(error_codes.INVALID_REQUEST, "Module metadata is incomplete.")
            title, credit, fields = item["module_title"], item["credit"], item["file_fields"]
            if not isinstance(title, str) or not 1 <= len(title.strip()) <= limits.MODULE_TITLE_LENGTH or type(credit) is not int or not 1 <= credit <= limits.CREDIT:
                raise ProcessingError(error_codes.INVALID_REQUEST, "Module title or credit is invalid.")
            display, normalized = self._normalize_title(title)
            if normalized in titles:
                raise ProcessingError(error_codes.DUPLICATE_MODULE, "Module titles must be distinct.", "module")
            if not isinstance(fields, list) or not 1 <= len(fields) <= limits.DOCUMENTS_PER_MODULE or any(not isinstance(field, str) or not re.fullmatch(limits.FIELD_NAME_PATTERN, field) for field in fields):
                raise ProcessingError(error_codes.INVALID_REQUEST, "Document fields are invalid.")
            titles.add(normalized); registered.extend(fields)
            modules.append(SubmitModuleRequest(display, normalized, credit, tuple(fields)))
        if not isinstance(file_fields, (list, tuple, set)) or len(set(registered)) != len(registered) or set(registered) != set(file_fields):
            raise ProcessingError(error_codes.INVALID_REQUEST, "Every upload must belong to exactly one module.")
        return tuple(modules)

    def validate_assessment_facts(self, record: dict, week_count: int) -> dict:
        """Check one extracted assessment record against the schedule rules.

        Every violated rule is collected so the error lists all of them at once.

        Raises:
            ProcessingError: ``invalid_extraction`` naming each invalid field.
        """
        violations = []

        def require(valid, field, rule):
            if not valid:
                violations.append(f"{field}: {rule}")

        key, name = record.get("key"), record.get("name")
        require(
            isinstance(key, str) and 1 <= len(key) <= limits.ASSESSMENT_KEY_LENGTH,
            "key",
            "use a nonempty bounded identity",
        )
        require(
            isinstance(name, str) and 1 <= len(name.strip()) <= limits.ASSESSMENT_NAME_LENGTH,
            "name",
            "use a nonempty bounded name",
        )
        require(record.get("kind") in ("assessment", "group"), "kind", "use assessment or group")
        require(
            record.get("weight_scope") in ("module", "group", "unknown"),
            "weight_scope",
            "use module, group or unknown",
        )
        weight = record.get("weight_percent")
        require(
            weight is None
            or (
                type(weight) in (int, float)
                and math.isfinite(weight)
                and 0 <= weight <= limits.WEIGHT_PERCENT
            ),
            "weight_percent",
            "use null or a number between 0 and 100",
        )
        for field in ("week", "end_week"):
            value = record.get(field)
            require(
                value is None or (type(value) is int and 1 <= value <= week_count),
                field,
                f"use null or an integer between 1 and {week_count}",
            )
        week, end = record.get("week"), record.get("end_week")
        if end is not None:
            require(
                type(week) is int and type(end) is int and end >= week,
                "end_week",
                "a range requires a start week and an end at or after it",
            )
        if record.get("kind") == "group":
            require(
                week is None and end is None,
                "kind",
                "a structural group cannot carry scheduled weeks; "
                "a timed assessment uses kind assessment",
            )
        parent = record.get("parent_key")
        require(
            parent is None
            or (
                isinstance(parent, str)
                and 1 <= len(parent) <= limits.ASSESSMENT_KEY_LENGTH
                and parent != key
            ),
            "parent_key",
            "use null or a distinct parent identity",
        )
        require(
            record.get("weight_scope") != "group" or parent is not None,
            "weight_scope",
            "a group-relative weight requires a parent",
        )
        if violations:
            raise ProcessingError(
                error_codes.INVALID_EXTRACTION,
                "Assessment validation failed — " + "; ".join(violations)[:430],
                "module",
            )
        return record

    def validate_source_references(self, assessment: dict, source_ids) -> dict:
        """Check that every populated fact cites evidence from the given sources.

        Raises:
            ProcessingError: ``invalid_extraction`` if evidence is malformed,
                cites an unknown source, or is missing for a populated fact.
        """
        evidence = assessment.get("evidence")
        if not isinstance(evidence, dict) or set(evidence) - limits.FACT_FIELDS:
            raise ProcessingError(
                error_codes.INVALID_EXTRACTION,
                "An assessment has invalid evidence references.",
                "module",
            )
        for field in limits.FACT_FIELDS:
            ids = evidence.get(field, [])
            if (
                not isinstance(ids, list)
                or len(ids) > limits.EVIDENCE_IDS_PER_FACT
                or any(not isinstance(i, str) or i not in source_ids for i in ids)
            ):
                raise ProcessingError(
                    error_codes.INVALID_EXTRACTION,
                    "Evidence is missing or belongs to another source.",
                    "module",
                )
            if assessment.get(field) is not None and not ids:
                raise ProcessingError(
                    error_codes.INVALID_EXTRACTION,
                    "Every populated fact needs source evidence.",
                    "module",
                )
        return assessment

    def validate_relationships(self, records: list[dict]) -> list[dict]:
        """Check parent links and weight totals after assessment facts are combined."""
        by_key = {r["key"]: r for r in records}
        if len(by_key) != len(records):
            raise ProcessingError(
                error_codes.INVALID_EXTRACTION,
                "Assessment keys must be unique before validating relationships.",
                "module",
            )
        children = {key: [] for key in by_key}
        roots = []
        for record in records:
            parent = record["parent_key"]
            if parent is None:
                roots.append(record["key"])
            elif parent not in by_key or by_key[parent]["kind"] != "group":
                raise ProcessingError(
                    error_codes.INVALID_EXTRACTION,
                    "An assessment parent is missing or invalid.",
                    "module",
                )
            else:
                children[parent].append(record["key"])
        # Every valid relationship forms a rooted forest. Visit children before
        # parents without Python recursion, even for deep provider output.
        order = []
        stack = list(roots)
        while stack:
            key = stack.pop()
            order.append(key)
            stack.extend(children[key])
        if len(order) != len(records):
            raise ProcessingError(
                error_codes.INVALID_EXTRACTION,
                "Assessment relationships contain a cycle.",
                "module",
            )
        module_weights = {}
        maximum = limits.WEIGHT_PERCENT + limits.WEIGHT_TOLERANCE
        for key in reversed(order):
            record = by_key[key]
            module_total = sum(module_weights[child] for child in children[key])
            group_total = sum(
                by_key[child]["weight_percent"] or 0
                for child in children[key]
                if by_key[child]["weight_scope"] == "group"
            )
            weight = record["weight_percent"]
            if record["weight_scope"] == "module" and weight is not None:
                if module_total > weight + limits.WEIGHT_TOLERANCE:
                    raise ProcessingError(
                        error_codes.INVALID_EXTRACTION,
                        "Child assessment weights exceed their parent total.",
                        "module",
                    )
                module_weights[key] = weight
            else:
                module_weights[key] = module_total
            if group_total > maximum:
                raise ProcessingError(
                    error_codes.INVALID_EXTRACTION,
                    "Assessment group weights exceed 100 percent.",
                    "module",
                )
        if sum(module_weights[key] for key in roots) > maximum:
            raise ProcessingError(
                error_codes.INVALID_EXTRACTION,
                "Assessment module weights exceed 100 percent.",
                "module",
            )
        return records

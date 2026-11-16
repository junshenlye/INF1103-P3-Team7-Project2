from __future__ import annotations

from src.config import limits
from src.errors import error_codes as errors

import math
import re

from src.errors.processing_error import ProcessingError
from copy import deepcopy
from dataclasses import replace
from src.models.assessments.individual_assessment import IndividualAssessment
from src.models.assessments.assessment_group import AssessmentGroup
from src.models.assessments.schedule import Schedule
from src.models.processing import lifecycle


class LogicManager:
    """Deterministic rules. No HTTP, files, SQL, provider calls or clocks."""

    FACT_FIELDS = limits.FACT_FIELDS

    @staticmethod
    def _normalize_module_title(value):
        display = " ".join(value.split())
        return display, display.casefold()

    def validate_project(self, raw):
        if not isinstance(raw, dict) or set(raw) != {"name", "week_count"}:
            raise ProcessingError(
                errors.INVALID_REQUEST, "Provide a project name and week count."
            )
        name = raw["name"]
        weeks = raw["week_count"]
        if (
            not isinstance(name, str)
            or not 1 <= len(name.strip()) <= limits.PROJECT_NAME_LENGTH
            or type(weeks) is not int
            or not 1 <= weeks <= limits.WEEK_COUNT
        ):
            raise ProcessingError(
                errors.INVALID_REQUEST,
                f"Use a name of 1–{limits.PROJECT_NAME_LENGTH} characters and 1–{limits.WEEK_COUNT} weeks.",
            )
        return {'name': name.strip(), 'week_count': weeks}

    def validate_submission(self, raw, file_fields):
        if not isinstance(raw, list) or not 1 <= len(raw) <= limits.MODULE_COUNT:
            raise ProcessingError(
                errors.INVALID_REQUEST,
                f"Submit between 1 and {limits.MODULE_COUNT} modules.",
            )
        modules = []
        titles = set()
        registered = []
        for item in raw:
            if not isinstance(item, dict) or set(item) != {
                "module_title",
                "credit",
                "file_fields",
            }:
                raise ProcessingError(
                    errors.INVALID_REQUEST, "Module metadata is incomplete."
                )
            title = item["module_title"]
            credit = item["credit"]
            fields = item["file_fields"]
            if (
                not isinstance(title, str)
                or not 1 <= len(title.strip()) <= limits.MODULE_TITLE_LENGTH
                or type(credit) is not int
                or not 1 <= credit <= limits.CREDIT
            ):
                raise ProcessingError(
                    errors.INVALID_REQUEST,
                    f"Use a module title and integer credits from 1 to {limits.CREDIT}.",
                )
            display_title, normalized = self._normalize_module_title(title)
            if normalized in titles:
                raise ProcessingError(
                    errors.DUPLICATE_MODULE, "Module titles must be distinct.", "module"
                )
            titles.add(normalized)
            if (
                not isinstance(fields, list)
                or not 1 <= len(fields) <= limits.DOCUMENTS_PER_MODULE
                or any(
                    not isinstance(f, str)
                    or not re.fullmatch(limits.FIELD_NAME_PATTERN, f)
                    for f in fields
                )
            ):
                raise ProcessingError(
                    errors.INVALID_REQUEST,
                    f"Each module needs 1–{limits.DOCUMENTS_PER_MODULE} named document fields.",
                )
            registered.extend(fields)
            modules.append({'module_title': display_title, 'normalized_title': normalized,
                            'credit': credit, 'file_fields': tuple(fields)})
        if len(set(registered)) != len(registered) or set(registered) != set(
            file_fields
        ):
            raise ProcessingError(
                errors.INVALID_REQUEST,
                "Every upload must belong to exactly one module.",
            )
        return tuple(modules)

    def validate_extraction(self, raw, module, source_ids, week_count):
        if not isinstance(raw, dict) or set(raw) != {
            "module_title",
            "assessments",
            "uncertainties",
        }:
            raise ProcessingError(
                errors.INVALID_EXTRACTION,
                "Assessment extraction has an invalid shape.",
                "module",
                module_id=module.id,
            )
        if (
            not isinstance(raw["module_title"], str)
            or self._normalize_module_title(raw["module_title"])[1]
            != module.normalized_title
        ):
            raise ProcessingError(
                errors.INVALID_EXTRACTION,
                "Extracted module identity does not match the submission.",
                "module",
                module_id=module.id,
            )
        records = raw["assessments"]
        uncertainties = raw["uncertainties"]
        if (
            not isinstance(records, list)
            or len(records) > limits.ASSESSMENTS_PER_CHUNK
            or not isinstance(uncertainties, list)
            or len(uncertainties) > limits.UNCERTAINTIES_PER_CHUNK
            or any(
                not isinstance(x, str) or len(x) > limits.UNCERTAINTY_LENGTH
                for x in uncertainties
            )
        ):
            raise ProcessingError(
                errors.INVALID_EXTRACTION,
                "Assessment extraction exceeds supported bounds.",
                "module",
                module_id=module.id,
            )
        validated = []
        for record in records:
            if not isinstance(record, dict) or set(record) != self.FACT_FIELDS | {
                "key",
                "evidence",
            }:
                raise ProcessingError(
                    errors.INVALID_EXTRACTION,
                    "An assessment has invalid fields.",
                    "module",
                    module_id=module.id,
                )
            self.validate_assessment_facts(record, week_count)
            self.validate_source_references(record, source_ids)
            validated.append(
                {
                    **record,
                    "evidence": {
                        k: sorted(set(v)) for k, v in record["evidence"].items()
                    },
                }
            )
        if len({r["key"] for r in validated}) != len(validated):
            raise ProcessingError(
                errors.INVALID_EXTRACTION,
                "Assessment keys must be unique within an extraction.",
                "module",
                module_id=module.id,
            )
        return validated, uncertainties

    def validate_assessment_facts(self, record, week_count):
        violations = []
        def require(valid, field, rule):
            if not valid:
                violations.append(f"{field}: {rule}")
        key, name = record.get('key'), record.get('name')
        require(isinstance(key, str) and 1 <= len(key) <= limits.ASSESSMENT_KEY_LENGTH, 'key', f'use an identity of 1–{limits.ASSESSMENT_KEY_LENGTH} characters')
        name_length = len(name.strip()) if isinstance(name, str) else None
        require(name_length is not None and 1 <= name_length <= limits.ASSESSMENT_NAME_LENGTH, 'name',
                f'use a source-supported short label of 1–{limits.ASSESSMENT_NAME_LENGTH} characters'
                + (f' (received {name_length}); omit task instructions and descriptions' if name_length is not None else ''))
        require(record.get('kind') in ('assessment', 'group'), 'kind', 'use assessment or group')
        require(record.get('weight_scope') in ('module', 'group', 'unknown'), 'weight_scope', 'use module, group or unknown')
        weight = record.get('weight_percent')
        require(weight is None or (type(weight) in (int, float) and math.isfinite(weight) and 0 <= weight <= limits.WEIGHT_PERCENT), 'weight_percent', 'use null or a number between 0 and 100')
        for field in ('week', 'end_week'):
            value = record.get(field)
            require(value is None or (type(value) is int and 1 <= value <= week_count), field, f'use null or an integer between 1 and {week_count}')
        week, end = record.get('week'), record.get('end_week')
        if end is not None:
            require(type(week) is int and type(end) is int and end >= week, 'end_week', 'a range requires a start week and an end at or after it')
        if record.get('kind') == 'group':
            require(week is None and end is None, 'kind', 'a structural group cannot carry scheduled weeks; a timed assessment uses kind assessment')
        parent = record.get('parent_key')
        require(parent is None or (isinstance(parent, str) and 1 <= len(parent) <= limits.ASSESSMENT_KEY_LENGTH and parent != key), 'parent_key', 'use null or a distinct parent identity')
        require(record.get('weight_scope') != 'group' or parent is not None, 'weight_scope', 'a group-relative weight requires a parent')
        if violations:
            raise ProcessingError(errors.INVALID_EXTRACTION, 'Assessment validation failed — ' + '; '.join(violations)[:430], 'module')
        return record

    def validate_source_references(self, assessment, source_ids):
        evidence = assessment.get("evidence")
        if not isinstance(evidence, dict) or set(evidence) - self.FACT_FIELDS:
            raise ProcessingError(
                errors.INVALID_EXTRACTION,
                "An assessment has invalid evidence references.",
                "module",
            )
        for field in self.FACT_FIELDS:
            ids = evidence.get(field, [])
            if (
                not isinstance(ids, list)
                or len(ids) > limits.EVIDENCE_IDS_PER_FACT
                or any(not isinstance(i, str) or i not in source_ids for i in ids)
            ):
                raise ProcessingError(
                    errors.INVALID_EXTRACTION,
                    "Evidence is missing or belongs to another source.",
                    "module",
                )
            if assessment.get(field) is not None and not ids:
                raise ProcessingError(
                    errors.INVALID_EXTRACTION,
                    "Every populated fact needs source evidence.",
                    "module",
                )
        return assessment

    def merge_assessments(self, records, validate_relationships=True):
        if not records:
            raise ProcessingError(
                errors.NO_ASSESSMENTS,
                "No assessment facts were found in this module.",
                "module",
            )
        merged = {}
        for record in records:
            key = record["key"]
            if key not in merged:
                merged[key] = {
                    **record,
                    "evidence": {k: list(v) for k, v in record["evidence"].items()},
                }
                continue
            existing = merged[key]
            for field in self.FACT_FIELDS:
                old, new = existing[field], record[field]
                if old is not None and new is not None and old != new:
                    raise ProcessingError(
                        errors.INVALID_EXTRACTION,
                        "Sources disagree about an assessment fact.",
                        "module",
                    )
                if old is None:
                    existing[field] = new
                existing["evidence"][field] = sorted(
                    set(
                        existing["evidence"].get(field, [])
                        + record["evidence"].get(field, [])
                    )
                )
        if validate_relationships:
            self.validate_relationships(list(merged.values()))
        return [merged[k] for k in sorted(merged)]

    def validate_relationships(self, records):
        by_key = {r["key"]: r for r in records}
        children = {key: [] for key in by_key}
        roots = []
        for record in records:
            parent = record["parent_key"]
            if parent is None:
                roots.append(record["key"])
            elif parent not in by_key or by_key[parent]["kind"] != "group":
                raise ProcessingError(
                    errors.INVALID_EXTRACTION,
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
                errors.INVALID_EXTRACTION,
                "Assessment relationships contain a cycle.",
                "module",
            )
        module_weights = {}
        maximum = limits.WEIGHT_PERCENT + limits.WEIGHT_TOLERANCE
        for key in reversed(order):
            record = by_key[key]
            child_records = [by_key[child] for child in children[key]]
            module_total = sum(module_weights[child] for child in children[key])
            group_total = sum(
                child["weight_percent"] or 0
                for child in child_records
                if child["weight_scope"] == "group"
            )
            weight = record["weight_percent"]
            if record["weight_scope"] == "module" and weight is not None:
                if module_total > weight + limits.WEIGHT_TOLERANCE:
                    raise ProcessingError(
                        errors.INVALID_EXTRACTION,
                        "Child assessment weights exceed their parent total.",
                        "module",
                    )
                module_weights[key] = weight
            else:
                module_weights[key] = module_total
            if group_total > maximum:
                raise ProcessingError(
                    errors.INVALID_EXTRACTION,
                    "Assessment group weights exceed 100 percent.",
                    "module",
                )
        if sum(module_weights[key] for key in roots) > maximum:
            raise ProcessingError(
                errors.INVALID_EXTRACTION,
                "Assessment module weights exceed 100 percent.",
                "module",
            )
        return records

    def correct_assessment(self, original, changes, week_count):
        allowed = limits.REVIEW_FIELDS
        if not isinstance(changes, dict) or not changes or set(changes) - allowed:
            raise ProcessingError(
                errors.INVALID_REQUEST,
                "Only primitive assessment facts can be reviewed.",
                "assessment",
            )
        corrected = {**original, **changes}
        self.validate_assessment_facts(corrected, week_count)
        return corrected

    @staticmethod
    def create_assessment(id, result_id, module_id, facts, evidence,
                          parent_assessment_id=None, revision=0):
        """Select a concrete entity once at the validated input boundary."""
        implementations = {'group': AssessmentGroup, 'assessment': IndividualAssessment}
        try:
            implementation = implementations[facts['kind']]
        except (KeyError, TypeError) as exc:
            raise ValueError('Unknown assessment kind.') from exc
        return implementation(id, result_id, module_id, facts, evidence,
                              parent_assessment_id, revision)

    def group_assessments(self, modules, assessments):
        """Wire aggregation without delegating peer access to an entity."""
        objects = [self.create_assessment(
            row['id'], row['result_id'], row['module_id'], row['facts'],
            row['evidence'], row.get('parent_assessment_id'), row.get('revision', 0),
        ) for row in assessments]
        return tuple(replace(module, _assessments=tuple(
            item for item in objects if item.module_id == module.id
        )) for module in modules)

    def build_schedule(self, modules, assessments, week_count, project_id):
        grouped = self.group_assessments(modules, assessments)
        by_module = {module.id: module for module in grouped}
        objects = [item for module in grouped for item in module.get_assessments()]
        if len(objects) != len(assessments):
            raise ValueError('An assessment belongs to an unknown module.')
        schedule = Schedule(project_id, week_count)
        for assessment in sorted(objects, key=lambda item: (
            by_module[item.module_id].position, item.facts['key'], item.id,
        )):
            span = assessment.scheduling_span()
            if span is None:
                continue
            record = assessment.to_record(by_module[assessment.module_id].module_title)
            start, end = span
            if start is None and end is None:
                schedule.add_undated(record)
            else:
                schedule.add_item(record, start, end)
        return schedule

    @staticmethod
    def build_document_outcome(chunks, issues=()):
        """Keep understanding separate from execution; retain every accepted fact."""
        records = tuple(r for chunk in chunks for r in chunk['records'])
        unknowns = tuple(sorted({u for chunk in chunks for u in chunk['uncertainties']} | {
            f"{r['name']}: {field} could not be inferred from this source."
            for r in records if r['kind'] == 'assessment'
            for field in ('week', 'weight_percent') if r[field] is None
        }))
        if records:
            incomplete = bool(issues or unknowns) or any(
                r['kind'] == 'assessment' and (r['week'] is None or r['weight_percent'] is None)
                for r in records
            )
            inference = 'partially_understood' if incomplete else 'understood'
        else:
            inference = 'unknown' if issues else 'no_assessment_content'
        return {'inference': inference, 'records': records,
                'uncertainties': unknowns, 'issues': tuple(issues)}

    @staticmethod
    def can_retry_document(job_status, task_state, issues, replaced=False):
        return (not replaced
                and job_status in (lifecycle.READY, lifecycle.PARTIAL, lifecycle.FAILED, lifecycle.INTERRUPTED)
                and (task_state in ('queued', 'failed') or (task_state == 'succeeded' and bool(issues))))

    @staticmethod
    def settled_status(module_count, available, tasks, has_errors=False, stale=False):
        unresolved = has_errors or stale or any(
            task['state'] != 'succeeded' or task['inference'] != 'understood' or task['issues']
            for task in tasks)
        if available == module_count and module_count and not unresolved:
            return lifecycle.READY
        return lifecycle.PARTIAL if available else lifecycle.FAILED

    @staticmethod
    def coverage(status, has_assessments, documents, stale=False):
        complete = status == lifecycle.READY and not stale and all(
            d['execution'] == 'succeeded' and d['inference'] == 'understood' and not d['issues']
            for d in documents)
        return 'complete' if complete else 'partial' if has_assessments else 'none'

    def reconcile_reviews(self, records, previous, source_ids, week_count):
        """Apply reviewed field deltas only while their cited evidence survives.

        Raw extraction remains immutable. Publication separately appends these
        effective facts as reviews of the new assessment identities.
        """
        effective = {r['key']: deepcopy(r) for r in records}
        transfers = []
        for old in previous:
            if not old['revision']:
                continue
            key = old['facts']['key']
            if key not in effective:
                raise ProcessingError(errors.REVISION_CONFLICT,
                                      'A reviewed assessment changed identity. Review the affected module before publication.', 'module')
            record = effective[key]
            for field in self.FACT_FIELDS:
                if (old['facts'][field] == old['original_facts'][field]
                        and old['evidence'].get(field, []) == old['original_evidence'].get(field, [])):
                    continue
                citations = old['evidence'].get(field, [])
                if any(source_id not in source_ids for source_id in citations):
                    raise ProcessingError(errors.REVISION_CONFLICT,
                                          'A correction cites replaced source evidence. Review its evidence before publication.', 'module')
                record[field] = deepcopy(old['facts'][field])
                record['evidence'][field] = list(citations)
            self.validate_assessment_facts(record, week_count)
            self.validate_source_references(record, source_ids)
            transfers.append({'key': key, 'previous_assessment_id': old['id'], 'revision': old['revision'],
                              'facts': {k: v for k, v in record.items() if k != 'evidence'},
                              'evidence': deepcopy(record['evidence'])})
        self.validate_relationships(list(effective.values()))
        return tuple(transfers)

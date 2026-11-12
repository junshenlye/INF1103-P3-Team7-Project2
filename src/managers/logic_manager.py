"""Deterministic validation rules for project submissions."""

from __future__ import annotations

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

from dataclasses import replace
import json
from uuid import uuid4

import pytest

from src.managers.ai_manager import AIManager
from src.managers.logic_manager import LogicManager
from src.models.projects.module import Module
from src.errors.processing_error import ProcessingError
from src.config.settings import Settings


def record(key="exam", **changes):
    fields = {
        "key": key,
        "name": "Exam",
        "kind": "assessment",
        "weight_percent": None,
        "weight_scope": "unknown",
        "week": None,
        "end_week": None,
        "parent_key": None,
        **changes,
    }
    fields["evidence"] = {
        k: ["source"] for k, v in fields.items() if k != "key" and v is not None
    }
    return fields


def test_unknown_values_and_merge_do_not_invent_facts():
    logic = LogicManager()
    first = record()
    second = record(week=8, weight_percent=50, weight_scope="module")
    # A different weight scope is conflicting evidence, not a silent overwrite.
    with pytest.raises(ProcessingError):
        logic.merge_assessments([first, second])
    second = record(week=8)
    merged = logic.merge_assessments([first, second])[0]
    assert merged["week"] == 8 and merged["weight_percent"] is None
    assert first["week"] is None
    with pytest.raises(ProcessingError):
        logic.merge_assessments([record(week=8), record(week=9)])


def test_group_weights_and_relationships():
    logic = LogicManager()
    parent = record("project", kind="group", weight_percent=40, weight_scope="module")
    children = [
        record(
            "proposal",
            parent_key="project",
            weight_scope="group",
            weight_percent=25,
            week=4,
        ),
        record(
            "report",
            parent_key="project",
            weight_scope="group",
            weight_percent=75,
            week=10,
        ),
    ]
    assert len(logic.merge_assessments([parent, *children])) == 3
    with pytest.raises(ProcessingError):
        logic.merge_assessments(children)
    with pytest.raises(ProcessingError):
        logic.merge_assessments(
            [
                record("a", kind="group", parent_key="b"),
                record("b", kind="group", parent_key="a"),
            ]
        )
    with pytest.raises(ProcessingError):
        logic.merge_assessments(
            [
                record("a", weight_percent=80, weight_scope="module"),
                record("b", weight_percent=30, weight_scope="module"),
            ]
        )


@pytest.mark.parametrize(
    "changes",
    [
        {"week": True},
        {"week": 53},
        {"week": None, "end_week": 8},
        {"week": "bad", "end_week": 8},
        {"week": 8, "end_week": 7},
        {"weight_percent": float("nan")},
        {"weight_percent": -1},
        {"weight_percent": True},
        {"parent_key": "exam"},
    ],
)
def test_invalid_primitives(changes):
    with pytest.raises(ProcessingError):
        LogicManager().validate_assessment_facts(record(**changes), 14)


def test_extraction_ownership_and_populated_fact_evidence():
    logic = LogicManager()
    module = Module("m", "p", "j", "INF1103", "inf1103", 6, 0)
    raw = {
        "module_title": "INF1103",
        "assessments": [record(week=7)],
        "uncertainties": [],
    }
    assert logic.validate_extraction(raw, module, {"source"}, 14)[0][0]["week"] == 7
    with pytest.raises(ProcessingError):
        logic.validate_extraction(raw, module, {"another-module-source"}, 14)
    raw["assessments"][0]["evidence"].pop("name")
    with pytest.raises(ProcessingError):
        logic.validate_extraction(raw, module, {"source"}, 14)


def test_derived_schedule_ranges_unknown_groups_and_determinism():
    logic = LogicManager()
    module = Module("m", "p", "j", "INF1103", "inf1103", 6, 0)
    facts = [
        record("range", week=3, end_week=5),
        record("unknown"),
        record("parent", kind="group"),
    ]
    rows = [
        {
            "id": str(i),
            "module_id": "m",
            "result_id": "r",
            "facts": f,
            "evidence": f.pop("evidence"),
        }
        for i, f in enumerate(facts)
    ]
    schedule = logic.build_schedule([module], rows, 14, "p")
    assert [w['week'] for w in schedule.to_record()['weeks'] if w['items']] == [3, 4, 5]
    assert len(schedule.to_record()['unscheduled']) == 1
    assert logic.build_schedule([module], rows[::-1], 14, "p").to_record() == schedule.to_record()


def test_chunk_bounds_and_unicode_are_lossless(tmp_path):
    settings = Settings(
        "postgresql://local/test", tmp_path, chunk_bytes=1024, max_chunks=10
    )
    ai = AIManager(None, None, None, None, settings)
    text = "Assessment 学习 details. " * 80
    elements = ai._read_source_elements(
        {"texts": [{"text": text, "prov": [{"page_no": 1}]}]}, "document", str(uuid4())
    )
    assert "".join(e['text'] for e in elements) == text
    chunks = ai._make_chunks(elements)
    assert 1 < len(chunks) <= 10
    assert all(
        len(
            json.dumps(
                [ai._provider_element(e) for e in chunk], ensure_ascii=False
            ).encode()
        )
        <= settings.chunk_bytes
        for chunk in chunks
    )
    ai._settings = replace(settings, max_chunks=1)
    with pytest.raises(ProcessingError):
        ai._make_chunks(elements)


def test_unknown_parent_weight_does_not_hide_excessive_child_module_weights():
    records = [
        record("parent", kind="group"),
        record("a", parent_key="parent", weight_scope="module", weight_percent=80),
        record("b", parent_key="parent", weight_scope="module", weight_percent=30),
    ]
    with pytest.raises(ProcessingError):
        LogicManager().merge_assessments(records)


@pytest.mark.parametrize(
    "changes",
    [{"kind": []}, {"weight_scope": {}}, {"name": None}, {"week": {}, "end_week": []}],
)
def test_wrong_json_primitive_types_are_domain_errors(changes):
    with pytest.raises(ProcessingError):
        LogicManager().validate_assessment_facts(record(**changes), 14)


def test_malformed_docling_table_is_a_structured_parse_failure(tmp_path):
    settings = Settings("postgresql://local/test", tmp_path)
    ai = AIManager(None, None, None, None, settings)
    with pytest.raises(ProcessingError) as error:
        ai._read_source_elements(
            {"texts": [], "tables": [{"data": []}]}, "document", str(uuid4())
        )
    assert error.value.code == "document_parse_failed"


def test_empty_module_assessment_rule_is_owned_by_logic():
    with pytest.raises(ProcessingError) as failure:
        LogicManager().merge_assessments([])
    assert failure.value.code == "no_assessments"


def test_deep_assessment_relationships_need_no_python_recursion():
    records = [
        record(str(i), kind="group", parent_key=str(i - 1) if i else None)
        for i in range(2000)
    ]
    records.append(
        record("leaf", parent_key="1999", weight_scope="module", weight_percent=20)
    )
    assert LogicManager().validate_relationships(records) == records


def test_docling_regions_normalize_for_project2_source_highlights(tmp_path):
    settings = Settings("postgresql://local/test", tmp_path)
    ai = AIManager(None, None, None, None, settings)
    parsed = {
        "pages": {"1": {"size": {"width": 100, "height": 100}}},
        "texts": [
            {
                "text": "Quiz",
                "prov": [
                    {
                        "page_no": 1,
                        "bbox": {
                            "l": 10,
                            "r": 90,
                            "t": 90,
                            "b": 70,
                            "coord_origin": "BOTTOMLEFT",
                        },
                    }
                ],
            }
        ],
    }
    element = ai._read_source_elements(parsed, "document", str(uuid4()))[0]
    assert element['regions'][0]["bbox"] == [0.1, 0.1, 0.9, 0.3]
    assert element['regions'][0]["coordinate_origin"] == "TOPLEFT"
    parsed["texts"][0]["prov"][0]["bbox"]["t"] = 110
    with pytest.raises(ProcessingError):
        ai._read_source_elements(parsed, "document", str(uuid4()))


def table_parse():
    def cell(text, row, column, bbox):
        return {
            "text": text,
            "start_row_offset_idx": row,
            "start_col_offset_idx": column,
            "bbox": {
                "l": bbox[0],
                "t": bbox[1],
                "r": bbox[2],
                "b": bbox[3],
                "coord_origin": "TOPLEFT",
            },
        }

    return {
        "pages": {"1": {"size": {"width": 100, "height": 100}}},
        "texts": [],
        "tables": [
            {
                "prov": [
                    {
                        "page_no": 1,
                        "bbox": {
                            "l": 0,
                            "t": 100,
                            "r": 100,
                            "b": 0,
                            "coord_origin": "BOTTOMLEFT",
                        },
                    }
                ],
                "data": {
                    "table_cells": [
                        cell("Due", 0, 2, [80, 5, 98, 15]),
                        cell("Task", 0, 0, [2, 5, 40, 15]),
                        cell("Weight", 0, 1, [45, 5, 65, 15]),
                        cell("Quiz", 1, 0, [2, 40, 40, 60]),
                        cell("25%", 1, 1, [45, 45, 65, 55]),
                        cell("Week 4", 1, 2, [80, 45, 98, 55]),
                    ]
                },
            }
        ],
    }


def test_table_cells_keep_distinct_ids_coordinates_and_reading_order(tmp_path):
    ai = AIManager(None, None, None, None, Settings("postgresql://local/test", tmp_path))
    elements = ai._read_source_elements(table_parse(), "document", str(uuid4()))
    assert [e['text'] for e in elements] == ["Task", "Weight", "Due", "Quiz", "25%", "Week 4"]
    assert len({e['id'] for e in elements}) == 6
    assert [e['regions'][0]["bbox"] for e in elements[3:]] == [
        [0.02, 0.4, 0.4, 0.6], [0.45, 0.45, 0.65, 0.55], [0.8, 0.45, 0.98, 0.55]
    ]
    assert all(e['regions'][0]["granularity"] == "cell" for e in elements)
    assert all(e['regions'][0]["role"] == "column_header" for e in elements[:3])
    assert "row: 1; column: 1; header: Task | Weight | Due" in elements[4]['context']


def test_table_rows_stay_complete_and_headers_remain_citable_across_chunks(tmp_path):
    parsed = table_parse()
    template = parsed["tables"][0]["data"]["table_cells"][3:]
    for row in range(2, 6):
        parsed["tables"][0]["data"]["table_cells"].extend(
            {**cell, "start_row_offset_idx": row} for cell in template
        )
    ai = AIManager(None, None, None, None,
                   Settings("postgresql://local/test", tmp_path, chunk_bytes=2200))
    elements = ai._read_source_elements(parsed, "document", str(uuid4()))
    chunks = ai._make_chunks(elements)
    assert len(chunks) > 1
    header_ids = {e['id'] for e in elements[:3]}
    assert set(e['id'] for chunk in chunks for e in chunk) == {e['id'] for e in elements}
    for chunk in chunks:
        ids = {e['id'] for e in chunk}
        assert header_ids <= ids
        for row in range(1, 6):
            row_ids = {e['id'] for e in elements if f"; row: {row};" in e['context']}
            assert not ids & row_ids or row_ids <= ids
        assert len(json.dumps([ai._provider_element(e) for e in chunk],
                              ensure_ascii=False).encode()) <= ai._settings.chunk_bytes


def test_missing_cell_geometry_keeps_honest_table_scope(tmp_path):
    parsed = table_parse()
    parsed["tables"][0]["data"]["table_cells"][-1].pop("bbox")
    ai = AIManager(
        None, None, None, None, Settings("postgresql://local/test", tmp_path)
    )
    elements = ai._read_source_elements(parsed, "document", str(uuid4()))
    assert elements[-1]['regions'][0]["bbox"] == [0.0, 0.0, 1.0, 1.0]
    assert elements[-1]['regions'][0]["granularity"] == "table"
    assert elements[-2]['regions'][0]["granularity"] == "cell"


def test_multi_page_table_does_not_assign_page_less_cells_to_one_page(tmp_path):
    parsed = table_parse()
    parsed["pages"]["2"] = parsed["pages"]["1"]
    parsed["tables"][0]["prov"].append({**parsed["tables"][0]["prov"][0], "page_no": 2})
    ai = AIManager(
        None, None, None, None, Settings("postgresql://local/test", tmp_path)
    )
    elements = ai._read_source_elements(parsed, "document", str(uuid4()))
    assert [r["page"] for r in elements[1]['regions']] == [1, 2]
    assert all(r["granularity"] == "table" for r in elements[1]['regions'])


def test_invalid_cell_coordinates_are_rejected(tmp_path):
    parsed = table_parse()
    parsed["tables"][0]["data"]["table_cells"][-1]["bbox"]["l"] = float("nan")
    ai = AIManager(
        None, None, None, None, Settings("postgresql://local/test", tmp_path)
    )
    with pytest.raises(ProcessingError) as error:
        ai._read_source_elements(parsed, "document", str(uuid4()))
    assert error.value.code == "document_parse_failed"

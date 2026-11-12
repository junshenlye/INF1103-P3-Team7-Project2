"""Tests for turning parsed documents into bounded, citable source elements."""

import json
from types import SimpleNamespace
import unittest
from uuid import uuid4

from src.config import limits
from src.errors import error_codes
from src.errors.processing_error import ProcessingError
from src.processing.source_reader import SourceReader


def reader(chunk_bytes=limits.CHUNK_BYTES, max_chunks=limits.CHUNK_COUNT):
    return SourceReader(SimpleNamespace(chunk_bytes=chunk_bytes, max_chunks=max_chunks))


def serialized_size(source_reader, chunk):
    payload = [source_reader.provider_element(element) for element in chunk]
    return len(json.dumps(payload, ensure_ascii=False).encode())


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
                        "bbox": {"l": 0, "t": 100, "r": 100, "b": 0, "coord_origin": "BOTTOMLEFT"},
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


class TextElementTests(unittest.TestCase):
    def test_long_unicode_text_splits_losslessly_into_bounded_chunks(self):
        source_reader = reader(chunk_bytes=1024, max_chunks=10)
        text = "Assessment 学习 details. " * 80
        elements = source_reader.read_elements(
            {"texts": [{"text": text, "prov": [{"page_no": 1}]}]}, "document", str(uuid4())
        )
        self.assertEqual("".join(e.text for e in elements), text)

        chunks = source_reader.make_chunks(elements)
        self.assertTrue(1 < len(chunks) <= 10)
        for chunk in chunks:
            self.assertLessEqual(serialized_size(source_reader, chunk), 1024)

        with self.assertRaises(ProcessingError):
            reader(chunk_bytes=1024, max_chunks=1).make_chunks(elements)

    def test_element_ids_are_stable_for_the_same_parse(self):
        parse_id = str(uuid4())
        parsed = {"texts": [{"text": "Quiz", "prov": []}, {"text": "Exam", "prov": []}]}
        first = reader().read_elements(parsed, "document", parse_id)
        second = reader().read_elements(parsed, "document", parse_id)
        self.assertEqual([e.id for e in first], [e.id for e in second])
        self.assertEqual(len({e.id for e in first}), 2)

    def test_regions_normalize_to_top_left_page_fractions(self):
        parsed = {
            "pages": {"1": {"size": {"width": 100, "height": 100}}},
            "texts": [
                {
                    "text": "Quiz",
                    "prov": [
                        {
                            "page_no": 1,
                            "bbox": {"l": 10, "r": 90, "t": 90, "b": 70, "coord_origin": "BOTTOMLEFT"},
                        }
                    ],
                }
            ],
        }
        element = reader().read_elements(parsed, "document", str(uuid4()))[0]
        self.assertEqual(element.regions[0]["bbox"], [0.1, 0.1, 0.9, 0.3])
        self.assertEqual(element.regions[0]["coordinate_origin"], "TOPLEFT")

        parsed["texts"][0]["prov"][0]["bbox"]["t"] = 110
        with self.assertRaises(ProcessingError):
            reader().read_elements(parsed, "document", str(uuid4()))

    def test_blank_or_empty_documents_are_parse_failures(self):
        for parsed in ({"texts": []}, {"texts": [{"text": "   ", "prov": []}]}):
            with self.subTest(parsed=parsed):
                with self.assertRaises(ProcessingError) as error:
                    reader().read_elements(parsed, "document", str(uuid4()))
                self.assertEqual(error.exception.code, error_codes.DOCUMENT_PARSE_FAILED)

    def test_malformed_structures_are_parse_failures_with_document_id(self):
        cases = (
            {"texts": {}},
            {"texts": ["not an element"]},
            {"texts": [], "tables": [{"data": []}]},
            {"texts": [{"text": "Quiz", "prov": [{"page_no": 0}]}]},
            {"texts": [{"text": "Quiz", "prov": [{"page_no": limits.PDF_PAGES + 1}]}]},
        )
        for parsed in cases:
            with self.subTest(parsed=parsed):
                with self.assertRaises(ProcessingError) as error:
                    reader().read_elements(parsed, "document-7", str(uuid4()))
                self.assertEqual(error.exception.code, error_codes.DOCUMENT_PARSE_FAILED)
                self.assertEqual(error.exception.related_ids, {"document_id": "document-7"})


class TableElementTests(unittest.TestCase):
    def test_cells_keep_distinct_ids_coordinates_and_reading_order(self):
        elements = reader().read_elements(table_parse(), "document", str(uuid4()))
        self.assertEqual([e.text for e in elements], ["Task", "Weight", "Due", "Quiz", "25%", "Week 4"])
        self.assertEqual(len({e.id for e in elements}), 6)
        self.assertEqual(
            [e.regions[0]["bbox"] for e in elements[3:]],
            [[0.02, 0.4, 0.4, 0.6], [0.45, 0.45, 0.65, 0.55], [0.8, 0.45, 0.98, 0.55]],
        )
        self.assertTrue(all(e.regions[0]["granularity"] == "cell" for e in elements))
        self.assertTrue(all(e.regions[0]["role"] == "column_header" for e in elements[:3]))
        self.assertIn("row: 1; column: 1; header: Task | Weight | Due", elements[4].context)

    def test_rows_stay_complete_and_headers_remain_citable_across_chunks(self):
        parsed = table_parse()
        template = parsed["tables"][0]["data"]["table_cells"][3:]
        for row in range(2, 6):
            parsed["tables"][0]["data"]["table_cells"].extend(
                {**cell, "start_row_offset_idx": row} for cell in template
            )
        source_reader = reader(chunk_bytes=2200)
        elements = source_reader.read_elements(parsed, "document", str(uuid4()))
        chunks = source_reader.make_chunks(elements)

        self.assertGreater(len(chunks), 1)
        header_ids = {e.id for e in elements[:3]}
        self.assertEqual({e.id for chunk in chunks for e in chunk}, {e.id for e in elements})
        for chunk in chunks:
            ids = {e.id for e in chunk}
            self.assertLessEqual(header_ids, ids)
            for row in range(1, 6):
                row_ids = {e.id for e in elements if f"; row: {row};" in e.context}
                self.assertTrue(not ids & row_ids or row_ids <= ids)
            self.assertLessEqual(serialized_size(source_reader, chunk), 2200)

    def test_missing_cell_geometry_keeps_table_scope(self):
        parsed = table_parse()
        parsed["tables"][0]["data"]["table_cells"][-1].pop("bbox")
        elements = reader().read_elements(parsed, "document", str(uuid4()))
        self.assertEqual(elements[-1].regions[0]["bbox"], [0.0, 0.0, 1.0, 1.0])
        self.assertEqual(elements[-1].regions[0]["granularity"], "table")
        self.assertEqual(elements[-2].regions[0]["granularity"], "cell")

    def test_multi_page_table_does_not_assign_cells_to_one_page(self):
        parsed = table_parse()
        parsed["pages"]["2"] = parsed["pages"]["1"]
        parsed["tables"][0]["prov"].append({**parsed["tables"][0]["prov"][0], "page_no": 2})
        elements = reader().read_elements(parsed, "document", str(uuid4()))
        self.assertEqual([r["page"] for r in elements[1].regions], [1, 2])
        self.assertTrue(all(r["granularity"] == "table" for r in elements[1].regions))

    def test_invalid_cell_coordinates_are_rejected(self):
        parsed = table_parse()
        parsed["tables"][0]["data"]["table_cells"][-1]["bbox"]["l"] = float("nan")
        with self.assertRaises(ProcessingError) as error:
            reader().read_elements(parsed, "document", str(uuid4()))
        self.assertEqual(error.exception.code, error_codes.DOCUMENT_PARSE_FAILED)


class ChunkTests(unittest.TestCase):
    def test_chunking_keeps_order_and_source_id_budget_at_maximum_bound(self):
        source_reader = reader(chunk_bytes=limits.MAX_CHUNK_BYTES, max_chunks=limits.MAX_CHUNK_COUNT)
        parsed = {"texts": [{"text": f"Item {i}", "prov": []} for i in range(600)]}
        elements = source_reader.read_elements(parsed, "document", str(uuid4()))
        chunks = source_reader.make_chunks(elements)
        self.assertGreater(len(chunks), 1)
        self.assertEqual([e.id for chunk in chunks for e in chunk], [e.id for e in elements])
        for chunk in chunks:
            self.assertLessEqual(sum(len(e.id) for e in chunk), limits.GPT_SOURCE_ID_CHARACTERS)

    def test_provider_element_exposes_only_citable_fields(self):
        element = reader().read_elements({"texts": [{"text": "Quiz", "prov": []}]}, "d", str(uuid4()))[0]
        self.assertEqual(set(reader().provider_element(element)), {"id", "text", "regions", "context"})


if __name__ == "__main__":
    unittest.main()

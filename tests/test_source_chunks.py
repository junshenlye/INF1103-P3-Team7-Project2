"""Tests for bounded source chunks and table evidence."""

import json
import unittest
from unittest.mock import patch

from src.errors.error_codes import DOCUMENT_PARSE_FAILED
from src.errors.processing_error import ProcessingError
from src.models.documents.source_element import SourceElement
from src.processing.source_chunks import make_chunks, provider_element


def source(element_id, text, context="", role=None):
    regions = [{"role": role}] if role else []
    return SourceElement(element_id, "document", "parse", text, regions, context)


def byte_size(elements):
    payload = [provider_element(element) for element in elements]
    return len(json.dumps(payload, ensure_ascii=False).encode("utf-8"))


class SourceChunkTests(unittest.TestCase):
    def test_keeps_rows_together_and_repeats_citable_headers(self):
        header = source("h", "Week", "table cell; table: 1; row: 0; column: 1", "column_header")
        first = source("a", "一", "table cell; table: 1; row: 1; column: 1")
        second = source("b", "Quiz", "table cell; table: 1; row: 1; column: 2")
        third = source("c", "二", "table cell; table: 1; row: 2; column: 1")
        bound = byte_size([header, first, second])

        self.assertEqual(
            make_chunks([header, first, second, third], chunk_bytes=bound),
            [[header, first, second], [header, third]],
        )

    def test_rejects_an_oversized_row_with_document_context(self):
        first = source("a", "Week", "table cell; table: 1; row: 1; column: 1")
        second = source("b", "Quiz", "table cell; table: 1; row: 1; column: 2")

        with self.assertRaises(ProcessingError) as caught:
            make_chunks([first, second], chunk_bytes=byte_size([first, second]) - 1)

        self.assertEqual(caught.exception.code, DOCUMENT_PARSE_FAILED)
        self.assertEqual(caught.exception.related_ids, {"document_id": "document"})

    def test_limits_source_id_characters_and_number_of_chunks(self):
        first = source("first", "One")
        second = source("second", "Two")

        with patch("src.processing.source_chunks.limits.GPT_SOURCE_ID_CHARACTERS", 6):
            self.assertEqual(make_chunks([first, second]), [[first], [second]])
            with self.assertRaisesRegex(ProcessingError, "too many extraction chunks"):
                make_chunks([first, second], max_chunks=1)

    def test_empty_input_produces_no_chunks(self):
        self.assertEqual(make_chunks([]), [])

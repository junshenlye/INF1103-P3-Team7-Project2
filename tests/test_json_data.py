"""Tests for strict JSON decoding."""

import json
import unittest

from src.serialization.json_data import load_json


class LoadJsonTests(unittest.TestCase):
    def test_decodes_json_text_and_bytes(self):
        raw = '{"modules": [{"week": 3}], "ready": false, "error": null}'
        expected = {"modules": [{"week": 3}], "ready": False, "error": None}
        self.assertEqual(load_json(raw), expected)
        self.assertEqual(load_json(raw.encode()), expected)

    def test_rejects_duplicate_fields_in_nested_objects(self):
        with self.assertRaisesRegex(ValueError, "Duplicate JSON field"):
            load_json('{"modules": [{"week": 3, "week": 7}]}')

    def test_rejects_nonstandard_number_constants(self):
        for token in ("NaN", "Infinity", "-Infinity"):
            with self.subTest(token=token):
                with self.assertRaisesRegex(ValueError, "Non-finite JSON value"):
                    load_json(f'{{"value": {token}}}')

    def test_preserves_json_syntax_errors(self):
        with self.assertRaises(json.JSONDecodeError):
            load_json('{"week": }')

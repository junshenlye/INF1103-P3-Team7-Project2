import unittest

from src.errors.error_codes import INVALID_REQUEST
from src.errors.processing_error import ProcessingError
from src.serialization.event_cursor import parse_event_cursor


class EventCursorTests(unittest.TestCase):
    def test_uses_query_cursor_when_no_header_is_supplied(self):
        self.assertEqual(parse_event_cursor(), 0)
        self.assertEqual(parse_event_cursor(123), 123)
        self.assertEqual(parse_event_cursor(10**18 - 1), 10**18 - 1)

    def test_header_overrides_query_cursor_including_zero(self):
        self.assertEqual(parse_event_cursor(12, last_event_id="003"), 3)
        self.assertEqual(parse_event_cursor(12, last_event_id="0"), 0)
        self.assertEqual(parse_event_cursor(last_event_id="9" * 18), 10**18 - 1)

    def test_rejects_invalid_cursors(self):
        cases = (
            (-1, None),
            (True, None),
            (10**18, None),
            (10, ""),
            (10, "-1"),
            (10, "+1"),
            (10, " 1"),
            (10, "1\n"),
            (10, "١"),
            (10, "9" * 19),
        )
        for after, header in cases:
            with self.subTest(after=after, header=header):
                with self.assertRaises(ProcessingError) as caught:
                    parse_event_cursor(after, last_event_id=header)
                self.assertEqual(caught.exception.code, INVALID_REQUEST)
                self.assertEqual(caught.exception.scope, "request")

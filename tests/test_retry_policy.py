"""Regression tests for bounded provider retry decisions and backoff."""

import unittest

from src.errors import error_codes
from src.processing.retry_policy import RetryPolicy


class RetryPolicyTests(unittest.TestCase):
    def setUp(self):
        self.policy = RetryPolicy()

    def test_invalid_extraction_allows_one_correction_retry(self):
        self.assertTrue(self.policy.allows(1, error_codes.INVALID_EXTRACTION))
        self.assertFalse(self.policy.allows(2, error_codes.INVALID_EXTRACTION))

    def test_provider_unavailable_allows_three_total_attempts(self):
        self.assertTrue(self.policy.allows(1, error_codes.PROVIDER_UNAVAILABLE))
        self.assertTrue(self.policy.allows(2, error_codes.PROVIDER_UNAVAILABLE))
        self.assertFalse(self.policy.allows(3, error_codes.PROVIDER_UNAVAILABLE))

    def test_unknown_error_codes_are_not_retryable(self):
        self.assertFalse(self.policy.allows(1, "unexpected_provider_error"))

    def test_attempt_numbers_are_one_based(self):
        self.assertFalse(self.policy.allows(0, error_codes.PROVIDER_UNAVAILABLE))
        self.assertFalse(self.policy.allows(-1, error_codes.INVALID_EXTRACTION))
        with self.assertRaises(ValueError):
            self.policy.delay(0)

    def test_retryable_http_statuses(self):
        for status in (408, 429, 500, 503, 599):
            with self.subTest(status=status):
                self.assertTrue(
                    self.policy.allows(1, error_codes.PROVIDER_UNAVAILABLE, status)
                )

    def test_non_retryable_http_statuses(self):
        for status in (200, 400, 404, 499, 600):
            with self.subTest(status=status):
                self.assertFalse(
                    self.policy.allows(1, error_codes.PROVIDER_UNAVAILABLE, status)
                )

    def test_http_status_filter_also_applies_to_invalid_extraction(self):
        self.assertTrue(self.policy.allows(1, error_codes.INVALID_EXTRACTION, 503))
        self.assertFalse(self.policy.allows(1, error_codes.INVALID_EXTRACTION, 400))

    def test_exponential_backoff_increases_by_attempt(self):
        self.assertEqual(self.policy.delay(1), 0.25)
        self.assertEqual(self.policy.delay(2), 0.5)
        self.assertEqual(self.policy.delay(3), 1.0)

    def test_exponential_backoff_is_capped(self):
        self.assertEqual(self.policy.delay(10), 30.0)

    def test_retry_after_is_parsed_and_capped(self):
        self.assertEqual(self.policy.delay(1, "2.5"), 2.5)
        self.assertEqual(self.policy.delay(1, "45"), 30.0)
        self.assertEqual(self.policy.delay(1, "-5"), 0.0)

    def test_invalid_retry_after_falls_back_to_exponential_backoff(self):
        self.assertEqual(self.policy.delay(2, "not-a-number"), 0.5)
        self.assertEqual(self.policy.delay(2, None), 0.5)
        self.assertEqual(self.policy.delay(2, ""), 0.5)

    def test_custom_attempt_limits_and_backoff_bounds(self):
        policy = RetryPolicy(
            transient_attempts=2,
            invalid_attempts=3,
            base_delay=1.0,
            max_delay=1.5,
        )
        self.assertFalse(policy.allows(2, error_codes.PROVIDER_UNAVAILABLE))
        self.assertTrue(policy.allows(2, error_codes.INVALID_EXTRACTION))
        self.assertEqual(policy.delay(2), 1.5)
        self.assertEqual(policy.delay(1, "9"), 1.5)

    def test_invalid_policy_configuration_is_rejected(self):
        for kwargs in (
            {"transient_attempts": 0},
            {"invalid_attempts": 0},
            {"base_delay": -0.1},
            {"max_delay": -1},
        ):
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(ValueError):
                    RetryPolicy(**kwargs)


if __name__ == "__main__":
    unittest.main()

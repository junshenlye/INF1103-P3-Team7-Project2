"""Bounded retry decisions for transient provider failures.

Attempts are one-based. Invalid extraction responses get one correction retry;
provider availability failures get up to three attempts. Explicit HTTP statuses
must be retryable (408, 429, or 5xx) before the error code is considered.

>>> from src.errors.error_codes import INVALID_EXTRACTION, PROVIDER_UNAVAILABLE
>>> policy = RetryPolicy()
>>> policy.allows(1, INVALID_EXTRACTION)
True
>>> policy.allows(2, INVALID_EXTRACTION)
False
>>> policy.allows(2, PROVIDER_UNAVAILABLE, 503)
True
>>> policy.allows(1, PROVIDER_UNAVAILABLE, 404)
False
>>> policy.delay(3)
1.0
>>> policy.delay(2, "45")
30.0
>>> policy.delay(1, "Wed, 21 Oct 2099 07:28:00 GMT")
30.0
>>> policy.delay(1, "Wed, 21 Oct 2015 07:28:00 GMT")
0.0
>>> policy.delay(2, "not-a-date")
0.5
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

from src.errors import error_codes as errors


@dataclass(frozen=True)
class RetryPolicy:
    """Keep provider retries predictable and bounded across transports."""

    transient_attempts: int = 3
    invalid_attempts: int = 2
    base_delay: float = 0.25
    max_delay: float = 30.0

    def __post_init__(self):
        if self.transient_attempts < 1 or self.invalid_attempts < 1:
            raise ValueError("Retry attempt limits must be positive.")
        if self.base_delay < 0 or self.max_delay < 0:
            raise ValueError("Retry delays cannot be negative.")

    def allows(self, attempt: int, code: str, status: int | None = None) -> bool:
        """Return whether this one-based attempt may be retried."""
        if attempt < 1:
            return False
        if status is not None and status not in (408, 429) and not 500 <= status <= 599:
            return False
        if code == errors.INVALID_EXTRACTION:
            return attempt < self.invalid_attempts
        return code == errors.PROVIDER_UNAVAILABLE and attempt < self.transient_attempts

    def delay(self, attempt: int, retry_after=None) -> float:
        """Return a bounded numeric or HTTP-date Retry-After value.

        HTTP-date values are converted to a delay relative to the current UTC
        time. Invalid values fall back to the normal exponential backoff.
        """
        if attempt < 1:
            raise ValueError("Retry attempts are one-based.")
        if retry_after is not None and retry_after != "":
            try:
                seconds = float(retry_after)
            except (TypeError, ValueError, OverflowError):
                try:
                    retry_at = parsedate_to_datetime(str(retry_after))
                    if retry_at.tzinfo is None:
                        retry_at = retry_at.replace(tzinfo=timezone.utc)
                    seconds = (retry_at - datetime.now(timezone.utc)).total_seconds()
                except (TypeError, ValueError, OverflowError, IndexError, OSError):
                    seconds = None
            if seconds is not None:
                return min(self.max_delay, max(0.0, seconds))
        exponential = self.base_delay * (2 ** (attempt - 1))
        return min(self.max_delay, exponential)

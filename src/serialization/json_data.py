"""Decode JSON at application boundaries without accepting ambiguous input."""

import json


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON field.")
        result[key] = value
    return result


def _reject_nonfinite_constant(_value):
    raise ValueError("Non-finite JSON value.")


def load_json(raw):
    """Decode JSON text or bytes, rejecting repeated keys and nonstandard constants."""
    return json.loads(
        raw,
        object_pairs_hook=_unique_object,
        parse_constant=_reject_nonfinite_constant,
    )

"""Strict JSON data decoding shared by transport boundaries."""

import json


def load_json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("Duplicate JSON field.")
            result[key] = value
        return result

    def nonfinite(_value):
        raise ValueError("Non-finite JSON value.")

    return json.loads(raw, object_pairs_hook=pairs, parse_constant=nonfinite)

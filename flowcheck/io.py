"""Strict JSON input and stable output for local experiments."""

import json
from pathlib import Path


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Repeated JSON key: {key}")
        result[key] = value
    return result


def reject_constant(value):
    raise ValueError(f"Not a JSON number: {value}")


def decode(text):
    return json.loads(text, object_pairs_hook=unique_object, parse_constant=reject_constant)


def rows(path):
    """Yield line numbers and parsed values, including parse failures as data."""
    with Path(path).open(encoding="utf-8") as source:
        for line_number, text in enumerate(source, 1):
            if not text.strip():
                continue
            try:
                yield line_number, decode(text), None
            except ValueError as error:
                yield line_number, None, str(error)


def read_records(path):
    result = []
    for line_number, value, error in rows(path):
        if error or not isinstance(value, dict):
            raise ValueError(f"{path}:{line_number}: {error or 'Expected a JSON object'}")
        result.append(value)
    if not result:
        raise ValueError(f"{path}: No records")
    return result


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)

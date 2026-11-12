"""Group parsed source elements into bounded extraction chunks."""

import json

from src.config import limits
from src.errors import error_codes
from src.errors.processing_error import ProcessingError


def provider_element(element):
    """Return the source fields sent for extraction and cited as evidence."""
    return {
        "id": element.id,
        "text": element.text,
        "regions": element.regions,
        "context": element.context,
    }


def _source_units(elements):
    """Collect contiguous table rows and their original header elements."""
    units = []
    headers = {}
    previous_row = None
    for element in elements:
        row = None
        table = None
        if element.context.startswith("table cell;"):
            row = element.context.partition("; column:")[0]
            table = row.partition("; row:")[0]
            if any(region.get("role") == "column_header" for region in element.regions):
                headers.setdefault(table, []).append(element)
        if row is None or row != previous_row:
            units.append((table, []))
        units[-1][1].append(element)
        previous_row = row
    return units, headers


def make_chunks(elements, *, chunk_bytes=limits.CHUNK_BYTES, max_chunks=limits.CHUNK_COUNT):
    """Preserve complete table rows and citable headers within extraction bounds."""
    elements = tuple(elements)
    units, headers = _source_units(elements)
    # For a nonempty JSON list, brackets and separators contribute two bytes
    # per element with the default separators used here.
    sizes = {
        element.id: len(json.dumps(provider_element(element), ensure_ascii=False).encode("utf-8")) + 2
        for element in elements
    }
    chunks = []
    current = {}
    size = 0
    id_characters = 0
    for table, unit in units:
        supported = {element.id: element for element in (*headers.get(table, ()), *unit)}
        additions = {key: element for key, element in supported.items() if key not in current}
        extra_size = sum(sizes[key] for key in additions)
        extra_ids = sum(map(len, additions))
        if current and (
            size + extra_size > chunk_bytes
            or id_characters + extra_ids > limits.GPT_SOURCE_ID_CHARACTERS
        ):
            chunks.append(list(current.values()))
            current = {}
            size = id_characters = 0
            additions = supported
            extra_size = sum(sizes[key] for key in additions)
            extra_ids = sum(map(len, additions))
        if extra_size > chunk_bytes or extra_ids > limits.GPT_SOURCE_ID_CHARACTERS:
            raise ProcessingError(
                error_codes.DOCUMENT_PARSE_FAILED,
                "A source element or complete table row exceeds the chunk bound.",
                "document",
                document_id=unit[0].document_id,
            )
        current.update(additions)
        size += extra_size
        id_characters += extra_ids

    if current:
        chunks.append(list(current.values()))
    if len(chunks) > max_chunks:
        raise ProcessingError(
            error_codes.DOCUMENT_PARSE_FAILED,
            "The document requires too many extraction chunks.",
            "document",
        )
    return chunks

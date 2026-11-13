"""Turn Docling text and tables into bounded, citable source elements."""
import json
import math
from uuid import uuid5, UUID

from src.config import limits
from src.errors import error_codes as errors
from src.errors.processing_error import ProcessingError
from src.models.documents.source_element import SourceElement


class SourceReader:
    """Owns source geometry, stable citation IDs and complete-row chunking.

    ``settings`` is any object providing ``chunk_bytes``, the serialized size
    limit for one extraction chunk, and ``max_chunks``, the most chunks one
    document may use.
    """

    def __init__(self, settings):
        self.settings = settings

    def _table_cell_provenance(self, cell, provenance, document_id, header):
        """Keep each cell's geometry; never guess its page in a multi-page table."""
        if not isinstance(provenance, list):
            return provenance  # The common provenance validator reports malformed data.
        fallback = [
            {**p, "granularity": "table"} if isinstance(p, dict) else p
            for p in provenance
        ]
        box = cell.get("bbox")
        precise = (
            len(provenance) == 1
            and isinstance(provenance[0], dict)
            and isinstance(box, dict)
            and box.get("coord_origin") in ("TOPLEFT", "BOTTOMLEFT")
        )
        if precise:
            origin = box["coord_origin"]
            if (
                any(
                    type(box.get(k)) not in (int, float) or not math.isfinite(box[k])
                    for k in ("l", "t", "r", "b")
                )
                or box["l"] >= box["r"]
                or (
                    box["t"] >= box["b"]
                    if origin == "TOPLEFT"
                    else box["t"] <= box["b"]
                )
            ):
                raise ProcessingError(
                    errors.DOCUMENT_PARSE_FAILED,
                    "A table cell has invalid coordinates.",
                    "document",
                    document_id=document_id,
                )
            fallback = [
                {
                    "page_no": provenance[0].get("page_no"),
                    "bbox": box,
                    "granularity": "cell",
                }
            ]
        return [
            {**p, "role": "column_header" if header else "value"}
            if isinstance(p, dict)
            else p
            for p in fallback
        ]

    def read_elements(self, parsed, document_id, parse_id):
        records = []
        texts = parsed.get("texts", [])
        tables = parsed.get("tables", [])
        pages = parsed.get("pages", {})
        if (
            not isinstance(texts, list)
            or not isinstance(tables, list)
            or not isinstance(pages, dict)
        ):
            raise ProcessingError(
                errors.DOCUMENT_PARSE_FAILED,
                "The document parse has invalid source elements.",
                "document",
                document_id=document_id,
            )
        for item in texts:
            if not isinstance(item, dict):
                raise ProcessingError(
                    errors.DOCUMENT_PARSE_FAILED,
                    "A source element is invalid.",
                    "document",
                    document_id=document_id,
                )
            records.append(
                (
                    item.get("text"),
                    item.get("prov", []),
                    str(item.get("label", "text"))[: limits.SOURCE_LABEL_LENGTH],
                )
            )
        for table_index, table in enumerate(tables):
            if not isinstance(table, dict):
                raise ProcessingError(
                    errors.DOCUMENT_PARSE_FAILED,
                    "A source table is invalid.",
                    "document",
                    document_id=document_id,
                )
            table_data = table.get("data", {})
            if not isinstance(table_data, dict):
                raise ProcessingError(
                    errors.DOCUMENT_PARSE_FAILED,
                    "A source table is invalid.",
                    "document",
                    document_id=document_id,
                )
            cells = table_data.get("table_cells", [])
            if not isinstance(cells, list) or len(cells) > limits.TABLE_CELLS:
                raise ProcessingError(
                    errors.DOCUMENT_PARSE_FAILED,
                    "A source table exceeds supported bounds.",
                    "document",
                    document_id=document_id,
                )
            rows = {}
            for cell in cells:
                if not isinstance(cell, dict) or not isinstance(cell.get("text"), str):
                    raise ProcessingError(
                        errors.DOCUMENT_PARSE_FAILED,
                        "A source table is invalid.",
                        "document",
                        document_id=document_id,
                    )
                index = cell.get("start_row_offset_idx")
                if type(index) is not int or index < 0:
                    raise ProcessingError(
                        errors.DOCUMENT_PARSE_FAILED,
                        "A source table is invalid.",
                        "document",
                        document_id=document_id,
                    )
                column = cell.get("start_col_offset_idx", 0)
                if type(column) is not int or column < 0:
                    raise ProcessingError(
                        errors.DOCUMENT_PARSE_FAILED,
                        "A source table has invalid columns.",
                        "document",
                        document_id=document_id,
                    )
                rows.setdefault(index, []).append(cell)
            for cells_in_row in rows.values():
                cells_in_row.sort(key=lambda cell: cell.get("start_col_offset_idx", 0))
            header = (
                " | ".join(cell["text"] for cell in rows[min(rows)])[
                    : limits.TABLE_HEADER_LENGTH
                ]
                if rows
                else ""
            )
            for index in sorted(rows):
                for cell in rows[index]:
                    is_header = cell.get("column_header", index == min(rows)) is True
                    records.append(
                        (
                            cell["text"],
                            self._table_cell_provenance(
                                cell, table.get("prov", []), document_id, is_header
                            ),
                            f"table cell; table: {table_index}; row: {index}; "
                            f"column: {cell.get('start_col_offset_idx', 0)}; header: {header}",
                        )
                    )
        elements = []
        total = 0
        for text, provenance, context in records:
            if not isinstance(text, str) or not text.strip():
                continue
            if (
                not isinstance(provenance, list)
                or len(provenance) > limits.SOURCE_REGIONS
            ):
                raise ProcessingError(
                    errors.DOCUMENT_PARSE_FAILED,
                    "A source region is invalid.",
                    "document",
                    document_id=document_id,
                )
            regions = []
            for prov in provenance:
                if (
                    not isinstance(prov, dict)
                    or type(prov.get("page_no")) is not int
                    or not 1 <= prov["page_no"] <= limits.PDF_PAGES
                ):
                    raise ProcessingError(
                        errors.DOCUMENT_PARSE_FAILED,
                        "A source page is invalid.",
                        "document",
                        document_id=document_id,
                    )
                bbox = prov.get("bbox") or {}
                if not isinstance(bbox, dict):
                    raise ProcessingError(
                        errors.DOCUMENT_PARSE_FAILED,
                        "A source region is invalid.",
                        "document",
                        document_id=document_id,
                    )
                region = {"page": prov["page_no"]}
                if prov.get("granularity") in ("cell", "row", "table"):
                    region["granularity"] = prov["granularity"]
                if prov.get("role") in ("column_header", "value"):
                    region["role"] = prov["role"]
                if bbox:
                    for key in ("l", "t", "r", "b"):
                        v = bbox.get(key)
                        if (
                            type(v) not in (int, float)
                            or not math.isfinite(v)
                            or abs(v) > limits.COORDINATE_MAGNITUDE
                        ):
                            raise ProcessingError(
                                errors.DOCUMENT_PARSE_FAILED,
                                "A source region is invalid.",
                                "document",
                                document_id=document_id,
                            )
                    region["bbox"] = {k: bbox[k] for k in ("l", "t", "r", "b")}
                    region["origin"] = bbox.get("coord_origin", "BOTTOMLEFT")
                    if region["origin"] not in ("BOTTOMLEFT", "TOPLEFT"):
                        raise ProcessingError(
                            errors.DOCUMENT_PARSE_FAILED,
                            "A source coordinate system is invalid.",
                            "document",
                            document_id=document_id,
                        )
                    page_data = pages.get(str(prov["page_no"]), {})
                    if not isinstance(page_data, dict) or not isinstance(
                        page_data.get("size", {}), dict
                    ):
                        raise ProcessingError(
                            errors.DOCUMENT_PARSE_FAILED,
                            "A source page has invalid dimensions.",
                            "document",
                            document_id=document_id,
                        )
                    size = page_data.get("size", {})
                    if size:
                        width, height = size.get("width"), size.get("height")
                        if any(
                            type(v) not in (int, float)
                            or not math.isfinite(v)
                            or v <= 0
                            for v in (width, height)
                        ):
                            raise ProcessingError(
                                errors.DOCUMENT_PARSE_FAILED,
                                "A source page has invalid dimensions.",
                                "document",
                                document_id=document_id,
                            )
                        left, right, top, bottom = (
                            bbox["l"],
                            bbox["r"],
                            bbox["t"],
                            bbox["b"],
                        )
                        if region["origin"] == "BOTTOMLEFT":
                            top, bottom = height - top, height - bottom
                        if not (
                            0 <= left < right <= width and 0 <= top < bottom <= height
                        ):
                            raise ProcessingError(
                                errors.DOCUMENT_PARSE_FAILED,
                                "A source region is outside its page.",
                                "document",
                                document_id=document_id,
                            )
                        region["bbox"] = [
                            left / width,
                            top / height,
                            right / width,
                            bottom / height,
                        ]
                        region["coordinate_origin"] = "TOPLEFT"
                regions.append(region)
            # UTF-8 slicing preserves every character and stays below the chunk
            # limit including IDs, regions, context and JSON escaping.
            segment = ""
            segment_bytes = 0
            for char in text:
                char_bytes = len(char.encode("utf-8"))
                if segment_bytes + char_bytes > self.settings.chunk_bytes // 4:
                    elements.append(
                        SourceElement(
                            str(uuid5(UUID(parse_id), str(len(elements)))),
                            document_id,
                            parse_id,
                            segment,
                            regions,
                            context,
                        )
                    )
                    segment = ""
                    segment_bytes = 0
                segment += char
                segment_bytes += char_bytes
            if segment:
                elements.append(
                    SourceElement(
                        str(uuid5(UUID(parse_id), str(len(elements)))),
                        document_id,
                        parse_id,
                        segment,
                        regions,
                        context,
                    )
                )
            total += len(text.encode("utf-8"))
            if (
                total > self.settings.chunk_bytes * self.settings.max_chunks
                or len(elements) > limits.SOURCE_ELEMENTS
            ):
                raise ProcessingError(
                    errors.DOCUMENT_PARSE_FAILED,
                    "Parsed content exceeds the supported bound.",
                    "document",
                    document_id=document_id,
                )
        if not elements:
            raise ProcessingError(
                errors.DOCUMENT_PARSE_FAILED,
                "The document contains no readable source text.",
                "document",
                document_id=document_id,
            )
        return elements

    def make_chunks(self, elements):
        # Keep complete table rows as units without merging their cell identities.
        units = []
        headers = {}
        previous_key = None
        for element in elements:
            key = element.id
            if element.context.startswith("table cell;"):
                key = element.context.partition("; column:")[0]
                table = key.partition("; row:")[0]
                if any(r.get("role") == "column_header" for r in element.regions):
                    headers.setdefault(table, []).append(element)
            if key != previous_key:
                units.append([])
            units[-1].append(element)
            previous_key = key

        # Account for list separators as well as each serialized source element.
        sizes = {
            e.id: len(json.dumps(self.provider_element(e), ensure_ascii=False).encode("utf-8")) + 2
            for e in elements
        }
        chunks = []
        current = {}
        size = 2
        source_id_characters = 0
        for unit in units:
            table = unit[0].context.partition("; row:")[0]
            # Repeat real header elements in each relevant chunk so they remain citable.
            supported = {e.id: e for e in headers.get(table, []) + unit}
            additions = [e for e in supported.values() if e.id not in current]
            count = sum(sizes[e.id] for e in additions)
            ids = sum(len(e.id) for e in additions)
            if current and (
                size + count > self.settings.chunk_bytes
                or source_id_characters + ids > limits.GPT_SOURCE_ID_CHARACTERS
            ):
                chunks.append(list(current.values()))
                current = {}
                size = 2
                source_id_characters = 0
                additions = list(supported.values())
                count = sum(sizes[e.id] for e in additions)
                ids = sum(len(e.id) for e in additions)
            if (
                size + count > self.settings.chunk_bytes
                or source_id_characters + ids > limits.GPT_SOURCE_ID_CHARACTERS
            ):
                raise ProcessingError(
                    errors.DOCUMENT_PARSE_FAILED,
                    "A source element or complete table row exceeds the chunk bound.",
                    "document",
                    document_id=unit[0].document_id,
                )
            current.update((e.id, e) for e in additions)
            size += count
            source_id_characters += ids
        if current:
            chunks.append(list(current.values()))
        if len(chunks) > self.settings.max_chunks:
            raise ProcessingError(
                errors.DOCUMENT_PARSE_FAILED,
                "The document requires too many extraction chunks.",
                "document",
            )
        return chunks

    @staticmethod
    def provider_element(element):
        return {
            "id": element.id,
            "text": element.text,
            "regions": element.regions,
            "context": element.context,
        }


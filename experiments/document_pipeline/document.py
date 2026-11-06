"""Docling HTTP boundary and immutable, content-addressed provenance."""

import base64
import hashlib
import json
import math
import time
from pathlib import Path
import httpx

DOCLING_IMAGE = "ghcr.io/docling-project/docling-serve-cpu@sha256:7a480a1604fa3b42efeddc7db9527690d9f9bc903226136013e2bfe6b1a4dfb0"
OPTIONS = {
    "to_formats": ["json", "md"],
    "do_ocr": True,
    "do_table_structure": True,
    "table_mode": "accurate",
    "document_timeout": 300,
}


def normalized_region(prov, pages):
    page = prov["page_no"]
    size = pages[str(page)]["size"]
    width, height = size["width"], size["height"]
    box = prov["bbox"]
    left, right, top, bottom = (box[k] for k in ("l", "r", "t", "b"))
    if box["coord_origin"] == "BOTTOMLEFT":
        top, bottom = height - top, height - bottom
    elif box["coord_origin"] != "TOPLEFT":
        raise ValueError("Unknown coordinate origin")
    values = (width, height, left, right, top, bottom)
    if not all(type(v) in (float, int) and math.isfinite(v) for v in values) or not (
        width > 0
        and height > 0
        and 0 <= left < right <= width
        and 0 <= top < bottom <= height
    ):
        raise ValueError("Invalid document source bounds")
    return {
        "page": page,
        "bbox": [left / width, top / height, right / width, bottom / height],
        "coordinate_origin": "TOPLEFT",
        "page_size": size,
    }


def prepare_document(raw, source_hash, parse_id):
    doc = raw["document"]["json_content"]
    if not isinstance(doc, dict):
        raise ValueError("Docling did not return structured JSON")
    pages = doc["pages"]
    elements = []

    def add(ref, text, prov, **context):
        elements.append(
            {
                "id": f"{parse_id}:{ref}",
                "document_sha256": source_hash,
                "parse_id": parse_id,
                "text": text,
                "regions": [normalized_region(p, pages) for p in prov],
                **context,
            }
        )

    # Preserve paragraphs, headings, captions and furniture, not just table cells.
    for item in doc.get("texts", []):
        add(
            item["self_ref"],
            item["text"],
            item.get("prov", []),
            kind=item["label"],
            parent=item.get("parent"),
        )
    for table in doc.get("tables", []):
        prov = table.get("prov", [])
        for index, cell in enumerate(table["data"]["table_cells"]):
            # A cell bbox has no page ID. It is unambiguous only for a single-page table.
            cell_prov = (
                [{"page_no": prov[0]["page_no"], "bbox": cell["bbox"]}]
                if len(prov) == 1 and cell.get("bbox")
                else prov
            )
            add(
                f"{table['self_ref']}/cell/{index}",
                cell["text"],
                cell_prov,
                kind="table_cell",
                table=table["self_ref"],
                row=cell["start_row_offset_idx"],
                column=cell["start_col_offset_idx"],
                row_span=cell["row_span"],
                column_span=cell["col_span"],
                column_header=cell["column_header"],
                row_header=cell["row_header"],
                precision="cell" if len(prov) == 1 and cell.get("bbox") else "table",
            )
    return {
        "document_sha256": source_hash,
        "parse_id": parse_id,
        "schema_version": doc["version"],
        "elements": elements,
        "body": doc.get("body"),
        "groups": doc.get("groups", []),
        "markdown": raw["document"].get("md_content", ""),
    }


async def convert(path, output, url, render_pages=False):
    path, output = Path(path), Path(output)
    options = dict(OPTIONS)
    if render_pages and path.suffix.lower() == ".pdf":
        options.update(include_page_images=True, image_export_mode="embedded")
    content = path.read_bytes()
    digest = hashlib.sha256(content).hexdigest()
    # No cache in paired cold-processing benchmark: include every conversion.
    started = time.perf_counter()
    async with httpx.AsyncClient(timeout=360) as client:
        response = await client.post(
            url.rstrip("/") + "/v1/convert/file",
            files={"files": (path.name, content)},
            data=options,
        )
        response.raise_for_status()
        raw = response.json()
    if raw.get("status") != "success" or raw.get("errors"):
        raise ValueError("Docling conversion incomplete or failed")
    parse_id = hashlib.sha256(
        (
            digest
            + json.dumps(options, sort_keys=True)
            + DOCLING_IMAGE
            + json.dumps(raw["document"]["json_content"], sort_keys=True)
        ).encode()
    ).hexdigest()[:20]
    prepared = prepare_document(raw, digest, parse_id)
    output.mkdir(parents=True, exist_ok=True)
    (output / ("original" + path.suffix.lower())).write_bytes(content)
    (output / "docling.json").write_text(json.dumps(raw, indent=2))
    prepared["page_images"] = {}
    if render_pages:
        for number, page in raw["document"]["json_content"].get("pages", {}).items():
            uri = (page.get("image") or {}).get("uri", "")
            if isinstance(uri, str) and uri.startswith("data:image/png;base64,"):
                name = f"page-{int(number)}.png"
                (output / name).write_bytes(
                    base64.b64decode(uri.split(",", 1)[1], validate=True)
                )
                prepared["page_images"][number] = name
    (output / "document.json").write_text(json.dumps(prepared, indent=2))
    (output / "document.md").write_text(prepared["markdown"])
    return prepared, time.perf_counter() - started

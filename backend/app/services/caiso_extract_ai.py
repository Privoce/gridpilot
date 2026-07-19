"""Real AI extraction of CAISO intake fields from uploaded kickoff documents.

The guided demo uses deterministic example extractions; real accounts upload
actual files, which are parsed to text here and sent to Grok in a single call
that maps document content onto the structured intake schema.
"""

from __future__ import annotations

import asyncio
import io
import json
import logging
import re
import zipfile
from typing import Any

import httpx

logger = logging.getLogger("gridpilot.extract")

from backend.app.config import settings
from backend.app.services.caiso_packet import INTAKE_SECTIONS

# Upload slots and human labels (mirrors the documents section of the intake).
SLOT_LABELS = {
    "file_site_control": "Site exclusivity agreement (lease / option / deed)",
    "file_technical": "Technical data workbook",
    "file_bess": "BESS specification sheet",
    "file_signatory": "Proof of authorized signatory",
    "file_dyd": "Vendor PSLF dynamic model (.dyd)",
    "file_boundary": "Project boundary (KMZ / parcel map)",
}

MAX_CHARS_PER_DOC = 9000


class ExtractionError(RuntimeError):
    pass


def _pdf_text(data: bytes) -> str:
    import fitz

    with fitz.open(stream=data, filetype="pdf") as doc:
        return "\n".join(page.get_text() for page in doc)


def _xlsx_text(data: bytes) -> str:
    import openpyxl

    wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    lines: list[str] = []
    for ws in wb.worksheets:
        lines.append(f"# Sheet: {ws.title}")
        for row in ws.iter_rows(values_only=True):
            cells = [str(c) for c in row if c is not None and str(c).strip() != ""]
            if cells:
                lines.append(" | ".join(cells))
    return "\n".join(lines)


def _kmz_text(data: bytes) -> str:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            kml_names = [n for n in z.namelist() if n.lower().endswith(".kml")]
            if not kml_names:
                return ""
            kml = z.read(kml_names[0]).decode("utf-8", errors="replace")
    except zipfile.BadZipFile:
        kml = data.decode("utf-8", errors="replace")
    # Strip tags but keep coordinates and names readable.
    text = re.sub(r"<[^>]+>", " ", kml)
    return re.sub(r"\s+", " ", text)


def document_text(filename: str, data: bytes) -> str:
    name = filename.lower()
    try:
        if name.endswith(".pdf"):
            return _pdf_text(data)
        if name.endswith((".xlsx", ".xls")):
            return _xlsx_text(data)
        if name.endswith((".kmz", ".kml")):
            return _kmz_text(data)
        # .dyd, .csv, .txt, .md — treat as text
        return data.decode("utf-8", errors="replace")
    except Exception as exc:  # noqa: BLE001
        return f"[Could not parse file: {exc}]"


def _scalar_fields() -> list[dict[str, Any]]:
    fields = []
    for section in INTAKE_SECTIONS:
        for f in section["fields"]:
            if f.get("type") == "file":
                continue
            fields.append({
                "key": f["key"],
                "label": f["label"],
                "type": f.get("type", "text"),
                **({"options": f["options"]} if f.get("options") else {}),
            })
    return fields


def _extract_output_text(payload: dict[str, Any]) -> str:
    if isinstance(payload.get("output_text"), str) and payload["output_text"].strip():
        return payload["output_text"]
    chunks: list[str] = []
    for item in payload.get("output") or []:
        if item.get("type") == "message":
            for content in item.get("content") or []:
                if content.get("type") in {"output_text", "text"} and content.get("text"):
                    chunks.append(content["text"])
        elif item.get("type") in {"output_text", "text"} and item.get("text"):
            chunks.append(item["text"])
    if chunks:
        return "\n".join(chunks)
    raise ExtractionError("Could not parse model output")


def _parse_json_block(text: str) -> dict[str, Any]:
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fence:
        return json.loads(fence.group(1))
    start, end = text.find("{"), text.rfind("}")
    if start >= 0 and end > start:
        return json.loads(text[start : end + 1])
    raise ExtractionError("Model did not return valid JSON")


async def extract_intake_from_uploads(
    docs: dict[str, tuple[str, bytes]],
) -> dict[str, Any]:
    """One Grok call mapping uploaded kickoff documents onto intake fields.

    `docs` maps slot key -> (filename, bytes). Returns the same shape the demo
    extraction uses: {fields, provenance, summary}.
    """
    if not settings.xai_api_key:
        raise ExtractionError("AI extraction is not configured (XAI_API_KEY missing)")
    if not docs:
        raise ExtractionError("No documents provided")

    doc_sections = []
    for slot, (filename, data) in docs.items():
        text = document_text(filename, data)[:MAX_CHARS_PER_DOC]
        doc_sections.append(
            f"### DOCUMENT slot={slot} — {SLOT_LABELS.get(slot, slot)} — file: {filename}\n{text}"
        )

    fields_schema = json.dumps(_scalar_fields(), indent=1)
    prompt = f"""You are GridPilot, preparing a CAISO interconnection request intake for a renewable developer.

Extract values for the intake fields below from the attached kickoff documents.

RULES:
- Return STRICT JSON only (no markdown): {{"fields": {{<key>: <value>}}, "sources": {{<key>: <document slot>}}}}
- Only include fields you can actually support with document content — never guess or invent.
- Numbers must be plain JSON numbers (MW, MWh, kV, acres). Dates as MM/DD/YYYY strings.
- For "select"-type fields, the value MUST be one of the listed options (choose the closest supported by the documents).
- "gps" should be "lat, lon" in decimal degrees if coordinates appear (e.g. from KML).
- "sources" maps each extracted field key to the slot of the document that supports it.

INTAKE FIELDS:
{fields_schema}

DOCUMENTS:
{chr(10).join(doc_sections)}
"""

    data: dict[str, Any] | None = None
    last_err: Exception | None = None
    for attempt in range(2):  # one retry — xAI occasionally drops a request
        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                resp = await client.post(
                    f"{settings.xai_base_url.rstrip('/')}/responses",
                    headers={
                        "Authorization": f"Bearer {settings.xai_api_key}",
                        "Content-Type": "application/json",
                    },
                    json={"model": settings.xai_model, "input": prompt},
                )
            if resp.status_code >= 400:
                raise ExtractionError(f"xAI API {resp.status_code}: {resp.text[:400]}")
            data = _parse_json_block(_extract_output_text(resp.json()))
            break
        except (httpx.HTTPError, ExtractionError, json.JSONDecodeError) as exc:
            last_err = exc
            logger.warning("Extraction attempt %d failed: %s", attempt + 1, exc)
            if attempt == 0:
                await asyncio.sleep(1.5)
    if data is None:
        raise ExtractionError(f"AI extraction failed: {last_err}")
    raw_fields = data.get("fields") or {}
    sources = data.get("sources") or {}

    valid_keys = {f["key"] for f in _scalar_fields()}
    fields: dict[str, Any] = {}
    provenance: dict[str, dict[str, str]] = {}
    for key, value in raw_fields.items():
        if key not in valid_keys or value is None or value == "":
            continue
        fields[key] = value
        slot = sources.get(key)
        if slot in docs:
            provenance[key] = {
                "source": slot,
                "source_label": SLOT_LABELS.get(slot, slot),
                "file": docs[slot][0],
            }
    return {
        "fields": fields,
        "provenance": provenance,
        "summary": f"{len(fields)} fields extracted from {len(docs)} document(s)",
    }

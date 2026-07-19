"""CAISO Interconnection Request API — intake, validation, packet generation."""

from __future__ import annotations

import base64
import json
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse

from backend.app.deps import AuthContext, get_auth
from backend.app.services.caiso_packet import (
    CORRECTED_EXTRACTIONS,
    DEFAULT_INTAKE,
    INTAKE_SECTIONS,
    REQUIREMENTS,
    extract_from_documents,
    generate_packet,
    load_manifest,
    packet_file,
    validate_intake,
)
from backend.app.services.packet_preview import (
    render_kickoff_preview,
    render_preview,
    render_requirement_preview,
)

router = APIRouter(prefix="/api/caiso", tags=["caiso"])


def _decode_intake_param(d: str | None) -> dict[str, Any] | None:
    """Decode the base64url intake JSON clients attach to packet URLs."""
    if not d:
        return None
    try:
        raw = base64.urlsafe_b64decode(d + "=" * (-len(d) % 4))
        intake = json.loads(raw.decode("utf-8"))
        return intake if isinstance(intake, dict) else None
    except Exception:
        return None


def _resolve_manifest(packet_id: str, request: Request, auth: AuthContext) -> dict[str, Any]:
    """Load a packet manifest, regenerating it if this instance doesn't have it.

    Serverless instances don't share /tmp. Packet URLs carry the validated intake
    (`?d=`); the id is content-derived, so any instance can rebuild the identical
    packet on demand.
    """
    manifest = load_manifest(packet_id)
    if manifest and manifest.get("org_id") == auth.org.id:
        return manifest
    intake = _decode_intake_param(request.query_params.get("d"))
    if intake:
        try:
            manifest = generate_packet(intake, auth.org.id)
        except ValueError:
            manifest = None
        if manifest:
            return manifest
    raise HTTPException(status_code=404, detail="Packet not found")

MEDIA_TYPES = {
    ".pdf": "application/pdf",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".kmz": "application/vnd.google-earth.kmz",
    ".md": "text/markdown",
    ".epc": "text/plain",
    ".dyd": "text/plain",
    ".zip": "application/zip",
}


@router.get("/intake")
def get_intake(auth: AuthContext = Depends(get_auth)):
    return {"sections": INTAKE_SECTIONS, "defaults": DEFAULT_INTAKE}


@router.post("/extract")
def post_extract(
    body: dict[str, Any] = Body(...),
    auth: AuthContext = Depends(get_auth),
):
    """Extraction over document *metadata* — used by the guided demo's example files."""
    return extract_from_documents(body.get("files") or {})


@router.post("/extract-files")
async def post_extract_files(request: Request, auth: AuthContext = Depends(get_auth)):
    """Real AI extraction from uploaded document bytes (multipart form).

    Each form part is named after its upload slot (file_site_control,
    file_technical, …). Grok reads the parsed document text and returns
    intake fields with per-field provenance.
    """
    from backend.app.services.caiso_extract_ai import (
        SLOT_LABELS,
        ExtractionError,
        extract_intake_from_uploads,
    )

    form = await request.form()
    docs: dict[str, tuple[str, bytes]] = {}
    for slot in SLOT_LABELS:
        part = form.get(slot)
        if part is None or isinstance(part, str):
            continue
        data = await part.read()
        if data:
            docs[slot] = (part.filename or slot, data)
    if not docs:
        raise HTTPException(status_code=400, detail="Attach at least one document")
    try:
        return await extract_intake_from_uploads(docs)
    except ExtractionError as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@router.post("/validate")
def post_validate(
    intake: dict[str, Any] = Body(...),
    auth: AuthContext = Depends(get_auth),
):
    return validate_intake(intake)


@router.post("/generate")
def post_generate(
    intake: dict[str, Any] = Body(...),
    auth: AuthContext = Depends(get_auth),
):
    validation = validate_intake(intake)
    if not validation["ok"]:
        return {"ok": False, "validation": validation}
    manifest = generate_packet(intake, auth.org.id)
    return {"ok": True, "packet": manifest}


@router.get("/kickoff/{key}/preview", response_class=HTMLResponse)
def preview_kickoff_document(key: str, request: Request, auth: AuthContext = Depends(get_auth)):
    """Preview of a kickoff document (Step 2 uploads).

    Query params: `hl` — comma-separated highlight anchors for the part a validation
    check examined; `file` — display filename; any scalar intake key — current value
    override (the client's intake lives in its local storage, not on the server).
    """
    if not key.startswith("file_"):
        raise HTTPException(status_code=404, detail="Unknown kickoff document")
    q = request.query_params
    hl = [s for s in (q.get("hl") or "").split(",") if s]
    intake = dict(DEFAULT_INTAKE)
    for k, v in q.items():
        if k in DEFAULT_INTAKE and not isinstance(DEFAULT_INTAKE[k], dict):
            intake[k] = v
    default_meta = DEFAULT_INTAKE.get(key)
    name = q.get("file") or (default_meta.get("name") if isinstance(default_meta, dict) else key)
    example = not q.get("file") or bool(
        isinstance(default_meta, dict) and q.get("file") == default_meta.get("name")
    )
    # A replacement document represents the developer's corrected revision — its
    # preview shows the corrected values (matching what extraction will return),
    # so users can verify the fix before submitting it.
    if not example and key in CORRECTED_EXTRACTIONS:
        intake.update(CORRECTED_EXTRACTIONS[key])
    return HTMLResponse(render_kickoff_preview(key, intake, {"name": name, "example": example}, hl=hl))


@router.get("/requirements/{rule_id}/preview", response_class=HTMLResponse)
def preview_requirement(rule_id: str, auth: AuthContext = Depends(get_auth)):
    """The ISO requirement (ground truth) behind a validation check, clause highlighted."""
    req = REQUIREMENTS.get(rule_id)
    if not req:
        raise HTTPException(status_code=404, detail="Unknown requirement")
    return HTMLResponse(render_requirement_preview(rule_id, req))


@router.get("/packets/{packet_id}")
def get_packet(packet_id: str, request: Request, auth: AuthContext = Depends(get_auth)):
    return _resolve_manifest(packet_id, request, auth)


@router.get("/packets/{packet_id}/files/{filename}")
def get_packet_file(
    packet_id: str, filename: str, request: Request, auth: AuthContext = Depends(get_auth)
):
    manifest = _resolve_manifest(packet_id, request, auth)
    path = packet_file(manifest["id"], filename)
    if not path:
        raise HTTPException(status_code=404, detail="File not found")
    suffix = path.suffix.lower()
    media = MEDIA_TYPES.get(suffix, "application/octet-stream")
    disposition = "inline" if suffix in (".pdf", ".md") else "attachment"
    return FileResponse(path, filename=path.name, media_type=media,
                        content_disposition_type=disposition)


@router.get("/packets/{packet_id}/preview/{filename}", response_class=HTMLResponse)
def preview_packet_file(
    packet_id: str, filename: str, request: Request, auth: AuthContext = Depends(get_auth)
):
    """Styled in-browser preview for any packet document (xlsx, kmz, epc/dyd, md, pdf)."""
    manifest = _resolve_manifest(packet_id, request, auth)
    path = packet_file(manifest["id"], filename)
    if not path:
        raise HTTPException(status_code=404, detail="File not found")
    doc = next((d for d in manifest["documents"] if d["file"] == filename), {"file": filename})
    d_param = request.query_params.get("d")
    download_url = f"/api/caiso/packets/{manifest['id']}/files/{filename}" + (
        f"?d={d_param}" if d_param else ""
    )
    try:
        return HTMLResponse(render_preview(manifest, doc, path, download_url))
    except Exception:
        # Never dead-end the demo on a preview bug — fall back to the raw file.
        return HTMLResponse(
            f'<meta http-equiv="refresh" content="0;url={download_url}" />', status_code=200
        )

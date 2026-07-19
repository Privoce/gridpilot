"""CAISO Interconnection Request API — intake, validation, packet generation."""

from __future__ import annotations

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
    """AI extraction of intake fields from the uploaded kickoff documents."""
    return extract_from_documents(body.get("files") or {})


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
def get_packet(packet_id: str, auth: AuthContext = Depends(get_auth)):
    manifest = load_manifest(packet_id)
    if not manifest or manifest.get("org_id") != auth.org.id:
        raise HTTPException(status_code=404, detail="Packet not found")
    return manifest


@router.get("/packets/{packet_id}/files/{filename}")
def get_packet_file(packet_id: str, filename: str, auth: AuthContext = Depends(get_auth)):
    manifest = load_manifest(packet_id)
    if not manifest or manifest.get("org_id") != auth.org.id:
        raise HTTPException(status_code=404, detail="Packet not found")
    path = packet_file(packet_id, filename)
    if not path:
        raise HTTPException(status_code=404, detail="File not found")
    suffix = path.suffix.lower()
    media = MEDIA_TYPES.get(suffix, "application/octet-stream")
    disposition = "inline" if suffix in (".pdf", ".md") else "attachment"
    return FileResponse(path, filename=path.name, media_type=media,
                        content_disposition_type=disposition)


@router.get("/packets/{packet_id}/preview/{filename}", response_class=HTMLResponse)
def preview_packet_file(packet_id: str, filename: str, auth: AuthContext = Depends(get_auth)):
    """Styled in-browser preview for any packet document (xlsx, kmz, epc/dyd, md, pdf)."""
    manifest = load_manifest(packet_id)
    if not manifest or manifest.get("org_id") != auth.org.id:
        raise HTTPException(status_code=404, detail="Packet not found")
    path = packet_file(packet_id, filename)
    if not path:
        raise HTTPException(status_code=404, detail="File not found")
    doc = next((d for d in manifest["documents"] if d["file"] == filename), {"file": filename})
    download_url = f"/api/caiso/packets/{packet_id}/files/{filename}"
    try:
        return HTMLResponse(render_preview(manifest, doc, path, download_url))
    except Exception:
        # Never dead-end the demo on a preview bug — fall back to the raw file.
        return HTMLResponse(
            f'<meta http-equiv="refresh" content="0;url={download_url}" />', status_code=200
        )

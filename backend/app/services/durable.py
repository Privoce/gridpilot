"""Cross-instance durability for drawings and audits via Vercel Blob.

Serverless instances keep separate /tmp SQLite files. Uploads and completed
audits are snapshotted to Blob so any instance can restore rows and file bytes
another instance created. Everything degrades to a no-op locally.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path

from sqlalchemy.orm import Session

from backend.app.config import settings
from backend.app.db_models import (
    AuditRun,
    AuditStatus,
    Drawing,
    FindingRow,
    FindingSeverity,
    FindingTriage,
)
from backend.app.services.blob_store import (
    blob_enabled,
    blob_fetch,
    blob_get_json,
    blob_list,
    blob_put,
)

logger = logging.getLogger("gridpilot.durable")


def _dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Drawings
# ---------------------------------------------------------------------------

def _drawing_blob_path(org_id: str, project_id: str, drawing_id: str) -> str:
    return f"drawings/{org_id}/{project_id}/{drawing_id}.pdf"


def _drawing_meta_path(org_id: str, project_id: str, drawing_id: str) -> str:
    return f"meta/drawings/{org_id}/{project_id}/{drawing_id}.json"


def persist_drawing(drawing: Drawing, org_id: str, data: bytes) -> None:
    """Push a drawing's bytes + row snapshot to Blob (best-effort)."""
    if not blob_enabled():
        return
    blob_put(
        _drawing_blob_path(org_id, drawing.project_id, drawing.id),
        data,
        content_type=drawing.content_type or "application/pdf",
    )
    meta = {
        "id": drawing.id,
        "project_id": drawing.project_id,
        "org_id": org_id,
        "filename": drawing.filename,
        "content_type": drawing.content_type,
        "version_label": drawing.version_label,
        "page_count": drawing.page_count,
        "uploaded_by": drawing.uploaded_by,
        "created_at": drawing.created_at.isoformat() if drawing.created_at else None,
        "is_latest": drawing.is_latest,
    }
    blob_put(
        _drawing_meta_path(org_id, drawing.project_id, drawing.id),
        json.dumps(meta).encode("utf-8"),
        content_type="application/json",
    )


def restore_drawings(db: Session, org_id: str, project_id: str) -> None:
    """Recreate drawing rows this instance has never seen for a project."""
    if not blob_enabled():
        return
    blobs = blob_list(f"meta/drawings/{org_id}/{project_id}/", limit=20)
    if not blobs:
        return
    restored = False
    newest_seen = False
    for b in blobs:  # newest first
        raw = blob_fetch(b["url"])
        if not raw:
            continue
        try:
            meta = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if db.get(Drawing, meta["id"]):
            newest_seen = newest_seen or meta.get("is_latest", False)
            continue
        db.add(
            Drawing(
                id=meta["id"],
                project_id=project_id,
                filename=meta.get("filename") or "drawing.pdf",
                stored_path=str(
                    settings.upload_dir / org_id / project_id / f"{meta['id']}.pdf"
                ),
                content_type=meta.get("content_type") or "application/pdf",
                version_label=meta.get("version_label") or "Rev A",
                page_count=meta.get("page_count") or 1,
                uploaded_by=meta.get("uploaded_by"),
                created_at=_dt(meta.get("created_at")),
                is_latest=bool(meta.get("is_latest")) and not newest_seen,
            )
        )
        if meta.get("is_latest"):
            newest_seen = True
        restored = True
    if restored:
        db.commit()
        logger.info("Restored drawings for project %s from blob", project_id)


def ensure_drawing_file(drawing: Drawing, org_id: str) -> Path | None:
    """Return a local path for the drawing, downloading from Blob if needed."""
    path = Path(drawing.stored_path)
    if path.exists():
        return path
    if not blob_enabled():
        return None
    blobs = blob_list(_drawing_blob_path(org_id, drawing.project_id, drawing.id), limit=1)
    if not blobs:
        return None
    data = blob_fetch(blobs[0]["url"])
    if not data:
        return None
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


# ---------------------------------------------------------------------------
# Audits
# ---------------------------------------------------------------------------

def _audit_meta_path(org_id: str, audit_id: str) -> str:
    return f"meta/audits/{org_id}/{audit_id}.json"


def persist_audit(audit: AuditRun) -> None:
    """Snapshot a completed audit + findings to Blob (best-effort)."""
    if not blob_enabled():
        return
    snapshot = {
        "id": audit.id,
        "project_id": audit.project_id,
        "drawing_id": audit.drawing_id,
        "org_id": audit.org_id,
        "created_by": audit.created_by,
        "iso": audit.iso,
        "status": audit.status.value,
        "readiness_score": audit.readiness_score,
        "readiness_status": audit.readiness_status,
        "summary": audit.summary,
        "model": audit.model,
        "mode": audit.mode,
        "error": audit.error,
        "extract_json": audit.extract_json,
        "rules_checked_json": audit.rules_checked_json,
        "pages_analyzed": audit.pages_analyzed,
        "blocking_open": audit.blocking_open,
        "warning_open": audit.warning_open,
        "created_at": audit.created_at.isoformat() if audit.created_at else None,
        "started_at": audit.started_at.isoformat() if audit.started_at else None,
        "completed_at": audit.completed_at.isoformat() if audit.completed_at else None,
        "findings": [
            {
                "id": f.id,
                "external_key": f.external_key,
                "severity": f.severity.value,
                "title": f.title,
                "detail": f.detail,
                "rule_id": f.rule_id,
                "location": f.location,
                "recommendation": f.recommendation,
                "evidence": f.evidence,
                "triage": f.triage.value,
                "triage_note": f.triage_note,
                "triaged_by": f.triaged_by,
                "triaged_at": f.triaged_at.isoformat() if f.triaged_at else None,
            }
            for f in audit.findings
        ],
    }
    blob_put(
        _audit_meta_path(audit.org_id, audit.id),
        json.dumps(snapshot).encode("utf-8"),
        content_type="application/json",
    )


def restore_audit(db: Session, org_id: str, audit_id: str) -> AuditRun | None:
    """Recreate an audit row (+ findings) from its Blob snapshot."""
    if not blob_enabled():
        return None
    snap = blob_get_json(_audit_meta_path(org_id, audit_id))
    if not snap or snap.get("org_id") != org_id:
        return None
    # Foreign keys are enforced — the project row comes from the gp_projects
    # cookie (restored in get_auth); drawings must be restored here.
    from backend.app.db_models import Project

    if not db.get(Project, snap["project_id"]):
        logger.warning("restore_audit %s: project %s unknown", audit_id, snap["project_id"])
        return None
    restore_drawings(db, org_id, snap["project_id"])
    if snap.get("drawing_id") and not db.get(Drawing, snap["drawing_id"]):
        logger.warning("restore_audit %s: drawing %s unknown", audit_id, snap["drawing_id"])
        return None
    audit = AuditRun(
        id=snap["id"],
        project_id=snap["project_id"],
        drawing_id=snap["drawing_id"],
        org_id=org_id,
        created_by=snap.get("created_by"),
        iso=snap.get("iso") or "CAISO",
        status=AuditStatus(snap.get("status") or "completed"),
        readiness_score=snap.get("readiness_score"),
        readiness_status=snap.get("readiness_status"),
        summary=snap.get("summary"),
        model=snap.get("model"),
        mode=snap.get("mode"),
        error=snap.get("error"),
        extract_json=snap.get("extract_json"),
        rules_checked_json=snap.get("rules_checked_json"),
        pages_analyzed=snap.get("pages_analyzed") or 0,
        blocking_open=snap.get("blocking_open") or 0,
        warning_open=snap.get("warning_open") or 0,
        created_at=_dt(snap.get("created_at")),
        started_at=_dt(snap.get("started_at")),
        completed_at=_dt(snap.get("completed_at")),
    )
    db.add(audit)
    for f in snap.get("findings") or []:
        db.add(
            FindingRow(
                id=f["id"],
                audit_id=audit.id,
                external_key=f.get("external_key"),
                severity=FindingSeverity(f.get("severity") or "warning"),
                title=f.get("title") or "",
                detail=f.get("detail") or "",
                rule_id=f.get("rule_id"),
                location=f.get("location"),
                recommendation=f.get("recommendation"),
                evidence=f.get("evidence"),
                triage=FindingTriage(f.get("triage") or "open"),
                triage_note=f.get("triage_note"),
                triaged_by=f.get("triaged_by"),
                triaged_at=_dt(f.get("triaged_at")),
            )
        )
    db.commit()
    logger.info("Restored audit %s from blob", audit_id)
    return db.get(AuditRun, audit_id)


def restore_audits_for_org(db: Session, org_id: str, limit: int = 10) -> None:
    """Restore an org's recent audit snapshots (for list/dashboard views)."""
    if not blob_enabled():
        return
    blobs = blob_list(f"meta/audits/{org_id}/", limit=limit)
    for b in blobs:
        audit_id = b.get("pathname", "").rsplit("/", 1)[-1].removesuffix(".json")
        if not audit_id or db.get(AuditRun, audit_id):
            continue
        try:
            restore_audit(db, org_id, audit_id)
        except Exception as exc:  # noqa: BLE001 — one bad snapshot shouldn't kill the page
            logger.warning("restore_audits_for_org %s: %s", audit_id, exc)
            db.rollback()

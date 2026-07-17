from __future__ import annotations

import shutil
import uuid
from pathlib import Path
from typing import Optional

import fitz
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from backend.app.billing import assert_can_create_project, assert_can_run_audit
from backend.app.config import settings
from backend.app.db import get_db
from backend.app.db_models import AuditRun, AuditStatus, Drawing, Project
from backend.app.deps import AuthContext, get_auth
from backend.app.schemas import ProjectCreate, ProjectUpdate
from backend.app.serializers import drawing_out, project_out
from backend.app.services.jobs import enqueue_audit
from backend.app.services.pdf_extract import render_pdf

router = APIRouter(prefix="/api/projects", tags=["projects"])


def _get_project(db: Session, auth: AuthContext, project_id: str) -> Project:
    project = db.get(Project, project_id)
    if not project or project.org_id != auth.org.id:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


def _latest_drawing(db: Session, project_id: str) -> Drawing | None:
    return (
        db.query(Drawing)
        .filter(Drawing.project_id == project_id, Drawing.is_latest.is_(True))
        .order_by(Drawing.created_at.desc())
        .first()
    )


def _latest_audit(db: Session, project_id: str) -> AuditRun | None:
    return (
        db.query(AuditRun)
        .filter(AuditRun.project_id == project_id)
        .order_by(AuditRun.created_at.desc())
        .first()
    )


@router.get("")
def list_projects(auth: AuthContext = Depends(get_auth), db: Session = Depends(get_db)):
    projects = (
        db.query(Project)
        .filter(Project.org_id == auth.org.id, Project.status == "active")
        .order_by(Project.updated_at.desc())
        .all()
    )
    return {
        "projects": [
            project_out(p, _latest_drawing(db, p.id), _latest_audit(db, p.id)) for p in projects
        ]
    }


@router.post("")
def create_project(
    payload: ProjectCreate,
    auth: AuthContext = Depends(get_auth),
    db: Session = Depends(get_db),
):
    assert_can_create_project(db, auth.org)
    project = Project(
        org_id=auth.org.id,
        name=payload.name.strip(),
        iso=payload.iso,
        capacity_mw=payload.capacity_mw,
        state=payload.state,
        poi_substation=payload.poi_substation,
    )
    db.add(project)
    db.commit()
    db.refresh(project)
    return project_out(project)


@router.get("/{project_id}")
def get_project(
    project_id: str,
    auth: AuthContext = Depends(get_auth),
    db: Session = Depends(get_db),
):
    project = _get_project(db, auth, project_id)
    drawings = (
        db.query(Drawing)
        .filter(Drawing.project_id == project.id)
        .order_by(Drawing.created_at.desc())
        .all()
    )
    audits = (
        db.query(AuditRun)
        .filter(AuditRun.project_id == project.id)
        .order_by(AuditRun.created_at.desc())
        .limit(20)
        .all()
    )
    from backend.app.serializers import audit_summary

    return {
        "project": project_out(project, _latest_drawing(db, project.id), _latest_audit(db, project.id)),
        "drawings": [drawing_out(d) for d in drawings],
        "audits": [
            audit_summary(a, next((d.filename for d in drawings if d.id == a.drawing_id), None))
            for a in audits
        ],
    }


@router.patch("/{project_id}")
def update_project(
    project_id: str,
    payload: ProjectUpdate,
    auth: AuthContext = Depends(get_auth),
    db: Session = Depends(get_db),
):
    project = _get_project(db, auth, project_id)
    data = payload.model_dump(exclude_unset=True)
    for key, value in data.items():
        setattr(project, key, value)
    db.commit()
    db.refresh(project)
    return project_out(project, _latest_drawing(db, project.id), _latest_audit(db, project.id))


@router.post("/{project_id}/drawings")
async def upload_drawing(
    project_id: str,
    file: UploadFile = File(...),
    version_label: str = Form("Rev A"),
    auth: AuthContext = Depends(get_auth),
    db: Session = Depends(get_db),
):
    project = _get_project(db, auth, project_id)
    suffix = Path(file.filename or "drawing.pdf").suffix.lower()
    if suffix not in {".pdf", ".png", ".jpg", ".jpeg"}:
        raise HTTPException(status_code=400, detail="Upload a PDF or image (PNG/JPG)")

    dest_dir = settings.upload_dir / auth.org.id / project.id
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"{uuid.uuid4().hex}{suffix}"
    with dest.open("wb") as out:
        shutil.copyfileobj(file.file, out)

    if suffix != ".pdf":
        pdf_path = dest.with_suffix(".pdf")
        doc = fitz.open()
        img = fitz.open(dest)
        rect = img[0].rect
        page = doc.new_page(width=rect.width, height=rect.height)
        page.insert_image(rect, filename=str(dest))
        doc.save(pdf_path)
        doc.close()
        img.close()
        dest = pdf_path
        content_type = "application/pdf"
        filename = Path(file.filename or "drawing").with_suffix(".pdf").name
    else:
        content_type = file.content_type or "application/pdf"
        filename = file.filename or dest.name

    pdf_meta = render_pdf(dest, max_pages=1)
    for old in (
        db.query(Drawing)
        .filter(Drawing.project_id == project.id, Drawing.is_latest.is_(True))
        .all()
    ):
        old.is_latest = False

    drawing = Drawing(
        project_id=project.id,
        filename=filename,
        stored_path=str(dest),
        content_type=content_type,
        version_label=version_label.strip() or "Rev A",
        page_count=pdf_meta.page_count,
        uploaded_by=auth.user.id,
        is_latest=True,
    )
    db.add(drawing)
    db.commit()
    db.refresh(drawing)
    return drawing_out(drawing)


@router.api_route("/{project_id}/drawings/{drawing_id}/file", methods=["GET", "HEAD"])
def download_drawing(
    project_id: str,
    drawing_id: str,
    auth: AuthContext = Depends(get_auth),
    db: Session = Depends(get_db),
):
    project = _get_project(db, auth, project_id)
    drawing = db.get(Drawing, drawing_id)
    if not drawing or drawing.project_id != project.id:
        raise HTTPException(status_code=404, detail="Drawing not found")
    path = Path(drawing.stored_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="File missing")
    return FileResponse(
        path,
        filename=drawing.filename,
        media_type=drawing.content_type,
        content_disposition_type="inline",
    )


@router.get("/{project_id}/drawings/{drawing_id}/preview.png")
def preview_drawing(
    project_id: str,
    drawing_id: str,
    auth: AuthContext = Depends(get_auth),
    db: Session = Depends(get_db),
):
    """Rasterize page 1 — more reliable than embedding PDFs in iframes."""
    import fitz
    from fastapi.responses import Response

    project = _get_project(db, auth, project_id)
    drawing = db.get(Drawing, drawing_id)
    if not drawing or drawing.project_id != project.id:
        raise HTTPException(status_code=404, detail="Drawing not found")
    path = Path(drawing.stored_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="File missing")
    doc = fitz.open(path)
    try:
        page = doc[0]
        pix = page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5), alpha=False)
        return Response(content=pix.tobytes("png"), media_type="image/png")
    finally:
        doc.close()


@router.post("/{project_id}/audits")
def start_audit(
    project_id: str,
    drawing_id: Optional[str] = None,
    auth: AuthContext = Depends(get_auth),
    db: Session = Depends(get_db),
):
    project = _get_project(db, auth, project_id)
    assert_can_run_audit(auth.org)

    drawing = None
    if drawing_id:
        drawing = db.get(Drawing, drawing_id)
        if drawing and drawing.project_id != project.id:
            drawing = None
    if not drawing:
        # Stale client drawing ids are common on serverless cold starts — use latest.
        drawing = _latest_drawing(db, project.id)
    if not drawing:
        raise HTTPException(status_code=400, detail="Upload a drawing before running an audit")

    audit = AuditRun(
        project_id=project.id,
        drawing_id=drawing.id,
        org_id=auth.org.id,
        created_by=auth.user.id,
        iso=project.iso,
        status=AuditStatus.QUEUED,
    )
    auth.org.audits_used_period += 1
    db.add(audit)
    db.commit()
    db.refresh(audit)

    enqueue_audit(audit.id)

    from backend.app.serializers import audit_summary

    db.refresh(audit)
    return audit_summary(audit, drawing.filename)

from __future__ import annotations

import shutil
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from backend.app.auth import create_session_token
from backend.app.billing import maybe_roll_period
from backend.app.config import ROOT, settings
from backend.app.db import get_db
from backend.app.db_models import (
    AuditRun,
    Drawing,
    FindingRow,
    Membership,
    Organization,
    Project,
    User,
)
from backend.app.deps import AuthContext, get_auth, org_payload
from backend.app.seed import DEMO_EMAIL, DEMO_PASSWORD, ensure_sample_pdf, seed_demo

router = APIRouter(prefix="/api/demo", tags=["demo"])

INTENTIONAL_DEFECTS = [
    {
        "severity": "blocking",
        "title": "Inverter LVRT / ride-through not documented",
        "why": "PJM IBR filings expect LVRT/HVRT callouts on the inverter schedule.",
    },
    {
        "severity": "blocking",
        "title": "POI breaker interrupting rating (kA) missing",
        "why": "52-POI is drawn but the interrupting capability field is blank — common requeue cause.",
    },
    {
        "severity": "warning",
        "title": "Transformer %Z / X/R not annotated",
        "why": "GSU MVA is present; impedance is required for model quality.",
    },
    {
        "severity": "warning",
        "title": "SCADA / RTU telemetry path omitted",
        "why": "ISO reviewers expect a telemetry note for new generation.",
    },
    {
        "severity": "warning",
        "title": "Grounding transformer / IEEE 1547 citation missing",
        "why": "Completeness items that often trigger RFIs before acceptance.",
    },
]


def _demo_user(db: Session) -> User:
    seed_demo(db)
    db.commit()
    user = db.query(User).filter(User.email == DEMO_EMAIL).first()
    if not user:
        raise HTTPException(status_code=500, detail="Demo account unavailable")
    return user


def _demo_project(db: Session, org_id: str) -> Project:
    project = (
        db.query(Project)
        .filter(Project.org_id == org_id, Project.name == "Cedar Ridge Solar + Storage")
        .first()
    )
    if not project:
        project = (
            db.query(Project)
            .filter(Project.org_id == org_id, Project.status == "active")
            .order_by(Project.created_at.asc())
            .first()
        )
    if not project:
        raise HTTPException(status_code=404, detail="Demo project not found")
    return project


def _ensure_drawing(db: Session, project: Project, user_id: str) -> Drawing:
    latest = (
        db.query(Drawing)
        .filter(Drawing.project_id == project.id, Drawing.is_latest.is_(True))
        .order_by(Drawing.created_at.desc())
        .first()
    )
    if latest and Path(latest.stored_path).exists():
        return latest

    sample = ensure_sample_pdf()
    dest_dir = settings.upload_dir / project.org_id / project.id
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"demo_{sample.name}"
    shutil.copy2(sample, dest)

    for old in (
        db.query(Drawing)
        .filter(Drawing.project_id == project.id, Drawing.is_latest.is_(True))
        .all()
    ):
        old.is_latest = False

    drawing = Drawing(
        project_id=project.id,
        filename=sample.name,
        stored_path=str(dest),
        version_label="Rev A — demo SLD",
        page_count=1,
        uploaded_by=user_id,
        is_latest=True,
    )
    db.add(drawing)
    db.commit()
    db.refresh(drawing)
    return drawing


@router.get("/info")
def demo_info():
    """Public demo brief — no auth required."""
    return {
        "email": DEMO_EMAIL,
        "password": DEMO_PASSWORD,
        "scenario": {
            "project": "Cedar Ridge Solar + Storage",
            "capacity_mw": 120,
            "iso": "PJM",
            "poi": "Cedar Ridge 138 kV",
            "state": "IN",
            "role": "Interconnection manager at Northwind Renewables",
        },
        "sample_drawing": "cedar_ridge_sld_demo.pdf",
        "intentional_defects": INTENTIONAL_DEFECTS,
        "steps": [
            "Enter the demo workspace as Alex Rivera (interconnection manager).",
            "Open the seeded Cedar Ridge project and review the sample SLD PDF.",
            "Run a PJM interconnection readiness audit on that drawing.",
            "Triage blocking findings (resolve / acknowledge) until the filing gate clears.",
            "Export the Interconnection Readiness Report.",
        ],
    }


@router.post("/start")
def start_demo(response: Response, db: Session = Depends(get_db)):
    """One-click demo login + ensure sample project/drawing exist."""
    user = _demo_user(db)
    membership = db.query(Membership).filter(Membership.user_id == user.id).first()
    if not membership:
        raise HTTPException(status_code=500, detail="Demo membership missing")
    org = db.get(Organization, membership.org_id)
    assert org
    maybe_roll_period(org)

    project = _demo_project(db, org.id)
    drawing = _ensure_drawing(db, project, user.id)
    db.commit()

    token = create_session_token(user.id)
    response.set_cookie(
        key=settings.session_cookie,
        value=token,
        httponly=True,
        samesite="lax",
        max_age=settings.session_max_age,
        path="/",
    )

    project_count = (
        db.query(Project).filter(Project.org_id == org.id, Project.status == "active").count()
    )
    latest_audit = (
        db.query(AuditRun)
        .filter(AuditRun.project_id == project.id)
        .order_by(AuditRun.created_at.desc())
        .first()
    )

    return {
        "user": {"id": user.id, "email": user.email, "name": user.name},
        "org": org_payload(org, membership.role.value, project_count),
        "is_demo": True,
        "project_id": project.id,
        "drawing_id": drawing.id,
        "latest_audit_id": latest_audit.id if latest_audit else None,
        "onboarding_path": f"onboarding",
    }


@router.get("/context")
def demo_context(auth: AuthContext = Depends(get_auth), db: Session = Depends(get_db)):
    if auth.user.email != DEMO_EMAIL:
        raise HTTPException(status_code=403, detail="Demo context is only for the demo account")

    project = _demo_project(db, auth.org.id)
    drawing = _ensure_drawing(db, project, auth.user.id)
    latest_audit = (
        db.query(AuditRun)
        .filter(AuditRun.project_id == project.id)
        .order_by(AuditRun.created_at.desc())
        .first()
    )

    open_blocking = latest_audit.blocking_open if latest_audit else 0
    completed = bool(latest_audit and latest_audit.status.value == "completed")

    return {
        "is_demo": True,
        "scenario": {
            "project": project.name,
            "capacity_mw": project.capacity_mw,
            "iso": project.iso,
            "poi": project.poi_substation,
            "state": project.state,
        },
        "project_id": project.id,
        "drawing_id": drawing.id,
        "drawing_filename": drawing.filename,
        "drawing_url": f"/api/projects/{project.id}/drawings/{drawing.id}/file",
        "sample_pdf_url": "/api/demo/sample.pdf",
        "latest_audit_id": latest_audit.id if latest_audit else None,
        "latest_audit_status": latest_audit.status.value if latest_audit else None,
        "readiness_score": latest_audit.readiness_score if latest_audit else None,
        "open_blocking": open_blocking,
        "can_file": completed and open_blocking == 0,
        "intentional_defects": INTENTIONAL_DEFECTS,
        "progress": {
            "viewed_project": True,  # client tracks finer steps in localStorage
            "has_drawing": True,
            "has_audit": latest_audit is not None,
            "audit_completed": completed,
            "blockers_cleared": completed and open_blocking == 0,
        },
    }


@router.get("/sample.pdf")
def sample_pdf():
    path = ensure_sample_pdf()
    return FileResponse(
        path,
        filename=path.name,
        media_type="application/pdf",
        content_disposition_type="inline",
    )


@router.post("/reset")
def reset_demo(auth: AuthContext = Depends(get_auth), db: Session = Depends(get_db)):
    """Clear prior audits so the guided demo can be re-run cleanly."""
    if auth.user.email != DEMO_EMAIL:
        raise HTTPException(status_code=403, detail="Only the demo account can reset")

    project = _demo_project(db, auth.org.id)
    audits = db.query(AuditRun).filter(AuditRun.project_id == project.id).all()
    for audit in audits:
        db.query(FindingRow).filter(FindingRow.audit_id == audit.id).delete()
        db.delete(audit)
    _ensure_drawing(db, project, auth.user.id)
    db.commit()
    return {"ok": True, "project_id": project.id, "message": "Demo audits cleared. Sample SLD retained."}

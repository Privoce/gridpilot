from __future__ import annotations

import shutil
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from backend.app.auth import create_session_token
from backend.app.billing import maybe_roll_period
from backend.app.config import settings
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

DEMO_PROJECT_NAME = "Cedar Ridge Solar + Storage"

# AES Indiana Facilities Connection Requirements — common SLD gaps (demo)
INTENTIONAL_DEFECTS = [
    {
        "severity": "blocking",
        "rule_id": "R-PROTECT-01",
        "title": "Protective relays missing ANSI function numbers",
        "why": "AES Indiana expects relays labeled with ANSI device numbers (27/59/81/67, etc.).",
    },
    {
        "severity": "blocking",
        "rule_id": "R-METER-01",
        "title": "CT/PT ratios not annotated at POI metering",
        "why": "Revenue metering CT/PT ratios are required on the interconnection SLD.",
    },
    {
        "severity": "blocking",
        "rule_id": "R-IBR-01",
        "title": "IBR P-Q / capability curves not shown",
        "why": "New IBRs on AES Indiana must document reactive capability (NERC VAR-002 / FERC 842).",
    },
    {
        "severity": "warning",
        "rule_id": "R-TITLE-01",
        "title": "As-built revision / date block incomplete",
        "why": "AES Indiana requires as-built one-lines with revision number and date before energization.",
    },
    {
        "severity": "warning",
        "rule_id": "R-METER-02",
        "title": "Bidirectional / AES Indiana meter labeling incomplete",
        "why": "POI revenue meter should call out bidirectional metering for the AES Indiana interconnection.",
    },
]

SCENARIO = {
    "project": DEMO_PROJECT_NAME,
    "capacity_mw": 120,
    "iso": "MISO",
    "utility": "AES Indiana",
    "poi": "AES Indiana — Cedar Ridge 138 kV",
    "state": "IN",
    "role": "Interconnection manager at Northwind Renewables (developer)",
    "buyer": "Developer",
    "filing_path": "Transmission-scale → MISO DPP (AES Indiana is the transmission owner)",
    "channel": "MISO DPP + AES Indiana Facilities Connection Requirements",
    "why_this_demo": (
        "120 MW exceeds typical distribution thresholds, so the primary queue is MISO. "
        "AES Indiana still reviews TO / Facilities Connection Requirements (SLD, protection, metering). "
        "GridPilot runs that checklist before you pay for another consultant revision or burn queue time."
    ),
    "portal": "https://www.aesindiana.com/interconnections",
    "powerclerk": "https://aesindianainterconnection.powerclerk.com",
}


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
        .filter(Project.org_id == org_id, Project.name == DEMO_PROJECT_NAME)
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
    # Keep seeded demo aligned with AES Indiana / MISO scenario
    project.iso = SCENARIO["iso"]
    project.state = SCENARIO["state"]
    project.poi_substation = SCENARIO["poi"]
    project.capacity_mw = float(SCENARIO["capacity_mw"])
    return project


def _ensure_drawing(db: Session, project: Project, user_id: str) -> Drawing:
    sample = ensure_sample_pdf()
    latest = (
        db.query(Drawing)
        .filter(Drawing.project_id == project.id, Drawing.is_latest.is_(True))
        .order_by(Drawing.created_at.desc())
        .first()
    )
    dest_dir = settings.upload_dir / project.org_id / project.id
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"demo_{sample.name}"
    shutil.copy2(sample, dest)

    if latest:
        latest.stored_path = str(dest)
        latest.filename = sample.name
        latest.version_label = "Rev A — AES Indiana demo SLD"
        db.commit()
        db.refresh(latest)
        return latest

    drawing = Drawing(
        project_id=project.id,
        filename=sample.name,
        stored_path=str(dest),
        version_label="Rev A — AES Indiana demo SLD",
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
        "scenario": SCENARIO,
        "sample_drawing": "cedar_ridge_sld_demo.pdf",
        "intentional_defects": INTENTIONAL_DEFECTS,
        "steps": [
            "Enter as Alex Rivera — interconnection manager at a developer (not the utility).",
            "Review the Cedar Ridge SLD that would go into the AES Indiana / MISO filing packet.",
            "Run a pre-filing audit against published AES Indiana Facilities Connection Requirements.",
            "Triage blockers before consultants resubmit or you enter the MISO DPP queue.",
            "Export a readiness report — then you would file (PowerClerk / MISO), not GridPilot.",
        ],
        "links": {
            "aes_indiana_interconnections": SCENARIO["portal"],
            "powerclerk": SCENARIO["powerclerk"],
        },
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
        secure=settings.use_secure_cookies,
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
        "onboarding_path": "onboarding",
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
    db.commit()

    open_blocking = latest_audit.blocking_open if latest_audit else 0
    completed = bool(latest_audit and latest_audit.status.value == "completed")

    return {
        "is_demo": True,
        "scenario": {
            **SCENARIO,
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
        "drawing_preview_url": f"/api/projects/{project.id}/drawings/{drawing.id}/preview.png",
        "sample_pdf_url": "/api/demo/sample.pdf",
        "sample_preview_url": "/assets/img/cedar_ridge_sld_demo.png",
        "latest_audit_id": latest_audit.id if latest_audit else None,
        "latest_audit_status": latest_audit.status.value if latest_audit else None,
        "readiness_score": latest_audit.readiness_score if latest_audit else None,
        "open_blocking": open_blocking,
        "can_file": completed and open_blocking == 0,
        "intentional_defects": INTENTIONAL_DEFECTS,
        "links": {
            "aes_indiana_interconnections": SCENARIO["portal"],
            "powerclerk": SCENARIO["powerclerk"],
        },
        "progress": {
            "viewed_project": True,
            "has_drawing": True,
            "has_audit": latest_audit is not None,
            "audit_completed": completed,
            "blockers_cleared": completed and open_blocking == 0,
        },
    }


@router.api_route("/sample.pdf", methods=["GET", "HEAD"])
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
    for a in audits:
        db.query(FindingRow).filter(FindingRow.audit_id == a.id).delete()
        db.delete(a)
    _ensure_drawing(db, project, auth.user.id)
    db.commit()
    return {"ok": True, "message": "Demo audits cleared. Re-run the AES Indiana SLD audit."}

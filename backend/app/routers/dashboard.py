from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.app.billing import audit_limit_for, maybe_roll_period, plan_features, project_limit_for
from backend.app.db import get_db
from backend.app.db_models import AuditRun, AuditStatus, Project
from backend.app.deps import AuthContext, get_auth
from backend.app.serializers import audit_summary, project_out

router = APIRouter(prefix="/api", tags=["dashboard"])


@router.get("/dashboard")
def dashboard(auth: AuthContext = Depends(get_auth), db: Session = Depends(get_db)):
    maybe_roll_period(auth.org)
    db.commit()

    projects = (
        db.query(Project)
        .filter(Project.org_id == auth.org.id, Project.status == "active")
        .order_by(Project.updated_at.desc())
        .all()
    )
    audits = (
        db.query(AuditRun)
        .filter(AuditRun.org_id == auth.org.id)
        .order_by(AuditRun.created_at.desc())
        .limit(8)
        .all()
    )

    open_blocking = sum(a.blocking_open for a in audits if a.status.value == "completed")
    open_warnings = sum(a.warning_open for a in audits if a.status.value == "completed")

    # Prefer org-wide open counts from latest completed audit per project
    latest_by_project: dict[str, AuditRun] = {}
    for a in (
        db.query(AuditRun)
        .filter(AuditRun.org_id == auth.org.id, AuditRun.status == AuditStatus.COMPLETED)
        .order_by(AuditRun.created_at.desc())
        .all()
    ):
        if a.project_id not in latest_by_project:
            latest_by_project[a.project_id] = a
    open_blocking = sum(a.blocking_open for a in latest_by_project.values())
    open_warnings = sum(a.warning_open for a in latest_by_project.values())

    recent_projects = []
    for p in projects[:6]:
        latest_audit = latest_by_project.get(p.id)
        latest_drawing = next((d for d in p.drawings if d.is_latest), None)
        recent_projects.append(project_out(p, latest_drawing, latest_audit))

    return {
        "projects": len(projects),
        "audits_this_period": auth.org.audits_used_period,
        "audit_limit": audit_limit_for(auth.org.plan),
        "open_blocking": open_blocking,
        "open_warnings": open_warnings,
        "recent_audits": [
            audit_summary(a, a.drawing.filename if a.drawing else None) for a in audits
        ],
        "recent_projects": recent_projects,
    }


@router.get("/billing")
def billing(auth: AuthContext = Depends(get_auth), db: Session = Depends(get_db)):
    maybe_roll_period(auth.org)
    db.commit()
    project_count = (
        db.query(Project)
        .filter(Project.org_id == auth.org.id, Project.status == "active")
        .count()
    )
    return {
        "plan": auth.org.plan.value,
        "audits_used_period": auth.org.audits_used_period,
        "audit_limit": audit_limit_for(auth.org.plan),
        "project_count": project_count,
        "project_limit": project_limit_for(auth.org.plan),
        "period_start": auth.org.period_start,
        "features": plan_features(auth.org.plan),
    }


@router.post("/billing/upgrade")
def upgrade(auth: AuthContext = Depends(get_auth), db: Session = Depends(get_db)):
    """Demo upgrade path — flips org to Pro without Stripe."""
    from backend.app.db_models import Plan

    auth.org.plan = Plan.PRO
    db.commit()
    return {"ok": True, "plan": "pro", "message": "Upgraded to Pro (demo billing)."}

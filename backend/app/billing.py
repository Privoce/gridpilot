from __future__ import annotations

from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy.orm import Session

from backend.app.config import settings
from backend.app.db_models import Organization, Plan, Project


def audit_limit_for(plan: Plan) -> int:
    if plan == Plan.ENTERPRISE:
        return 10_000
    if plan == Plan.PRO:
        return settings.pro_audit_limit
    return settings.free_audit_limit


def project_limit_for(plan: Plan) -> int:
    if plan == Plan.ENTERPRISE:
        return 10_000
    if plan == Plan.PRO:
        return 250
    return settings.free_project_limit


def maybe_roll_period(org: Organization) -> None:
    now = datetime.now(timezone.utc)
    start = org.period_start
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    if (now - start).days >= 30:
        org.period_start = now
        org.audits_used_period = 0


def assert_can_create_project(db: Session, org: Organization) -> None:
    maybe_roll_period(org)
    count = db.query(Project).filter(Project.org_id == org.id, Project.status == "active").count()
    limit = project_limit_for(org.plan)
    if count >= limit:
        raise HTTPException(
            status_code=402,
            detail=f"Project limit reached ({limit} on {org.plan.value} plan). Upgrade to continue.",
        )


def assert_can_run_audit(org: Organization) -> None:
    maybe_roll_period(org)
    limit = audit_limit_for(org.plan)
    if org.audits_used_period >= limit:
        raise HTTPException(
            status_code=402,
            detail=f"Monthly audit limit reached ({limit} on {org.plan.value} plan). Upgrade to continue.",
        )


def plan_features(plan: Plan) -> list[str]:
    base = [
        "Developer pre-filing SLD audit",
        "Utility + ISO rule packs (AES Indiana / MISO demo)",
        "Finding triage workflow",
        "Filing readiness gate",
        "HTML + JSON export",
    ]
    if plan == Plan.FREE:
        return base + [f"{settings.free_audit_limit} audits / 30 days", f"{settings.free_project_limit} active projects"]
    if plan == Plan.PRO:
        return base + [
            f"{settings.pro_audit_limit} audits / 30 days",
            "Priority Vision queue",
            "Drawing version history",
            "Team seats (coming soon)",
        ]
    return base + [
        "Unlimited audits",
        "SSO / VPC / on-prem options",
        "Custom utility + ISO rule packs",
        "Dedicated success engineer",
    ]

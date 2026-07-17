from __future__ import annotations

from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from backend.app.auth import read_session_token
from backend.app.billing import audit_limit_for, project_limit_for
from backend.app.config import settings
from backend.app.db import get_db
from backend.app.db_models import Membership, Organization, User


@dataclass
class AuthContext:
    user: User
    org: Organization
    membership: Membership


def get_current_user(
    request: Request,
    db: Session = Depends(get_db),
) -> User:
    token = request.cookies.get(settings.session_cookie)
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    user_id = read_session_token(token)
    if not user_id:
        raise HTTPException(status_code=401, detail="Session expired")
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user


def get_auth(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> AuthContext:
    membership = (
        db.query(Membership)
        .filter(Membership.user_id == user.id)
        .order_by(Membership.id.asc())
        .first()
    )
    if not membership:
        raise HTTPException(status_code=403, detail="No organization membership")
    org = db.get(Organization, membership.org_id)
    if not org:
        raise HTTPException(status_code=403, detail="Organization missing")
    return AuthContext(user=user, org=org, membership=membership)


def org_payload(org: Organization, role: str, project_count: int) -> dict:
    return {
        "id": org.id,
        "name": org.name,
        "slug": org.slug,
        "plan": org.plan.value,
        "audits_used_period": org.audits_used_period,
        "audit_limit": audit_limit_for(org.plan),
        "project_count": project_count,
        "project_limit": project_limit_for(org.plan),
        "role": role,
    }

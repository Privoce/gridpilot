from __future__ import annotations

from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from backend.app.auth import read_projects_token, read_session_claims
from backend.app.billing import audit_limit_for, project_limit_for
from backend.app.config import settings
from backend.app.db import get_db
from backend.app.db_models import MemberRole, Membership, Organization, Plan, Project, User

PROJECTS_COOKIE = "gp_projects"


@dataclass
class AuthContext:
    user: User
    org: Organization
    membership: Membership


def _restore_user_from_claims(db: Session, claims: dict) -> User | None:
    """Recreate the account carried by a signed session on this instance.

    On serverless hosts every instance has its own ephemeral SQLite file, so a
    valid session may reference a user this instance has never seen. The token
    claims carry enough identity to rebuild user, org, and membership with the
    same primary keys, keeping sessions valid across instances and cold starts.
    """
    email = claims.get("em")
    if not email:
        return None
    user = db.query(User).filter(User.email == email).first()
    if user:
        return user

    org_id = claims.get("oid")
    org = db.get(Organization, org_id) if org_id else None
    if not org:
        try:
            plan = Plan(claims.get("pl") or "free")
        except ValueError:
            plan = Plan.FREE
        org = Organization(
            id=org_id,
            name=claims.get("on") or "Workspace",
            slug=claims.get("os") or f"org-{claims['uid']}",
            plan=plan,
        )
        db.add(org)
    user = User(
        id=claims["uid"],
        email=email,
        name=claims.get("nm") or email,
        # No password hash survives the trip; sign-in still works via the session.
        password_hash="!restored-session",
    )
    db.add(user)
    db.flush()
    try:
        role = MemberRole(claims.get("rl") or "owner")
    except ValueError:
        role = MemberRole.OWNER
    db.add(Membership(user_id=user.id, org_id=org.id, role=role))
    db.commit()
    return user


def get_current_user(
    request: Request,
    db: Session = Depends(get_db),
) -> User:
    token = request.cookies.get(settings.session_cookie)
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    claims = read_session_claims(token)
    if not claims:
        raise HTTPException(status_code=401, detail="Session expired")
    user = db.get(User, str(claims["uid"]))
    if not user:
        user = _restore_user_from_claims(db, claims)
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user


def _restore_projects_from_cookie(request: Request, db: Session, org_id: str) -> None:
    """Recreate project rows this instance has never seen.

    Pairs with the gp_projects cookie set on project create/update: serverless
    instances keep separate SQLite files, so a project created on one instance
    must be restorable on any other.
    """
    token = request.cookies.get(PROJECTS_COOKIE)
    if not token:
        return
    data = read_projects_token(token)
    if not data or data.get("org") != org_id:
        return
    restored = False
    for entry in data.get("projects") or []:
        pid = entry.get("id")
        if not pid or db.get(Project, pid):
            continue
        db.add(
            Project(
                id=pid,
                org_id=org_id,
                name=entry.get("n") or "Project",
                iso=entry.get("i") or "CAISO",
                capacity_mw=entry.get("c"),
                state=entry.get("s"),
                poi_substation=entry.get("poi"),
            )
        )
        restored = True
    if restored:
        db.commit()


def get_auth(
    request: Request,
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
    _restore_projects_from_cookie(request, db, org.id)
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

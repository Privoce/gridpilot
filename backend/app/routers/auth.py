from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from backend.app.auth import (
    create_session_token,
    hash_password,
    slugify,
    verify_password,
)
from backend.app.billing import maybe_roll_period
from backend.app.config import settings
from backend.app.db import get_db
from backend.app.db_models import MemberRole, Membership, Organization, Plan, Project, User
from backend.app.deps import AuthContext, get_auth, org_payload
from backend.app.schemas import LoginRequest, MeResponse, SignupRequest
from backend.app.seed import DEMO_EMAIL

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _me_payload(user: User, org: Organization, role: str, project_count: int) -> dict:
    return {
        "user": {"id": user.id, "email": user.email, "name": user.name},
        "org": org_payload(org, role, project_count),
        "is_demo": user.email == DEMO_EMAIL,
    }


def _set_session(response: Response, user: User, org: Organization, role: str) -> None:
    token = create_session_token(
        user.id,
        email=user.email,
        name=user.name,
        org_id=org.id,
        org_name=org.name,
        org_slug=org.slug,
        plan=org.plan.value,
        role=role,
    )
    response.set_cookie(
        key=settings.session_cookie,
        value=token,
        httponly=True,
        samesite="lax",
        secure=settings.use_secure_cookies,
        max_age=settings.session_max_age,
        path="/",
    )


@router.post("/signup", response_model=MeResponse)
def signup(payload: SignupRequest, response: Response, db: Session = Depends(get_db)):
    email = payload.email.lower().strip()
    if db.query(User).filter(User.email == email).first():
        raise HTTPException(status_code=409, detail="Email already registered")

    base_slug = slugify(payload.org_name)
    slug = base_slug
    i = 2
    while db.query(Organization).filter(Organization.slug == slug).first():
        slug = f"{base_slug}-{i}"
        i += 1

    user = User(email=email, name=payload.name.strip(), password_hash=hash_password(payload.password))
    org = Organization(name=payload.org_name.strip(), slug=slug, plan=Plan.FREE)
    db.add(user)
    db.add(org)
    db.flush()
    db.add(Membership(user_id=user.id, org_id=org.id, role=MemberRole.OWNER))
    db.commit()
    db.refresh(user)
    db.refresh(org)

    _set_session(response, user, org, MemberRole.OWNER.value)
    return _me_payload(user, org, MemberRole.OWNER.value, 0)


@router.post("/login", response_model=MeResponse)
def login(payload: LoginRequest, response: Response, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == payload.email.lower().strip()).first()
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    membership = db.query(Membership).filter(Membership.user_id == user.id).first()
    if not membership:
        raise HTTPException(status_code=403, detail="No organization")
    org = db.get(Organization, membership.org_id)
    assert org
    maybe_roll_period(org)
    db.commit()

    project_count = (
        db.query(Project).filter(Project.org_id == org.id, Project.status == "active").count()
    )
    _set_session(response, user, org, membership.role.value)
    return _me_payload(user, org, membership.role.value, project_count)


@router.post("/logout")
def logout(response: Response):
    response.delete_cookie(
        settings.session_cookie,
        path="/",
        secure=settings.use_secure_cookies,
        httponly=True,
        samesite="lax",
    )
    return {"ok": True}


@router.get("/me", response_model=MeResponse)
def me(auth: AuthContext = Depends(get_auth), db: Session = Depends(get_db)):
    maybe_roll_period(auth.org)
    db.commit()
    project_count = (
        db.query(Project)
        .filter(Project.org_id == auth.org.id, Project.status == "active")
        .count()
    )
    return _me_payload(auth.user, auth.org, auth.membership.role.value, project_count)

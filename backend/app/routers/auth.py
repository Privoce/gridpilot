from __future__ import annotations

import secrets
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from backend.app.auth import (
    create_account_token,
    create_oauth_state,
    create_session_token,
    hash_password,
    read_account_token,
    read_oauth_state,
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

ACCOUNT_COOKIE = "gp_account"


def _set_account_cookie(response: Response, user: User, org: Organization, role: str) -> None:
    """Signed account snapshot that outlives logout — lets password sign-in work
    even when the serverless instance holding the account was recycled."""
    response.set_cookie(
        key=ACCOUNT_COOKIE,
        value=create_account_token({
            "uid": user.id, "em": user.email, "nm": user.name,
            "ph": user.password_hash,
            "oid": org.id, "on": org.name, "os": org.slug,
            "pl": org.plan.value, "rl": role,
        }),
        httponly=True,
        samesite="lax",
        secure=settings.use_secure_cookies,
        max_age=60 * 60 * 24 * 30,
        path="/",
    )


def _restore_account_from_cookie(request: Request, db: Session, email: str) -> User | None:
    """Recreate a locally-unknown account from the gp_account cookie."""
    token = request.cookies.get(ACCOUNT_COOKIE)
    if not token:
        return None
    data = read_account_token(token)
    if not data or data.get("em") != email or not data.get("ph"):
        return None
    org = db.get(Organization, data.get("oid")) if data.get("oid") else None
    if not org:
        try:
            plan = Plan(data.get("pl") or "free")
        except ValueError:
            plan = Plan.FREE
        org = Organization(
            id=data.get("oid"),
            name=data.get("on") or "Workspace",
            slug=data.get("os") or f"org-{data['uid']}",
            plan=plan,
        )
        db.add(org)
    user = User(
        id=data["uid"],
        email=email,
        name=data.get("nm") or email,
        password_hash=data["ph"],
    )
    db.add(user)
    db.flush()
    try:
        role = MemberRole(data.get("rl") or "owner")
    except ValueError:
        role = MemberRole.OWNER
    db.add(Membership(user_id=user.id, org_id=org.id, role=role))
    db.commit()
    return user


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
def signup(
    payload: SignupRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    email = payload.email.lower().strip()
    if db.query(User).filter(User.email == email).first():
        raise HTTPException(status_code=409, detail="Email already registered")
    # This instance's DB may not have the account, but the browser's signed
    # account cookie proves it exists (serverless instances don't share SQLite).
    cookie_token = request.cookies.get(ACCOUNT_COOKIE)
    if cookie_token:
        known = read_account_token(cookie_token)
        if known and known.get("em") == email:
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
    _set_account_cookie(response, user, org, MemberRole.OWNER.value)
    return _me_payload(user, org, MemberRole.OWNER.value, 0)


@router.post("/login", response_model=MeResponse)
def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    email = payload.email.lower().strip()
    user = db.query(User).filter(User.email == email).first()
    if not user:
        # This instance may never have seen the account — restore it from the
        # signed account cookie set at signup/login (serverless instances don't
        # share their SQLite files).
        user = _restore_account_from_cookie(request, db, email)
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
    _set_account_cookie(response, user, org, membership.role.value)
    return _me_payload(user, org, membership.role.value, project_count)


GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"


def _external_base(request: Request) -> str:
    """Public origin of this request — Vercel terminates TLS at the proxy."""
    proto = request.headers.get("x-forwarded-proto") or request.url.scheme
    host = request.headers.get("x-forwarded-host") or request.headers.get("host") or request.url.netloc
    return f"{proto}://{host}"


def _google_configured() -> bool:
    return bool(settings.google_client_id and settings.google_client_secret)


@router.get("/config")
def auth_config():
    """Which optional sign-in methods are available (drives the UI)."""
    return {"google": _google_configured()}


@router.get("/google/start")
def google_start(request: Request):
    if not _google_configured():
        raise HTTPException(status_code=404, detail="Google sign-in is not configured")
    base = _external_base(request)
    state = create_oauth_state({"n": secrets.token_urlsafe(16), "b": base})
    params = {
        "client_id": settings.google_client_id,
        "redirect_uri": f"{base}/api/auth/google/callback",
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "prompt": "select_account",
    }
    return RedirectResponse(f"{GOOGLE_AUTH_URL}?{urlencode(params)}", status_code=302)


@router.get("/google/callback")
def google_callback(request: Request, db: Session = Depends(get_db)):
    if not _google_configured():
        raise HTTPException(status_code=404, detail="Google sign-in is not configured")

    def fail(reason: str) -> RedirectResponse:
        return RedirectResponse(f"/app?auth_error={reason}#/login", status_code=302)

    state = read_oauth_state(request.query_params.get("state") or "")
    code = request.query_params.get("code")
    if not state or not code:
        return fail("google_state")
    base = state.get("b") or _external_base(request)

    try:
        with httpx.Client(timeout=15) as client:
            token_res = client.post(GOOGLE_TOKEN_URL, data={
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret,
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": f"{base}/api/auth/google/callback",
            })
            token_res.raise_for_status()
            access_token = token_res.json().get("access_token")
            if not access_token:
                return fail("google_token")
            info_res = client.get(GOOGLE_USERINFO_URL,
                                  headers={"Authorization": f"Bearer {access_token}"})
            info_res.raise_for_status()
            info = info_res.json()
    except httpx.HTTPError:
        return fail("google_http")

    email = str(info.get("email") or "").lower().strip()
    if not email or not info.get("email_verified", True):
        return fail("google_email")
    name = str(info.get("name") or email.split("@")[0]).strip()

    user = db.query(User).filter(User.email == email).first()
    if not user:
        # The account may live on another serverless instance — the signed
        # account cookie can restore it here.
        user = _restore_account_from_cookie(request, db, email)
    if not user:
        # First Google sign-in: provision a user + workspace. The random
        # password keeps password login closed until the user sets one.
        base_slug = slugify(f"{name}-workspace")
        slug = base_slug
        i = 2
        while db.query(Organization).filter(Organization.slug == slug).first():
            slug = f"{base_slug}-{i}"
            i += 1
        user = User(email=email, name=name,
                    password_hash=hash_password(secrets.token_urlsafe(32)))
        org = Organization(name=f"{name}'s Workspace", slug=slug, plan=Plan.FREE)
        db.add(user)
        db.add(org)
        db.flush()
        db.add(Membership(user_id=user.id, org_id=org.id, role=MemberRole.OWNER))
        db.commit()
        db.refresh(user)

    membership = db.query(Membership).filter(Membership.user_id == user.id).first()
    if not membership:
        return fail("google_org")
    org = db.get(Organization, membership.org_id)
    assert org
    maybe_roll_period(org)
    db.commit()

    response = RedirectResponse("/app#/dashboard", status_code=302)
    _set_session(response, user, org, membership.role.value)
    _set_account_cookie(response, user, org, membership.role.value)
    return response


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

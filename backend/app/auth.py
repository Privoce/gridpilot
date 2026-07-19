from __future__ import annotations

import re

import bcrypt
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from backend.app.config import settings


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except ValueError:
        return False


def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(settings.secret_key, salt="gridpilot-session")


def create_session_token(
    user_id: str,
    *,
    email: str | None = None,
    name: str | None = None,
    org_id: str | None = None,
    org_name: str | None = None,
    org_slug: str | None = None,
    plan: str | None = None,
    role: str | None = None,
) -> str:
    """Signed session token carrying identity claims.

    The claims let any server instance reconstruct the account when its local
    database doesn't have it — required on serverless hosts where each instance
    keeps its own ephemeral SQLite file.
    """
    payload: dict = {"uid": user_id}
    if email:
        payload.update({
            "em": email, "nm": name or email,
            "oid": org_id, "on": org_name, "os": org_slug,
            "pl": plan, "rl": role,
        })
    return _serializer().dumps(payload)


def read_session_claims(token: str) -> dict | None:
    try:
        data = _serializer().loads(token, max_age=settings.session_max_age)
    except (BadSignature, SignatureExpired):
        return None
    return data if isinstance(data, dict) and data.get("uid") else None


def read_session_token(token: str) -> str | None:
    claims = read_session_claims(token)
    return str(claims["uid"]) if claims else None


def slugify(value: str) -> str:
    value = value.strip().lower()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    value = value.strip("-")
    return value[:60] or "org"

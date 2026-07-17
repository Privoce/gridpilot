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


def create_session_token(user_id: str) -> str:
    return _serializer().dumps({"uid": user_id})


def read_session_token(token: str) -> str | None:
    try:
        data = _serializer().loads(token, max_age=settings.session_max_age)
    except (BadSignature, SignatureExpired):
        return None
    uid = data.get("uid")
    return str(uid) if uid else None


def slugify(value: str) -> str:
    value = value.strip().lower()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    value = value.strip("-")
    return value[:60] or "org"

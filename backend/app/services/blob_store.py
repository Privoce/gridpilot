"""Vercel Blob helpers — durable cross-instance storage for uploads and audits.

Serverless instances only share what we persist externally. Drawings and audit
snapshots go to Vercel Blob so any instance can serve files and reports created
by another. All functions no-op (return None) when the token is absent, so
local development keeps working from the filesystem alone.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

import httpx

logger = logging.getLogger("gridpilot.blob")

BLOB_API = "https://blob.vercel-storage.com"
_HEADERS_VERSION = "7"


def _token() -> str:
    return os.getenv("BLOB_READ_WRITE_TOKEN", "")


def blob_enabled() -> bool:
    return bool(_token())


def blob_put(pathname: str, data: bytes, content_type: str = "application/octet-stream") -> str | None:
    """Upload bytes; returns the public URL or None on failure."""
    if not blob_enabled():
        return None
    try:
        resp = httpx.put(
            f"{BLOB_API}/{pathname}",
            content=data,
            headers={
                "Authorization": f"Bearer {_token()}",
                "x-api-version": _HEADERS_VERSION,
                "Content-Type": content_type,
            },
            timeout=30.0,
        )
        resp.raise_for_status()
        return resp.json().get("url")
    except Exception as exc:  # noqa: BLE001 — durability is best-effort
        logger.warning("blob_put %s failed: %s", pathname, exc)
        return None


def blob_list(prefix: str, limit: int = 50) -> list[dict[str, Any]]:
    """List blobs under a prefix, newest first."""
    if not blob_enabled():
        return []
    try:
        resp = httpx.get(
            BLOB_API,
            params={"prefix": prefix, "limit": str(limit)},
            headers={
                "Authorization": f"Bearer {_token()}",
                "x-api-version": _HEADERS_VERSION,
            },
            timeout=20.0,
        )
        resp.raise_for_status()
        blobs = resp.json().get("blobs") or []
        return sorted(blobs, key=lambda b: b.get("uploadedAt") or "", reverse=True)
    except Exception as exc:  # noqa: BLE001
        logger.warning("blob_list %s failed: %s", prefix, exc)
        return []


def blob_fetch(url: str) -> bytes | None:
    try:
        resp = httpx.get(url, timeout=30.0)
        resp.raise_for_status()
        return resp.content
    except Exception as exc:  # noqa: BLE001
        logger.warning("blob_fetch failed: %s", exc)
        return None


def blob_get_json(prefix: str) -> dict[str, Any] | None:
    """Fetch the newest JSON blob under a prefix (suffix-agnostic)."""
    blobs = blob_list(prefix, limit=3)
    if not blobs:
        return None
    data = blob_fetch(blobs[0]["url"])
    if not data:
        return None
    try:
        return json.loads(data)
    except json.JSONDecodeError:
        return None

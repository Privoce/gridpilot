from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from backend.app.routers import audits, auth, caiso, dashboard, demo, projects
from backend.app.seed import init_db
from backend.app.services.rules_engine import list_isos

STATIC_DIR = Path(__file__).resolve().parent / "static"

app = FastAPI(
    title="GridPilot",
    description="Interconnection readiness platform for utility-scale renewables",
    version="0.2.0",
)

_cors_origins = [
    "http://localhost:8000",
    "http://127.0.0.1:8000",
    "http://localhost:3000",
]
_vercel_url = os.getenv("VERCEL_URL")
if _vercel_url:
    _cors_origins.append(f"https://{_vercel_url}")
_extra = os.getenv("CORS_ORIGINS", "")
if _extra:
    _cors_origins.extend([o.strip() for o in _extra.split(",") if o.strip()])

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(caiso.router)
app.include_router(demo.router)
app.include_router(projects.router)
app.include_router(audits.router)
app.include_router(dashboard.router)


@app.on_event("startup")
def on_startup() -> None:
    init_db()


@app.get("/api/health")
def health():
    from backend.app.config import settings

    return {
        "status": "ok",
        "product": "GridPilot",
        "version": "0.2.0",
        "model": settings.xai_model,
        "api_configured": bool(settings.xai_api_key),
    }


@app.get("/api/isos")
def isos():
    return {"isos": list_isos()}


if STATIC_DIR.exists():
    app.mount("/assets", StaticFiles(directory=STATIC_DIR), name="assets")


@app.get("/", response_class=HTMLResponse)
def landing(request: Request):
    # demo.* serves the guided demo directly.
    host = (request.headers.get("host") or "").split(":")[0]
    if host.startswith("demo."):
        return RedirectResponse(url="/app#/demo", status_code=307)
    path = STATIC_DIR / "landing.html"
    if path.exists():
        return HTMLResponse(path.read_text(encoding="utf-8"))
    return HTMLResponse("<a href='/app'>Open GridPilot</a>")


@app.get("/app")
@app.get("/app/{path:path}")
def spa(path: str = ""):
    app_path = STATIC_DIR / "app.html"
    if not app_path.exists():
        return HTMLResponse("<h1>App missing</h1>", status_code=500)
    return HTMLResponse(app_path.read_text(encoding="utf-8"))


@app.get("/favicon.ico")
def favicon():
    # Tiny empty response avoids 404 noise
    return HTMLResponse(status_code=204)

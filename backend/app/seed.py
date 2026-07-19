from __future__ import annotations

import logging
import shutil
from pathlib import Path

from sqlalchemy.orm import Session

from backend.app.auth import hash_password, slugify
from backend.app.billing import maybe_roll_period
from backend.app.config import ROOT, settings
from backend.app.db import Base, SessionLocal, engine
from backend.app.db_models import (
    Drawing,
    MemberRole,
    Membership,
    Organization,
    Plan,
    Project,
    User,
)

logger = logging.getLogger("gridpilot.seed")

DEMO_EMAIL = "demo@gridpilot.dev"
DEMO_PASSWORD = "gridpilot"
SAMPLE_NAME = "cedar_ridge_sld_demo.pdf"

# Fixed IDs so every serverless instance seeds identical rows — a demo session
# minted on one instance must resolve on any other.
DEMO_USER_ID = "demouser0001"
DEMO_ORG_ID = "demoorg00001"
DEMO_PROJECT_ID = "demoproj0001"
DEMO_DRAWING_ID = "demodraw0001"


def ensure_sample_pdf() -> Path:
    out = ROOT / "samples" / SAMPLE_NAME
    if out.exists():
        return out
    import runpy

    runpy.run_path(str(ROOT / "samples" / "generate_sample_sld.py"), run_name="__main__")
    if not out.exists():
        raise RuntimeError(f"Failed to generate sample SLD at {out}")
    return out


def init_db() -> None:
    Base.metadata.create_all(bind=engine)
    ensure_sample_pdf()
    db = SessionLocal()
    try:
        seed_demo(db)
        db.commit()
    finally:
        db.close()


def seed_demo(db: Session) -> None:
    existing = db.query(User).filter(User.email == DEMO_EMAIL).first()
    if existing:
        # Keep drawing + scenario present even if user already exists
        membership = db.query(Membership).filter(Membership.user_id == existing.id).first()
        if membership:
            project = (
                db.query(Project)
                .filter(
                    Project.org_id == membership.org_id,
                    Project.name == "Cedar Ridge Solar + Storage",
                )
                .first()
            )
            if not project:
                project = Project(
                    org_id=membership.org_id,
                    name="Cedar Ridge Solar + Storage",
                    iso="MISO",
                    capacity_mw=120.0,
                    state="IN",
                    poi_substation="AES Indiana — Cedar Ridge 138 kV",
                )
                db.add(project)
                db.flush()
            else:
                project.iso = "MISO"
                project.state = "IN"
                project.poi_substation = "AES Indiana — Cedar Ridge 138 kV"
                project.capacity_mw = 120.0
            has_drawing = (
                db.query(Drawing)
                .filter(Drawing.project_id == project.id, Drawing.is_latest.is_(True))
                .first()
            )
            if not has_drawing:
                _attach_sample(db, project, existing.id)
        return

    user = User(
        id=DEMO_USER_ID,
        email=DEMO_EMAIL,
        name="Alex Rivera",
        password_hash=hash_password(DEMO_PASSWORD),
    )
    org = Organization(
        id=DEMO_ORG_ID,
        name="Northwind Renewables",
        slug=slugify("Northwind Renewables"),
        plan=Plan.PRO,
    )
    db.add(user)
    db.add(org)
    db.flush()
    db.add(
        Membership(
            user_id=user.id,
            org_id=org.id,
            role=MemberRole.OWNER,
        )
    )

    project = Project(
        id=DEMO_PROJECT_ID,
        org_id=org.id,
        name="Cedar Ridge Solar + Storage",
        iso="MISO",
        capacity_mw=120.0,
        state="IN",
        poi_substation="AES Indiana — Cedar Ridge 138 kV",
    )
    db.add(project)
    db.flush()
    _attach_sample(db, project, user.id)

    maybe_roll_period(org)
    logger.info("Seeded demo account %s / %s", DEMO_EMAIL, DEMO_PASSWORD)


def _attach_sample(db: Session, project: Project, user_id: str) -> None:
    sample = ensure_sample_pdf()
    dest_dir = settings.upload_dir / project.org_id / project.id
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"seed_{sample.name}"
    shutil.copy2(sample, dest)
    db.add(
        Drawing(
            id=DEMO_DRAWING_ID,
            project_id=project.id,
            filename=sample.name,
            stored_path=str(dest),
            version_label="Rev A — AES Indiana demo SLD",
            page_count=1,
            uploaded_by=user_id,
            is_latest=True,
        )
    )

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from backend.app.db import SessionLocal
from backend.app.db_models import (
    AuditRun,
    AuditStatus,
    FindingRow,
    FindingSeverity,
    FindingTriage,
)
from backend.app.models import ISORegion
from backend.app.services.audit import run_audit

logger = logging.getLogger("gridpilot.jobs")

_running: set[str] = set()


def _recompute_open_counts(db, audit: AuditRun) -> None:  # noqa: ANN001
    findings = (
        db.query(FindingRow).filter(FindingRow.audit_id == audit.id).all()
        if audit.id
        else list(audit.findings)
    )
    blocking = 0
    warning = 0
    for f in findings:
        # Only resolved/dismissed clear the open counts; acknowledged still blocks.
        if f.triage in {FindingTriage.RESOLVED, FindingTriage.DISMISSED}:
            continue
        sev = f.severity.value if hasattr(f.severity, "value") else str(f.severity)
        if sev == FindingSeverity.BLOCKING.value:
            blocking += 1
        elif sev == FindingSeverity.WARNING.value:
            warning += 1
    audit.blocking_open = blocking
    audit.warning_open = warning


async def execute_audit_run(audit_id: str) -> None:
    if audit_id in _running:
        return
    _running.add(audit_id)
    db = SessionLocal()
    try:
        audit = db.get(AuditRun, audit_id)
        if not audit:
            return

        from backend.app.db_models import User
        from backend.app.seed import DEMO_EMAIL

        drawing_path = Path(audit.drawing.stored_path)
        project_name = audit.project.name if audit.project else ""
        iso = audit.iso
        creator = db.get(User, audit.created_by) if audit.created_by else None
        # Guided demo must always surface the intentional AES Indiana blockers.
        force_demo = bool(
            (creator and creator.email == DEMO_EMAIL)
            or project_name == "Cedar Ridge Solar + Storage"
        )

        audit.status = AuditStatus.RUNNING
        audit.started_at = datetime.now(timezone.utc)
        audit.error = None
        db.commit()

        report, _, _ = await run_audit(
            file_path=drawing_path,
            iso=ISORegion(iso),
            project_name=project_name,
            force_demo=force_demo,
        )

        audit = db.get(AuditRun, audit_id)
        assert audit
        for old in list(audit.findings):
            db.delete(old)
        db.flush()

        for f in report.findings:
            db.add(
                FindingRow(
                    audit_id=audit.id,
                    external_key=f.id,
                    severity=FindingSeverity(f.severity.value),
                    title=f.title,
                    detail=f.detail,
                    rule_id=f.rule_id,
                    location=f.location,
                    recommendation=f.recommendation,
                    evidence=f.evidence,
                    triage=FindingTriage.OPEN
                    if f.severity.value != "ready"
                    else FindingTriage.RESOLVED,
                )
            )
        db.flush()
        audit = db.get(AuditRun, audit_id)
        assert audit
        audit.status = AuditStatus.COMPLETED
        audit.readiness_score = report.readiness_score
        audit.readiness_status = report.status
        audit.summary = report.summary
        audit.model = report.model
        audit.mode = report.mode
        audit.pages_analyzed = report.pages_analyzed
        audit.extract_json = json.dumps(report.extract.model_dump())
        audit.rules_checked_json = json.dumps(report.rules_checked)
        audit.completed_at = datetime.now(timezone.utc)
        _recompute_open_counts(db, audit)
        db.commit()
        logger.info("Audit %s completed score=%s", audit_id, report.readiness_score)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Audit %s failed", audit_id)
        db.rollback()
        audit = db.get(AuditRun, audit_id)
        if audit:
            audit.status = AuditStatus.FAILED
            audit.error = str(exc)[:2000]
            audit.completed_at = datetime.now(timezone.utc)
            db.commit()
    finally:
        db.close()
        _running.discard(audit_id)


def _run_inline(audit_id: str) -> None:
    """Run the audit to completion in this request (needed on serverless)."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        asyncio.run(execute_audit_run(audit_id))
        return
    # Sync handlers usually have no loop; if one exists, finish in a worker thread.
    import concurrent.futures

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        pool.submit(asyncio.run, execute_audit_run(audit_id)).result()


def enqueue_audit(audit_id: str, *, wait: bool | None = None) -> None:
    from backend.app.config import settings

    # On Vercel the function freezes after the response — always finish inline.
    if wait is None:
        wait = settings.is_vercel
    if wait:
        _run_inline(audit_id)
        return
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(execute_audit_run(audit_id))
    except RuntimeError:
        asyncio.run(execute_audit_run(audit_id))

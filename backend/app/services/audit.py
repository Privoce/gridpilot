from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path

from backend.app.config import settings
from backend.app.models import (
    AuditExtract,
    AuditReport,
    EquipmentItem,
    Finding,
    ISORegion,
    Severity,
)
from backend.app.services.grok_client import GrokError, analyze_sld
from backend.app.services.pdf_extract import render_pdf
from backend.app.services.report import write_report_artifacts
from backend.app.services.rules_engine import (
    deterministic_findings,
    load_iso_pack,
    score_report,
)


def _merge_findings(ai: list[Finding], det: list[Finding]) -> list[Finding]:
    merged: list[Finding] = []
    seen: set[tuple[str, str]] = set()

    def key(f: Finding) -> tuple[str, str]:
        return ((f.rule_id or f.id).lower(), f.severity.value)

    # Prefer AI blocking/warning detail when present; keep deterministic gaps
    for f in ai + det:
        k = key(f)
        if k in seen:
            continue
        # Skip duplicate READY noise if we already have a non-ready for same rule
        if f.severity == Severity.READY:
            rule = (f.rule_id or "").lower()
            if any(
                (x.rule_id or "").lower() == rule and x.severity != Severity.READY
                for x in merged
            ):
                continue
        seen.add(k)
        merged.append(f)

    order = {Severity.BLOCKING: 0, Severity.WARNING: 1, Severity.READY: 2}
    merged.sort(key=lambda f: (order[f.severity], f.title))
    return merged


def _demo_extract(iso: ISORegion) -> tuple[AuditExtract, list[Finding], str]:
    """AES Indiana interconnection SLD demo findings (MISO TO path)."""
    extract = AuditExtract(
        project_name="Cedar Ridge Solar + Storage",
        capacity_mw=120.0,
        interconnection_voltage_kv=138.0,
        inverter_models=["Sungrow SG3600UD", "Sungrow SG3600UD"],
        transformers=["GSU 150 MVA 34.5/138 kV", "Collector pad 4.0 MVA"],
        equipment=[
            EquipmentItem(type="Inverter", label="INV Bank A", rating="57.6 MW", notes="No P-Q curve"),
            EquipmentItem(type="Inverter", label="INV Bank B", rating="57.6 MW", notes="No PFR / droop note"),
            EquipmentItem(type="Transformer", label="GSU-1", rating="150 MVA", notes="%Z present in demo"),
            EquipmentItem(type="Relay", label="POI protection", rating=None, notes="ANSI numbers missing"),
            EquipmentItem(type="Meter", label="Revenue meter", rating=None, notes="CT/PT ratios blank"),
            EquipmentItem(type="Breaker", label="52-POI", rating="40 kA"),
        ],
        observed_notes=[
            "AES Indiana / MISO 138 kV POI labeled",
            "Relay package drawn without ANSI 27/59/81/67 callouts",
            "CT/PT ratios blank at revenue meter",
            "IBR P-Q / capability curves omitted",
            "Title-block revision date incomplete",
        ],
        raw_summary=(
            "120 MW solar + storage SLD for AES Indiana (MISO) interconnection. "
            "POI and ownership demarcation are present; protection ANSI numbers, "
            "metering ratios, and IBR capability curves are intentionally incomplete."
        ),
    )
    findings = [
        Finding(
            id="DEMO-R-PROTECT-01",
            severity=Severity.BLOCKING,
            title="Protective relays missing ANSI function numbers",
            detail=(
                "POI protection is shown but relays are not labeled with ANSI device numbers "
                "(27/59/81/67, etc.) required by AES Indiana Facilities Connection Requirements."
            ),
            rule_id="R-PROTECT-01",
            location="POI protection package",
            recommendation="Annotate each relay with ANSI function numbers before AES Indiana review.",
            evidence="Demo SLD shows protection block without ANSI labels.",
        ),
        Finding(
            id="DEMO-R-METER-01",
            severity=Severity.BLOCKING,
            title="CT/PT ratios not annotated at POI metering",
            detail="Revenue meter is drawn at the AES Indiana POI but CT and PT ratios are blank.",
            rule_id="R-METER-01",
            location="Revenue meter / POI",
            recommendation="Add CT and PT ratios matching the metering design package.",
            evidence="Meter symbol present; ratio fields marked MISSING.",
        ),
        Finding(
            id="DEMO-R-IBR-01",
            severity=Severity.BLOCKING,
            title="IBR P-Q / capability curves not shown",
            detail=(
                "Inverter banks list MWAC totals but omit P-Q / reactive capability curves. "
                "AES Indiana requires primary frequency response (FERC 842) and closed-loop "
                "voltage control per NERC VAR-002 (±2% at POI)."
            ),
            rule_id="R-IBR-01",
            location="Inverter schedule",
            recommendation="Attach P-Q capability and PFR/droop notes from the inverter datasheet.",
            evidence="Demo SLD notes intentionally omit IBR capability curves.",
        ),
        Finding(
            id="DEMO-R-TITLE-01",
            severity=Severity.WARNING,
            title="As-built revision / date block incomplete",
            detail=(
                "AES Indiana requires three as-built one-lines with revision number and date "
                "before Facility energization; the demo title block leaves the date blank."
            ),
            rule_id="R-TITLE-01",
            location="Title block",
            recommendation="Complete revision letter, date, and as-built stamp before filing.",
            evidence="Rev A shown; date field blank.",
        ),
        Finding(
            id="DEMO-R-METER-02",
            severity=Severity.WARNING,
            title="Bidirectional / AES Indiana meter labeling incomplete",
            detail="POI meter should explicitly call out bidirectional revenue metering for AES Indiana.",
            rule_id="R-METER-02",
            location="Revenue meter",
            recommendation="Label bidirectional metering and AES Indiana interconnection meter ID.",
            evidence="Generic 'Revenue Meter' text only.",
        ),
        Finding(
            id="DEMO-R-POI-01",
            severity=Severity.READY,
            title="POI voltage and ownership boundary labeled",
            detail="AES Indiana 138 kV POI and ownership demarcation at 52-POI are clearly marked.",
            rule_id="R-POI-01",
            evidence="POI bus + ownership note present on demo SLD.",
        ),
    ]
    summary = (
        f"AES Indiana / {iso.value} demo audit: 3 blocking issues and 2 warnings. "
        "Clear R-PROTECT-01, R-METER-01, and R-IBR-01 before PowerClerk / MISO DPP submission."
    )
    return extract, findings, summary


async def run_audit(
    *,
    file_path: Path,
    iso: ISORegion,
    project_name: str = "",
    force_demo: bool = False,
) -> tuple[AuditReport, Path, Path]:
    pack = load_iso_pack(iso)
    pdf = render_pdf(file_path, max_pages=settings.max_pages)

    mode = "live"
    if force_demo:
        extract, ai_findings, summary = _demo_extract(iso)
        mode = "demo"
    else:
        try:
            extract, ai_findings, summary = await analyze_sld(
                iso=iso.value,
                rules_pack=pack,
                pages=pdf.pages,
                ocr_text=pdf.text,
                project_hint=project_name or file_path.stem,
            )
        except GrokError:
            # Fall back so the product still demos if API is unavailable
            extract, ai_findings, summary = _demo_extract(iso)
            mode = "demo"
            summary = (
                "[Demo fallback — live Vision audit unavailable] " + summary
            )

    det = deterministic_findings(iso, extract, pdf.text)
    findings = _merge_findings(ai_findings, det)
    score, status = score_report(findings)

    report = AuditReport(
        report_id=str(uuid.uuid4())[:8],
        project_name=project_name or extract.project_name or file_path.stem,
        iso=iso,
        filename=file_path.name,
        created_at=datetime.now(timezone.utc).isoformat(),
        readiness_score=score,
        status=status,  # type: ignore[arg-type]
        summary=summary,
        findings=findings,
        extract=extract,
        rules_checked=[r["id"] for r in pack.get("rules", [])],
        pages_analyzed=len(pdf.pages),
        model=settings.xai_model if mode == "live" else "demo-rules-engine",
        mode=mode,  # type: ignore[arg-type]
    )

    html_path, json_path = write_report_artifacts(report)
    return report, html_path, json_path

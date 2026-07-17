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
    extract = AuditExtract(
        project_name="Cedar Ridge Solar + Storage",
        capacity_mw=120.0,
        interconnection_voltage_kv=138.0,
        inverter_models=["Sungrow SG3600UD", "Sungrow SG3600UD"],
        transformers=["GSU 150 MVA 34.5/138 kV", "Collector pad 4.0 MVA"],
        equipment=[
            EquipmentItem(type="Inverter", label="INV-A", rating="3.6 MW", notes="No LVRT callout"),
            EquipmentItem(type="Inverter", label="INV-B bank", rating="116.4 MW aggregate"),
            EquipmentItem(type="Transformer", label="GSU-1", rating="150 MVA", notes="%Z missing"),
            EquipmentItem(type="Breaker", label="52-POI", rating="missing kA"),
            EquipmentItem(type="Meter", label="Revenue meter", rating=None, notes="Shown at POI"),
        ],
        observed_notes=[
            "POI labeled at 138 kV bus",
            "No SCADA/RTU block",
            "IEEE 1547 not cited",
            "Grounding transformer not shown",
        ],
        raw_summary=(
            "120 MW solar SLD interconnecting at 138 kV. GSU MVA present but impedance and "
            "inverter ride-through annotations are incomplete; telemetry path absent."
        ),
    )
    findings = [
        Finding(
            id="DEMO-LVRT",
            severity=Severity.BLOCKING,
            title="Inverter LVRT / ride-through not documented",
            detail=(
                f"Inverter schedule lists SG3600UD units but does not show LVRT/HVRT setpoints "
                f"required for {iso.value} IBR ride-through review."
            ),
            rule_id=f"{iso.value}-INV",
            location="Inverter schedule / INV-A notes",
            recommendation="Add LVRT/HVRT capability table from the datasheet before filing.",
            evidence="Demo SLD intentionally omits ride-through annotations.",
        ),
        Finding(
            id="DEMO-KA",
            severity=Severity.BLOCKING,
            title="POI breaker interrupting rating missing",
            detail="Breaker 52-POI is drawn but interrupting capability (kA) is blank.",
            rule_id=f"{iso.value}-PROT",
            location="POI breaker 52-POI",
            recommendation="Annotate interrupting rating consistent with short-circuit study.",
            evidence="Breaker symbol present without kA text.",
        ),
        Finding(
            id="DEMO-Z",
            severity=Severity.WARNING,
            title="Transformer impedance (%Z) not annotated",
            detail="GSU-1 shows 150 MVA 34.5/138 kV but %Z / X/R are missing for model quality.",
            rule_id=f"{iso.value}-XFMR",
            location="GSU-1",
            recommendation="Add %Z and X/R from transformer datasheet.",
            evidence="MVA and voltage ratio present; impedance absent.",
        ),
        Finding(
            id="DEMO-SCADA",
            severity=Severity.WARNING,
            title="Telemetry / SCADA path not shown",
            detail=f"{iso.value} reviewers expect an RTU/SCADA/ICCP note for new generation.",
            rule_id=f"{iso.value}-COMM",
            recommendation="Add telemetry block referencing ISO communication requirements.",
            evidence="No SCADA/RTU keywords on drawing.",
        ),
        Finding(
            id="DEMO-POI-OK",
            severity=Severity.READY,
            title="POI and revenue metering labeled",
            detail="Point of Interconnection and revenue meter are clearly marked at the 138 kV bus.",
            rule_id=f"{iso.value}-SLD",
            evidence="POI + meter annotations present on demo SLD.",
        ),
    ]
    summary = (
        f"Demo audit against {iso.value}: 2 blocking issues and 2 warnings. "
        "Fix LVRT documentation and POI breaker kA before submission to avoid requeue risk."
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

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from backend.app.config import settings
from backend.app.models import AuditExtract, Finding, ISORegion, Severity


def load_iso_pack(iso: ISORegion) -> dict[str, Any]:
    path = settings.rules_dir / f"{iso.value.lower()}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"No rules pack for {iso.value}")
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def list_isos() -> list[dict[str, Any]]:
    items = []
    for iso in ISORegion:
        pack = load_iso_pack(iso)
        items.append(
            {
                "id": iso.value,
                "name": pack.get("name", iso.value),
                "description": pack.get("description", ""),
                "rule_count": len(pack.get("rules", [])),
            }
        )
    return items


def _text_blob(extract: AuditExtract, ocr_text: str) -> str:
    parts = [
        extract.raw_summary or "",
        ocr_text or "",
        " ".join(extract.observed_notes or []),
        " ".join(extract.inverter_models or []),
        " ".join(extract.transformers or []),
    ]
    for eq in extract.equipment or []:
        parts.append(f"{eq.type} {eq.label or ''} {eq.rating or ''} {eq.notes or ''}")
    return " ".join(parts).lower()


def _has_any(blob: str, keywords: list[str]) -> bool:
    return any(k.lower() in blob for k in keywords)


def deterministic_findings(
    iso: ISORegion, extract: AuditExtract, ocr_text: str
) -> list[Finding]:
    """Python rule engine that cross-checks Vision extract + OCR against ISO pack."""
    pack = load_iso_pack(iso)
    blob = _text_blob(extract, ocr_text)
    findings: list[Finding] = []

    check_map = {
        "poi_and_metering": (
            ["poi", "point of interconnection", "ownership"],
            "POI / metering / ownership boundary not clearly identified on the SLD.",
            "Add POI, revenue metering, and ownership demarcation labels.",
        ),
        "ansi_relay_labels": (
            ["27/", "59/", "81/", "67/", "ansi 27", "ansi 59", "function 27", "device no"],
            "Protective relays are not labeled with ANSI function numbers (27/59/81/67, etc.).",
            "Annotate each relay with ANSI device numbers for utility review.",
        ),
        "ct_pt_ratios": (
            ["ct:", "pt:", "ct/", "pt/", "ct ratio", "pt ratio"],
            "CT/PT ratios are not annotated at POI revenue metering.",
            "Add CT and PT ratios matching the metering design package.",
        ),
        "ibr_capability": (
            ["p-q", "p/q", "capability curve", "reactive capability", "pfr", "droop curve"],
            "IBR P-Q / reactive capability and frequency response are not documented.",
            "Add P-Q capability, PFR/droop, and closed-loop voltage control notes.",
        ),
        "title_revision_date": (
            ["as-built"],
            "As-built revision / date block is incomplete.",
            "Complete revision letter, date, and as-built stamp before filing.",
        ),
        "bidirectional_meter": (
            ["bidirectional", "bi-directional", "bi directional"],
            "Bidirectional AES Indiana revenue metering is not explicitly labeled.",
            "Call out bidirectional metering and utility meter identification.",
        ),
        "lvrt_capability": (
            ["lvrt", "ride-through", "ride through", "hvrt", "voltage ride"],
            "Inverter LVRT / ride-through capability is not documented on the drawing.",
            "Add LVRT/HVRT capability and setpoints from the inverter datasheet.",
        ),
        "transformer_mva": (
            ["mva", "gsu", "%z"],
            "GSU / station transformer MVA (and preferably %Z) is missing or incomplete.",
            "Annotate transformer MVA, voltage ratio, and impedance.",
        ),
        "protection_devices": (
            ["breaker", "circuit breaker", "recloser", "interrupting", "ka"],
            "Interconnecting protective / interrupting device is not clearly shown.",
            "Show POI breaker/switchgear with interrupting rating (kA).",
        ),
        "grounding": (
            ["grounding transformer", "effectively grounded"],
            "Grounding scheme / grounding transformer is not indicated.",
            "Add grounding transformer or effective grounding note.",
        ),
        "capacity_consistency": (
            ["mwac", "inverter"],
            "Project capacity vs equipment schedule may be inconsistent or incomplete.",
            "Reconcile title-block MW with inverter/transformer totals.",
        ),
        "telemetry": (
            ["scada", "rtu", "telemetry", "iccp", "agc"],
            "Telemetry / SCADA interface is not noted.",
            "Add SCADA/RTU/telemetry path note required by the ISO.",
        ),
        "reactive_power": (
            ["power factor", "reactive capability", "statcom", "capacitor bank"],
            "Reactive capability / power factor operating range is not noted.",
            "Add PF/Q capability note or reactive support equipment.",
        ),
        "site_reference": (
            ["substation", "county", "project", "revision"],
            "Title block site / POI substation reference looks incomplete.",
            "Complete project name, site, POI substation, and revision.",
        ),
        "ieee1547_reference": (
            ["ieee 1547", "ieee1547"],
            "IEEE 1547 / ride-through standard reference not found in notes.",
            "Cite IEEE 1547 in general notes.",
        ),
    }

    for rule in pack.get("rules", []):
        check = rule.get("check")
        if check not in check_map:
            continue
        keywords, fail_detail, fail_rec = check_map[check]
        present = _has_any(blob, keywords)
        severity = Severity(rule.get("severity", "warning"))

        # Demo SLD leaves the date blank — treat as fail for title_revision_date.
        if check == "title_revision_date" and (
            "date: ____" in blob or "date:____" in blob or "date ____" in blob
        ):
            present = False
        # Demo SLD literally marks CT/PT / ANSI as missing.
        if check == "ct_pt_ratios" and ("ct: ____" in blob or "(missing)" in blob):
            present = False
        if check == "ansi_relay_labels" and ("ansi # missing" in blob or "ansi numbers missing" in blob):
            present = False

        if severity == Severity.READY:
            if present:
                findings.append(
                    Finding(
                        id=f"DET-{rule['id']}",
                        severity=Severity.READY,
                        title=rule["title"],
                        detail=rule.get("description", "Requirement appears satisfied."),
                        rule_id=rule["id"],
                        recommendation=rule.get("recommendation"),
                        evidence="Keyword/annotation match in drawing text or model extract.",
                    )
                )
            continue

        if not present:
            findings.append(
                Finding(
                    id=f"DET-{rule['id']}",
                    severity=severity,
                    title=rule["title"],
                    detail=fail_detail,
                    rule_id=rule["id"],
                    recommendation=fail_rec or rule.get("recommendation"),
                    evidence="No matching annotation found in OCR text or Vision extract.",
                )
            )
        else:
            findings.append(
                Finding(
                    id=f"DET-{rule['id']}-OK",
                    severity=Severity.READY,
                    title=f"{rule['title']} — annotated",
                    detail=f"Evidence found for rule {rule['id']}.",
                    rule_id=rule["id"],
                    evidence="Matched keywords/annotations in drawing content.",
                )
            )

    # Capacity heuristic: if both MW and inverter ratings present but wildly off, warn
    if extract.capacity_mw and extract.equipment:
        inv_mw = 0.0
        for eq in extract.equipment:
            if "inverter" in (eq.type or "").lower() and eq.rating:
                digits = "".join(ch if ch.isdigit() or ch == "." else " " for ch in eq.rating)
                for token in digits.split():
                    try:
                        inv_mw += float(token)
                        break
                    except ValueError:
                        continue
        if inv_mw > 0 and abs(inv_mw - extract.capacity_mw) / max(extract.capacity_mw, 1) > 0.15:
            findings.append(
                Finding(
                    id="DET-CAP-MISMATCH",
                    severity=Severity.WARNING,
                    title="Capacity mismatch between title block and inverter schedule",
                    detail=(
                        f"Title-block capacity ~{extract.capacity_mw} MW vs inferred inverter "
                        f"total ~{inv_mw:.1f} MW (>15% delta)."
                    ),
                    rule_id=f"{iso.value}-CAP",
                    recommendation="Reconcile inverter count/ratings with interconnection MW before filing.",
                    evidence="Numeric comparison of extract.capacity_mw vs inverter ratings.",
                )
            )

    return findings


def score_report(findings: list[Finding]) -> tuple[int, str]:
    blocking = sum(1 for f in findings if f.severity == Severity.BLOCKING)
    warnings = sum(1 for f in findings if f.severity == Severity.WARNING)
    ready = sum(1 for f in findings if f.severity == Severity.READY)

    score = 100 - blocking * 18 - warnings * 6
    score = max(0, min(100, score + min(ready, 4)))

    if blocking > 0:
        status = "not_ready"
    elif warnings > 0:
        status = "needs_review"
    else:
        status = "ready"
    return score, status

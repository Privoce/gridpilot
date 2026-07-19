"""CAISO Interconnection Request packet generation.

GridPilot's core demo: take the developer's Phase-1 intake and generate the
consulting-firm workstream — Appendix 1, Attachment A data, models, drawings,
plots, and legal drafts — as a downloadable submission packet.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import shutil
import zipfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import fitz

from backend.app.config import DATA_ROOT

PACKETS_DIR = DATA_ROOT / "packets"

RIMS5_URL = "https://rimspub.caiso.com/rims5/logon.do"
CAISO_FORMS_URL = "https://www.caiso.com/library/interconnection-request-technical-data-forms"

# ---------------------------------------------------------------------------
# Intake schema (drives the wizard form) + Ravenwood example defaults
# ---------------------------------------------------------------------------

INTAKE_SECTIONS: list[dict[str, Any]] = [
    {
        "id": "legal",
        "title": "1 · Legal & Corporate",
        "hint": "Legal name must match the Secretary of State certificate exactly — punctuation included.",
        "fields": [
            {"key": "legal_name", "label": "Legal entity name", "type": "text", "required": True,
             "hint": "Exactly as registered with the Secretary of State"},
            {"key": "state_of_origin", "label": "State of origin", "type": "text"},
            {"key": "signatory_name", "label": "Authorized signatory — name", "type": "text", "required": True},
            {"key": "signatory_title", "label": "Authorized signatory — title", "type": "text"},
            {"key": "contact_email", "label": "Contact email", "type": "text"},
            {"key": "contact_phone", "label": "Contact phone", "type": "text"},
        ],
    },
    {
        "id": "site",
        "title": "2 · Site Control",
        "hint": "Letters of intent are not accepted as evidence of site exclusivity.",
        "fields": [
            {"key": "project_name", "label": "Project name", "type": "text", "required": True},
            {"key": "gps_lat", "label": "GPS latitude (decimal)", "type": "number", "required": True},
            {"key": "gps_lon", "label": "GPS longitude (decimal)", "type": "number", "required": True},
            {"key": "county", "label": "County", "type": "text"},
            {"key": "state", "label": "State", "type": "text"},
            {"key": "site_acreage", "label": "Site acreage", "type": "number"},
            {"key": "site_control", "label": "Site exclusivity type", "type": "select", "required": True,
             "options": ["Lease Agreement", "Option to Purchase", "Deed (ownership)", "Letter of Intent", "None yet"],
             "hint": "LOI is not accepted by CAISO"},
            {"key": "site_owner", "label": "Site owner / lessor", "type": "text"},
        ],
    },
    {
        "id": "intent",
        "title": "3 · Interconnection Intent",
        "hint": "POI choice drives study cost and upgrade exposure.",
        "fields": [
            {"key": "poi_name", "label": "Target POI — substation / line", "type": "text", "required": True},
            {"key": "poi_voltage_kv", "label": "POI voltage (kV)", "type": "number", "required": True},
            {"key": "track", "label": "Process track", "type": "select", "required": True,
             "options": ["Independent Study Process", "Fast Track", "Cluster"],
             "hint": "Fast Track requires ≤ 5 MW; ISP requires an eligibility demonstration"},
            {"key": "deliverability", "label": "Requested deliverability", "type": "select",
             "options": ["Full Capacity", "Partial Deliverability", "Energy Only"]},
            {"key": "cod", "label": "Target COD (YYYY-MM-DD)", "type": "text", "required": True,
             "hint": "Must be within 7 years of the application"},
        ],
    },
    {
        "id": "technical",
        "title": "4 · Project Technical Parameters",
        "hint": "MW chain: Gross Output − Aux Load − Losses = Net MW at POI. Must match across every document.",
        "fields": [
            {"key": "project_type", "label": "Project type", "type": "select", "required": True,
             "options": ["Solar PV", "Solar PV + BESS (AC-coupled)", "Solar PV + BESS (DC-coupled)",
                          "Standalone BESS", "Wind", "Wind + BESS"]},
            {"key": "gross_mva", "label": "Gross capacity (MVA)", "type": "number", "required": True},
            {"key": "gross_mw", "label": "Gross output (MW)", "type": "number", "required": True},
            {"key": "aux_mw", "label": "Auxiliary load (MW)", "type": "number", "required": True},
            {"key": "losses_mw", "label": "Losses to POI (MW)", "type": "number", "required": True},
            {"key": "net_mw_poi", "label": "Requested net MW at POI", "type": "number", "required": True,
             "hint": "The number that appears in the CAISO queue"},
            {"key": "bess_mw", "label": "BESS power (MW)", "type": "number", "hint": "Blank if no storage"},
            {"key": "bess_mwh", "label": "BESS energy (MWh)", "type": "number"},
            {"key": "bess_charging", "label": "BESS charging source", "type": "select",
             "options": ["On-site generation only", "Grid charging permitted", "N/A — no storage"]},
        ],
    },
    {
        "id": "equipment",
        "title": "5 · Equipment & Vendor",
        "hint": "Vendor .dyd dynamic model files are the most common schedule risk — request them on day one.",
        "fields": [
            {"key": "inverter", "label": "Inverter manufacturer / model / qty", "type": "text",
             "hint": "Enter TBD if not selected — generic PSLF models will be used"},
            {"key": "module", "label": "PV module / turbine model", "type": "text"},
            {"key": "bess_vendor", "label": "BESS manufacturer / model", "type": "text"},
            {"key": "dyd_status", "label": "Vendor .dyd model files", "type": "select", "required": True,
             "options": ["Received from vendor", "Requested — pending", "Equipment not selected"],
             "hint": "PSLF dynamic models from the equipment vendor"},
            {"key": "transformer", "label": "Main transformer (GSU) data", "type": "text",
             "hint": "MVA, voltage ratio, impedance, vector group"},
            {"key": "collector_kv", "label": "Collector system voltage (kV)", "type": "number"},
        ],
    },
    {
        "id": "documents",
        "title": "6 · Kickoff Documents",
        "hint": "The files a consulting firm collects at the kickoff meeting. Example files are preloaded "
                "and may be replaced or removed; validation reflects any change.",
        "fields": [
            {"key": "file_site_control", "label": "Executed site exclusivity agreement", "type": "file",
             "required": True, "accept": ".pdf,.doc,.docx",
             "hint": "Executed lease / option / deed. This is the evidence behind the site exclusivity "
                     "declaration — CAISO rejects LOIs."},
            {"key": "file_technical", "label": "Technical data workbook", "type": "file",
             "required": True, "accept": ".xlsx,.xls,.csv",
             "hint": "The developer's technical data sheet — MW chain, inverter, GSU, collector system. "
                     "Source of the technical parameters in the intake form."},
            {"key": "file_bess", "label": "BESS specification sheet", "type": "file",
             "accept": ".xlsx,.xls,.pdf",
             "hint": "The storage vendor's specification — power rating, energy capacity, charging "
                     "configuration. Source of the storage parameters in the intake form."},
            {"key": "file_signatory", "label": "Proof of authorized signatory", "type": "file",
             "accept": ".pdf,.doc,.docx",
             "hint": "Officer certificate or board resolution naming the signatory. If missing, GridPilot "
                     "drafts one for counsel to execute."},
            {"key": "file_dyd", "label": "Vendor PSLF dynamic model (.dyd)", "type": "file",
             "accept": ".dyd,.zip",
             "hint": "From the inverter/BESS vendor — the most common schedule risk. Generic WECC models "
                     "are used until it arrives."},
            {"key": "file_boundary", "label": "Project boundary (KMZ / parcel map)", "type": "file",
             "accept": ".kmz,.kml,.pdf",
             "hint": "Optional — without it, GridPilot derives the boundary from GPS + acreage."},
        ],
    },
]

DEFAULT_INTAKE: dict[str, Any] = {
    "legal_name": "Ravenwood Energy LLC",
    "state_of_origin": "Delaware",
    "signatory_name": "Ryan Yang",
    "signatory_title": "Director of Development",
    "contact_email": "ryan@ravenwoodenergy.com",
    "contact_phone": "(661) 555-0142",
    "project_name": "Ravenwood",
    "gps_lat": 35.0842,
    "gps_lon": -118.3081,
    "county": "Kern",
    "state": "CA",
    "site_acreage": 610,
    "site_control": "Lease Agreement",
    "site_owner": "Willow Springs Ranch LP",
    "poi_name": "Whirlwind Substation (SCE)",
    "poi_voltage_kv": 230,
    "track": "Independent Study Process",
    "deliverability": "Full Capacity",
    "cod": "2028-06-30",
    "project_type": "Solar PV + BESS (AC-coupled)",
    "gross_mva": 132.0,
    "gross_mw": 128.0,
    "aux_mw": 2.5,
    "losses_mw": 0.5,
    # Deliberate kickoff-data defects so the demo exercises the fix-and-revalidate
    # loop: net at POI doesn't reconcile the MW chain, and BESS energy is missing.
    "net_mw_poi": 128.0,
    "bess_mw": 50.0,
    "bess_mwh": None,
    "bess_charging": "On-site generation only",
    "inverter": "Sungrow SG4400UD-MV, qty 18",
    "module": "JinkoSolar Tiger Neo 620W bifacial",
    "bess_vendor": "Tesla Megapack 2XL, qty 50",
    "dyd_status": "Requested — pending",
    "transformer": "140 MVA, 34.5/230 kV, Z = 8.5% @ ONAF, YNd1",
    "collector_kv": 34.5,
    # Kickoff document uploads: {name, size} metadata; "example" marks preloaded demo
    # files. All examples start staged (uploaded, not yet submitted) so the demo walks
    # the full choose → upload → preview → submit interaction.
    "file_site_control": {"name": "Ravenwood_Lease_WillowSpringsRanch_Executed_2026-03-14.pdf",
                          "size": 2_871_342, "example": True, "staged": True},
    "file_technical": {"name": "Ravenwood_TechnicalData_Workbook_v1.xlsx", "size": 87_450,
                       "example": True, "staged": True},
    "file_bess": {"name": "Ravenwood_BESS_Spec_Megapack2XL_v1.xlsx", "size": 54_120,
                  "example": True, "staged": True},
    "file_signatory": {"name": "Ravenwood_OfficerCertificate_RYang.pdf", "size": 184_230,
                       "example": True, "staged": True},
    "file_dyd": None,  # pending from vendor — matches dyd_status default
    "file_boundary": {"name": "Ravenwood_ParcelBoundary_KernCounty.kmz", "size": 46_210,
                      "example": True, "staged": True},
}


def _file_meta(v: Any) -> dict[str, Any] | None:
    """Return upload metadata ({name, size, ...}) if a file is submitted, else None.

    Files carry a staged→submitted lifecycle: uploads marked `staged` are visible
    in the UI but do not count for validation or extraction until submitted.
    """
    if isinstance(v, dict) and str(v.get("name") or "").strip() and not v.get("staged"):
        return v
    return None


# Intake fields each kickoff document yields under AI extraction. Ordered so the
# most authoritative source for a field wins (e.g. boundary file for GPS).
EXTRACTION_SOURCES: list[tuple[str, str, list[str]]] = [
    ("file_site_control", "Site exclusivity agreement",
     ["legal_name", "site_owner", "site_control", "site_acreage", "county", "state"]),
    ("file_technical", "Technical data workbook",
     ["project_type", "gross_mva", "gross_mw", "aux_mw", "losses_mw", "net_mw_poi",
      "inverter", "module", "transformer", "collector_kv"]),
    ("file_bess", "BESS specification sheet",
     ["bess_vendor", "bess_mw", "bess_mwh", "bess_charging"]),
    ("file_signatory", "Certificate of authorized signatory",
     ["signatory_name", "signatory_title", "legal_name", "state_of_origin"]),
    ("file_boundary", "Project boundary file",
     ["project_name", "gps_lat", "gps_lon", "site_acreage", "county", "state"]),
    ("file_dyd", "Vendor dynamic model", ["dyd_status"]),
]

# The example documents carry the seeded kickoff defects — one per file, so each
# corrected upload clears exactly its own finding. A replacement upload represents
# the developer's corrected revision; extraction from a non-example file returns
# the reconciled values.
CORRECTED_EXTRACTIONS: dict[str, dict[str, Any]] = {
    "file_technical": {"net_mw_poi": 125.0},
    "file_bess": {"bess_mwh": 200.0},
}


# Ground-truth requirements each validation check enforces. Rendered as a
# previewable requirement page with the operative clause highlighted.
# Demo-drafted summaries of the CAISO tariff / BPM provisions, not verbatim text.
REQUIREMENTS: dict[str, dict[str, Any]] = {
    "legal-name": {
        "title": "Interconnection Customer legal identity",
        "source": "CAISO BPM for Generator Interconnection — Appendix 1 completion instructions",
        "paragraphs": [
            "The Interconnection Request must identify the Interconnection Customer by its full legal "
            "name as registered with the Secretary of State of its state of formation.",
            "The legal name entered in Appendix 1 is cross-checked against the site exclusivity "
            "documentation and the certificate of authorized signatory during deficiency review.",
        ],
        "clause": "The name of the Interconnection Customer must match the Secretary of State "
                  "registration exactly and must be used consistently across all submitted documents.",
    },
    "signatory": {
        "title": "Execution by an authorized signatory",
        "source": "CAISO BPM for Generator Interconnection — Appendix 1 execution requirements",
        "paragraphs": [
            "Appendix 1 must be executed in RIMS5 by an individual with authority to bind the "
            "Interconnection Customer.",
            "CAISO may request evidence of that authority — typically an officer certificate or a "
            "board resolution naming the signatory.",
        ],
        "clause": "The Interconnection Request must be executed by an authorized representative of "
                  "the Interconnection Customer; evidence of signing authority must be available on request.",
    },
    "gps": {
        "title": "Site location data",
        "source": "CAISO Appendix 1 — Section 6 (Project site information)",
        "paragraphs": [
            "The Interconnection Request must state the geographic location of the Generating "
            "Facility, including latitude and longitude in decimal format.",
            "The stated coordinates feed Appendix 1, Attachment A, and the project boundary file, "
            "and must agree across all three.",
        ],
        "clause": "Latitude and longitude must be provided in decimal degrees and must be consistent "
                  "with the project boundary file submitted with the request.",
    },
    "site-exclusivity": {
        "title": "Evidence of site exclusivity",
        "source": "CAISO Tariff Appendix DD (GIDAP) — Site Exclusivity requirements",
        "paragraphs": [
            "An Interconnection Request under the Independent Study Process must demonstrate site "
            "exclusivity for the Generating Facility site, or pay the site exclusivity deposit in lieu.",
            "Acceptable evidence is an executed lease, an option to lease or purchase, or a deed for "
            "the parcels comprising the site. The document itself must be produced.",
        ],
        "clause": "A letter of intent or other non-binding instrument does not constitute site "
                  "exclusivity — an executed lease, option, or deed is required.",
    },
    "poi": {
        "title": "Point of Interconnection identification",
        "source": "CAISO Appendix 1 — Section 5 (Point of Interconnection)",
        "paragraphs": [
            "The request must identify the proposed Point of Interconnection: the transmission "
            "substation or line segment and the interconnection voltage level.",
            "The POI stated in Appendix 1 governs the load flow model, the single-line diagram, and "
            "the study scope.",
        ],
        "clause": "Both the substation / line name and the voltage level (kV) of the Point of "
                  "Interconnection are required entries.",
    },
    "mw-chain": {
        "title": "Consistency of stated capacity values",
        "source": "CAISO Attachment A — technical data consistency rules",
        "paragraphs": [
            "Attachment A requires gross generating capability, auxiliary (station) load, electrical "
            "losses to the Point of Interconnection, and the requested net output at the POI.",
            "These values are checked arithmetically during deficiency review and are cross-referenced "
            "against Appendix 1 and the submitted PSLF models.",
        ],
        "clause": "The requested net MW at the Point of Interconnection must equal gross output minus "
                  "auxiliary load minus losses; inconsistent MW values are a deficiency finding.",
    },
    "fast-track": {
        "title": "Fast Track eligibility limit",
        "source": "CAISO Tariff Appendix DD (GIDAP) — Fast Track Process eligibility",
        "paragraphs": [
            "The Fast Track Process is available only to Generating Facilities with a capacity at or "
            "below the Fast Track limit at the Point of Interconnection.",
        ],
        "clause": "A Generating Facility exceeding 5 MW at the Point of Interconnection is not "
                  "eligible for the Fast Track Process.",
    },
    "isp": {
        "title": "Independent Study Process requirements",
        "source": "CAISO Tariff Appendix DD (GIDAP) — Independent Study Process",
        "paragraphs": [
            "An ISP request must include an eligibility demonstration showing the project is "
            "electrically independent of pending cluster requests, together with the study deposit.",
        ],
        "clause": "The Independent Study Process requires an eligibility demonstration and a "
                  "$150,000 study deposit submitted with the Interconnection Request.",
    },
    "deliverability": {
        "title": "Deliverability assessment timing",
        "source": "CAISO Tariff Appendix DD (GIDAP) — Section 4.6 (Deliverability)",
        "paragraphs": [
            "A request for Full Capacity Deliverability Status is assessed in the annual Cluster "
            "Study deliverability analysis, even where the interconnection study proceeds under ISP.",
        ],
        "clause": "Full Capacity Deliverability Status is determined in the next annual Cluster "
                  "Study cycle — it is not established by the Independent Study itself.",
    },
    "cluster-window": {
        "title": "Cluster request window",
        "source": "CAISO Tariff Appendix DD (GIDAP) — Cluster Study process",
        "paragraphs": [
            "Cluster Interconnection Requests are accepted only during the annual request window; "
            "requests received outside the window roll to the following cycle.",
        ],
        "clause": "Interconnection Requests under the Cluster Study process may be submitted only "
                  "during the annual open request window.",
    },
    "cod-limit": {
        "title": "Commercial operation date limit",
        "source": "CAISO Tariff Appendix DD (GIDAP) — Interconnection Request contents",
        "paragraphs": [
            "The Interconnection Request must state a proposed commercial operation date.",
        ],
        "clause": "The proposed commercial operation date may not exceed seven years from the date "
                  "the Interconnection Request is submitted.",
    },
    "bess-energy": {
        "title": "Energy storage technical data",
        "source": "CAISO Attachment A — energy storage supplement",
        "paragraphs": [
            "Where the Generating Facility includes an energy storage component, the request must "
            "state both the storage power rating and the energy capacity.",
            "Charging behavior must also be declared, as it affects the deliverability assessment "
            "and the load flow model.",
        ],
        "clause": "Storage projects must state the energy capacity (MWh) and duration in addition "
                  "to the MW rating; a power rating alone is a deficiency.",
    },
    "bess-charging": {
        "title": "Storage charging source declaration",
        "source": "CAISO Attachment A — energy storage supplement",
        "paragraphs": [
            "The request must declare whether the storage component charges exclusively from on-site "
            "generation or also from the grid.",
        ],
        "clause": "Grid charging changes the deliverability assessment and the load-flow model and "
                  "must be declared in the Interconnection Request.",
    },
    "dyd-models": {
        "title": "Dynamic model data requirements",
        "source": "CAISO BPM for Generator Interconnection — modeling data requirements",
        "paragraphs": [
            "The Interconnection Request must include dynamic models compatible with the CAISO "
            "planning tools (GE PSLF), using WECC-approved model structures.",
            "Vendor-specific parameter files (.dyd) are required for the inverter and storage "
            "equipment; generic WECC models are accepted only as placeholders.",
        ],
        "clause": "Dynamic model data declared as received from the vendor must be included with "
                  "the submission in PSLF-compatible (.dyd) format.",
    },
    "boundary": {
        "title": "Project boundary file",
        "source": "CAISO BPM for Generator Interconnection — site documentation",
        "paragraphs": [
            "A geographic boundary file (KMZ/KML) delineating the Generating Facility site supports "
            "the site exclusivity review and the study of the interconnection route.",
        ],
        "clause": "The project boundary file must be consistent with the site coordinates and "
                  "acreage stated in Appendix 1.",
    },
}


def extract_from_documents(files: dict[str, Any]) -> dict[str, Any]:
    """Simulated AI extraction: map attached kickoff documents to intake fields.

    The demo's example documents carry the Ravenwood values; each extracted field
    is returned with provenance so the form can show where the value came from.
    """
    fields: dict[str, Any] = {}
    provenance: dict[str, dict[str, str]] = {}
    docs_used = 0
    for key, source_label, field_keys in EXTRACTION_SOURCES:
        meta = _file_meta(files.get(key))
        if meta is None:
            continue
        docs_used += 1
        corrections = {} if meta.get("example") else CORRECTED_EXTRACTIONS.get(key, {})
        for fk in field_keys:
            if fk in corrections:
                value = corrections[fk]
            elif fk == "dyd_status":
                value = "Received from vendor"
            else:
                value = DEFAULT_INTAKE.get(fk)
            if value is None:
                continue
            fields[fk] = value
            provenance[fk] = {"source": key, "source_label": source_label, "file": str(meta["name"])}
    return {
        "fields": fields,
        "provenance": provenance,
        "summary": f"{len(fields)} fields extracted from {docs_used} document(s)",
    }


# ---------------------------------------------------------------------------
# Validation — the consulting "Step A: kickoff & data validation"
# ---------------------------------------------------------------------------

def _num(v: Any) -> float | None:
    if v is None or v == "":
        return None
    try:
        return float(str(v).replace(",", ""))
    except ValueError:
        return None


def _parse_cod(v: Any) -> date | None:
    s = str(v or "").strip()
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def validate_intake(intake: dict[str, Any]) -> dict[str, Any]:
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    passed: list[dict[str, Any]] = []

    def _rule_ref(rule_id: str | None) -> dict[str, str] | None:
        req = REQUIREMENTS.get(rule_id or "")
        if not req:
            return None
        return {"id": rule_id, "title": req["title"], "source": req["source"]}

    def _evidence_ref(file_key: str | None, hl: list[str] | None = None) -> dict[str, Any] | None:
        """The examined document behind a check: which upload, and what to highlight."""
        if not file_key:
            return None
        meta = _file_meta(intake.get(file_key))
        return {
            "key": file_key,
            "file": meta["name"] if meta else None,
            "attached": meta is not None,
            "example": bool(meta and meta.get("example")),
            "hl": hl or [],
        }

    def _item(field: str, title: str, detail: str,
              rule: str | None, evidence: str | None, hl: list[str] | None) -> dict[str, Any]:
        it: dict[str, Any] = {"field": field, "title": title, "detail": detail}
        r = _rule_ref(rule)
        if r:
            it["rule"] = r
        e = _evidence_ref(evidence, hl)
        if e:
            it["evidence"] = e
        return it

    # `checks` preserves the canonical run order regardless of outcome, so the UI
    # can keep every check in a stable position as its status changes.
    checks: list[dict[str, Any]] = []

    def err(field: str, title: str, detail: str,
            rule: str | None = None, evidence: str | None = None, hl: list[str] | None = None) -> None:
        it = _item(field, title, detail, rule, evidence, hl)
        it["status"] = "error"
        errors.append(it)
        checks.append(it)

    def warn(field: str, title: str, detail: str,
             rule: str | None = None, evidence: str | None = None, hl: list[str] | None = None) -> None:
        it = _item(field, title, detail, rule, evidence, hl)
        it["status"] = "warn"
        warnings.append(it)
        checks.append(it)

    def ok(title: str, detail: str,
           rule: str | None = None, evidence: str | None = None, hl: list[str] | None = None) -> None:
        it = _item("", title, detail, rule, evidence, hl)
        it["status"] = "ok"
        passed.append(it)
        checks.append(it)

    if not str(intake.get("legal_name") or "").strip():
        err("legal_name", "Legal entity name missing",
            "Required — and it must match the Secretary of State certificate exactly.",
            rule="legal-name", evidence="file_signatory", hl=["legal_name"])
    else:
        ok("Legal entity identified",
           f'"{intake["legal_name"]}" will be used consistently across Appendix 1, site exclusivity, and signatory documents.',
           rule="legal-name", evidence="file_signatory", hl=["legal_name"])

    if not str(intake.get("signatory_name") or "").strip():
        err("signatory_name", "Authorized signatory missing",
            "Appendix 1 must be executed by an authorized signatory in RIMS5.",
            rule="signatory", evidence="file_signatory", hl=["signatory"])

    lat, lon = _num(intake.get("gps_lat")), _num(intake.get("gps_lon"))
    if lat is None or lon is None:
        err("gps_lat", "GPS coordinates missing or invalid",
            "Decimal-format latitude and longitude are required (they feed Appendix 1, Attachment A, and the KMZ).",
            rule="gps", evidence="file_boundary", hl=["gps"])
    else:
        if not (32.0 <= lat <= 42.5 and -125.0 <= lon <= -113.5):
            warn("gps_lat", "Coordinates outside the typical CAISO footprint",
                 f"({lat}, {lon}) does not look like a California site — verify before submission.",
                 rule="gps", evidence="file_boundary", hl=["gps"])
        else:
            ok("Site coordinates valid", f"({lat}, {lon}) — {intake.get('county') or '—'} County, {intake.get('state') or 'CA'}.",
               rule="gps", evidence="file_boundary", hl=["gps"])

    site_control = str(intake.get("site_control") or "")
    site_file = _file_meta(intake.get("file_site_control"))
    if site_control == "Letter of Intent":
        err("site_control", "Letter of Intent is not accepted",
            "CAISO requires a lease, option to purchase, or deed as evidence of site exclusivity.",
            rule="site-exclusivity", evidence="file_site_control", hl=["exclusivity"])
    elif site_control in ("None yet", ""):
        err("site_control", "No site exclusivity",
            "An executed lease, option, or deed is required before submission — the most common source of delay.",
            rule="site-exclusivity", evidence="file_site_control", hl=["exclusivity"])
    elif site_file is None:
        err("file_site_control", "Executed site agreement not attached",
            f"Site exclusivity is declared as \"{site_control}\", but no executed agreement is uploaded. "
            "CAISO requires the document itself as evidence — the declaration alone is not sufficient.",
            rule="site-exclusivity", evidence="file_site_control", hl=["exclusivity"])
    else:
        ok("Site exclusivity evidenced",
           f"{site_control} — \"{site_file['name']}\" will accompany the site exclusivity declaration.",
           rule="site-exclusivity", evidence="file_site_control", hl=["exclusivity"])

    if not str(intake.get("poi_name") or "").strip() or _num(intake.get("poi_voltage_kv")) is None:
        err("poi_name", "Point of Interconnection incomplete",
            "Substation / line name and voltage level (kV) are both required.", rule="poi")
    else:
        ok("POI defined", f"{intake['poi_name']} at {_fmt(_num(intake.get('poi_voltage_kv')))} kV.", rule="poi")

    gross = _num(intake.get("gross_mw"))
    aux = _num(intake.get("aux_mw"))
    losses = _num(intake.get("losses_mw"))
    net = _num(intake.get("net_mw_poi"))
    if None in (gross, aux, losses, net):
        err("net_mw_poi", "MW chain incomplete",
            "Gross output, auxiliary load, losses, and net MW at POI are all required.",
            rule="mw-chain", evidence="file_technical",
            hl=["gross_mw", "aux_mw", "losses_mw", "net_mw_poi"])
    else:
        computed = round(gross - aux - losses, 3)
        if abs(computed - net) > 0.05:
            err("net_mw_poi", "MW chain does not reconcile",
                f"Gross {_fmt(gross)} − Aux {_fmt(aux)} − Losses {_fmt(losses)} = {_fmt(computed)} MW, "
                f"but requested net at POI is {_fmt(net)} MW. Inconsistent MW values are among the most "
                "common CAISO deficiency findings.",
                rule="mw-chain", evidence="file_technical", hl=["net_mw_poi"])
        else:
            ok("MW chain reconciles",
               f"Gross {_fmt(gross)} − Aux {_fmt(aux)} − Losses {_fmt(losses)} = {_fmt(net)} MW at POI. "
               "This value will be enforced across all generated documents.",
               rule="mw-chain", evidence="file_technical", hl=["net_mw_poi"])
        if net is not None and net > 20:
            ok("Large Generating Facility", f"{_fmt(net)} MW > 20 MW — Large project rules apply.")

    track = str(intake.get("track") or "")
    if not track:
        err("track", "Process track not selected", "Choose Cluster, Independent Study, or Fast Track.")
    elif track == "Fast Track" and net is not None and net > 5:
        err("track", "Fast Track not available above 5 MW",
            f"Requested {_fmt(net)} MW at POI exceeds the 5 MW Fast Track limit — use ISP or Cluster.",
            rule="fast-track", evidence="file_technical", hl=["net_mw_poi"])
    elif track == "Independent Study Process":
        ok("ISP track selected",
           "GridPilot will draft the ISP eligibility demonstration; the $150,000 study deposit is wired directly to CAISO.",
           rule="isp")
        if str(intake.get("deliverability")) == "Full Capacity":
            warn("deliverability", "Full Capacity deliverability under ISP",
                 "Deliverability is assessed in the next annual Cluster Study (GIDAP 4.6) — flag this to offtake counterparties.",
                 rule="deliverability")
    elif track == "Cluster":
        warn("track", "Cluster window timing",
             "Cluster requests are only accepted during the annual request window; typical study-to-GIA timeline is ~3 years.",
             rule="cluster-window")

    cod = _parse_cod(intake.get("cod"))
    if cod is None:
        err("cod", "Target COD missing or unparseable", "Provide the commercial operation date as YYYY-MM-DD.",
            rule="cod-limit")
    elif cod > date.today() + timedelta(days=365 * 7):
        err("cod", "COD beyond the 7-year limit",
            f"{cod.isoformat()} is more than 7 years out — CAISO caps COD at 7 years from the application.",
            rule="cod-limit")
    elif cod < date.today():
        err("cod", "COD is in the past", f"{cod.isoformat()} — update the target commercial operation date.",
            rule="cod-limit")
    else:
        ok("COD within limits", f"{cod.strftime('%m/%d/%Y')} — in-service and trial-operation dates will be derived sequentially.",
           rule="cod-limit")

    bess_mw = _num(intake.get("bess_mw"))
    if bess_mw and bess_mw > 0:
        if not _num(intake.get("bess_mwh")):
            err("bess_mwh", "BESS energy missing", "MWh (duration) is required when storage is included.",
                rule="bess-energy", evidence="file_bess", hl=["bess_mwh"])
        else:
            ok("Storage parameters complete",
               f"{_fmt(bess_mw)} MW / {_fmt(_num(intake.get('bess_mwh')))} MWh — "
               f"charging: {intake.get('bess_charging') or 'unspecified'}.",
               rule="bess-energy", evidence="file_bess", hl=["bess_mw", "bess_mwh"])
        if str(intake.get("bess_charging")) == "Grid charging permitted":
            warn("bess_charging", "Grid charging affects deliverability & modeling",
                 "Charging from the grid changes the deliverability assessment and the load-flow model — confirm intent.",
                 rule="bess-charging", evidence="file_bess", hl=["bess_charging"])

    dyd = str(intake.get("dyd_status") or "")
    dyd_file = _file_meta(intake.get("file_dyd"))
    if dyd == "Received from vendor":
        if dyd_file is None:
            err("file_dyd", "Vendor .dyd marked received but not uploaded",
                "The intake indicates the vendor dynamic model files are in hand — attach the .dyd file "
                "so its parameters can be integrated into the PSLF dynamic model.",
                rule="dyd-models", evidence="file_dyd")
        else:
            ok("Vendor dynamic models in hand",
               f"\"{dyd_file['name']}\" — vendor parameters will be integrated into the PSLF dynamic model.",
               rule="dyd-models", evidence="file_dyd")
    elif dyd_file is not None:
        ok("Vendor .dyd file received",
           f"\"{dyd_file['name']}\" attached — vendor parameters will be integrated into the PSLF dynamic model.",
           rule="dyd-models", evidence="file_dyd")
    elif dyd == "Requested — pending":
        warn("dyd_status", "Vendor .dyd files still pending",
             "The single most common schedule risk. GridPilot will use standard WECC models "
             "(REGC_A / REEC_A / REPC_A) as placeholders — swap in vendor files before submission.",
             rule="dyd-models", evidence="file_dyd")
    else:
        warn("dyd_status", "Equipment not selected",
             "Generic PSLF models will be used as placeholders; later equipment swaps add rework and possible re-study.",
             rule="dyd-models", evidence="file_dyd")

    sig_file = _file_meta(intake.get("file_signatory"))
    if sig_file is None:
        warn("file_signatory", "Signatory proof not attached",
             "No officer certificate or board resolution uploaded — GridPilot will generate a draft "
             "for counsel to review and execute before submission.",
             rule="signatory", evidence="file_signatory", hl=["signatory"])
    else:
        ok("Signatory proof on file",
           f"\"{sig_file['name']}\" documents {intake.get('signatory_name') or 'the signatory'}'s authority to execute Appendix 1.",
           rule="signatory", evidence="file_signatory", hl=["signatory"])

    boundary_file = _file_meta(intake.get("file_boundary"))
    if boundary_file is not None:
        ok("Project boundary file received",
           f"\"{boundary_file['name']}\" — the KMZ and site drawing will follow this boundary.",
           rule="boundary", evidence="file_boundary", hl=["gps"])

    if "TBD" in str(intake.get("inverter") or "").upper() or not str(intake.get("inverter") or "").strip():
        warn("inverter", "Inverter not finalized",
             "Attachment A will carry generic values — update before submission to avoid deficiency review.",
             rule="dyd-models", evidence="file_technical", hl=["inverter"])

    return {
        "ok": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
        "passed": passed,
        "checks": checks,
        "summary": (
            f"{len(errors)} blocking issue(s), {len(warnings)} advisory item(s), {len(passed)} check(s) passed."
        ),
    }


def _fmt(v: float | None) -> str:
    if v is None:
        return "—"
    return f"{v:g}"


# ---------------------------------------------------------------------------
# PDF helpers (PyMuPDF)
# ---------------------------------------------------------------------------

INK = (0.10, 0.12, 0.11)
MUT = (0.42, 0.46, 0.44)
ACC = (0.13, 0.35, 0.75)
RED = (0.62, 0.18, 0.10)
OKC = (0.10, 0.45, 0.25)
LINE = (0.80, 0.82, 0.80)

PAGE_W, PAGE_H = 612, 792  # portrait letter


class _Pdf:
    def __init__(self, title: str, subtitle: str, banner: str = "GENERATED DRAFT — GridPilot"):
        self.doc = fitz.open()
        self.title = title
        self.subtitle = subtitle
        self.banner = banner
        self.page: fitz.Page | None = None
        self.y = 0.0
        self._new_page()

    def _new_page(self) -> None:
        self.page = self.doc.new_page(width=PAGE_W, height=PAGE_H)
        self.page.draw_rect(fitz.Rect(0, 0, PAGE_W, 6), color=ACC, fill=ACC)
        self.page.insert_text((36, 34), self.banner, fontsize=7.5, fontname="cour", color=RED)
        self.page.insert_text((36, 56), self.title, fontsize=15, fontname="hebo", color=INK)
        self.page.insert_text((36, 72), self.subtitle, fontsize=9, fontname="helv", color=MUT)
        self.page.draw_line(fitz.Point(36, 82), fitz.Point(PAGE_W - 36, 82), color=LINE, width=0.8)
        self.page.insert_text(
            (36, PAGE_H - 28),
            f"GridPilot — generated {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')} — verify before RIMS5 submission",
            fontsize=7, fontname="helv", color=MUT,
        )
        self.y = 100

    def _ensure(self, needed: float) -> None:
        if self.y + needed > PAGE_H - 48:
            self._new_page()

    def section(self, text: str) -> None:
        self._ensure(28)
        self.y += 8
        self.page.insert_text((36, self.y), text.upper(), fontsize=8.5, fontname="hebo", color=ACC)
        self.y += 6
        self.page.draw_line(fitz.Point(36, self.y), fitz.Point(PAGE_W - 36, self.y), color=LINE, width=0.6)
        self.y += 14

    def kv(self, label: str, value: str, note: str = "") -> None:
        self._ensure(16)
        self.page.insert_text((36, self.y), label, fontsize=8.5, fontname="helv", color=MUT)
        self.page.insert_text((250, self.y), value, fontsize=9, fontname="hebo", color=INK)
        if note:
            self.y += 11
            self.page.insert_text((250, self.y), note, fontsize=7.5, fontname="helv", color=MUT)
        self.y += 15

    def para(self, text: str, size: float = 9, color=INK, indent: float = 36) -> None:
        width_chars = int((PAGE_W - indent - 36) / (size * 0.5))
        words = text.split()
        line = ""
        lines: list[str] = []
        for w in words:
            if len(line) + len(w) + 1 > width_chars:
                lines.append(line)
                line = w
            else:
                line = f"{line} {w}".strip()
        if line:
            lines.append(line)
        for ln in lines:
            self._ensure(13)
            self.page.insert_text((indent, self.y), ln, fontsize=size, fontname="helv", color=color)
            self.y += size + 4

    def bullet(self, text: str, color=INK) -> None:
        self._ensure(13)
        self.page.insert_text((44, self.y), "•", fontsize=9, fontname="helv", color=color)
        keep_y = self.y
        self.y = keep_y
        # simple single-level wrap
        width_chars = 92
        words = text.split()
        line = ""
        first = True
        for w in words:
            if len(line) + len(w) + 1 > width_chars:
                self._ensure(13)
                self.page.insert_text((56, self.y), line, fontsize=9, fontname="helv", color=color)
                self.y += 13
                line = w
                first = False
            else:
                line = f"{line} {w}".strip()
        if line:
            self._ensure(13)
            self.page.insert_text((56, self.y), line, fontsize=9, fontname="helv", color=color)
            self.y += 13

    def checkbox(self, checked: bool, text: str) -> None:
        self._ensure(15)
        r = fitz.Rect(38, self.y - 8, 47, self.y + 1)
        self.page.draw_rect(r, color=INK, width=0.8)
        if checked:
            self.page.insert_text((39.5, self.y - 0.5), "X", fontsize=8, fontname="hebo", color=INK)
        self.page.insert_text((54, self.y), text, fontsize=9, fontname="helv", color=INK)
        self.y += 16

    def save(self, path: Path) -> None:
        self.doc.save(path)
        self.doc.close()


def _axes(page: fitz.Page, rect: fitz.Rect, title: str, xlabel: str, ylabel: str) -> None:
    page.draw_rect(rect, color=LINE, width=0.8)
    page.insert_text((rect.x0, rect.y0 - 10), title, fontsize=9.5, fontname="hebo", color=INK)
    page.insert_text((rect.x0 + rect.width / 2 - 30, rect.y1 + 16), xlabel, fontsize=7.5, fontname="helv", color=MUT)
    page.insert_text((rect.x0 - 24, rect.y0 - 2), ylabel, fontsize=7.5, fontname="helv", color=MUT)


def _polyline(page: fitz.Page, pts: list[tuple[float, float]], color, width=1.4) -> None:
    for a, b in zip(pts, pts[1:]):
        page.draw_line(fitz.Point(*a), fitz.Point(*b), color=color, width=width)


# ---------------------------------------------------------------------------
# Document builders
# ---------------------------------------------------------------------------

def _derived(intake: dict[str, Any]) -> dict[str, Any]:
    gross = _num(intake.get("gross_mw")) or 0
    aux = _num(intake.get("aux_mw")) or 0
    losses = _num(intake.get("losses_mw")) or 0
    net = _num(intake.get("net_mw_poi")) or 0
    cod = _parse_cod(intake.get("cod")) or date.today() + timedelta(days=540)
    bess_mw = _num(intake.get("bess_mw")) or 0
    pv_mw = max(gross - bess_mw, 0)
    track = str(intake.get("track") or "Independent Study Process")
    deposit = {"Independent Study Process": "$150,000", "Fast Track": "$500 (non-refundable)"}.get(
        track, "Per CAISO Cluster study deposit schedule"
    )
    return {
        "gross": gross, "aux": aux, "losses": losses, "net": net,
        "max_net": round(gross - aux, 3),
        "pv_mw": pv_mw, "bess_mw": bess_mw,
        "cod": cod,
        "in_service": cod - timedelta(days=210),
        "trial_op": cod - timedelta(days=120),
        "track": track,
        "deposit": deposit,
        "kv": _num(intake.get("poi_voltage_kv")) or 230,
        "col_kv": _num(intake.get("collector_kv")) or 34.5,
        "lat": _num(intake.get("gps_lat")) or 35.0,
        "lon": _num(intake.get("gps_lon")) or -118.3,
        "acres": _num(intake.get("site_acreage")) or 600,
        "is_isp": track == "Independent Study Process",
        "has_bess": bess_mw > 0,
    }


def _slug(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", s or "project").strip("_") or "project"


def _gen_appendix1(intake: dict, d: dict, path: Path) -> None:
    pdf = _Pdf(
        "Appendix 1 — Interconnection Request",
        "Independent Study Process / Fast Track (RIMS-IR-NON-CLUSTER-V01) — execute electronically in RIMS5",
    )
    pdf.section("1 · Process")
    pdf.checkbox(d["track"] == "Fast Track", "Fast Track Process")
    pdf.checkbox(d["is_isp"], "Independent Study Process")
    pdf.checkbox(d["track"] == "Cluster", "Cluster (use the Cluster Appendix 1 form)")

    pdf.section("2 · Request type & deliverability")
    pdf.checkbox(True, "A proposed new Generating Facility")
    pdf.kv("Requested deliverability (on-peak)", str(intake.get("deliverability") or "Full Capacity"),
           "ISP: Full Capacity deliverability assessed in the next annual Cluster Study (GIDAP 4.6)")

    pdf.section("4a · Project name & location")
    pdf.kv("Project name", str(intake.get("project_name") or ""))
    pdf.kv("County / State", f"{intake.get('county') or '—'} / {intake.get('state') or 'CA'}")
    pdf.kv("GPS latitude (decimal)", f"{d['lat']}")
    pdf.kv("GPS longitude (decimal)", f"{d['lon']}")

    pdf.section("4b · Project megawatt values")
    pdf.kv("Gross capacity (MVA, unity PF)", _fmt(_num(intake.get("gross_mva"))))
    pdf.kv("Gross output (MW)", _fmt(d["gross"]))
    pdf.kv("Auxiliary load (MW)", _fmt(d["aux"]))
    pdf.kv("Maximum net electrical output (MW)", _fmt(d["max_net"]))
    pdf.kv("Anticipated losses to POI (MW)", _fmt(d["losses"]))
    pdf.kv("Requested Interconnection Service Capacity", f"{_fmt(d['net'])} MW at POI",
           "This value appears in the CAISO queue and must match every document in the packet")
    pdf.para(
        "Output-limiting control: plant-level Power Plant Controller (PPC) monitors POI revenue metering and "
        f"limits aggregate export to {_fmt(d['net'])} MW via real-time inverter setpoint dispatch; "
        "inverter-level curtailment provides backup limitation.", size=8.5, color=MUT)

    pdf.section("4c · Type of project / configuration")
    pdf.kv("Project type", str(intake.get("project_type") or ""))
    conf = f"{intake.get('inverter') or 'Inverters TBD'}; {intake.get('module') or 'modules TBD'}"
    if d["has_bess"]:
        conf += f"; {intake.get('bess_vendor') or 'BESS TBD'} — {_fmt(d['bess_mw'])} MW / {_fmt(_num(intake.get('bess_mwh')))} MWh"
    conf += f"; GSU {intake.get('transformer') or 'TBD'}; collector {_fmt(d['col_kv'])} kV."
    pdf.para(conf, size=8.5)

    pdf.section("4d · Dates (sequential; COD within 7 years)")
    pdf.kv("Proposed in-service date", d["in_service"].strftime("%m/%d/%Y"))
    pdf.kv("Proposed trial operation date", d["trial_op"].strftime("%m/%d/%Y"))
    pdf.kv("Proposed commercial operation date", d["cod"].strftime("%m/%d/%Y"))
    pdf.kv("Proposed term of service", "40 years")

    pdf.section("4e / 4f · Contact & Point of Interconnection")
    pdf.kv("Interconnection customer contact",
           f"{intake.get('signatory_name') or ''}, {intake.get('signatory_title') or ''}")
    pdf.kv("Company", str(intake.get("legal_name") or ""))
    pdf.kv("Phone / Email", f"{intake.get('contact_phone') or '—'} / {intake.get('contact_email') or '—'}")
    pdf.kv("Point of Interconnection", str(intake.get("poi_name") or ""))
    pdf.kv("Voltage level", f"{_fmt(d['kv'])} kV")

    pdf.section("5–9 · Deposit, exclusivity, submission")
    pdf.kv("Study deposit", d["deposit"],
           "Wire directly to CAISO — Wells Fargo, ABA 121000248, Acct 4122041825; reference the project name")
    _sf = _file_meta(intake.get("file_site_control"))
    pdf.kv("Site exclusivity", f"{intake.get('site_control') or ''} — attached",
           f"Owner: {intake.get('site_owner') or '—'}; {_fmt(d['acres'])} acres"
           + (f"; evidence: {_sf['name']}" if _sf else ""))
    pdf.kv("Legal name of Interconnection Customer", str(intake.get("legal_name") or ""),
           "Must match the Secretary of State certificate exactly")
    pdf.kv("State of origin", str(intake.get("state_of_origin") or "—"))
    pdf.para(f"Submit electronically via {RIMS5_URL}. Electronic signature executed in RIMS5 by "
             f"{intake.get('signatory_name') or ''}, {intake.get('signatory_title') or ''}.", size=8.5, color=MUT)
    pdf.save(path)


def _gen_attachment_a(intake: dict, d: dict, path: Path) -> None:
    import openpyxl
    from openpyxl.styles import Alignment, Font, PatternFill

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Technical Data"
    head = Font(bold=True, size=11)
    sect = Font(bold=True, color="1F4BB8")
    fill = PatternFill("solid", fgColor="F2F4F2")
    ws.column_dimensions["A"].width = 46
    ws.column_dimensions["B"].width = 44
    ws.column_dimensions["C"].width = 52

    def row(a="", b="", c="", style=None):
        ws.append([a, b, c])
        r = ws.max_row
        if style == "head":
            ws.cell(r, 1).font = head
        elif style == "sect":
            for col in (1, 2, 3):
                ws.cell(r, col).fill = fill
            ws.cell(r, 1).font = sect
        ws.cell(r, 3).alignment = Alignment(wrap_text=True)

    row(f"GridPilot draft — {intake.get('project_name')} — transfer into the official CAISO Attachment A (.xlsm macro file); "
        "run validation to zero errors before submission.", style="head")
    row("GENERAL", style="sect")
    row("Project Name", str(intake.get("project_name") or ""))
    row("Interconnection Customer (legal name)", str(intake.get("legal_name") or ""),
        "Must match Secretary of State certificate exactly")
    row("Process", d["track"])
    row("Project Type", str(intake.get("project_type") or ""))
    row("County / State", f"{intake.get('county') or ''} County, {intake.get('state') or 'CA'}")
    row("GPS (decimal)", f"{d['lat']}, {d['lon']}")
    row("Point of Interconnection", str(intake.get("poi_name") or ""), f"Voltage: {_fmt(d['kv'])} kV")
    row("CAPACITY (MW CHAIN)", style="sect")
    row("Total Gross Capacity (MVA)", _fmt(_num(intake.get("gross_mva"))), "At unity PF")
    row("Total Gross Output (MW)", _fmt(d["gross"]))
    row("Auxiliary Load (MW)", _fmt(d["aux"]))
    row("Maximum Net Electrical Output (MW)", _fmt(d["max_net"]), f"{_fmt(d['gross'])} − {_fmt(d['aux'])}")
    row("Anticipated Losses to POI (MW)", _fmt(d["losses"]), "GSU + gen-tie")
    row("Requested Interconnection Service Capacity (MW)", _fmt(d["net"]),
        "= queue value; must match all documents")
    row("Deliverability Status", str(intake.get("deliverability") or ""),
        "ISP: assessed in next annual Cluster Study (GIDAP 4.6)")
    row("GENERATION BLOCK", style="sect")
    row("Inverter Mfr / Model / Qty", str(intake.get("inverter") or "TBD"))
    row("Module / Turbine", str(intake.get("module") or "TBD"))
    if d["has_bess"]:
        row("STORAGE BLOCK", style="sect")
        row("BESS Mfr / Model", str(intake.get("bess_vendor") or "TBD"))
        row("BESS Power / Energy", f"{_fmt(d['bess_mw'])} MW / {_fmt(_num(intake.get('bess_mwh')))} MWh")
        row("Charging source", str(intake.get("bess_charging") or ""))
    row("TRANSFORMATION & COLLECTION", style="sect")
    row("Main GSU", str(intake.get("transformer") or "TBD"))
    row("Collector system", f"{_fmt(d['col_kv'])} kV")
    row("REACTIVE / CONTROL", style="sect")
    row("Power factor range at POI", "±0.95", "Plant controller regulated")
    row("Plant controller", f"PPC limits POI export to {_fmt(d['net'])} MW")
    row("Dynamic models", "REGC_A / REEC_A / REPC_A (+ vendor UDM when received)")
    row("DATES", style="sect")
    row("Proposed In-Service Date", d["in_service"].strftime("%m/%d/%Y"))
    row("Proposed Trial Operation Date", d["trial_op"].strftime("%m/%d/%Y"))
    row("Proposed COD", d["cod"].strftime("%m/%d/%Y"))
    row("Term of Service (years)", "40")

    ws2 = wb.create_sheet("IR Validation & Comments")
    ws2.column_dimensions["A"].width = 10
    ws2.column_dimensions["B"].width = 72
    ws2.column_dimensions["C"].width = 46
    ws2.append(["Yes/N-A", "Checklist Item", "Comment"])
    ws2.cell(1, 1).font = head
    ws2.cell(1, 2).font = head
    deposit_item = f"Interconnection Study Deposit ({d['deposit']}) wired to CAISO"
    checklist = [
        ("Yes", deposit_item, f"Reference: {str(intake.get('project_name') or '').upper()}"),
        ("Yes", "Appendix 1 completed and executed in RIMS5", ""),
        ("Yes", "Attachment A Technical Data tab — zero errors; warnings explained", ""),
        ("Yes", "Evidence of Site Exclusivity attached", f"{intake.get('site_control')} — {intake.get('site_owner')}"),
        ("Yes" if d["is_isp"] else "N/A", "ISP eligibility demonstration attached", ""),
        ("Yes", "Load Flow Model (.epc) attached", ""),
        ("Yes", "Dynamic Model (.dyd) attached",
         "Vendor UDM pending" if intake.get("dyd_status") != "Received from vendor" else "Vendor UDM included"),
        ("Yes", "Reactive Power capability document attached", ""),
        ("Yes", "Site Drawing to scale attached", ""),
        ("Yes", "Single Line Diagram attached", ""),
        ("Yes", "Flat run and bump test plots attached (fault cleared after 5 cycles)", ""),
        ("Yes", f"Requested MW at POI plot attached ({_fmt(d['net'])} MW)", ""),
        ("N/A", "Generator terminal voltage vs field current (OCC) — synchronous only", "Inverter-based facility"),
        ("N/A", "Excitation system block diagram — synchronous only", "Inverter-based facility"),
    ]
    for r in checklist:
        ws2.append(list(r))
    wb.save(path)


def _gen_isp_eligibility(intake: dict, d: dict, path: Path) -> None:
    pdf = _Pdf("ISP Eligibility Demonstration",
               f"{intake.get('project_name')} — {intake.get('legal_name')} — checklist item 5")
    pdf.para("Per the ISP/Fast Track Minimum Requirements checklist, the Interconnection Customer demonstrates:")
    pdf.bullet(f"Queue Cluster cannot accommodate the desired COD: the next Cluster window (~3-year study/GIA "
               f"timeline) yields an earliest COD of {d['cod'].year + 2}+, incompatible with the target COD of "
               f"{d['cod'].strftime('%m/%d/%Y')}. [Attach PPA term sheet or offtake evidence]")
    pdf.bullet(f"Regulatory approvals: {intake.get('county') or '—'} County CUP application status and CEQA "
               "documentation. [Attach permit filings]")
    pdf.bullet(f"Purchase order for generating equipment: {intake.get('inverter') or 'inverters TBD'}"
               + (f"; {intake.get('bess_vendor')}" if d["has_bess"] else "")
               + ". [Attach executed supply agreements / POs]")
    pdf.bullet("Financing: committed term sheet for construction debt and LC facility sufficient for "
               "Interconnection Financial Security postings. [Attach lender term sheet + sponsor financials]")
    pdf.bullet(f"POI is an existing facility: {intake.get('poi_name')} is existing and in service for the "
               f"requested {_fmt(d['net'])} MW.")
    pdf.bullet("Precursor network upgrades: none identified; all applicable upgrades in service. [Confirm with CAISO]")
    pdf.section("Action required")
    pdf.para("Each bracketed item requires developer evidence before submission. GridPilot pre-fills the narrative; "
             "counsel should review the final demonstration.", color=RED, size=8.5)
    pdf.save(path)


def _gen_sos_instructions(intake: dict, path: Path) -> None:
    pdf = _Pdf("Secretary of State Certification — Instructions",
               "Official government document — cannot be drafted by GridPilot or a consultant",
               banner="ACTION REQUIRED — DEVELOPER OBTAINS")
    pdf.para(f"Required: Certificate of Good Standing for {intake.get('legal_name')} from the "
             f"{intake.get('state_of_origin') or 'formation state'} Secretary of State "
             "(plus a CA SOS Certificate of Status if foreign-qualified in California).")
    pdf.section("How to order")
    pdf.bullet("Delaware: corp.delaware.gov — ~$50, same-day service available.")
    pdf.bullet("California: bizfileonline.sos.ca.gov.")
    pdf.section("Critical")
    pdf.para(f'The legal name on the certificate must match "{intake.get("legal_name")}" in Appendix 1 Section 9 '
             "and the site exclusivity agreement exactly — punctuation and spelling included.", color=RED)
    pdf.save(path)


def _gen_signatory(intake: dict, path: Path) -> None:
    pdf = _Pdf("Proof of Authorized Signatory — Draft Consent",
               f"{intake.get('legal_name')} — for counsel review")
    pdf.para(f"WRITTEN CONSENT OF THE SOLE MEMBER OF {str(intake.get('legal_name') or '').upper()}")
    pdf.para(f"The undersigned, being the sole Member of {intake.get('legal_name')}, a "
             f"{intake.get('state_of_origin') or 'Delaware'} limited liability company (the \"Company\"), "
             "hereby adopts the following resolutions:")
    pdf.bullet(f"RESOLVED, that {intake.get('signatory_name')}, {intake.get('signatory_title')}, is authorized to "
               "execute and submit on behalf of the Company all documents in connection with the Company's "
               "interconnection request to the California Independent System Operator Corporation, including "
               "Appendix 1 (Interconnection Request), Attachment A, and related submissions via the RIMS5 system;")
    pdf.bullet("RESOLVED FURTHER, that such officer is authorized to make deposits and payments required by the "
               "CAISO Tariff in connection therewith.")
    pdf.para("Date: ____________        Sole Member: ____________________________", size=9)
    sig_file = _file_meta(intake.get("file_signatory"))
    if sig_file:
        pdf.section("Developer-provided evidence")
        pdf.para(f"Uploaded at intake: {sig_file['name']} — include it alongside this draft in the submission.",
                 size=8.5, color=MUT)
    pdf.save(path)


def _gen_site_exclusivity(intake: dict, d: dict, path: Path) -> None:
    pdf = _Pdf("Evidence of Site Exclusivity — Demonstration",
               f"{intake.get('project_name')} — accompanies the executed {intake.get('site_control') or 'agreement'}")
    pdf.kv("Interconnection Customer", str(intake.get("legal_name") or ""),
           "Same entity as Appendix 1 Section 9")
    pdf.kv("Type of site exclusivity", str(intake.get("site_control") or ""),
           "Letters of intent are not acceptable")
    pdf.kv("Lessor / site owner", str(intake.get("site_owner") or "—"))
    pdf.kv("Acreage", f"~{_fmt(d['acres'])} acres — {intake.get('county')} County, {intake.get('state') or 'CA'}")
    pdf.kv("GPS reference", f"{d['lat']}, {d['lon']}")
    site_file = _file_meta(intake.get("file_site_control"))
    if site_file:
        pdf.section("Executed agreement — provided at intake")
        pdf.para(f"{site_file['name']} — uploaded by the developer; include the executed agreement "
                 "with this demonstration in the RIMS5 submission.", size=8.5)
    else:
        pdf.section("Attachment required")
        pdf.para("Attach the fully executed agreement (PDF) including site owner name, address, and contact "
                 "information, plus a recorded memorandum where applicable.", color=RED, size=8.5)
    pdf.save(path)


def _gen_sld(intake: dict, d: dict, path: Path) -> None:
    doc = fitz.open()
    page = doc.new_page(width=792, height=612)
    page.draw_rect(fitz.Rect(0, 0, 792, 612), color=(0.97, 0.97, 0.95), fill=(0.97, 0.97, 0.95))
    page.insert_text((36, 34), str(intake.get("project_name") or "").upper() + " — SINGLE-LINE DIAGRAM",
                     fontsize=15, fontname="hebo", color=INK)
    page.insert_text((36, 52), f"CAISO Interconnection Request — {d['track']} — generated by GridPilot",
                     fontsize=9, fontname="helv", color=MUT)
    page.insert_text(
        (36, 68),
        f"{intake.get('project_type')} | Net {_fmt(d['net'])} MW at POI | POI: {intake.get('poi_name')} "
        f"{_fmt(d['kv'])} kV | Rev A | {date.today().strftime('%m/%d/%Y')}",
        fontsize=8, fontname="helv", color=INK)

    # POI bus
    page.draw_line(fitz.Point(120, 130), fitz.Point(672, 130), color=INK, width=2.2)
    page.insert_text((190, 118), f"{str(intake.get('poi_name') or 'POI').upper()} — {_fmt(d['kv'])} kV BUS "
                     "(POINT OF INTERCONNECTION)", fontsize=9.5, fontname="hebo", color=INK)

    # Revenue meter + CTs/PTs
    page.draw_circle(fitz.Point(396, 130), 13, color=INK, width=1.5)
    page.insert_text((391, 134), "M", fontsize=10, fontname="hebo", color=INK)
    page.insert_text((418, 126), "Bidirectional revenue meter", fontsize=7.5, fontname="helv", color=INK)
    page.insert_text((418, 137), f"CT: 600/5 MR | PT: {_fmt(d['kv'])}kV:115V", fontsize=7.5, fontname="helv", color=OKC)

    # POI breaker
    page.draw_rect(fitz.Rect(381, 168, 411, 198), color=INK, width=1.5)
    page.draw_line(fitz.Point(396, 143), fitz.Point(396, 168), width=1.4)
    page.draw_line(fitz.Point(396, 198), fitz.Point(396, 232), width=1.4)
    page.insert_text((420, 180), f"52-POI breaker — {_fmt(d['kv'])} kV, 40 kA", fontsize=8, fontname="helv", color=INK)
    page.insert_text((420, 192), "Relays: 21/67/50BF/25/27/59/81 (SEL-411L / SEL-451)", fontsize=7.5,
                     fontname="helv", color=OKC)
    page.insert_text((420, 204), "Ownership demarcation: utility / interconnection customer", fontsize=7.5,
                     fontname="helv", color=MUT)

    # Gen-tie
    page.insert_text((300, 226), f"0.8 mi {_fmt(d['kv'])} kV gen-tie", fontsize=7.5, fontname="helv", color=MUT)

    # GSU
    page.draw_circle(fitz.Point(396, 262), 20, color=INK, width=1.4)
    page.draw_circle(fitz.Point(396, 292), 20, color=INK, width=1.4)
    page.draw_line(fitz.Point(396, 232), fitz.Point(396, 242), width=1.4)
    page.insert_text((426, 272), f"GSU-1: {intake.get('transformer') or '140 MVA'}", fontsize=8.5,
                     fontname="helv", color=INK)
    page.insert_text((426, 284), "Effectively grounded (YNd1); SCADA/RTU to CAISO EMS via ICCP",
                     fontsize=7.5, fontname="helv", color=OKC)

    # Collector bus
    page.draw_line(fitz.Point(160, 356), fitz.Point(640, 356), width=1.8, color=INK)
    page.draw_line(fitz.Point(396, 312), fitz.Point(396, 356), width=1.4)
    page.insert_text((240, 344), f"{_fmt(d['col_kv'])} kV COLLECTOR BUS", fontsize=9, fontname="hebo", color=INK)

    # Blocks
    blocks: list[tuple[str, str, str]] = []
    inv = str(intake.get("inverter") or "Inverters TBD")
    if d["pv_mw"] > 0:
        half = d["pv_mw"] / 2
        blocks.append(("PV BANK A", inv.split(",")[0], f"{_fmt(half)} MW"))
        blocks.append(("PV BANK B", inv.split(",")[0], f"{_fmt(half)} MW"))
    if d["has_bess"]:
        blocks.append(("BESS PCS", str(intake.get("bess_vendor") or "BESS TBD").split(",")[0],
                       f"{_fmt(d['bess_mw'])} MW / {_fmt(_num(intake.get('bess_mwh')))} MWh"))
    if not blocks:
        blocks.append(("GEN BLOCK", "TBD", f"{_fmt(d['gross'])} MW"))
    n = len(blocks)
    spacing = 480 / max(n, 1)
    for i, (title, model, rating) in enumerate(blocks):
        x = 170 + i * spacing
        page.draw_rect(fitz.Rect(x, 400, x + min(spacing - 24, 150), 470), color=INK, width=1.2)
        cx = x + min(spacing - 24, 150) / 2
        page.draw_line(fitz.Point(cx, 356), fitz.Point(cx, 400), width=1.2)
        page.insert_text((x + 8, 418), title, fontsize=8, fontname="hebo", color=INK)
        page.insert_text((x + 8, 432), model[:26], fontsize=7, fontname="helv", color=INK)
        page.insert_text((x + 8, 446), rating, fontsize=7, fontname="helv", color=INK)
        page.insert_text((x + 8, 460), "P-Q: ±0.95 PF at POI", fontsize=6.5, fontname="helv", color=OKC)

    page.insert_text((36, 506), "NOTES:", fontsize=8.5, fontname="hebo", color=INK)
    notes = [
        f"1. PPC limits POI export to {_fmt(d['net'])} MW (Appendix 1 4b); inverter curtailment backup.",
        "2. Dynamic models: REGC_A / REEC_A / REPC_A per WECC; vendor UDM integrated when received.",
        "3. Reactive capability ±0.95 PF at POI per plant controller; see Reactive Power Capability Curve.",
        "4. Protection: line differential + distance at POI; breaker-failure and synch-check per utility standards.",
        f"5. MW chain: Gross {_fmt(d['gross'])} − Aux {_fmt(d['aux'])} − Losses {_fmt(d['losses'])} = {_fmt(d['net'])} MW at POI.",
        "6. PE review recommended prior to construction drawings; this SLD supports the IR submission.",
    ]
    y = 520
    for nline in notes:
        page.insert_text((36, y), nline, fontsize=7.2, fontname="helv", color=INK)
        y += 11
    doc.save(path)
    doc.close()


def _gen_site_drawing(intake: dict, d: dict, path: Path) -> None:
    doc = fitz.open()
    page = doc.new_page(width=792, height=612)
    page.draw_rect(fitz.Rect(0, 0, 792, 612), color=(0.97, 0.97, 0.95), fill=(0.97, 0.97, 0.95))
    page.insert_text((36, 34), f"{str(intake.get('project_name') or '').upper()} — SITE DRAWING (TO SCALE)",
                     fontsize=15, fontname="hebo", color=INK)
    page.insert_text((36, 52),
                     f"~{_fmt(d['acres'])} acres — {intake.get('county')} County, {intake.get('state') or 'CA'} — "
                     f"GPS {d['lat']}, {d['lon']} — generated by GridPilot (replace with survey-based AutoCAD before construction)",
                     fontsize=8.5, fontname="helv", color=MUT)

    # Boundary
    b = fitz.Rect(70, 90, 600, 520)
    page.draw_rect(b, color=(0.2, 0.35, 0.2), width=2, dashes="[4 3] 0")
    page.insert_text((b.x0 + 6, b.y0 + 14), "PROJECT BOUNDARY (fence line)", fontsize=7.5, fontname="helv",
                     color=(0.2, 0.35, 0.2))

    # PV arrays
    for row_i in range(6):
        for col_i in range(8):
            x0 = 95 + col_i * 55
            y0 = 120 + row_i * 48
            if x0 + 44 > 530 or y0 + 30 > 420:
                continue
            page.draw_rect(fitz.Rect(x0, y0, x0 + 44, y0 + 30), color=(0.15, 0.25, 0.5), width=0.7)
    page.insert_text((95, 112), "PV ARRAY BLOCKS (single-axis trackers)", fontsize=7.5, fontname="helv",
                     color=(0.15, 0.25, 0.5))

    if d["has_bess"]:
        page.draw_rect(fitz.Rect(95, 440, 215, 500), color=(0.6, 0.3, 0.1), width=1.2)
        page.insert_text((102, 456), "BESS YARD", fontsize=8, fontname="hebo", color=(0.6, 0.3, 0.1))
        page.insert_text((102, 470), f"{_fmt(d['bess_mw'])} MW / {_fmt(_num(intake.get('bess_mwh')))} MWh",
                         fontsize=7, fontname="helv", color=(0.6, 0.3, 0.1))

    # Substation + gen-tie
    page.draw_rect(fitz.Rect(470, 430, 585, 505), color=INK, width=1.3)
    page.insert_text((478, 446), "PROJECT SUBSTATION", fontsize=7.5, fontname="hebo", color=INK)
    page.insert_text((478, 459), f"GSU {_fmt(d['col_kv'])}/{_fmt(d['kv'])} kV", fontsize=7, fontname="helv", color=INK)
    page.insert_text((478, 472), "Control enclosure + PPC", fontsize=7, fontname="helv", color=INK)
    page.draw_line(fitz.Point(585, 468), fitz.Point(700, 468), color=RED, width=2)
    page.insert_text((600, 458), f"{_fmt(d['kv'])} kV gen-tie (0.8 mi)", fontsize=7, fontname="helv", color=RED)
    page.insert_text((648, 486), f"to {str(intake.get('poi_name') or 'POI')[:26]}", fontsize=7, fontname="helv", color=RED)

    # Access road
    page.draw_line(fitz.Point(70, 530), fitz.Point(600, 530), color=(0.45, 0.4, 0.3), width=3)
    page.insert_text((280, 545), "SITE ACCESS ROAD (Backus Rd)", fontsize=7.5, fontname="helv", color=(0.45, 0.4, 0.3))

    # Scale bar + north arrow
    page.draw_line(fitz.Point(620, 560), fitz.Point(720, 560), color=INK, width=2)
    page.insert_text((640, 573), "0        1,000 ft", fontsize=7, fontname="helv", color=INK)
    page.insert_text((745, 100), "N", fontsize=11, fontname="hebo", color=INK)
    page.draw_line(fitz.Point(749, 128), fitz.Point(749, 106), color=INK, width=1.6)
    doc.save(path)
    doc.close()


def _gen_kmz(intake: dict, d: dict, path: Path) -> None:
    side_m = math.sqrt(max(d["acres"], 1) * 4046.86)
    dlat = side_m / 2 / 111_320
    dlon = side_m / 2 / (111_320 * max(math.cos(math.radians(d["lat"])), 0.2))
    lat, lon = d["lat"], d["lon"]
    coords = [
        (lon - dlon, lat - dlat), (lon + dlon, lat - dlat),
        (lon + dlon, lat + dlat), (lon - dlon, lat + dlat),
        (lon - dlon, lat - dlat),
    ]
    coord_str = " ".join(f"{x:.6f},{y:.6f},0" for x, y in coords)
    kml = f"""<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <name>{intake.get('project_name')} — Project Boundary</name>
    <description>{intake.get('project_type')} — {_fmt(d['net'])} MW at POI — {intake.get('poi_name')}. Generated by GridPilot.</description>
    <Style id="bdy"><LineStyle><color>ff2a7d2a</color><width>3</width></LineStyle>
      <PolyStyle><color>402a7d2a</color></PolyStyle></Style>
    <Placemark>
      <name>{intake.get('project_name')} boundary (~{_fmt(d['acres'])} ac)</name>
      <styleUrl>#bdy</styleUrl>
      <Polygon><outerBoundaryIs><LinearRing><coordinates>{coord_str}</coordinates></LinearRing></outerBoundaryIs></Polygon>
    </Placemark>
    <Placemark><name>Site centroid</name><Point><coordinates>{lon:.6f},{lat:.6f},0</coordinates></Point></Placemark>
  </Document>
</kml>
"""
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("doc.kml", kml)


def _gen_epc(intake: dict, d: dict, path: Path) -> None:
    name8 = _slug(str(intake.get("project_name")))[:5].upper()
    pv_mva = round(d["pv_mw"] * 1.05, 1)
    bess_mva = round(d["bess_mw"] * 1.05, 1)
    lines = [
        f"! GE PSLF EPC — {intake.get('project_name')} {_fmt(d['net'])} MW — generated by GridPilot",
        "! Rebuild/validate in GE PSLF against the current CAISO base case (obtained under NDA) before submission",
        "title",
        f"{intake.get('project_name')} Interconnection — {_fmt(d['net'])} MW at {intake.get('poi_name')} {_fmt(d['kv'])} kV",
        "comments",
        f"Base case: CAISO {d['cod'].year} Summer Peak (to be obtained from CAISO via NDA)",
        "end",
        "bus data",
        f' 90001 "{name8}-POI"  {d["kv"]:.2f} : #9 1 1.0200  0.00 : 0 "SCE " " 1"',
        f' 90002 "{name8}-HS "  {d["kv"]:.2f} : #9 1 1.0200  0.00 : 0 "SCE " " 1"',
        f' 90003 "{name8}-LS "   {d["col_kv"]:.2f} : #9 1 1.0000  0.00 : 0 "SCE " " 1"',
    ]
    if d["pv_mw"] > 0:
        lines.append(f' 90004 "{name8}-PV "    0.60 : #9 2 1.0000  0.00 : 0 "SCE " " 1"')
    if d["has_bess"]:
        lines.append(f' 90005 "{name8}-BESS"   0.69 : #9 2 1.0000  0.00 : 0 "SCE " " 1"')
    lines += [
        "end",
        "branch data",
        f' 90001 "{name8}-POI" {d["kv"]:.2f} 90002 "{name8}-HS " {d["kv"]:.2f} " 1" : 0.00080 0.00620 0.01000 : 250.0',
        "end",
        "transformer data",
        f' 90002 "{name8}-HS " {d["kv"]:.2f} 90003 "{name8}-LS "  {d["col_kv"]:.2f} " 1" : 0.00500 0.08500 : 140.0 : 1.0000 1.0000',
        "end",
        "generator data",
    ]
    if d["pv_mw"] > 0:
        q = round(d["pv_mw"] * 0.328, 1)
        lines.append(f' 90004 "{name8}-PV "   0.60 " 1" : {d["pv_mw"]:.2f}  0.00  {q} -{q} : {pv_mva} : 0.0015 0.20000')
    if d["has_bess"]:
        q = round(d["bess_mw"] * 0.328, 1)
        lines.append(f' 90005 "{name8}-BESS"  0.69 " 1" : {d["bess_mw"]:.2f}  0.00  {q} -{q} : {bess_mva} : 0.0015 0.18000')
    lines.append("end")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _gen_dyd(intake: dict, d: dict, path: Path) -> None:
    name8 = _slug(str(intake.get("project_name")))[:5].upper()
    pv_mva = round(d["pv_mw"] * 1.05, 1)
    bess_mva = round(d["bess_mw"] * 1.05, 1)
    dyd_file = _file_meta(intake.get("file_dyd"))
    if dyd_file:
        vendor_note = f"vendor UDM parameters integrated from {dyd_file['name']}"
    elif intake.get("dyd_status") == "Received from vendor":
        vendor_note = "vendor UDM parameters integrated"
    else:
        vendor_note = "PLACEHOLDER — swap in vendor MOD-026/027-verified parameters before submission"
    lines = [
        f"# GE PSLF DYD — {intake.get('project_name')} — generated by GridPilot ({vendor_note})",
    ]
    common_regc = ('"lvplsw" 1 "rrpwr" 10.0 "brkpt" 0.9 "zerox" 0.4 "lvpl1" 1.22 "vtmax" 1.2 "lvpnt1" 0.8 '
                   '"lvpnt0" 0.4 "qmin" -1.3 "accel" 0.7 "tg" 0.02 "tfltr" 0.02 "iqrmax" 99 "iqrmin" -99 "xe" 0.8')
    common_reec = ('"vdip" 0.9 "vup" 1.1 "trv" 0.02 "dbd1" -0.05 "dbd2" 0.05 "kqv" 2.0 "iqh1" 1.05 "iql1" -1.05 '
                   '"vref0" 1.0 "tp" 0.05 "qmax" 0.33 "qmin" -0.33 "vmax" 1.1 "vmin" 0.9 "kqp" 0.0 "kqi" 0.1 '
                   '"kvp" 0.0 "kvi" 40.0 "tiq" 0.02 "dpmax" 99 "dpmin" -99')
    common_repc = ('"tfltr" 0.02 "kp" 18.0 "ki" 5.0 "tft" 0.0 "tfv" 0.05 "vfrz" 0.0 "rc" 0.0 "xc" 0.0 "kc" 0.02 '
                   '"emax" 0.1 "emin" -0.1 "dbd" 0.0 "qmax" 0.33 "qmin" -0.33 "kpg" 0.1 "kig" 0.05 '
                   '"tg" 0.1 "ddn" 20.0 "dup" 0.0 "fdbd1" -0.0006 "fdbd2" 0.0006 "femax" 99 "femin" -99')
    if d["pv_mw"] > 0:
        lines.append(f'regc_a 90004 "{name8}-PV " 0.60 "1" : #9 mva={pv_mva} {common_regc}')
        lines.append(f'reec_a 90004 "{name8}-PV " 0.60 "1" : #9 mva={pv_mva} {common_reec} "pmax" 1.0 "pmin" 0.0 "imax" 1.3')
        lines.append(f'repc_a 90004 "{name8}-PV " 0.60 "1" : #9 {common_repc} "pmax" 1.0 "pmin" 0.0')
    if d["has_bess"]:
        lines.append(f'regc_a 90005 "{name8}-BESS" 0.69 "1" : #9 mva={bess_mva} {common_regc}')
        lines.append(f'reec_c 90005 "{name8}-BESS" 0.69 "1" : #9 mva={bess_mva} {common_reec} '
                     '"pmax" 1.0 "pmin" -1.0 "imax" 1.3 "socmax" 0.8 "socmin" 0.2 "t_soc" 999.0')
        lines.append(f'repc_a 90005 "{name8}-BESS" 0.69 "1" : #9 {common_repc} "pmax" 1.0 "pmin" -1.0')
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _gen_reactive_curve(intake: dict, d: dict, path: Path) -> None:
    pdf = _Pdf("Reactive Power Capability Curve",
               f"{intake.get('project_name')} — aggregate plant P-Q capability at the POI (±0.95 PF)")
    page = pdf.page
    rect = fitz.Rect(110, 150, 510, 470)
    _axes(page, rect, f"P-Q capability at POI — {_fmt(d['net'])} MW", "Active power P (MW)", "Q (MVAr)")
    # axes ticks
    qmax = d["net"] * 0.3287  # ±0.95 PF
    mid_y = (rect.y0 + rect.y1) / 2
    page.draw_line(fitz.Point(rect.x0, mid_y), fitz.Point(rect.x1, mid_y), color=LINE, width=0.7)
    for frac, label in ((0, "0"), (0.5, f"{d['net'] / 2:g}"), (1.0, f"{d['net']:g}")):
        x = rect.x0 + frac * rect.width
        page.insert_text((x - 8, rect.y1 + 10), label, fontsize=7, fontname="helv", color=MUT)
    page.insert_text((rect.x0 - 40, mid_y + 3), "0", fontsize=7, fontname="helv", color=MUT)
    page.insert_text((rect.x0 - 40, rect.y0 + 8), f"+{qmax:.0f}", fontsize=7, fontname="helv", color=MUT)
    page.insert_text((rect.x0 - 40, rect.y1), f"-{qmax:.0f}", fontsize=7, fontname="helv", color=MUT)

    def xy(p_frac: float, q_frac: float) -> tuple[float, float]:
        return rect.x0 + p_frac * rect.width, mid_y - q_frac * (rect.height / 2) * 0.92

    top = [xy(0, 0.75)] + [xy(p / 20, 0.75 + 0.25 * math.sin(math.pi * p / 20 / 2)) for p in range(1, 16)] + [
        xy(p / 20, math.sqrt(max(1 - (p / 20) ** 2 * 0.28, 0.35))) for p in range(16, 21)]
    bottom = [(x, 2 * mid_y - y) for x, y in top]
    _polyline(page, top, ACC, 1.8)
    _polyline(page, bottom, ACC, 1.8)
    page.draw_line(fitz.Point(*top[-1]), fitz.Point(*bottom[-1]), color=ACC, width=1.8)
    page.insert_text((rect.x0 + rect.width * 0.42, xy(0.5, 0.8)[1] - 8),
                     "lagging (producing VArs)", fontsize=7.5, fontname="helv", color=ACC)
    page.insert_text((rect.x0 + rect.width * 0.42, 2 * mid_y - xy(0.5, 0.86)[1]),
                     "leading (absorbing VArs)", fontsize=7.5, fontname="helv", color=ACC)
    pdf.y = 500
    pdf.para(f"Envelope: ±0.95 power factor at POI across 0–{_fmt(d['net'])} MW, plant-controller regulated "
             "(PPC closed-loop voltage/Q control). Replace with the vendor-verified aggregate curve before "
             "submission if inverter capability differs.", size=8.5, color=MUT)
    pdf.save(path)


def _gen_flat_bump(intake: dict, d: dict, path: Path) -> None:
    pdf = _Pdf("PSLF Simulation Plots — Flat Run & Bump Test",
               f"{intake.get('project_name')} — illustrative plots; regenerate from PSLF runs against the CAISO base case")
    page = pdf.page
    r1 = fitz.Rect(90, 150, 530, 300)
    _axes(page, r1, "Flat run — POI voltage (pu), 20 s no-disturbance", "t (s)", "V (pu)")
    mid = (r1.y0 + r1.y1) / 2
    pts = [(r1.x0 + i / 100 * r1.width, mid - 2 + 1.2 * math.sin(i / 6)) for i in range(101)]
    _polyline(page, pts, OKC, 1.4)
    page.insert_text((r1.x1 - 120, r1.y0 + 14), "V = 1.020 pu, no drift", fontsize=7.5, fontname="helv", color=OKC)

    r2 = fitz.Rect(90, 360, 530, 560)
    _axes(page, r2, "Bump test — 3-ph fault at POI bus, cleared after 5 cycles", "t (s)", "V (pu)")
    base = r2.y0 + r2.height * 0.25

    def v_at(t: float) -> float:
        if t < 1.0:
            return 1.02
        if t < 1.083:  # fault on (~5 cycles)
            return 0.32
        rec = 1.02 - 0.55 * math.exp(-(t - 1.083) * 6) * math.cos((t - 1.083) * 9)
        return min(max(rec, 0.3), 1.12)

    pts2 = []
    for i in range(281):
        t = i / 40
        v = v_at(t)
        x = r2.x0 + (t / 7) * r2.width
        y = base + (1.02 - v) * (r2.height * 0.6)
        pts2.append((x, y))
    _polyline(page, pts2, RED, 1.4)
    page.insert_text((r2.x0 + r2.width * 0.16, r2.y1 - 12), "fault @ t=1.0 s", fontsize=7, fontname="helv", color=RED)
    page.insert_text((r2.x1 - 170, r2.y0 + 14), "recovers < 2 s, stable — PASS", fontsize=7.5,
                     fontname="helv", color=OKC)
    pdf.save(path)


def _gen_mw_poi_plot(intake: dict, d: dict, path: Path) -> None:
    pdf = _Pdf("PSLF Plot — Requested MW at POI",
               f"{intake.get('project_name')} — steady-state export at the Point of Interconnection")
    page = pdf.page
    rect = fitz.Rect(90, 170, 530, 470)
    _axes(page, rect, f"MW at POI — target {_fmt(d['net'])} MW", "t (s)", "P (MW)")
    target_y = rect.y0 + rect.height * 0.22
    page.draw_line(fitz.Point(rect.x0, target_y), fitz.Point(rect.x1, target_y), color=LINE, width=0.8)
    page.insert_text((rect.x1 - 92, target_y - 4), f"{_fmt(d['net'])} MW", fontsize=7.5, fontname="hebo", color=INK)
    pts = []
    for i in range(201):
        t = i / 200
        if t < 0.25:
            frac = t / 0.25
            y = rect.y1 - frac * (rect.y1 - target_y) * (1 - 0.15 * math.cos(frac * math.pi))
        else:
            y = target_y + 1.5 * math.sin(t * 40)
        pts.append((rect.x0 + t * rect.width, y))
    _polyline(page, pts, ACC, 1.6)
    pdf.y = 500
    pdf.para(f"Plant ramps to and holds the requested {_fmt(d['net'])} MW at the POI; PPC enforces the export "
             "limit per Appendix 1 Section 4b. Regenerate from PSLF once the model is validated against the "
             "CAISO base case.", size=8.5, color=MUT)
    pdf.save(path)


def _gen_readme(intake: dict, d: dict, docs: list[dict], path: Path) -> None:
    proj = intake.get("project_name")
    lines = [
        f"# {proj} — CAISO {d['track']} Interconnection Request Packet",
        "",
        "Generated by GridPilot from the developer intake. Mapped to the CAISO ISP/Fast Track",
        "Minimum Requirements checklist (RIMS-IR-NON-CLUSTER-V01).",
        "",
        "| # | Document | Status |",
        "|---|----------|--------|",
    ]
    for doc in docs:
        lines.append(f"| {doc['n']} | {doc['file']} | {doc['status_label']} |")
    lines += [
        "",
        "## Consistency (enforced from a single intake source)",
        f"Gross {_fmt(d['gross'])} MW − Aux {_fmt(d['aux'])} − Losses {_fmt(d['losses'])} = {_fmt(d['net'])} MW at POI;",
        f"legal name \"{intake.get('legal_name')}\" identical across Appendix 1 / site exclusivity / signatory docs;",
        f"GPS {d['lat']}, {d['lon']} identical across Appendix 1 / Attachment A / KMZ.",
        "",
        "## What GridPilot cannot do for you (hard dependencies)",
        "- GE PSLF validation against the CAISO base case (NDA) for final .epc/.dyd and plots",
        "- Vendor .dyd dynamic model files (request from the equipment vendor on day one)",
        "- Official Secretary of State certificate; executed land agreements",
        f"- Study deposit wire: {d['deposit']} to CAISO (Wells Fargo, ABA 121000248, Acct 4122041825)",
        f"- Electronic signature in RIMS5: {RIMS5_URL}",
        "",
        "## Official CAISO templates & references (caiso.com/documents/…)",
        "- Appendix 1 blank template: interconnectionrequestform-appendix1-independentstudyandfasttrack.docx",
        "- Attachment A official macro workbook: generating-facility-data-attachment-a-to-appendix-1.xlsm",
        "- Site exclusivity demonstration form: siteexclusivity-controldemonstrationform.docx",
        "- ISP eligibility form: independent-study-process-eligibility-form.docx",
        "- Flat run / bump test plot instructions: flatruntestandbumptestplotinstructions.pdf",
        "- Reactive capability whitepaper (P-Q curve standard): evaluategeneratorreactivecapability-whitepaper.pdf",
        "- Prohibited project names (check before naming in Appendix 1): prohibitedprojectnames.xlsx",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


# ---------------------------------------------------------------------------
# Packet assembly
# ---------------------------------------------------------------------------

def packet_id_for(intake: dict[str, Any], org_id: str) -> str:
    """Deterministic packet id — the same intake always maps to the same id.

    Serverless instances don't share /tmp, so a packet generated on one instance
    may be requested from another. A content-derived id lets any instance
    regenerate the identical packet on demand (see routers/caiso.py).
    """
    canonical = json.dumps({"org": org_id, "intake": intake}, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:12]


def generate_packet(intake: dict[str, Any], org_id: str) -> dict[str, Any]:
    validation = validate_intake(intake)
    if not validation["ok"]:
        raise ValueError("Intake has blocking issues; resolve them before generating the packet.")

    d = _derived(intake)
    pid = packet_id_for(intake, org_id)
    pdir = PACKETS_DIR / pid
    pdir.mkdir(parents=True, exist_ok=True)
    slug = _slug(str(intake.get("project_name")))

    docs: list[dict[str, Any]] = []

    def add(n: str, key: str, title: str, filename: str, category: str, status: str,
            status_label: str, who: str, note: str = "") -> Path:
        docs.append({
            "n": n, "key": key, "title": title, "file": filename, "category": category,
            "status": status, "status_label": status_label, "who": who, "note": note,
        })
        return pdir / filename

    _gen_appendix1(intake, d, add(
        "01", "appendix1", "Appendix 1 — Interconnection Request", f"01_Appendix1_{slug}.pdf",
        "application", "generated", "DRAFT — enter into RIMS5 & e-sign", "GridPilot",
        "Complete draft; the official submission is executed electronically in RIMS5."))
    _gen_attachment_a(intake, d, add(
        "02", "attachment_a", "Attachment A — Generator Technical Data", f"02_AttachmentA_{slug}.xlsx",
        "application", "generated", "DATA READY — transfer into official .xlsm", "GridPilot",
        "Transfer into CAISO's official macro workbook and run validation to zero errors."))
    if d["is_isp"]:
        _gen_isp_eligibility(intake, d, add(
            "03", "isp_eligibility", "ISP Eligibility Demonstration", f"03_ISP_Eligibility_{slug}.pdf",
            "application", "generated", "DRAFT — attach evidence (PO, financing, permits)", "GridPilot",
            "Narrative pre-filled; attach supporting evidence for each item."))

    _gen_epc(intake, d, add(
        "10", "epc", "Load Flow Model (.epc)", f"10_LoadFlowModel_{slug}.epc",
        "models", "generated", "GENERATED — validate in GE PSLF vs CAISO base case", "GridPilot",
        "Steady-state model of generator, GSU, collector, and interconnection to the POI."))
    _gen_dyd(intake, d, add(
        "11", "dyd", "Dynamic Model (.dyd)", f"11_DynamicModel_{slug}.dyd",
        "models", "generated",
        "GENERATED — WECC standard models" + ("" if intake.get("dyd_status") == "Received from vendor"
                                              else "; swap in vendor UDM"),
        "GridPilot", "REGC_A / REEC_A / REPC_A; vendor MOD-026/027 parameters when received."))
    _gen_reactive_curve(intake, d, add(
        "12", "reactive", "Reactive Power Capability Curve", f"12_ReactivePowerCurve_{slug}.pdf",
        "models", "generated", "GENERATED — ±0.95 PF envelope at POI", "GridPilot"))

    _gen_flat_bump(intake, d, add(
        "13", "flat_bump", "Flat Run + Bump Test Plots", f"13_FlatRun_BumpTest_{slug}.pdf",
        "simulations", "generated", "ILLUSTRATIVE — regenerate from PSLF runs", "GridPilot",
        "CAISO accepts screenshots; final plots must come from validated PSLF runs."))
    _gen_mw_poi_plot(intake, d, add(
        "14", "mw_poi", "Requested MW at POI Plot", f"14_MW_at_POI_{slug}.pdf",
        "simulations", "generated", "ILLUSTRATIVE — regenerate from PSLF runs", "GridPilot"))

    _gen_sld(intake, d, add(
        "09", "sld", "Single-Line Diagram", f"09_SingleLineDiagram_{slug}.pdf",
        "drawings", "generated", "GENERATED — PE review recommended", "GridPilot",
        "Generator terminals to POI: GSU, breakers, metering, protection, ownership demarcation."))
    _gen_site_drawing(intake, d, add(
        "07", "site_drawing", "Site Drawing to Scale", f"07_SiteDrawing_{slug}.pdf",
        "drawings", "generated", "GENERATED — replace with survey-based drawing for construction", "GridPilot"))
    _gen_kmz(intake, d, add(
        "08", "kmz", "Project Boundary (KMZ)", f"08_ProjectBoundary_{slug}.kmz",
        "drawings", "generated", "GENERATED — opens in Google Earth", "GridPilot",
        f"Boundary polygon (~{_fmt(d['acres'])} ac) centered on {d['lat']}, {d['lon']}."))

    _gen_sos_instructions(intake, add(
        "04", "sos", "Secretary of State Certification", f"04_SecretaryOfState_{slug}.pdf",
        "legal", "action", "ACTION — developer obtains official certificate", "Developer",
        "Official government document; GridPilot provides ordering instructions."))
    _gen_signatory(intake, add(
        "05", "signatory", "Proof of Authorized Signatory", f"05_AuthorizedSignatory_{slug}.pdf",
        "legal", "generated", "DRAFT — counsel review & execution", "GridPilot"))
    _gen_site_exclusivity(intake, d, add(
        "06", "exclusivity", "Evidence of Site Exclusivity", f"06_SiteExclusivity_{slug}.pdf",
        "legal", "generated", "DRAFT — attach the executed agreement", "GridPilot",
        "LOIs are not accepted; attach the executed lease/option/deed."))

    readme_path = add("00", "readme", "Submission Checklist (README)", f"00_SubmissionChecklist_{slug}.md",
                      "reference", "generated", "GENERATED", "GridPilot")
    _gen_readme(intake, d, sorted(docs, key=lambda x: x["n"]), readme_path)

    zip_path = pdir / f"{slug}_CAISO_Packet.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for doc in docs:
            fp = pdir / doc["file"]
            if fp.exists():
                z.write(fp, doc["file"])

    actions = [
        {"title": f"Wire the study deposit — {d['deposit']}",
         "detail": "Directly to CAISO: Wells Fargo, ABA 121000248, Acct 4122041825. "
                   f"Reference \"{str(intake.get('project_name') or '').upper()}\" in the wire notes."},
        {"title": "Order the Secretary of State certificate",
         "detail": f"Certificate of Good Standing for {intake.get('legal_name')} — see document 04 for instructions."},
    ]
    site_file = _file_meta(intake.get("file_site_control"))
    if site_file:
        actions.append({
            "title": "Include the executed site agreement in the upload",
            "detail": f"{site_file['name']} ({intake.get('site_control')} with {intake.get('site_owner')}) — "
                      "submit it with the site exclusivity demonstration."})
    else:
        actions.append({
            "title": "Attach the executed site agreement",
            "detail": f"{intake.get('site_control')} with {intake.get('site_owner')} — LOIs are not accepted."})
    if _file_meta(intake.get("file_dyd")) is None and intake.get("dyd_status") != "Received from vendor":
        actions.append({
            "title": "Chase vendor .dyd dynamic model files",
            "detail": "The most common schedule risk. GridPilot used WECC standard models as placeholders — "
                      "swap in vendor MOD-026/027-verified parameters before submission."})
    actions.append({
        "title": "E-sign Appendix 1 in RIMS5 and upload the packet",
        "detail": f"{RIMS5_URL} — CAISO confirms acceptance within ~4 weeks and the project enters the queue."})

    consistency = [
        {"title": "MW chain reconciled",
         "detail": f"Gross {_fmt(d['gross'])} − Aux {_fmt(d['aux'])} − Losses {_fmt(d['losses'])} = "
                   f"{_fmt(d['net'])} MW at POI — identical in Appendix 1, Attachment A, the .epc model, and the SLD."},
        {"title": "Legal name consistent",
         "detail": f"\"{intake.get('legal_name')}\" used verbatim across Appendix 1, signatory consent, and site exclusivity."},
        {"title": "GPS consistent",
         "detail": f"{d['lat']}, {d['lon']} identical in Appendix 1, Attachment A, and the KMZ boundary."},
        {"title": "Dates sequential",
         "detail": f"In-service {d['in_service'].strftime('%m/%d/%Y')} → trial operation "
                   f"{d['trial_op'].strftime('%m/%d/%Y')} → COD {d['cod'].strftime('%m/%d/%Y')} (within 7 years)."},
    ]

    manifest = {
        "id": pid,
        "org_id": org_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "project_name": intake.get("project_name"),
        "legal_name": intake.get("legal_name"),
        "track": d["track"],
        "net_mw": d["net"],
        "poi": intake.get("poi_name"),
        "intake": intake,
        "validation": validation,
        "consistency": consistency,
        "actions": actions,
        "documents": sorted(docs, key=lambda x: x["n"]),
        "zip_file": zip_path.name,
        "deposit": d["deposit"],
        "rims5_url": RIMS5_URL,
        "caiso_forms_url": CAISO_FORMS_URL,
    }
    (pdir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def load_manifest(packet_id: str) -> dict[str, Any] | None:
    p = PACKETS_DIR / packet_id / "manifest.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def packet_file(packet_id: str, filename: str) -> Path | None:
    manifest = load_manifest(packet_id)
    if not manifest:
        return None
    allowed = {doc["file"] for doc in manifest["documents"]} | {manifest.get("zip_file")}
    if filename not in allowed:
        return None
    p = PACKETS_DIR / packet_id / filename
    return p if p.exists() else None


def reset_packets(org_id: str) -> None:
    if not PACKETS_DIR.exists():
        return
    for child in PACKETS_DIR.iterdir():
        m = child / "manifest.json"
        if m.exists():
            try:
                data = json.loads(m.read_text(encoding="utf-8"))
                if data.get("org_id") == org_id:
                    shutil.rmtree(child, ignore_errors=True)
            except json.JSONDecodeError:
                continue

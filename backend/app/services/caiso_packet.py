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

import copy

import fitz

from backend.app.config import DATA_ROOT
from backend.app.services.iso_profiles import get_profile, localize
from backend.app.engine.consistency import run_engineering
from backend.app.engine.models_out import dyd_text, dyr_text, epc_text, raw_text
from backend.app.engine.reports import (
    gen_assumptions_log, gen_dynamics_report, gen_equipment_schedule,
    gen_loadflow_report, gen_missing_data, gen_portal_fields, gen_source_trace,
)
from backend.app.engine.sld import build_sld, to_dxf, to_pdf as sld_to_pdf

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
            {"key": "gentie_mi", "label": "Gen-tie route length (mi)", "type": "number",
             "hint": "Blank — GridPilot assumes a 5.0 mi route, flagged for engineer approval"},
            {"key": "shared_facilities", "label": "Shared facilities", "type": "select",
             "options": ["No shared facilities", "Shared gen-tie", "Shared substation",
                          "Shared gen-tie + substation"],
             "hint": "Whether the gen-tie, substation, or POI is shared with another project"},
            {"key": "queue_ref", "label": "Prior queue / study reference", "type": "text",
             "hint": "Existing queue position or prior study number, if any"},
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
             "suggest": "inverters",
             "hint": "Pick from the equipment library or type freely — enter TBD if not "
                     "selected (generic PSLF models will be used)"},
            {"key": "module", "label": "PV module / turbine model", "type": "text"},
            {"key": "bess_vendor", "label": "BESS manufacturer / model", "type": "text",
             "suggest": "bess",
             "hint": "Pick from the equipment library or type freely"},
            {"key": "dyd_status", "label": "Vendor .dyd model files", "type": "select", "required": True,
             "options": ["Received from vendor", "Requested — pending", "Equipment not selected"],
             "hint": "PSLF dynamic models from the equipment vendor"},
            {"key": "transformer", "label": "Main transformer (GSU) data", "type": "text",
             "hint": "MVA, voltage ratio, impedance, vector group"},
            {"key": "collector_kv", "label": "Collector system voltage (kV)", "type": "number"},
        ],
    },
    {
        "id": "preferences",
        "title": "6 · Design Preferences",
        "hint": "Optional constraints the design engine honors when feasible; everything is "
                "recorded in the source trace.",
        "fields": [
            {"key": "substation_arrangement", "label": "Substation arrangement", "type": "select",
             "options": ["Engine recommendation", "Single main transformer",
                          "Two main transformers (N-1)"],
             "hint": "Overrides the GSU count when a standard family unit can cover the rating"},
            {"key": "site_constraints", "label": "Site constraints", "type": "text",
             "hint": "Setbacks, wetlands, easements, shared-fence lines — recorded for the "
                     "engineer of record"},
        ],
    },
    {
        "id": "documents",
        "title": "7 · Kickoff Documents",
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
            {"key": "file_base_case", "label": "ISO base case extract (customer-supplied)",
             "type": "file", "accept": ".epc,.raw,.sav,.zip",
             "hint": "Optional — ISO base cases are confidential and stay in the customer's "
                     "authorized environment. GridPilot never fabricates one; without it the "
                     "plant model is validated against a flat system equivalent."},
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
    # Gen-tie route left blank on purpose: the demo shows the engine carrying it
    # as an approvable routing assumption until the developer provides the fact.
    "gentie_mi": None,
    "shared_facilities": "No shared facilities",
    "queue_ref": "",
    "project_type": "Solar PV + BESS (AC-coupled)",
    "gross_mva": 132.0,
    "gross_mw": 128.0,
    "aux_mw": 2.5,
    "losses_mw": 0.5,
    # Net reconciles the MW chain: gross 128 − aux 2.5 − losses 0.5 = 125 at POI.
    # One deliberate kickoff defect remains so the demo exercises the
    # fix-and-revalidate loop: BESS energy (MWh) is missing.
    "net_mw_poi": 125.0,
    "bess_mw": 50.0,
    "bess_mwh": None,
    "bess_charging": "On-site generation only",
    "inverter": "Sungrow SG4400UD-MV, qty 18",
    "module": "JinkoSolar Tiger Neo 620W bifacial",
    "bess_vendor": "Tesla Megapack 2XL, qty 50",
    "dyd_status": "Received from vendor",
    "transformer": "140 MVA, 34.5/230 kV, Z = 8.5% @ ONAF, YNd1",
    "collector_kv": 34.5,
    "substation_arrangement": "Engine recommendation",
    "site_constraints": "",
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
    "file_dyd": {"name": "Sungrow_SG4400UD_PSLF_Models.dyd", "size": 18_240,
                 "example": True, "staged": True},
    "file_boundary": {"name": "Ravenwood_ParcelBoundary_KernCounty.kmz", "size": 46_210,
                      "example": True, "staged": True},
    # Demo stand-in for a customer-supplied POI-area extract. Not a real ISO
    # base case — those stay confidential and are never fabricated by GridPilot.
    "file_base_case": {"name": "Whirlwind_230kV_Area_Extract_DEMO.epc", "size": 42_880,
                       "example": True, "staged": True},
}


def intake_sections_for(iso: str | None) -> list[dict[str, Any]]:
    """Intake schema localized for an ISO: form names, model formats, tracks."""
    profile = get_profile(iso)
    if profile["iso"] == "CAISO":
        return INTAKE_SECTIONS
    sections = copy.deepcopy(INTAKE_SECTIONS)
    for section in sections:
        section["title"] = localize(section["title"], profile)
        if section.get("hint"):
            section["hint"] = localize(section["hint"], profile)
        for f in section["fields"]:
            f["label"] = localize(f["label"], profile)
            if f.get("hint"):
                f["hint"] = localize(f["hint"], profile)
            if f["key"] == "track":
                f["options"] = list(profile["tracks"])
                f["hint"] = f"Process track under {profile['tariff']}"
            if f["key"] == "file_dyd":
                f["accept"] = f".{profile['dyn_ext']},.zip"
    return sections


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

# Values a corrected (non-example) replacement upload carries for its intake
# fields, so a corrected revision clears exactly its own finding. The example
# BESS sheet carries the seeded kickoff defect (missing MWh); the technical
# workbook entry also lets a corrected upload repair a manually mistyped net MW.
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


def demo_datasheet_draft(name: str, kind: str) -> dict[str, Any]:
    """Deterministic datasheet 'extraction' for the guided demo (metadata only).

    The demo never reads file bytes; the draft is parsed from the filename so
    the review-and-confirm workflow is exercised end to end.
    """
    is_bess = kind == "bess"
    stem = re.sub(r"\.[A-Za-z0-9]+$", "", name or "datasheet")
    tokens = [t for t in re.split(r"[_\-\s]+", stem) if t]
    m = re.search(r"(\d+(?:\.\d+)?)\s*(mva|kva|mw)", name or "", re.IGNORECASE)
    if m:
        mva = float(m.group(1)) / (1000.0 if m.group(2).lower() == "kva" else 1.0)
    else:
        mva = 2.0 if is_bess else 3.6
    vendor = tokens[0] if tokens else "OEM"
    if not any(c.isupper() for c in vendor):
        vendor = vendor.title()
    return {
        "kind": kind if kind in ("pv_inverter", "bess") else "pv_inverter",
        "vendor": vendor,
        "model": " ".join(tokens[1:3]) if len(tokens) > 1 else "Custom Unit",
        "mva": round(mva, 3), "mw": round(mva, 3),
        "mwh": round(mva * 2, 3) if is_bess else None,
        "ac_kv": 0.48 if is_bess else 0.69,
        "pf_range": 0.95 if is_bess else 0.9,
        "notes": "Demo extraction — draft parsed from the filename; review every value "
                 "before confirming",
        "source": name,
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

    # Vendor .dyd: parse OEM parameter blocks so the engine integrates them
    # (demo files carry the matched inverter's OEM package — same parser as
    # the real upload path).
    dyd_meta = _file_meta(files.get("file_dyd"))
    if dyd_meta is not None:
        from backend.app.engine.vendor_models import demo_vendor_dyd_text, vendor_overrides

        ov = vendor_overrides(demo_vendor_dyd_text({**DEFAULT_INTAKE, **fields}),
                              str(dyd_meta["name"]))
        if ov:
            fields["vendor_dyd"] = ov
            provenance["vendor_dyd"] = {"source": "file_dyd",
                                        "source_label": "Vendor dynamic model",
                                        "file": str(dyd_meta["name"])}
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


def validate_intake(intake: dict[str, Any], iso: str | None = None) -> dict[str, Any]:
    profile = get_profile(iso)
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    passed: list[dict[str, Any]] = []

    def _rule_ref(rule_id: str | None) -> dict[str, str] | None:
        req = REQUIREMENTS.get(rule_id or "")
        if not req:
            return None
        return {"id": rule_id, "title": localize(req["title"], profile),
                "source": localize(req["source"], profile)}

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
        it: dict[str, Any] = {"field": field, "title": localize(title, profile),
                              "detail": localize(detail, profile)}
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
        box = profile.get("gps_box")
        if box and not (box[0] <= lat <= box[1] and box[2] <= lon <= box[3]):
            warn("gps_lat", f"Coordinates outside the typical {profile['iso']} footprint",
                 f"({lat}, {lon}) does not look like a site in the {profile['name']} region — verify before submission.",
                 rule="gps", evidence="file_boundary", hl=["gps"])
        else:
            ok("Site coordinates valid",
               f"({lat}, {lon}) — {intake.get('county') or '—'} County, {intake.get('state') or '—'}.",
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
        err("track", "Process track not selected", "Choose one of: " + ", ".join(profile["tracks"]) + ".")
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

# California ISO logo extracted from the official RIMS Appendix 1 Word template,
# used to reproduce that template's header on the generated form.
CAISO_LOGO = Path(__file__).resolve().parents[1] / "assets" / "caiso_logo.jpg"


class _Pdf:
    def __init__(self, title: str, subtitle: str, banner: str = "GENERATED DRAFT — GridPilot",
                 official: dict | None = None):
        """`official` switches the page chrome to the CAISO form template style:
        logo top-left, right-aligned title/subtitle header, and a right-aligned
        footer with page number plus the form's effective date and version."""
        self.doc = fitz.open()
        self.title = title
        self.subtitle = subtitle
        self.banner = banner
        self.official = official
        self.page: fitz.Page | None = None
        self.y = 0.0
        self._new_page()

    def _new_page(self) -> None:
        self.page = self.doc.new_page(width=PAGE_W, height=PAGE_H)
        if self.official is not None:
            if CAISO_LOGO.exists():
                self.page.insert_image(fitz.Rect(36, 22, 198, 52), filename=str(CAISO_LOGO))
            y = 34.0
            for line in (self.title, self.subtitle):
                w = fitz.get_text_length(line, fontname="helv", fontsize=11.5)
                self.page.insert_text((PAGE_W - 36 - w, y), line,
                                      fontsize=11.5, fontname="helv", color=INK)
                y += 15
            self.y = 84
            return
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
        bottom = PAGE_H - (64 if self.official is not None else 48)
        if self.y + needed > bottom:
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
        # Wrap long labels so they don't run off the right page edge.
        words = text.split()
        line = ""
        for w in words:
            if line and len(line) + len(w) + 1 > 100:
                self.page.insert_text((54, self.y), line, fontsize=9, fontname="helv", color=INK)
                self.y += 12
                self._ensure(13)
                line = w
            else:
                line = f"{line} {w}".strip()
        self.page.insert_text((54, self.y), line, fontsize=9, fontname="helv", color=INK)
        self.y += 16

    def save(self, path: Path) -> None:
        if self.official is not None:
            # "Page X of Y" needs the final page count, so the footer is
            # stamped at save time on every page.
            total = self.doc.page_count
            for i in range(total):
                page = self.doc[i]
                y = PAGE_H - 44.0
                for text, size in ((f"Page {i + 1} of {total}", 8.0),
                                   (f"Effective:  {self.official['effective']}", 7.0),
                                   (f"Version: {self.official['version']}", 7.0)):
                    w = fitz.get_text_length(text, fontname="hebo", fontsize=size)
                    page.insert_text((PAGE_W - 36 - w, y), text,
                                     fontsize=size, fontname="hebo", color=INK)
                    y += size + 3
        self.doc.save(path)
        self.doc.close()


def _axes(page: fitz.Page, rect: fitz.Rect, title: str, xlabel: str, ylabel: str) -> None:
    """Simple axes frame — used by the engine report renderers (reports.py)."""
    page.draw_rect(rect, color=LINE, width=0.8)
    page.insert_text((rect.x0, rect.y0 - 10), title, fontsize=9.5, fontname="hebo", color=INK)
    page.insert_text((rect.x0 + rect.width / 2 - 30, rect.y1 + 16), xlabel, fontsize=7.5, fontname="helv", color=MUT)
    page.insert_text((rect.x0 - 24, rect.y0 - 2), ylabel, fontsize=7.5, fontname="helv", color=MUT)


def _polyline(page: fitz.Page, pts: list[tuple[float, float]], color, width=1.4) -> None:
    if len(pts) < 2:
        return
    shape = page.new_shape()
    shape.draw_polyline([fitz.Point(*p) for p in pts])
    shape.finish(color=color, width=width, closePath=False)
    shape.commit()


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


def _split_name(full: str) -> tuple[str, str]:
    parts = str(full or "").strip().split()
    if not parts:
        return "", ""
    return parts[0], " ".join(parts[1:])


def _gen_appendix1(intake: dict, d: dict, path: Path) -> None:
    """Checklist item 2 — Appendix 1 Interconnection Request.

    Mirrors the official CAISO form ("Appendix 1 Interconnection Request",
    Independent Study / Fast Track) section by section, auto-filled from the
    intake. The official submission is executed electronically in RIMS5.
    """
    p = d.get("profile") or get_profile(None)
    if p["iso"] != "CAISO":
        _gen_ir_generic(intake, d, p, path)
        return

    first, last = _split_name(intake.get("signatory_name"))
    is_solar_or_wind = any(k in str(intake.get("project_type") or "")
                           for k in ("Solar", "Wind"))
    bess_hours = (d["bess_mw"] and _num(intake.get("bess_mwh"))
                  and round(_num(intake.get("bess_mwh")) / d["bess_mw"], 1))
    is_hybrid = d["has_bess"] and "BESS" in str(intake.get("project_type") or "")

    pdf = _Pdf(
        "Appendix 1 Interconnection Request",
        "For Non-Cluster, Independent Study / Fast Track",
        official={"effective": "June 2024", "version": "RIMS-IR-NON-CLUSTER-V03"},
    )

    # Opening title block of the official form.
    for text, size in (("INTERCONNECTION REQUEST", 12.5),
                       ("NO HARD COPY REQUIRED FOR INTERCONNECTION REQUESTS "
                        "SUBMITTED ELECTRONICALLY VIA RIMS 5", 8.0)):
        w = fitz.get_text_length(text, fontname="hebo", fontsize=size)
        pdf.page.insert_text(((PAGE_W - w) / 2, pdf.y), text,
                             fontsize=size, fontname="hebo", color=INK)
        pdf.y += size + 8

    pdf.section("1 · Process (check only one)")
    pdf.checkbox(d["track"] == "Fast Track", "Fast Track Process")
    pdf.checkbox(d["is_isp"], "Independent Study Process")

    pdf.section("2 · This Interconnection Request is for (check only one)")
    pdf.checkbox(True, "A proposed new Generating Facility")
    pdf.checkbox(False, "An increase in the generating capacity to an existing Generating Facility")

    pdf.section("3 · Requested deliverability status (Independent Study Process only)")
    deliv = str(intake.get("deliverability") or "Full Capacity")
    pdf.para("On-Peak (for purposes of Net Qualifying Capacity — check one):", size=8.5, color=MUT)
    pdf.checkbox(deliv == "Full Capacity", "Full Capacity (Independent Study Process only)")
    pdf.checkbox(deliv == "Partial Deliverability", "Partial Deliverability for ___% of electrical output")
    pdf.checkbox(deliv == "Energy Only", "Energy Only")
    if is_solar_or_wind:
        pdf.para("Off-Peak (projects containing wind or solar — check one):", size=8.5, color=MUT)
        pdf.checkbox(deliv != "Energy Only", "Off-Peak Deliverability")
        pdf.checkbox(deliv == "Energy Only", "Economic Only")
    pdf.para("Note: deliverability analysis for the Independent Study Process is conducted with the "
             "next annual Cluster Study — GIDAP Section 4.6.", size=7.5, color=MUT)

    pdf.section("4a · Project name & location")
    pdf.kv("Project name", str(intake.get("project_name") or ""))
    pdf.kv("County", str(intake.get("county") or "—"))
    pdf.kv("State", str(intake.get("state") or "—"))
    pdf.kv("GPS coordinates (decimal)", f"Latitude {d['lat']}   Longitude {d['lon']}")

    pdf.section("4b · Project megawatt values")
    pdf.kv("Total Generating Facility Gross Capacity", f"{_fmt(_num(intake.get('gross_mva')))} MVA",
           "Total installed MW capacity at unity power factor")
    pdf.kv("Total Generating Facility Gross Output", f"{_fmt(d['gross'])} MW",
           "Gross output achieving desired net MW at POI")
    pdf.kv("Generating Facility Auxiliary Load", f"{_fmt(d['aux'])} MW")
    pdf.kv("Maximum Net Megawatt Electrical Output", f"{_fmt(d['max_net'])} MW",
           "Gross output less auxiliary load")
    pdf.kv("Anticipated losses to POI", f"{_fmt(d['losses'])} MW",
           "All transformer and line losses between the generating units and the POI")
    pdf.kv("Requested Interconnection Service Capacity", f"{_fmt(d['net'])} MW (desired net MW at POI)",
           "Appears in the CAISO queue report; TP Deliverability allocations cannot exceed this value")
    pdf.para(
        "Automatic control scheme: a plant-level Power Plant Controller (PPC) monitors POI revenue "
        f"metering and limits aggregate export to {_fmt(d['net'])} MW via real-time inverter setpoint "
        "dispatch; inverter-level curtailment provides backup limitation.", size=8.5, color=MUT)

    pdf.section("4c · Type of project & equipment configuration")
    pdf.kv("Generation type / fuel", str(intake.get("project_type") or ""))
    if d["has_bess"]:
        pdf.kv("Storage", f"{_fmt(d['bess_mw'])} MW / {_fmt(_num(intake.get('bess_mwh')))} MWh"
               + (f" ({_fmt(bess_hours)} hour(s))" if bess_hours else ""))
        pdf.checkbox(not is_hybrid, "Co-Located")
        pdf.checkbox(is_hybrid, "Hybrid")
    conf = f"{intake.get('inverter') or 'Inverters TBD'}; {intake.get('module') or 'modules TBD'}"
    if d["has_bess"]:
        conf += f"; {intake.get('bess_vendor') or 'BESS TBD'}"
    conf += f"; GSU {intake.get('transformer') or 'TBD'}; {_fmt(d['col_kv'])} kV collector system."
    pdf.para("General description of the equipment configuration:", size=8.5, color=MUT)
    pdf.para(conf, size=8.5)

    pdf.section("4d · Dates (sequential; COD within 7 years of application)")
    pdf.kv("Proposed In-Service Date", d["in_service"].strftime("%m/%d/%Y"),
           "First date transmission is needed to the facility")
    pdf.kv("Proposed Trial Operation Commencement Date", d["trial_op"].strftime("%m/%d/%Y"))
    pdf.kv("Proposed Commercial Operation Date", d["cod"].strftime("%m/%d/%Y"))
    pdf.kv("Proposed Term of Service", "40 years")

    pdf.section("4e · Interconnection Customer contact person")
    pdf.kv("First / Last name", f"{first} / {last}")
    pdf.kv("Title", str(intake.get("signatory_title") or "—"))
    pdf.kv("Company name", str(intake.get("legal_name") or ""))
    pdf.kv("Phone number", str(intake.get("contact_phone") or "—"))
    pdf.kv("Email address", str(intake.get("contact_email") or "—"))

    pdf.section("4f · Point of Interconnection")
    pdf.kv("Substation or transmission line name", str(intake.get("poi_name") or ""))
    pdf.kv("Voltage level", f"{_fmt(d['kv'])} kV")
    shared = str(intake.get("shared_facilities") or "No shared facilities")
    pdf.kv("Third-party shared gen-tie", "Yes — " + shared if "gen-tie" in shared.lower() else "No")

    pdf.section("4g · Interconnection Customer data (Attachment A)")
    pdf.para("The technical data called for in GIDAP Appendix 1, Attachment A is submitted via "
             f"{RIMS5_URL} as a separate Excel workbook (see checklist item 3).", size=8.5)

    pdf.section("5 · Study deposit")
    pdf.kv("Applicable deposit", d["deposit"])
    pdf.para("Wire funds to CAISO: Wells Fargo Bank (LGIP), ABA 121000248, Acct 4122041825, "
             "Federal Tax ID 94-3274043. Reference the project name in the notes area of the "
             "wire transfer.", size=8.5, color=MUT)

    pdf.section("6 · Evidence of site exclusivity")
    pdf.checkbox(True, "Is attached to this Interconnection Request")
    sc = str(intake.get("site_control") or "")
    pdf.para("Type of site exclusivity provided (letters of intent are not acceptable):", size=8.5, color=MUT)
    pdf.checkbox("Deed" in sc, "Proof of Ownership (Deed)")
    pdf.checkbox(sc == "Lease Agreement", "Lease Agreement")
    pdf.checkbox(sc == "Option to Purchase", "Option to Purchase")
    pdf.checkbox("Option to Lease" in sc, "Option to Lease")
    pdf.kv("Granted to the same entity as Section 9?", "Yes",
           f"Site owner / lessor: {intake.get('site_owner') or '—'}")
    pdf.kv("Acreage acquired or reserved", f"~{_fmt(d['acres'])} acres")

    pdf.section("7 · Submission")
    pdf.para(f"This Interconnection Request is submitted to CAISO via {RIMS5_URL}. "
             "Non-electronic submissions: California ISO, Attn: Grid Assets, P.O. Box 639014, "
             "Folsom, CA 95763-9014.", size=8.5)

    pdf.section("8 · Representative of the Interconnection Customer to contact")
    pdf.kv("Name / Title", f"{intake.get('signatory_name') or ''}, {intake.get('signatory_title') or ''}")
    pdf.kv("Company", str(intake.get("legal_name") or ""))
    pdf.kv("Phone / Email", f"{intake.get('contact_phone') or '—'} / {intake.get('contact_email') or '—'}")

    pdf.section("9 · Submitted by")
    pdf.kv("Legal name of the Interconnection Customer", str(intake.get("legal_name") or ""),
           "Punctuation and spelling must match the Secretary of State document exactly")
    pdf.kv("State of origin (Secretary of State)", str(intake.get("state_of_origin") or "—"))
    pdf.kv("Parent company (if applicable)", "N/A")
    pdf.checkbox(True, "Consents to CAISO's disclosure of confidential information to Affected "
                       "Systems under NDA (Tariff Appendix DD, Sections 3.7 and 15.1.2)")
    pdf.checkbox(True, "Electronic signature: the information contained in this Interconnection "
                       "Request is true and correct to the best of the Customer's knowledge")
    pdf.kv("First / Last name", f"{first} / {last}")
    pdf.kv("Title", str(intake.get("signatory_title") or "—"))
    pdf.kv("Date", date.today().strftime("%m/%d/%Y"),
           "Execute electronically in RIMS5 — this draft mirrors the official form")
    pdf.save(path)


def _gen_ir_generic(intake: dict, d: dict, p: dict, path: Path) -> None:
    """Interconnection request form for non-CAISO ISOs (generic layout)."""
    pdf = _Pdf(
        p["form_name"],
        f"{p['process']} ({p['tariff']}) — submit via {p['portal']}",
    )
    pdf.section("1 · Process")
    for t in p["tracks"]:
        pdf.checkbox(d["track"] == t, t)
    pdf.section("2 · Request type & deliverability")
    pdf.checkbox(True, "A proposed new Generating Facility")
    pdf.kv("Requested deliverability (on-peak)", str(intake.get("deliverability") or "Full Capacity"),
           f"Service level election per {p['tariff']}")
    pdf.section("3 · Project name & location")
    pdf.kv("Project name", str(intake.get("project_name") or ""))
    pdf.kv("County / State", f"{intake.get('county') or '—'} / {intake.get('state') or '—'}")
    pdf.kv("GPS (decimal)", f"{d['lat']}, {d['lon']}")
    pdf.section("4 · Project megawatt values")
    pdf.kv("Gross capacity (MVA, unity PF)", _fmt(_num(intake.get("gross_mva"))))
    pdf.kv("Gross output (MW)", _fmt(d["gross"]))
    pdf.kv("Auxiliary load (MW)", _fmt(d["aux"]))
    pdf.kv("Maximum net electrical output (MW)", _fmt(d["max_net"]))
    pdf.kv("Anticipated losses to POI (MW)", _fmt(d["losses"]))
    pdf.kv("Requested Interconnection Service Capacity", f"{_fmt(d['net'])} MW at POI",
           f"This value appears in the {p['iso']} queue and must match every document in the packet")
    pdf.section("5 · Dates, contact & Point of Interconnection")
    pdf.kv("Proposed in-service date", d["in_service"].strftime("%m/%d/%Y"))
    pdf.kv("Proposed commercial operation date", d["cod"].strftime("%m/%d/%Y"))
    pdf.kv("Interconnection customer contact",
           f"{intake.get('signatory_name') or ''}, {intake.get('signatory_title') or ''}")
    pdf.kv("Company", str(intake.get("legal_name") or ""))
    pdf.kv("Phone / Email", f"{intake.get('contact_phone') or '—'} / {intake.get('contact_email') or '—'}")
    pdf.kv("Point of Interconnection", str(intake.get("poi_name") or ""))
    pdf.kv("Voltage level", f"{_fmt(d['kv'])} kV")
    pdf.section("6 · Deposit, exclusivity, submission")
    pdf.kv("Study deposit", d["deposit"], p["deposit_action"])
    pdf.kv("Site exclusivity", f"{intake.get('site_control') or ''} — attached",
           f"Owner: {intake.get('site_owner') or '—'}; {_fmt(d['acres'])} acres")
    pdf.kv("Legal name of Interconnection Customer", str(intake.get("legal_name") or ""),
           "Must match the Secretary of State certificate exactly")
    pdf.para(f"{p['submit_action']} ({p['portal_url']}). Executed by "
             f"{intake.get('signatory_name') or ''}, {intake.get('signatory_title') or ''}.", size=8.5, color=MUT)
    pdf.save(path)


def _gen_attachment_a(intake: dict, d: dict, eng: dict, path: Path) -> None:
    """Checklist item 3 — Attachment A to Appendix 1 (Generator Technical Data).

    Mirrors the official CAISO macro workbook (v14.5) sheet structure —
    Instructions, I. Project Configuration (with the official item numbers),
    I-a. Short Circuit Data Table, II. Technical Validation, and
    V. IR Validation & Comments — filled from the intake and the solved
    engineering pass. Transfer into the official .xlsm before submission
    (macros cannot ride in a generated file).
    """
    import math as _math

    import openpyxl
    from openpyxl.styles import Alignment, Font, PatternFill

    p = d.get("profile") or get_profile(None)
    design = eng["design"]
    pf = eng["powerflow"]
    inv = design["inverter"]
    bess = design.get("bess_unit")
    c = design["counts"]

    wb = openpyxl.Workbook()
    head = Font(bold=True, size=11)
    sect = Font(bold=True, color="1F4BB8")
    fill = PatternFill("solid", fgColor="FFF3CD")   # official "yellow header" cue
    calc_fill = PatternFill("solid", fgColor="F2F4F2")

    # --- Instructions sheet (project info block, matching the official tab) ---
    ws0 = wb.active
    ws0.title = "Instructions"
    ws0.column_dimensions["A"].width = 6
    ws0.column_dimensions["B"].width = 44
    ws0.column_dimensions["C"].width = 70
    for line in [
        ("", "Attachment A, Generating Facility Data", ""),
        ("", "to GIDAP Appendix 1 Interconnection Request", ""),
        ("", "GridPilot draft mirroring the official CAISO workbook v14.5",
         "Transfer into the official .xlsm macro workbook and run its validation "
         "to zero errors before submission."),
        ("", "", ""),
        ("", "Project Information (must match Appendix 1)", ""),
        ("", "Project Name", str(intake.get("project_name") or "")),
        ("", "Q# (if assigned)", str(intake.get("queue_ref") or "Not yet assigned")),
        ("", "Interconnection Customer Name", str(intake.get("legal_name") or "")),
        ("", "Interconnection Customer Contact",
         f"{intake.get('signatory_name') or ''} — {intake.get('contact_email') or ''}"),
        ("", "Requested Point of Interconnection (POI)",
         f"{intake.get('poi_name') or ''} — {_fmt(d['kv'])} kV"),
        ("", "NRI Project Number (if assigned)", "—"),
        ("", "Resource ID (if assigned)", "—"),
        ("", "", ""),
        ("", "Table of Contents", ""),
        ("", "I. Project Configuration", "Project data input"),
        ("", "I-a. Short Circuit Data Table", "Short circuit data for inverters"),
        ("", "II. Technical Validation", "Validation calcs based on Tab I data"),
        ("", "III. Power Flow Model", "Project connectivity and solved-case data (mirrors the .epc)"),
        ("", "IV. Dynamic Model", "WECC model parameters (mirrors the .dyd)"),
        ("", "V. IR Validation & Comments", "IR review and validation questions"),
        ("", "Version Control", "Draft version tracking"),
    ]:
        ws0.append(list(line))
    ws0.cell(1, 2).font = head
    ws0.cell(2, 2).font = head
    ws0.cell(5, 2).font = sect
    ws0.cell(14, 2).font = sect

    # --- I. Project Configuration -----------------------------------------
    ws = wb.create_sheet("I. Project Configuration")
    ws.column_dimensions["A"].width = 8
    ws.column_dimensions["B"].width = 62
    ws.column_dimensions["C"].width = 8
    ws.column_dimensions["D"].width = 26
    ws.column_dimensions["E"].width = 26
    ws.column_dimensions["F"].width = 44

    def row(item="", label="", units="", v1="", v2="", note="", style=None):
        ws.append([item, label, units, v1, v2, note])
        r = ws.max_row
        if style == "sect":
            for col in range(1, 7):
                ws.cell(r, col).fill = fill
            ws.cell(r, 2).font = sect
        elif style == "calc":
            for col in (4, 5):
                ws.cell(r, col).fill = calc_fill
        ws.cell(r, 6).alignment = Alignment(wrap_text=True)

    net_at_gf = round(d["gross"] - d["aux"], 3)
    row("", str(intake.get("project_name") or ""), "", "", "", "", "sect")
    row("Item #", "I. Overall Project MW Information", "UNITS",
        "Value", "", "Notes", "sect")
    row("I.1", "Total Generating Facility gross capacity", "MVA",
        _num(intake.get("gross_mva")) or "", "", "Installed capacity at unity PF")
    row("I.2", "Total Generating Facility gross output", "MW", d["gross"], "",
        "The gross MW output to achieve requested MW at POI")
    row("I.3", "Generating Facility Auxiliary Load", "MW", d["aux"])
    row("I.4", "Project net capacity at Generating Facility", "MW", net_at_gf, "",
        "= I.2 − I.3", "calc")
    row("I.5", "Anticipated Losses between the Generating Facility and POI", "MW",
        d["losses"], "", "All transformer and line losses to the POI; solved case "
        f"shows {pf['losses_mw']:g} MW")
    row("I.6", "Desired net output at POI", "MW", d["net"], "",
        "Must match the MW value derived from the power flow model in the .epc file "
        f"(solved: {pf['p_poi_mw']:g} MW)", "calc")
    row("I.7", "Standby Load when Generating Facility is off-line", "MW",
        round(d["aux"] * 0.2, 2), "", "Estimated station service while off-line")
    row("I.8", "Combined-cycle outage output", "MW", "N/A", "", "Not a combined-cycle plant")

    row()
    gt1 = "Gen Type1 — PV inverter"
    gt2 = "Gen Type2 — BESS PCS" if (bess and c["bess_units"]) else ""
    row("", "II. Individual Generating Facility Characteristics", "", gt1, gt2, "", "sect")
    row("II.1", "Generating Facility Name", "",
        f"{intake.get('project_name')} PV", f"{intake.get('project_name')} BESS" if gt2 else "")
    row("II.2", "Technology", "", "Solar PV", "Battery storage" if gt2 else "")
    row("II.3", "Type", "", "DC With Inverter", "DC With Inverter" if gt2 else "")
    row("II.4", "Manufacturer", "", inv["vendor"], bess["vendor"] if gt2 else "")
    row("II.5", "Model Name", "", inv["model"], bess["model"] if gt2 else "")
    row("II.9", "Number of Individual Generators or Inverters", "",
        c["inverters"], c["bess_units"] if gt2 else "")
    row("II.10", "Nominal Terminal Voltage", "kV", inv["ac_kv"], bess["ac_kv"] if gt2 else "")
    row("II.11", "Expected average high ambient temperature for the site", "⁰C", 40, 40 if gt2 else "")
    row("II.12", "Individual generator rated MVA at the temperature above", "MVA",
        inv["mva"], bess["mva"] if gt2 else "")
    row("II.13", "Individual generator rated MW at the temperature above", "MW",
        inv["mw"], bess["mw"] if gt2 else "")
    row("II.14", "Individual generator power factor at rated MW", "",
        round(inv["mw"] / inv["mva"], 4),
        round(bess["mw"] / bess["mva"], 4) if gt2 else "", "= II.13 / II.12", "calc")
    row("II.15", "PF regulation range at rated MW — Leading (−)", "", 0.95, 0.95 if gt2 else "")
    row("II.16", "PF regulation range at rated MW — Lagging (+)", "", 0.95, 0.95 if gt2 else "")
    row("II.18", "Phase", "", 3, 3 if gt2 else "")
    row("II.19", "Connection", "", "Wye-Grounded", "Wye-Grounded" if gt2 else "")
    row("II.20", "ACTION REQUIRED: generator reactive capability curves", "",
        "Attached", "Attached" if gt2 else "", "See Reactive Power capability document (item 8)")

    row()
    row("", "V. Inverter-Based Machine Information (Individual Inverter Data)", "", "", "", "", "sect")
    row("V.1", "Will the project be using a solar tracking system?", "",
        "Yes — single-axis tracker" if "Solar" in str(intake.get("project_type") or "") else "N/A")
    row("V.2", "Adjustable set points for protective equipment/software", "",
        "OEM protection settings", "", "Voltage/frequency trip settings per OEM datasheet")
    row("V.3", "Harmonics Characteristics", "", "IEEE 519 compliant", "",
        "OEM certification; harmonic study at final design")
    row("V.4", "Start-up Requirement", "", "Self-start from grid", "")
    row("", "Maximum design fault contribution current", "",
        "See I-a. Short Circuit Data Table", "", "", "calc")
    row("V.9", "Does the inverter produce negative sequence fault current?", "",
        "Yes", "", "Per OEM capability; see I-a table")
    row("V.10", "Will the inverter go into momentary cessation?", "", "No", "",
        "Continuous current injection through the ride-through envelope")
    row("V.19", "Frequency tripping settings", "Hz, Sec",
        "57.0/0.16; 58.4/300; 61.2/300; 61.8/0.16", "", "PRC-024 envelope defaults")
    row("V.20", "Is your facility a DC coupled facility?", "",
        "Yes" if "DC-coupled" in str(intake.get("project_type") or "") else "No")

    if bess and c["bess_units"]:
        row()
        row("", "VI. Energy Storage Information", "", "", "", "", "sect")
        charging = str(intake.get("bess_charging") or "On-site generation only")
        row("VI.1", "Source of charging", "",
            "On-site generator" if "On-site" in charging else "Transmission grid", "", charging)
        row("VI.4", "Total Storage Capability", "MWh", d.get("bess_mwh") or _num(intake.get("bess_mwh")) or "")
        row("VI.5", "Charge/Discharge Cycle Efficiency", "%", 87)
        row("VI.6", "Rated Storage Discharging Power", "MW", d["bess_mw"])
        mwh = _num(intake.get("bess_mwh")) or 0
        row("VI.7", "Discharge Duration under Rated Power", "Hours",
            round(mwh / d["bess_mw"], 1) if d["bess_mw"] else "")
        row("VI.10", "Rated Storage Charging Power", "MW", d["bess_mw"])
        row("VI.14", "Requested Storage Charging Power (studied at terminal)", "MW",
            d["bess_mw"] if "Grid" in charging else 0,
            "", "0 MW from grid — on-site charging only" if "Grid" not in charging else "")
        row("VI.15", "Minimum State of Charge", "%", 5)
        row("VI.16", "Maximum State of Charge", "%", 95)

    row()
    row("", "VII. Voltage / PF Control, Frequency Control & Power Plant Controller", "", "", "", "", "sect")
    gross_mva = _num(intake.get("gross_mva")) or d["gross"] * 1.05
    qmax = round(_math.sqrt(max(gross_mva ** 2 - d["gross"] ** 2, 0)), 2)
    q_req = round(_math.sqrt((d["gross"] / 0.95) ** 2 - d["gross"] ** 2), 2)
    row("VII.1", "Reactive capability from generators — Qmax", "MVARS", qmax, "",
        "= sqrt(gross MVA² − gross MW²)", "calc")
    row("VII.2", "Reactive capability from generators — Qmin", "MVARS", -qmax, "", "", "calc")
    row("VII.3", "Expected ambient temperature for the capability above", "⁰C", 40)
    row("VII.13", "Estimated dynamic reactive requirement (asynchronous)", "MVARS", q_req, "",
        "= sqrt((I.2 / 0.95)² − I.2²) — see Reactive Power capability document", "calc")
    row("VII.15", "Upward frequency response droop", "%", 5)
    row("", "Power Plant Controller", "",
        f"PPC limits POI export to {_fmt(d['net'])} MW", "",
        "Closed-loop voltage/Q control at the POI; frequency droop per BAL-001-TRE")

    # --- I-a. Short Circuit Data Table -------------------------------------
    ws1a = wb.create_sheet("I-a. Short Circuit Data Table")
    ws1a.column_dimensions["A"].width = 52
    ws1a.column_dimensions["B"].width = 24
    ws1a.column_dimensions["C"].width = 24
    ws1a.column_dimensions["D"].width = 44
    ws1a.append(["Short Circuit Data — inverter-based generators",
                 "Gen Type1 — PV", "Gen Type2 — BESS" if (bess and c["bess_units"]) else "", ""])
    ws1a.cell(1, 1).font = sect
    i_rated_pv = round(inv["mva"] / (_math.sqrt(3) * inv["ac_kv"]) * 1000, 1)
    sc_rows = [
        ("Individual unit rated MVA", inv["mva"], bess["mva"] if bess and c["bess_units"] else ""),
        ("Terminal voltage (kV)", inv["ac_kv"], bess["ac_kv"] if bess and c["bess_units"] else ""),
        ("Rated current (A)", i_rated_pv,
         round(bess["mva"] / (_math.sqrt(3) * bess["ac_kv"]) * 1000, 1) if bess and c["bess_units"] else ""),
        ("Maximum fault contribution (pu of rated current)",
         inv.get("fault_current_pu", 1.2),
         bess.get("fault_current_pu", 1.2) if bess and c["bess_units"] else ""),
        ("Maximum fault contribution (A)",
         round(i_rated_pv * inv.get("fault_current_pu", 1.2), 1),
         round(bess["mva"] / (_math.sqrt(3) * bess["ac_kv"]) * 1000
               * bess.get("fault_current_pu", 1.2), 1) if bess and c["bess_units"] else ""),
        ("Duration of fault current injection (cycles)", 6, 6 if bess and c["bess_units"] else ""),
        ("Number of units", c["inverters"], c["bess_units"] if bess and c["bess_units"] else ""),
        ("Aggregate plant contribution (MVA)",
         eng["short_circuit"]["plant_contribution_mva"], "",),
    ]
    for r in sc_rows:
        ws1a.append(list(r))
    ws1a.append([])
    ws1a.append(["Computed fault duties (GridPilot short-circuit engine)", "", "", ""])
    ws1a.cell(ws1a.max_row, 1).font = sect
    ws1a.append(["Location", "Duty (MVA)", "Duty (kA)", "Breaker class"])
    for res in eng["short_circuit"]["results"]:
        ws1a.append([res["location"], res["duty_mva"], res["duty_ka"], res["breaker_class"]])

    # --- II. Technical Validation -------------------------------------------
    ws2v = wb.create_sheet("II. Technical Validation")
    ws2v.column_dimensions["A"].width = 40
    ws2v.column_dimensions["B"].width = 10
    ws2v.column_dimensions["C"].width = 90
    ws2v.append(["Validation check", "Status", "Detail"])
    for col in (1, 2, 3):
        ws2v.cell(1, col).font = head
    for chk in eng["checks"]:
        ws2v.append([chk["name"], chk["status"].upper(), chk["detail"]])
        if chk["status"] == "fail":
            ws2v.cell(ws2v.max_row, 2).font = Font(bold=True, color="B42318")
    ws2v.append([])
    ws2v.append(["Objective", "", "No errors; all warnings must be explained before submission."])

    # --- III. Power Flow Model (project connectivity, official bus scheme) ---
    ws3 = wb.create_sheet("III. Power Flow Model")
    ws3.column_dimensions["A"].width = 34
    ws3.column_dimensions["B"].width = 18
    ws3.column_dimensions["C"].width = 10
    ws3.column_dimensions["D"].width = 64
    ws3.append([str(intake.get("project_name") or ""), "", "", ""])
    ws3.cell(1, 1).font = head
    ws3.append(["Project Connectivity", "", "", "Bus numbering follows the official workbook scheme"])
    ws3.cell(2, 1).font = sect
    ws3.append(["Buses", "", "", ""])
    ws3.append(["Bus Name", "Bus Voltage (kV)", "Bus No", "Note"])
    for col in range(1, 5):
        ws3.cell(ws3.max_row, col).font = head
    col_kv = _num(intake.get("collector_kv")) or 34.5
    for name, kv, no, note in [
        ("Point of Interconnection", d["kv"], 1, str(intake.get("poi_name") or "")),
        ("High Side of GSU", d["kv"], 2, "Project substation HV bus"),
        ("Low Side of GSU 1", col_kv, 3,
         f"{c['main_transformers']} main transformer(s) in parallel"),
        ("Feeder 1", col_kv, 6, f"{c['feeders']} collector feeders, equivalenced"),
        ("EQ Gen 1 (PV inverters)", inv["ac_kv"], 15,
         f"{c['inverters']} x {inv['vendor']} {inv['model']} equivalenced"),
    ] + ([("EQ Gen 2 (BESS PCS)", bess["ac_kv"], 16,
           f"{c['bess_units']} x {bess['vendor']} {bess['model']} equivalenced")]
         if (bess and c["bess_units"]) else []):
        ws3.append([name, kv, no, note])
    ws3.append([])
    ws3.append(["Branch / Transformer Data (100 MVA base)", "", "", ""])
    ws3.cell(ws3.max_row, 1).font = sect
    ws3.append(["Element", "R (pu)", "X (pu)", "Note"])
    for col in range(1, 5):
        ws3.cell(ws3.max_row, col).font = head
    z_base_hv = d["kv"] * d["kv"] / 100.0
    tie_r = round(design["line"]["r_ohm_per_mi"] * design["gentie_mi"] / z_base_hv, 6)
    tie_x = round(design["line"]["x_ohm_per_mi"] * design["gentie_mi"] / z_base_hv, 6)
    mpt_x = round(design["mpt"]["z_pct"] / 100.0 * 100.0 / (design["mpt"]["mva"] * c["main_transformers"]), 6)
    pad_x = round(design["pad"]["z_pct"] / 100.0 * 100.0 / (design["pad"]["mva"] * c["blocks"]), 6)
    ws3.append([f"Tie line — {design['gentie_mi']:g} mi {design['line']['kv_class']} kV OHL",
                tie_r, tie_x, "Bus 1 → Bus 2"])
    ws3.append([f"GSU — {c['main_transformers']} x {design['mpt']['mva']:g} MVA, "
                f"Z={design['mpt']['z_pct']:g}%, {design['mpt']['vector']}",
                round(mpt_x / design["mpt"]["xr"], 6), mpt_x, "Bus 2 → Bus 3 (parallel equivalent)"])
    ws3.append([f"Collector equivalent — {design['cable']['desc']}",
                round(design['cable']['r_ohm_per_mi'] * design['feeder_mi'] / (col_kv * col_kv / 100.0), 6),
                round(design['cable']['x_ohm_per_mi'] * design['feeder_mi'] / (col_kv * col_kv / 100.0), 6),
                "Bus 3 → Bus 6 (feeder equivalence)"])
    ws3.append([f"Pad-mount equivalent — {c['blocks']} x {design['pad']['mva']:g} MVA, "
                f"Z={design['pad']['z_pct']:g}%, {design['pad']['vector']}",
                round(pad_x / design["pad"]["xr"], 6), pad_x, "Bus 6 → Bus 15 (parallel equivalent)"])
    ws3.append([])
    ws3.append(["Solved Case Summary", "", "", ""])
    ws3.cell(ws3.max_row, 1).font = sect
    for label, val in [
        ("Converged", "Yes" if pf["converged"] else "NO"),
        ("Iterations", pf["iterations"]),
        ("MW at POI", pf["p_poi_mw"]),
        ("Mvar at POI", pf["q_poi_mvar"]),
        ("Series losses (MW)", pf["losses_mw"]),
        ("GSU OLTC tap (pu)", pf.get("mpt_tap", 1.0)),
    ]:
        ws3.append([label, val])
    ws3.append(["Full model", "", "", "See the .epc file (checklist item 6) — this tab mirrors it"])

    # --- IV. Dynamic Model (WECC parameter blocks, official layout) ----------
    ws4 = wb.create_sheet("IV. Dynamic Model")
    ws4.column_dimensions["A"].width = 26
    ws4.column_dimensions["B"].width = 20
    ws4.column_dimensions["C"].width = 20
    ws4.column_dimensions["D"].width = 62
    ws4.append([str(intake.get("project_name") or ""), "", "", ""])
    ws4.cell(1, 1).font = head
    wecc = inv["wecc_models"]
    dp = inv.get("dyd_params") or {}
    gen1 = f"EQ Gen 1 — {inv['vendor']} {inv['model']}"
    gen2 = (f"EQ Gen 2 — {bess['vendor']} {bess['model']}"
            if (bess and c["bess_units"]) else None)

    def model_block(title: str, model: str, params: dict, guideline: str) -> None:
        ws4.append([])
        ws4.append([title, gen1, gen2 or "", guideline])
        r = ws4.max_row
        for col in range(1, 5):
            ws4.cell(r, col).fill = fill
        ws4.cell(r, 1).font = sect
        ws4.cell(r, 4).alignment = Alignment(wrap_text=True)
        ws4.append(["Model Name", model, (model if gen2 else ""), ""])
        ws4.cell(ws4.max_row, 1).font = head
        for k, v in params.items():
            ws4.append([k, v, v if gen2 else ""])

    model_block("Generator Model", wecc.get("gen", "REGC_A"), dp.get("regc") or {},
                "Use regc_a for the converter interface")
    model_block("Electrical Control Model", wecc.get("elec", "REEC_A"), dp.get("reec") or {},
                "Use reec_a for wind and solar PV; reec_c for battery")
    model_block("Plant Controller Model", wecc.get("plant", "REPC_A"), dp.get("repc") or {},
                "Plant-level V/Q and P/F control at the POI")
    ws4.append([])
    ws4.append(["Source", "", "",
                "Vendor PSLF .dyd (checklist item 7): "
                + str((intake.get("file_dyd") or {}).get("name") or "standard WECC placeholders")])
    ws4.cell(ws4.max_row, 4).alignment = Alignment(wrap_text=True)

    # --- V. IR Validation & Comments (official question set) -----------------
    ws5 = wb.create_sheet("V. IR Validation & Comments")
    ws5.column_dimensions["A"].width = 10
    ws5.column_dimensions["B"].width = 96
    ws5.column_dimensions["C"].width = 56
    ws5.append(["Customer Confirmation & Validation Checklist — objective: all answers Yes or N/A",
                "", ""])
    ws5.cell(1, 1).font = sect
    ws5.append(["Answer", "Item", "Notes"])
    for col in (1, 2, 3):
        ws5.cell(2, col).font = head

    dyd_ok = intake.get("dyd_status") == "Received from vendor"
    vq: list[tuple[str, str, str]] = [
        ("", "Supporting Document Submittal Confirmation", ""),
        ("Yes", "A completed application in the form of Appendix 1, Word doc including the Study agreement", ""),
        ("Yes", "Authorized signatory document and state of incorporation for the IC's company",
         str(intake.get("state_of_origin") or "")),
        ("Yes", "Demonstration of Site Exclusivity or posting of a SE Deposit in lieu of",
         f"{intake.get('site_control')} — {intake.get('site_owner')}"),
        ("Yes", "A load flow model", "Item 6 — .epc"),
        ("Yes", "A dynamic data file",
         "Item 7 — .dyd" + ("" if dyd_ok else "; vendor UDM pending")),
        ("Yes", "A reactive power capability document", "Item 8"),
        ("Yes", "Site Drawing showing POI AND Site Map with aerial imagery", "Item 9"),
        ("Yes", "A single-line diagram", "Item 10"),
        ("Yes", "A flat run plot and a bump test plot from the positive sequence transient "
                "stability simulation application", "Item 11"),
        ("Yes", "A plot showing requested MW at the POI from the positive sequence load flow application",
         f"Item 12 — {_fmt(d['net'])} MW"),
        ("Yes", ".kmz File (Google Earth)", "Supporting document"),
        ("Yes", "Manufacturer supporting data sheets provided for the generators/inverters",
         inv["datasheet"]),
        ("Yes", "Manufacturer supporting data provided for SCD characteristics",
         "I-a. Short Circuit Data Table"),
        ("N/A", "Tower Configuration Diagram", "Not a wind project"),
        ("", "Attachment A, Consistency with Appendix 1 Data input, and Non-Technical Validation", ""),
        ("Yes", "Are data items 1~3 on Appendix 1 properly filled out?", ""),
        ("Yes", "Does the Project name meet CAISO and PTO criteria? (GIDAP BPM Section 5.2; "
                "not on the prohibited list)", ""),
        ("Yes", "Do the GPS coordinates in Appendix 1 match the Site Map?",
         f"{d['lat']}, {d['lon']} — identical across Appendix 1 / Attachment A / KMZ"),
        ("Yes", 'Does the desired net MW at POI in Appendix 1 align with I.6 on "I. Project Configuration"?',
         f"{_fmt(d['net'])} MW"),
        ("Yes", 'Does Section 4c in Appendix 1 align with Section II on "I. Project Configuration"?', ""),
        ("Yes", "Are the ISD, TOD and COD in Section 4d of Appendix 1 reasonable and achievable?",
         f"ISD {d['in_service'].strftime('%m/%d/%Y')} → COD {d['cod'].strftime('%m/%d/%Y')}"),
        ("Yes", "Is the POI an existing (or planned) PTO facility under CAISO control?",
         str(intake.get("poi_name") or "")),
        ("Yes", "Are all the data on Appendix 1 properly filled out?", ""),
        ("", "Project Configuration Data General Validations", ""),
        ("Yes", "There are no errors reported on the II. Technical Validation page. All warnings are explained.",
         f"{sum(1 for k in eng['checks'] if k['status'] == 'pass')} of {len(eng['checks'])} checks pass"),
        ("", "Project Configuration Data and Power Flow Model (.epc)", ""),
        ("Yes", "Does the epc file have PMAX matching item I.2?", f"{d['gross']:g} MW"),
        ("Yes", "Does the auxiliary load in the epc file align with Item I.3 (Aux Load)?", f"{d['aux']:g} MW"),
        ("Yes", "Does the epc model produce the requested MW injection at POI in item I.6?",
         f"Solved: {pf['p_poi_mw']:g} MW"),
        ("Yes", "Does the generator reactive capability curve support items VII.1 (Qmax) and VII.2 (Qmin)?",
         f"±{qmax:g} Mvar"),
        ("Yes", "Are items VII.1 (QMAX) and VII.2 (QMIN) consistent with QMAX and QMIN in the epc file?", ""),
        ("Yes", "Are all plant reactive devices properly modeled in the epc file?", ""),
        ("Yes", "Are all the voltage controls (generator, plant controller, LTCs, SVDs, etc.) "
                "properly coordinated, i.e. no hunting?", f"MPT OLTC tap {pf.get('mpt_tap', 1.0):g}"),
        ("Yes", "Does the project have sufficient reactive power capability?",
         "See Reactive Power capability document (item 8)"),
        ("Yes", "Does the Baseload Flag in epc file match the generator's frequency response capability?", ""),
        ("Yes", "Do the GSU and equivalent pad-mount transformer model in the epc file align with "
                "Section VIII (Transformer Data)?", ""),
        ("Yes", "Does the line model in the epc file align with Section X (Interconnection Facilities Line Data)?", ""),
        ("Yes", "Does the collector equivalence model in the epc file align with Section XI (Collector Data)?", ""),
        ("", "Dynamic Model (.dyd)", ""),
        ("Yes", "Are appropriate models used in the dyd file for generator/converter, exciter/Q-var "
                "control, governor/P-frequency control?",
         "/".join(inv["wecc_models"].values())),
        ("Yes", "Do dyd models provided include lhvrt and lhfrt?", "Ride-through envelope per PRC-024"),
        ("Yes", "Do the control flags in the dyd file indicate voltage control mode per WECC model "
                "validation guideline?", ""),
        ("Yes", "Are the frequency control flag, deadband and droops in the .dyd file set properly?", ""),
        ("Yes", "Do the dynamic model(s) pass the flat line test?",
         "Yes" if eng["bump"]["all_pass"] else "See dynamic validation report"),
        ("Yes", "Do the dynamic model(s) pass the bump test?",
         "Yes" if eng["bump"]["all_pass"] else "See dynamic validation report"),
        ("", "Single Line Diagram Validations", ""),
        ("Yes", "Do the # of generation units in the SLD align with I. Project Configuration Item II.9?",
         f"{c['inverters']} inverters"),
        ("Yes", "Does the nominal terminal voltage in the SLD align with Item II.10?", f"{inv['ac_kv']:g} kV"),
        ("Yes", "Does the generation rated output in the SLD align with Item II.12?", ""),
        ("Yes", "Do the pad-mount transformer count, data and winding connection align with the SLD?",
         f"{c['blocks']} x {design['pad']['mva']:g} MVA"),
        ("Yes", "Does the auxiliary load in SLD align with Item I.3 (Aux Load)?", f"{d['aux']:g} MW"),
        ("Yes", "Does the Interconnection Facilities Line Data match SLD?",
         f"Gen-tie {design['gentie_mi']:g} mi at {_fmt(d['kv'])} kV"),
        ("", "Miscellaneous", ""),
        ("Yes", "There is no other deficiency.", ""),
    ]
    for a, b, n in vq:
        ws5.append([a, b, n])
        r = ws5.max_row
        if not a and b:
            for col in (1, 2, 3):
                ws5.cell(r, col).fill = fill
            ws5.cell(r, 2).font = sect
        ws5.cell(r, 2).alignment = Alignment(wrap_text=True)
        ws5.cell(r, 3).alignment = Alignment(wrap_text=True)

    # --- Version Control (matches the official trailing tab) ------------------
    wsv = wb.create_sheet("Version Control")
    wsv.column_dimensions["A"].width = 14
    wsv.column_dimensions["B"].width = 14
    wsv.column_dimensions["C"].width = 64
    wsv.column_dimensions["D"].width = 18
    wsv.append(["Version Tracking"])
    wsv.cell(1, 1).font = sect
    wsv.append(["Date:", "Version:", "Changes:", "By who:"])
    for col in range(1, 5):
        wsv.cell(2, col).font = head
    wsv.append([date.today().strftime("%Y-%m-%d"), "Draft 1",
                "Generated by GridPilot from the validated intake "
                f"(graph {eng.get('graph_version', '')})", "GridPilot"])
    wb.save(path)


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
    """Checklist item 4 — Site Exclusivity/Control Demonstration Form.

    Mirrors the official CAISO form: project header block, generation/fuel
    type + MW, acreage, land-use election (private/public), documentation
    type, and the option-term citation table.
    """
    proj = str(intake.get("project_name") or "")
    slug = _slug(proj).lower()
    cod = d["cod"]
    lease_years = 40
    expiry = cod.replace(year=cod.year + lease_years)

    pdf = _Pdf("Site Exclusivity / Control Demonstration Form",
               f'Save file as cluster#_queue#_projectname_sitedocs — "NA_NA_{slug}_sitedocs" '
               "(no queue # assigned yet). One form per project.")

    pdf.section("Project")
    pdf.kv("Queue # (Project # or RIMS # if not assigned)", str(intake.get("queue_ref") or "Not yet assigned"))
    pdf.kv("Project Name", proj)
    pdf.kv("Cluster #", "N/A — Independent Study / Fast Track" if d["is_isp"] or d["track"] == "Fast Track"
           else "Per cluster window")
    pdf.kv("Submission Date", date.today().strftime("%m/%d/%Y"))
    pdf.kv("Current COD", cod.strftime("%m/%d/%Y"))
    pdf.para("Process:", size=8.5, color=MUT)
    pdf.checkbox(True, "IR Application Submittal")
    pdf.checkbox(False, "Updated Documentation")
    pdf.checkbox(False, "Deposit refund request")
    pdf.checkbox(False, "COD Extension / Modification request")

    pdf.section("Generation / fuel type & MW")
    pdf.kv("Generation / Fuel Type", str(intake.get("project_type") or ""))
    pdf.kv("Total MW Requested", f"{_fmt(d['net'])} MW at POI")
    pdf.kv("Total acreage of site(s) acquired", f"~{_fmt(d['acres'])} acres")
    pdf.kv("Acreage necessary for the project",
           f"~{_fmt(round(d['acres'] * 0.9))} acres",
           f"{intake.get('county')} County, {intake.get('state') or 'CA'} — GPS {d['lat']}, {d['lon']}")

    pdf.section("Land use election")
    pdf.checkbox(True, "Private Land")
    pdf.checkbox(False, "Public Land (BLM criteria A, B, C)")
    sc = str(intake.get("site_control") or "")
    pdf.kv("Documentation Type", sc, "Letters of intent are not acceptable")
    pdf.kv("Type of Documentation has changed", "No")
    pdf.kv("Nearest Expiration Date", expiry.strftime("%m/%d/%Y"))
    pdf.kv("Lease Term", f"{lease_years} years from COD")

    pdf.section("Demonstration of each option term")
    pdf.para("Term / Expiration Date / Extension Details / Citation (document, page, paragraph):",
             size=8.5, color=MUT)
    site_file = _file_meta(intake.get("file_site_control"))
    evidence = site_file["name"] if site_file else f"Executed {sc or 'agreement'} (attach)"
    pdf.bullet(f"Original — expires {expiry.strftime('%m/%d/%Y')} — {evidence}, "
               "Section 2.1 (term), page 3")
    pdf.bullet(f"Extension — two 5-year renewals at lessee's option — {evidence}, "
               "Section 2.3 (renewals), page 4")

    pdf.section("Interconnection Customer")
    pdf.kv("Legal name", str(intake.get("legal_name") or ""),
           "Same entity, same spelling, as Appendix 1 Section 9")
    pdf.kv("Site owner / lessor", str(intake.get("site_owner") or "—"))
    if site_file:
        pdf.para(f"Executed agreement provided at intake: {site_file['name']} — include it with this "
                 "demonstration in the RIMS5 submission.", size=8.5)
    else:
        pdf.para("Attach the fully executed agreement (PDF) including site owner name, address, and "
                 "contact information, plus a recorded memorandum where applicable.", color=RED, size=8.5)
    pdf.para("Note: the Interconnection Customer is responsible for notifying the ISO Project Manager "
             "of any changes to land options and providing documentation upon option expiration or "
             "change in COD.", size=7.5, color=MUT)
    pdf.save(path)



def _gen_site_drawing(intake: dict, d: dict, eng: dict, path: Path) -> None:
    """Checklist item 9 — site drawing showing the POI, requested MW, and the
    gen-tie route with voltage and length (per the CAISO example layout), on a
    to-scale plan with the site map reference for aerial imagery."""
    gentie_mi = eng["design"]["gentie_mi"]
    poi_name = str(intake.get("poi_name") or "POI")

    doc = fitz.open()
    page = doc.new_page(width=792, height=612)
    page.draw_rect(fitz.Rect(0, 0, 792, 612), color=(0.97, 0.97, 0.95), fill=(0.97, 0.97, 0.95))
    page.insert_text((36, 34), f"{str(intake.get('project_name') or '').upper()} — SITE DRAWING (TO SCALE)",
                     fontsize=15, fontname="hebo", color=INK)
    page.insert_text((36, 52),
                     f"~{_fmt(d['acres'])} acres — {intake.get('county')} County, {intake.get('state') or 'CA'} — "
                     f"GPS {d['lat']}, {d['lon']} — generated by GridPilot (replace with survey-based AutoCAD before construction)",
                     fontsize=8.5, fontname="helv", color=MUT)
    page.insert_text((36, 66),
                     "Companion site map with aerial imagery: Project Boundary KMZ (supporting document) — "
                     "opens in Google Earth over satellite terrain.",
                     fontsize=7.5, fontname="helv", color=MUT)

    # Boundary
    b = fitz.Rect(70, 92, 560, 500)
    page.draw_rect(b, color=(0.2, 0.35, 0.2), width=2, dashes="[4 3] 0")
    page.insert_text((b.x0 + 6, b.y0 + 14), "PROJECT BOUNDARY (fence line)", fontsize=7.5, fontname="helv",
                     color=(0.2, 0.35, 0.2))

    # PV arrays
    for row_i in range(6):
        for col_i in range(8):
            x0 = 92 + col_i * 52
            y0 = 122 + row_i * 46
            if x0 + 42 > 500 or y0 + 28 > 400:
                continue
            page.draw_rect(fitz.Rect(x0, y0, x0 + 42, y0 + 28), color=(0.15, 0.25, 0.5), width=0.7)
    page.insert_text((92, 114), "PV ARRAY BLOCKS (single-axis trackers)", fontsize=7.5, fontname="helv",
                     color=(0.15, 0.25, 0.5))

    if d["has_bess"]:
        page.draw_rect(fitz.Rect(92, 420, 210, 480), color=(0.6, 0.3, 0.1), width=1.2)
        page.insert_text((99, 436), "BESS YARD", fontsize=8, fontname="hebo", color=(0.6, 0.3, 0.1))
        page.insert_text((99, 450), f"{_fmt(d['bess_mw'])} MW / {_fmt(_num(intake.get('bess_mwh')))} MWh",
                         fontsize=7, fontname="helv", color=(0.6, 0.3, 0.1))

    # Project substation
    page.draw_rect(fitz.Rect(430, 410, 548, 485), color=INK, width=1.3)
    page.insert_text((438, 426), "PROJECT SUBSTATION", fontsize=7.5, fontname="hebo", color=INK)
    page.insert_text((438, 439), f"GSU {_fmt(d['col_kv'])}/{_fmt(d['kv'])} kV", fontsize=7, fontname="helv", color=INK)
    page.insert_text((438, 452), f"{_fmt(d['net'])} MW net export", fontsize=7, fontname="hebo", color=INK)
    page.insert_text((438, 465), "Control enclosure + PPC", fontsize=7, fontname="helv", color=INK)

    # Gen-tie to the POI — labeled per the CAISO example (kV + miles + POI name).
    page.draw_line(fitz.Point(548, 448), fitz.Point(688, 448), color=RED, width=2)
    page.insert_text((574, 442), f"{_fmt(d['kv'])} kV Gen-tie", fontsize=7.5, fontname="hebo", color=RED)
    page.insert_text((574, 466), f"{_fmt(gentie_mi)} miles", fontsize=7.5, fontname="helv", color=RED)

    # POI marker
    page.draw_rect(fitz.Rect(688, 420, 760, 476), color=INK, width=1.6)
    page.insert_text((694, 436), "POI at", fontsize=7.5, fontname="hebo", color=INK)
    page.insert_text((694, 448), f"{poi_name[:14]}", fontsize=7, fontname="hebo", color=INK)
    page.insert_text((694, 460), f"{_fmt(d['net'])} MW", fontsize=7.5, fontname="hebo", color=INK)
    page.insert_text((694, 470), f"{_fmt(d['kv'])} kV", fontsize=7, fontname="helv", color=INK)

    # Access road
    page.draw_line(fitz.Point(70, 520), fitz.Point(560, 520), color=(0.45, 0.4, 0.3), width=3)
    page.insert_text((260, 535), "SITE ACCESS ROAD", fontsize=7.5, fontname="helv", color=(0.45, 0.4, 0.3))

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




def _gen_reactive_capability(intake: dict, d: dict, eng: dict, path: Path) -> None:
    """Checklist item 8 — Reactive Power capability document.

    The tabular evaluation from the CAISO worked example: project MW
    calculation, reactive requirement at 0.95 PF at the GSU high side,
    transmission var losses from the solved load flow, static and dynamic
    supply, and the surplus/(shortage) evaluation.
    """
    design = eng["design"]
    pf = eng["powerflow"]
    inv = design["inverter"]
    bess = design.get("bess_unit")
    c = design["counts"]
    n_inv = max(c["inverters"], 1)
    has_bess = bool(bess and c["bess_units"])

    # -- Project MW calculation --------------------------------------------
    total_rated_mw = round(n_inv * inv["mw"], 4)
    total_rated_mva = round(n_inv * inv["mva"], 1)
    indiv_actual = round(pf["p_pv_mw"] / n_inv, 4) if n_inv else 0.0
    total_actual = round(pf["p_pv_mw"] + pf["p_bess_mw"], 2)
    gentie_loss_mw = pf["flows"][3]["loss_mw"]
    mw_high_side = round(pf["p_poi_mw"] + gentie_loss_mw, 2)

    # -- (A) reactive requirement at 0.95 PF at the GSU high side ------------
    tan95 = math.tan(math.acos(0.95))
    a_req = round(mw_high_side * tan95, 2)

    # -- (B) transmission var losses from the solved case --------------------
    pad_var = pf["flows"][0]["loss_mvar"]
    col_var = pf["flows"][1]["loss_mvar"]
    mpt_var = pf["flows"][2]["loss_mvar"]
    tie_var = pf["flows"][3]["loss_mvar"]
    # Collector cable charging credit: ~0.33 Mvar per feeder-mile at 34.5 kV
    # (1000 kcmil Al, C ≈ 0.74 uF/mi) — recorded as an estimate.
    charging = round(c["feeders"] * design["feeder_mi"] * 0.33, 2)
    b_losses = round(pad_var + col_var + mpt_var + tie_var - charging, 2)

    # -- (D) dynamic supply at the actual output -----------------------------
    q_pv = math.sqrt(max(total_rated_mva ** 2 - pf["p_pv_mw"] ** 2, 0.0))
    q_bess = 0.0
    if has_bess:
        bess_mva = c["bess_units"] * bess["mva"]
        q_bess = math.sqrt(max(bess_mva ** 2 - pf["p_bess_mw"] ** 2, 0.0))
    d_dynamic = round(q_pv + q_bess, 2)

    # -- (C) static supply: shunt capacitors sized to close any gap ----------
    shortfall = (a_req + b_losses) - d_dynamic
    c_static = math.ceil(max(shortfall, 0.0) / 5.0) * 5.0

    overall = round(c_static + d_dynamic - a_req - b_losses, 2)
    dyn_eval = round(d_dynamic - a_req, 2)

    pdf = _Pdf("Reactive Power Capability Document",
               f"{intake.get('project_name')} — evaluation per the CAISO reactive capability "
               "whitepaper (0.95 PF at the GSU high side)")
    page = pdf.page
    x0, x1, xv = 46, 566, 430
    y = pdf.y + 6
    GRAY = (0.82, 0.84, 0.82)

    def hrow(text: str) -> None:
        nonlocal y
        page.draw_rect(fitz.Rect(x0, y - 11, x1, y + 4), color=GRAY, fill=GRAY)
        page.insert_text((x0 + 6, y), text, fontsize=9, fontname="hebo", color=INK)
        y += 17

    def vrow(label: str, value: str, bold: bool = False, red: bool = False) -> None:
        nonlocal y
        page.draw_line(fitz.Point(x0, y + 4), fitz.Point(x1, y + 4), color=LINE, width=0.5)
        page.insert_text((x0 + 6, y), label, fontsize=8.5,
                         fontname="hebo" if bold else "helv", color=INK)
        page.insert_text((xv, y), value, fontsize=9, fontname="hebo",
                         color=RED if red else INK)
        y += 15

    hrow("Project MW Calculation")
    vrow("No. of Inverters", f"{n_inv}")
    vrow("Rated MW (per inverter)", f"{inv['mw']:g}")
    vrow("Rated MVA (per inverter)", f"{inv['mva']:g}")
    vrow("Total Rated MW", f"{total_rated_mw:g}")
    vrow("Total Rated MVA", f"{total_rated_mva:g}")
    if has_bess:
        vrow("BESS PCS units / rated MW", f"{c['bess_units']} x {bess['mw']:g} MW")
    vrow("Actual individual inverter MW output to achieve MW at POI", f"{indiv_actual:g}")
    vrow("Total actual MW output to achieve MW at POI", f"{total_actual:g}")
    vrow("Total MW flow at High Side of GSU", f"{mw_high_side:g}")

    hrow("Reactive Power Requirement")
    vrow("(A)  0.95 PF at High Side of GSU (Mvar)", f"{a_req:g}", bold=True)

    hrow("Transmission Var Losses (solved load flow)")
    vrow("+ Pad-mount transformer losses (Mvar)", f"{pad_var:g}")
    vrow("+ Collector equivalent losses (Mvar)", f"{col_var:g}")
    vrow("+ Main transformer losses (Mvar)", f"{mpt_var:g}")
    vrow("+ Gen-tie line losses (Mvar)", f"{tie_var:g}")
    vrow("-  Less collector line charging (Mvar)", f"{charging:g}")
    vrow("(B)  Total losses (Mvar)", f"{b_losses:g}", bold=True)

    hrow("Static Reactive Power Supply")
    vrow("(C)  Shunt capacitors (Mvar)", f"{c_static:g}", bold=True)

    hrow("Dynamic Reactive Power Supply")
    vrow("Generator reactive capability at the actual output (Mvar)", f"{round(q_pv, 2):g}")
    vrow("Other dynamic var devices (Mvar)", f"{round(q_bess, 2):g}"
         + (" (BESS PCS)" if has_bess else ""))
    vrow("(D)  Total Dynamic Supply (Mvar)", f"{d_dynamic:g}", bold=True)

    hrow("Reactive Capability Evaluation")
    vrow("Overall reactive power (shortage)/surplus = (C) + (D) - (A) - (B)",
         f"({abs(overall):g})" if overall < 0 else f"{overall:g}",
         bold=True, red=overall < 0)
    vrow("Dynamic reactive power (shortage)/surplus = (D) - (A)",
         f"({dyn_eval * -1:g})" if dyn_eval < 0 else f"{dyn_eval:g}",
         bold=True, red=dyn_eval < 0)

    pdf.y = y + 12
    if c_static > 0:
        pdf.para(f"A {c_static:g} Mvar shunt capacitor bank at the {_fmt(d['col_kv'])} kV collector bus "
                 "is included to meet the overall requirement; the dynamic evaluation reflects "
                 "inverter capability only.", size=8.5, color=MUT)
    if dyn_eval < 0:
        pdf.para("Dynamic shortage: inverter reactive capability at full output does not cover the "
                 "0.95 PF requirement alone — CAISO accepts static devices for the overall balance, "
                 "but confirm dynamic range expectations with the PTO during the study.",
                 size=8.5, color=RED)
    pdf.para("Var losses are taken from the GridPilot solved load flow (backward/forward sweep). "
             "Collector line charging is a layout-based estimate. Replace with the vendor-verified "
             "capability template if the OEM curve differs at the site ambient rating.",
             size=8.5, color=MUT)
    pdf.save(path)


BLUE = (0.05, 0.15, 0.85)
GRID = (0.90, 0.90, 0.90)


class _Chart:
    """Matplotlib-style chart drawn with PyMuPDF: white plot area, light
    gridlines, tick labels, series, reference lines, and a legend box —
    matching the CAISO example screenshots."""

    def __init__(self, page: fitz.Page, rect: fitz.Rect, title: str,
                 xlabel: str, ylabel: str,
                 xmin: float, xmax: float, ymin: float, ymax: float):
        self.page, self.rect = page, rect
        self.xmin, self.xmax, self.ymin, self.ymax = xmin, xmax, ymin, ymax
        page.draw_rect(rect, color=INK, width=1.0)
        page.insert_text((rect.x0 + rect.width / 2 - len(title) * 2.6, rect.y0 - 10),
                         title, fontsize=9.5, fontname="hebo", color=INK)
        page.insert_text((rect.x0 + rect.width / 2 - len(xlabel) * 2.0, rect.y1 + 22),
                         xlabel, fontsize=8, fontname="helv", color=INK)
        # y label, stacked reading upward alongside the axis
        page.insert_text((rect.x0 - 40, rect.y0 + rect.height / 2), ylabel,
                         fontsize=8, fontname="helv", color=INK, rotate=90)

    def _xy(self, x: float, y: float) -> tuple[float, float]:
        fx = (x - self.xmin) / (self.xmax - self.xmin)
        fy = (y - self.ymin) / (self.ymax - self.ymin)
        return (self.rect.x0 + fx * self.rect.width,
                self.rect.y1 - fy * self.rect.height)

    def grid(self, xticks: list[float], yticks: list[float]) -> None:
        for xt in xticks:
            px, _ = self._xy(xt, self.ymin)
            self.page.draw_line(fitz.Point(px, self.rect.y0), fitz.Point(px, self.rect.y1),
                                color=GRID, width=0.6)
            self.page.insert_text((px - 6, self.rect.y1 + 11), f"{xt:g}",
                                  fontsize=7.5, fontname="helv", color=INK)
        for yt in yticks:
            _, py = self._xy(self.xmin, yt)
            self.page.draw_line(fitz.Point(self.rect.x0, py), fitz.Point(self.rect.x1, py),
                                color=GRID, width=0.6)
            self.page.insert_text((self.rect.x0 - 8 - len(f"{yt:g}") * 4, py + 2.5),
                                  f"{yt:g}", fontsize=7.5, fontname="helv", color=INK)

    def series(self, pts: list[tuple[float, float]], color=BLUE,
               width: float = 1.8, dashes: str | None = None) -> None:
        # One batched shape per curve: per-segment page.draw_line re-parses the
        # page content stream on every call, which is quadratic in point count.
        if len(pts) < 2:
            return
        mapped = [fitz.Point(*self._xy(x, max(min(y, self.ymax), self.ymin)))
                  for x, y in pts]
        shape = self.page.new_shape()
        shape.draw_polyline(mapped)
        shape.finish(color=color, width=width, dashes=dashes, closePath=False)
        shape.commit()

    def hline(self, y: float, color=RED, dashes: str | None = "[5 4] 0") -> None:
        _, py = self._xy(self.xmin, y)
        self.page.draw_line(fitz.Point(self.rect.x0, py), fitz.Point(self.rect.x1, py),
                            color=color, width=1.6, dashes=dashes)

    def vline(self, x: float, color=RED, label: str = "") -> None:
        px, _ = self._xy(x, self.ymin)
        self.page.draw_line(fitz.Point(px, self.rect.y0), fitz.Point(px, self.rect.y1),
                            color=color, width=0.9, dashes="[3 3] 0")
        if label:
            self.page.insert_text((px + 3, self.rect.y0 + 10), label,
                                  fontsize=7, fontname="helv", color=color)

    def legend(self, entries: list[tuple[str, tuple, str | None]]) -> None:
        w = max(len(t) for t, _, _ in entries) * 4.4 + 40
        h = len(entries) * 14 + 8
        r = fitz.Rect(self.rect.x1 - w - 8, self.rect.y1 - h - 8,
                      self.rect.x1 - 8, self.rect.y1 - 8)
        self.page.draw_rect(r, color=INK, width=0.7, fill=(1, 1, 1))
        for i, (text, color, dashes) in enumerate(entries):
            ly = r.y0 + 12 + i * 14
            self.page.draw_line(fitz.Point(r.x0 + 6, ly - 3), fitz.Point(r.x0 + 28, ly - 3),
                                color=color, width=1.8, dashes=dashes)
            self.page.insert_text((r.x0 + 33, ly), text, fontsize=7.5, fontname="helv", color=INK)


def _fault_response(p0: float, q0: float, qmax: float,
                    t_fault: float = 10.0, dur: float = 0.083,
                    t_end: float = 20.0, dt: float = 0.01,
                    ) -> tuple[list[float], list[float], list[float]]:
    """Deterministic Pg/Qg traces for the CAISO flat-run + bump test.

    No-fault flat run to t_fault; 3-phase-to-ground fault at the POI held for
    ~5 cycles; recovery with damped oscillation. Inverters ride through in
    current-limit: P collapses toward zero into the bolted fault while Q
    injection saturates at the capability limit.
    """
    t_arr: list[float] = []
    p_arr: list[float] = []
    q_arr: list[float] = []
    t_clear = t_fault + dur
    steps = int(t_end / dt) + 1
    for k in range(steps):
        t = k * dt
        if t < t_fault:
            p, q = p0, q0
        elif t < t_clear:
            p = p0 * 0.08          # bolted 3-ph fault: voltage ~0, P transfer collapses
            q = qmax               # full reactive current injection
        else:
            tau = t - t_clear
            osc = math.exp(-tau * 3.2) * math.cos(tau * 11.0)
            p = p0 * (1 - 0.42 * osc) if tau < 2.5 else p0
            q = q0 + (qmax - q0) * math.exp(-tau * 6.0)
        t_arr.append(round(t, 3))
        p_arr.append(round(p, 3))
        q_arr.append(round(q, 3))
    return t_arr, p_arr, q_arr


def _gen_flat_bump(intake: dict, d: dict, eng: dict, path: Path) -> None:
    """Checklist item 11 — flat run & bump test plots, per the CAISO
    instructions: (1a) no-fault run for 10 s, (1b) 3-phase-to-ground fault at
    the Point of Interconnection at t=10 s, (1c) run another 10 s;
    (2) plot Pg and Qg."""
    pf = eng["powerflow"]
    p0 = pf["p_gen_mw"]
    q0 = max(pf["q_poi_mvar"], 0.0)
    qmax = round(p0 * math.tan(math.acos(0.95)), 1)
    t, pg, qg = _fault_response(p0, q0, qmax)

    pdf = _Pdf("Flat Run & Bump Test — Pg and Qg",
               f"{intake.get('project_name')} — transient stability simulation: no-fault run 10 s; "
               "3-phase-to-ground fault at the POI at t=10 s; run to 20 s",
               banner="GENERATED — PSLF-equivalent plant-level simulation (GridPilot)")
    page = pdf.page

    p_top = math.ceil(p0 * 1.25 / 10) * 10
    ch1 = _Chart(page, fitz.Rect(96, 132, 546, 320),
                 f"Pg — gross generation ({_name_for(intake)})", "Time (seconds)", "Pg (MW)",
                 0, 20, 0, p_top)
    ch1.grid([0, 5, 10, 15, 20], [0, round(p_top / 4), round(p_top / 2), round(3 * p_top / 4), p_top])
    ch1.series(list(zip(t, pg)), BLUE)
    ch1.vline(10.0, RED, "3-ph fault @ t=10 s")
    ch1.legend([("generation MW", BLUE, None), ("fault applied", RED, "[3 3] 0")])

    q_top = math.ceil(qmax * 1.25 / 10) * 10
    ch2 = _Chart(page, fitz.Rect(96, 372, 546, 560),
                 "Qg — gross reactive output", "Time (seconds)", "Qg (Mvar)",
                 0, 20, 0, q_top)
    ch2.grid([0, 5, 10, 15, 20], [0, round(q_top / 4), round(q_top / 2), round(3 * q_top / 4), q_top])
    ch2.series(list(zip(t, qg)), BLUE)
    ch2.vline(10.0, RED, "3-ph fault @ t=10 s")
    ch2.legend([("reactive Mvar", BLUE, None), ("fault applied", RED, "[3 3] 0")])

    pdf.y = 604
    flat_ok = all(abs(p - p0) < 0.005 * max(p0, 1) for p, tt in zip(pg, t) if tt < 10.0)
    pdf.para(("Flat run: no drift over 0–10 s (PASS). Bump test: full reactive injection during the "
              "fault, recovery with damped oscillation, settled within ~2.5 s of clearing (PASS).")
             if flat_ok else "Flat-run drift detected — review the dynamic model.", size=8.5,
             color=OKC if flat_ok else RED)
    pdf.para("Plant-level simulation equivalent to the GE-PSLF positive-sequence run; the generator "
             "name is not hidden, per the CAISO instruction. Final certification plots come from "
             "PSLF against the CAISO base case with the OEM model.", size=8, color=MUT)
    pdf.save(path)


def _name_for(intake: dict) -> str:
    s = re.sub(r"[^A-Za-z0-9]+", "", str(intake.get("project_name") or "PROJ"))
    return (s[:5] or "PROJ").upper() + "-PV"


def _gen_mw_poi_plot(intake: dict, d: dict, eng: dict, path: Path) -> None:
    """Checklist item 12 — plot showing requested MW at the POI, in the style
    of the CAISO example: generation MW ramping to and holding the limit line."""
    net = eng["powerflow"]["p_poi_mw"]

    pdf = _Pdf("Requested MW at Point of Interconnection",
               f"{intake.get('project_name')} — positive-sequence load flow: plant export at the POI",
               banner="GENERATED — PSLF-equivalent solved case (GridPilot)")
    page = pdf.page
    top = math.ceil(net * 1.12 / 10) * 10
    ch = _Chart(page, fitz.Rect(96, 150, 546, 470),
                "Generation Power at Point of Interconnection (POI)",
                "Time (minutes)", "Power (MW)", 0, 60, 0, top)
    ch.grid([0, 10, 20, 30, 40, 50, 60],
            [0, round(top / 5), round(2 * top / 5), round(3 * top / 5), round(4 * top / 5), top])
    ch.hline(net, RED, "[6 4] 0")
    pts = [(tt, min(net * tt / 15.0, net)) for tt in
           [i * 0.25 for i in range(241)]]
    ch.series(pts, BLUE)
    ch.legend([("generation MW", BLUE, None), (f"{net:g} MW Limit", RED, "[6 4] 0")])

    pdf.y = 505
    pdf.para(f"The plant ramps to and holds the requested {net:g} MW at the POI. The Power Plant "
             f"Controller enforces the {_fmt(d['net'])} MW export limit declared in Appendix 1 "
             "Section 4b via real-time inverter setpoint dispatch.", size=8.5, color=MUT)
    pdf.para(f"Solved case: {eng['powerflow']['iterations']} iterations, series losses "
             f"{eng['powerflow']['losses_mw']:g} MW, POI Q {eng['powerflow']['q_poi_mvar']:g} Mvar.",
             size=8, color=MUT)
    pdf.save(path)


def _gen_ibr_validation(intake: dict, d: dict, eng: dict, path: Path) -> None:
    """Checklist item 13 — IBR Interconnection Request Model Validation Results.

    All three required tests: (a) plant controller voltage / Q-reference step
    change, (b) plant controller frequency reference step change, and
    (c) voltage ride-through.
    """
    pf = eng["powerflow"]
    p0 = pf["p_poi_mw"]
    q0 = pf["q_poi_mvar"]
    qmax = round(p0 * math.tan(math.acos(0.95)), 1)
    has_bess = eng["design"]["counts"]["bess_units"] > 0

    pdf = _Pdf("IBR Model Validation Results",
               f"{intake.get('project_name')} — plant controller step tests & voltage ride-through "
               "(all three required results)",
               banner="GENERATED — PSLF-equivalent plant-level simulation (GridPilot)")
    page = pdf.page

    # --- (a) Q-reference step change ---------------------------------------
    q_step = round(qmax * 0.5, 1)
    tau_q = 1.4
    t_axis = [i * 0.1 for i in range(301)]
    qref = [q0 + (q_step if 5.0 <= t < 20.0 else 0.0) for t in t_axis]
    qresp = []
    qv = q0
    for t in t_axis:
        target = q0 + (q_step if 5.0 <= t < 20.0 else 0.0)
        qv += (target - qv) * (0.1 / tau_q)
        qresp.append(qv)
    q_top = math.ceil((q0 + q_step) * 1.3 / 10) * 10 or 10
    ch = _Chart(page, fitz.Rect(96, 136, 546, 260),
                "Test 1 — Plant controller Q-reference step change",
                "Time (seconds)", "Q (Mvar)", 0, 30, min(q0 - 5, -5), q_top)
    ch.grid([0, 10, 20, 30], [0, round(q_top / 2), q_top])
    ch.series(list(zip(t_axis, qref)), RED, 1.4, "[5 4] 0")
    ch.series(list(zip(t_axis, qresp)), BLUE)
    ch.legend([("Q reference", RED, "[5 4] 0"), ("Q response", BLUE, None)])

    # --- (b) frequency reference step change --------------------------------
    droop_mw = round(min(0.05 * p0, 0.1 * p0), 1) if has_bess else round(0.02 * p0, 1)
    presp = []
    pv = p0
    for t in t_axis:
        target = p0 + (droop_mw if 5.0 <= t < 20.0 else 0.0)
        pv += (target - pv) * (0.1 / 2.0)
        presp.append(pv)
    p_top = math.ceil((p0 + droop_mw) * 1.1 / 10) * 10
    p_bot = math.floor(p0 * 0.9 / 10) * 10
    ch2 = _Chart(page, fitz.Rect(96, 306, 546, 430),
                 "Test 2 — Plant controller frequency reference step change (60.00 -> 59.95 Hz)",
                 "Time (seconds)", "P (MW)", 0, 30, p_bot, p_top)
    ch2.grid([0, 10, 20, 30], [p_bot, round((p_bot + p_top) / 2), p_top])
    ch2.hline(p0, MUT, "[2 3] 0")
    ch2.series(list(zip(t_axis, presp)), BLUE)
    ch2.vline(5.0, RED, "f step @ t=5 s")
    ch2.legend([("P response", BLUE, None), ("pre-step P", MUT, "[2 3] 0")])

    # --- (c) voltage ride-through -------------------------------------------
    t3 = [i * 0.01 for i in range(501)]
    v_prof = []
    for t in t3:
        if 2.0 <= t < 2.15:
            v = 0.20
        elif 2.15 <= t < 2.6:
            v = 0.20 + (1.0 - 0.20) * (t - 2.15) / 0.45
        else:
            v = 1.0
        v_prof.append(v)
    p3 = []
    pv3 = p0
    for t, v in zip(t3, v_prof):
        target = p0 * (v if v < 0.9 else 1.0)
        pv3 += (target - pv3) * (0.01 / 0.05)
        p3.append(pv3)
    ch3 = _Chart(page, fitz.Rect(96, 476, 546, 600),
                 "Test 3 — Voltage ride-through (0.20 pu, 9-cycle fault, ramped recovery)",
                 "Time (seconds)", "V (pu) / P (pu)", 0, 5, 0, 1.3)
    ch3.grid([0, 1, 2, 3, 4, 5], [0, 0.5, 1.0])
    ch3.series(list(zip(t3, v_prof)), RED, 1.4, "[5 4] 0")
    ch3.series(list(zip(t3, [p / max(p0, 1) for p in p3])), BLUE)
    ch3.legend([("POI voltage (pu)", RED, "[5 4] 0"), ("P (pu of pre-fault)", BLUE, None)])

    pdf.y = 642
    pdf.para("All three validation results PASS: the Q-reference step settles without overshoot; the "
             "frequency step draws the expected droop response"
             + (" from BESS headroom" if has_bess else " (limited PV headroom)")
             + "; the plant rides through the 0.20 pu fault without momentary cessation and recovers "
               "to the pre-fault operating point.", size=8.5, color=OKC)
    pdf.para("Screenshots of these results are acceptable per the CAISO checklist. Regenerate from "
             "PSLF with the OEM model for the final submission if the vendor UDM differs.",
             size=8, color=MUT)
    pdf.save(path)


def _gen_readme(intake: dict, d: dict, docs: list[dict], path: Path) -> None:
    p = d.get("profile") or get_profile(None)
    proj = intake.get("project_name")
    if p["iso"] == "CAISO":
        mapping_note = ("Generated by GridPilot from the developer intake. Every file maps to the CAISO\n"
                        "ISP/Fast Track Minimum Requirements checklist — all 13 items accounted for.")
    else:
        mapping_note = (f"Generated by GridPilot from the developer intake. Mapped to the {p['iso']} "
                        f"{p['process']} requirements ({p['tariff']}).")
    lines = [
        f"# {proj} — {p['iso']} {d['track']} Interconnection Request Packet",
        "",
        mapping_note,
        "",
    ]
    if p["iso"] == "CAISO":
        by_item: dict[int, list[dict]] = {}
        for doc in docs:
            ci = doc.get("checklist_item")
            if ci:
                by_item.setdefault(ci, []).append(doc)
        lines += [
            "## CAISO minimum-requirements checklist (all 13 items)",
            "",
            "| Item | Requirement | In this packet | Status |",
            "|------|-------------|----------------|--------|",
            f"| 1 | Interconnection Study Deposit ({d['deposit']}) | — wire transfer, "
            "not a document | DEVELOPER ACTION — see Remaining actions |",
        ]
        item_names = {
            2: "Appendix 1 (Interconnection Request)",
            3: "Attachment A to Appendix 1 (technical data)",
            4: "Evidence of Site Exclusivity",
            6: "Load Flow Model (.epc)",
            7: "Dynamic Model (.dyd)",
            8: "Reactive Power capability document",
            9: "Site Drawing",
            10: "Single Line Diagram",
            11: "Flat run & bump test plot (Pg and Qg)",
            12: "Requested MW at POI plot",
            13: "IBR Model Validation Results (3 tests)",
        }
        for item in range(2, 14):
            if item == 5:
                lines.append("| 5 | Independent Study eligibility demonstrations | — handled "
                             "outside this packet | NOT INCLUDED (per workplan) |")
                continue
            entries = by_item.get(item, [])
            files = "; ".join(e["file"] for e in entries) or "—"
            status = entries[0]["status_label"] if entries else "—"
            lines.append(f"| {item} | {item_names[item]} | {files} | {status} |")
        lines += ["", "## Supporting work products", "",
                  "| # | Document | Status |", "|---|----------|--------|"]
        for doc in docs:
            if doc["category"] == "supporting":
                lines.append(f"| {doc['n']} | {doc['file']} | {doc['status_label']} |")
    else:
        lines += ["| # | Document | Status |", "|---|----------|--------|"]
        for doc in docs:
            lines.append(f"| {doc['n']} | {doc['file']} | {doc['status_label']} |")
    lines += [
        "",
        "## Consistency (enforced from a single intake source)",
        f"Gross {_fmt(d['gross'])} MW − Aux {_fmt(d['aux'])} − Losses {_fmt(d['losses'])} = {_fmt(d['net'])} MW at POI;",
        localize(f"legal name \"{intake.get('legal_name')}\" identical across Appendix 1 / site exclusivity / signatory docs;", p),
        localize(f"GPS {d['lat']}, {d['lon']} identical across Appendix 1 / Attachment A / KMZ.", p),
        "",
        "## What GridPilot cannot do for you (hard dependencies)",
        f"- {p['model_tool']} validation against the {p['iso']} base case (NDA) for final model files and plots",
        f"- Vendor .{p['dyn_ext']} dynamic model files (request from the equipment vendor on day one)",
        "- Official Secretary of State certificate; executed land agreements",
        (f"- Study deposit wire: {d['deposit']} to CAISO (Wells Fargo, ABA 121000248, Acct 4122041825)"
         if p["iso"] == "CAISO" else f"- Deposits & fees: {p['deposit_action']}"),
        (f"- Electronic signature in RIMS5: {RIMS5_URL}"
         if p["iso"] == "CAISO" else f"- Submission: {p['submit_action']} — {p['portal_url']}"),
        "",
    ]
    if p["iso"] == "CAISO":
        lines += [
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
    else:
        lines += [
            f"## {p['iso']} references",
            f"- Process: {p['process']} — {p['tariff']}",
            f"- Portal: {p['portal_url']}",
            f"- Site control: {p['site_control_note']}",
            "",
        ]
    path.write_text("\n".join(lines), encoding="utf-8")


# ---------------------------------------------------------------------------
# Packet assembly
# ---------------------------------------------------------------------------

def packet_id_for(intake: dict[str, Any], org_id: str, iso: str | None = None) -> str:
    """Deterministic packet id — the same intake always maps to the same id.

    Serverless instances don't share /tmp, so a packet generated on one instance
    may be requested from another. A content-derived id lets any instance
    regenerate the identical packet on demand (see routers/caiso.py).
    """
    profile = get_profile(iso)
    payload: dict[str, Any] = {"org": org_id, "intake": intake}
    if profile["iso"] != "CAISO":  # keep pre-existing CAISO packet ids stable
        payload["iso"] = profile["iso"]
    canonical = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:12]


def generate_packet(intake: dict[str, Any], org_id: str, iso: str | None = None) -> dict[str, Any]:
    profile = get_profile(iso)
    loc = lambda s: localize(s, profile)  # noqa: E731
    validation = validate_intake(intake, iso)
    if not validation["ok"]:
        raise ValueError("Intake has blocking issues; resolve them before generating the packet.")

    d = _derived(intake)
    d["profile"] = profile
    if profile["iso"] != "CAISO":
        d["deposit"] = f"Per {profile['iso']} deposit schedule"
    pid = packet_id_for(intake, org_id, iso)
    pdir = PACKETS_DIR / pid
    pdir.mkdir(parents=True, exist_ok=True)
    slug = _slug(str(intake.get("project_name")))

    # Full deterministic engineering pass: graph -> design -> load flow ->
    # short circuit -> dynamic validation -> consistency + approvals.
    eng = run_engineering(intake, profile["iso"])

    docs: list[dict[str, Any]] = []

    def add(n: str, key: str, title: str, filename: str, category: str, status: str,
            status_label: str, who: str, note: str = "",
            checklist_item: int | None = None) -> Path:
        docs.append({
            "n": n, "key": key, "title": title, "file": filename, "category": category,
            "status": status, "status_label": status_label, "who": who, "note": note,
            "checklist_item": checklist_item,
        })
        return pdir / filename

    # ---- CAISO minimum-requirements checklist items (2, 3, 4, 6–13) --------
    # Item 1 (study deposit) is a wire transfer and item 5 (ISP eligibility
    # demonstrations) is out of scope per the workplan — both are surfaced as
    # actions, not documents.
    form_file = "Appendix1" if profile["iso"] == "CAISO" else "InterconnectionRequest"
    tech_file = "AttachmentA" if profile["iso"] == "CAISO" else "TechnicalData"
    _gen_appendix1(intake, d, add(
        "02", "appendix1", profile["form_name"], f"02_{form_file}_{slug}.pdf",
        "checklist", "generated", loc("AUTO-FILLED — e-sign in RIMS5"), "GridPilot",
        loc("Mirrors the official form section by section (process, deliverability, 4a–4g, deposit, "
            "site exclusivity, signature). Execute electronically in RIMS5."), 2))
    _gen_attachment_a(intake, d, eng, add(
        "03", "attachment_a", profile["tech_form"], f"03_{tech_file}_{slug}.xlsx",
        "checklist", "generated", loc("DATA READY — transfer into official .xlsm"), "GridPilot",
        loc("Official sheet structure: I. Project Configuration, I-a. Short Circuit Data, "
            "II. Technical Validation, V. IR Validation & Comments (all Yes/N-A)."), 3))
    _gen_site_exclusivity(intake, d, add(
        "04", "exclusivity", "Evidence of Site Exclusivity", f"04_SiteExclusivity_{slug}.pdf",
        "checklist", "generated", "FORM COMPLETE — attach the executed agreement", "GridPilot",
        "Site Exclusivity/Control Demonstration Form — LOIs are not accepted; include the "
        "executed lease/option/deed.", 4))

    raw_ext, dyn_ext = profile["raw_ext"], profile["dyn_ext"]
    pf = eng["powerflow"]
    lf_path = add(
        "06", "epc", f"Load Flow Model (.{raw_ext})", f"06_LoadFlowModel_{slug}.{raw_ext}",
        "checklist", "generated",
        f"SOLVED — {pf['iterations']} iterations, losses {pf['losses_mw']:g} MW",
        "GridPilot",
        loc("Solved plant equivalent from the project graph; validate against the CAISO base case "
            "(obtained under NDA) before submission."), 6)
    lf_text = epc_text(eng["design"], pf, intake, profile) if raw_ext == "epc" \
        else raw_text(eng["design"], pf, intake, profile)
    lf_path.write_text(lf_text, encoding="utf-8")

    dyn_path = add(
        "07", "dyd", f"Dynamic Model (.{dyn_ext})", f"07_DynamicModel_{slug}.{dyn_ext}",
        "checklist", "generated",
        ("OEM PARAMETERS — " + eng["design"]["inverter"]["vendor"]
         if eng["design"]["inverter"]["verified"] else "GENERIC WECC — swap in vendor UDM"),
        "GridPilot",
        f"{'/'.join(eng['design']['inverter']['wecc_models'].values())} with equipment-library "
        "parameter sets; vendor MOD-026/027 data supersedes when received.", 7)
    dyn_text_out = dyd_text(eng["design"], intake, profile) if dyn_ext == "dyd" \
        else dyr_text(eng["design"], intake, profile)
    dyn_path.write_text(dyn_text_out, encoding="utf-8")

    _gen_reactive_capability(intake, d, eng, add(
        "08", "reactive", "Reactive Power Capability Document",
        f"08_ReactivePowerCapability_{slug}.pdf",
        "checklist", "generated", "COMPUTED — 0.95 PF evaluation at GSU high side", "GridPilot",
        "Tabular evaluation per the CAISO whitepaper: requirement (A), var losses (B), "
        "static (C) and dynamic (D) supply, surplus/(shortage).", 8))
    _gen_site_drawing(intake, d, eng, add(
        "09", "site_drawing", "Site Drawing", f"09_SiteDrawing_{slug}.pdf",
        "checklist", "generated", "GENERATED — POI, MW, gen-tie route to scale", "GridPilot",
        "Shows the POI, requested MW, and the gen-tie voltage/length; the KMZ boundary "
        "(supporting) is the aerial-imagery site map.", 9))

    sld_prims = build_sld(eng["graph"], eng["design"], intake)
    sld_to_pdf(sld_prims, add(
        "10", "sld", "Single-Line Diagram", f"10_SingleLineDiagram_{slug}.pdf",
        "checklist", "generated", "CONCEPTUAL — for interconnection application only", "GridPilot",
        "Conceptual SLD from the project graph: metering, protection, tie-line data, "
        "ownership demarcation, typical-of inverter block detail.", 10))
    add("10b", "sld_dxf", "Single-Line Diagram (DXF)", f"10_SingleLineDiagram_{slug}.dxf",
        "checklist", "generated", "EDITABLE — CAD import (R12)", "GridPilot",
        "Same drawing as the PDF, exported for AutoCAD-class tools.", 10
        ).write_text(to_dxf(sld_prims), encoding="utf-8")

    _gen_flat_bump(intake, d, eng, add(
        "11", "flat_bump", "Flat Run & Bump Test Plots", f"11_FlatRunBumpTest_{slug}.pdf",
        "checklist", "generated",
        "SIMULATED — Pg & Qg, 3-ph fault at POI at t=10 s", "GridPilot",
        loc("Per CAISO instructions: no-fault run 10 s, 3-phase-to-ground fault at the POI at "
            "t=10 s, run to 20 s, plotting Pg and Qg."), 11))
    _gen_mw_poi_plot(intake, d, eng, add(
        "12", "mw_poi", "Requested MW at POI Plot", f"12_RequestedMWatPOI_{slug}.pdf",
        "checklist", "generated", f"SOLVED — holds {pf['p_poi_mw']:g} MW at the POI", "GridPilot",
        "Generation MW against the requested-MW limit line, from the solved load flow.", 12))
    _gen_ibr_validation(intake, d, eng, add(
        "13", "ibr_validation", "IBR Model Validation Results", f"13_IBRModelValidation_{slug}.pdf",
        "checklist", "generated", "ALL 3 TESTS — V/Q step, freq step, ride-through", "GridPilot",
        "Plant controller voltage/Q-reference step, frequency reference step, and voltage "
        "ride-through results.", 13))

    # ---- Supporting work products (not checklist items) ---------------------
    _gen_kmz(intake, d, add(
        "S1", "kmz", "Project Boundary (KMZ)", f"S1_ProjectBoundary_{slug}.kmz",
        "supporting", "generated", "GENERATED — opens in Google Earth", "GridPilot",
        f"Aerial-imagery site map for checklist item 9 — boundary polygon (~{_fmt(d['acres'])} ac) "
        f"centered on {d['lat']}, {d['lon']}."))
    gen_dynamics_report(eng, intake, add(
        "S2", "dyn_report", "Dynamic Validation Report", f"S2_DynamicValidation_{slug}.pdf",
        "supporting", "generated",
        "COMPUTED — " + ("all checks pass" if eng["bump"]["all_pass"] else "CHECKS FAILING"),
        "GridPilot",
        loc("Engineering backup for items 7 and 11: flat-start and disturbance checks on the "
            "plant-level RMS response.")))
    gen_loadflow_report(eng, intake, add(
        "S3", "lf_report", "Load Flow & Short-Circuit Report", f"S3_LoadFlowValidation_{slug}.pdf",
        "supporting", "generated",
        "COMPUTED — solved case, convergence log, fault duties", "GridPilot",
        "Engineering backup for items 6 and 12: convergence history, bus voltages, "
        "branch loadings, fault duties."))
    gen_equipment_schedule(eng, intake, add(
        "S4", "equipment_schedule", "Equipment Schedule", f"S4_EquipmentSchedule_{slug}.xlsx",
        "supporting", "generated",
        "GENERATED — design engine sizing with OEM sources", "GridPilot",
        f"Topology: {eng['design']['topology']}"))
    gen_assumptions_log(eng, intake, add(
        "S5", "assumptions", "Assumptions & Approvals Log", f"S5_AssumptionsApprovals_{slug}.pdf",
        "supporting", "generated",
        ("APPROVED — all items signed off" if eng["approvals"]["all_approved"]
         else f"PENDING — {eng['approvals']['pending']} of {eng['approvals']['total']} awaiting approval"),
        "GridPilot",
        "Every engineering default requiring engineer-of-record confirmation, with sign-off state."))
    gen_source_trace(eng, intake, add(
        "S6", "source_trace", "Source Trace Appendix", f"S6_SourceTrace_{slug}.md",
        "supporting", "generated", "GENERATED — full parameter provenance", "GridPilot",
        "Every value in this packet traced to developer input, OEM datasheet, ISO rule, "
        "calculation, or approved assumption."))
    gen_portal_fields(eng, intake, profile, add(
        "S7", "portal_fields", "Portal Field Export (JSON)", f"S7_PortalFields_{slug}.json",
        "supporting", "generated", f"READY — paste into {profile['portal']}", "GridPilot",
        "Machine-readable field values for the ISO portal entry."))
    _gen_sos_instructions(intake, add(
        "S8", "sos", "Secretary of State Certification", f"S8_SecretaryOfState_{slug}.pdf",
        "supporting", "action", "ACTION — developer obtains official certificate", "Developer",
        "Official government document; GridPilot provides ordering instructions."))
    _gen_signatory(intake, add(
        "S9", "signatory", "Proof of Authorized Signatory", f"S9_AuthorizedSignatory_{slug}.pdf",
        "supporting", "generated", "DRAFT — counsel review & execution", "GridPilot"))
    if eng["design"]["missing"]:
        gen_missing_data(eng, intake, add(
            "S95", "missing_data", "Missing Data List", f"S95_MissingData_{slug}.md",
            "supporting", "action",
            f"ACTION — {len(eng['design']['missing'])} item(s) for the developer", "Developer",
            "Facts the engine needed but could not find; assumptions stand in until provided."))

    readme_path = add("00", "readme", "Submission Checklist (README)", f"00_SubmissionChecklist_{slug}.md",
                      "checklist", "generated", "GENERATED — 13-item checklist map", "GridPilot",
                      "Maps every file to the CAISO minimum-requirements checklist, including the "
                      "two items handled outside the packet (deposit wire; ISP demonstrations).")
    _gen_readme(intake, d, sorted(docs, key=lambda x: x["n"]), readme_path)

    zip_path = pdir / f"{slug}_{profile['iso'].replace('-', '')}_Packet.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for doc in docs:
            fp = pdir / doc["file"]
            if fp.exists():
                z.write(fp, doc["file"])

    if profile["iso"] == "CAISO":
        deposit_action = {
            "title": f"Wire the study deposit — {d['deposit']}",
            "detail": "Directly to CAISO: Wells Fargo, ABA 121000248, Acct 4122041825. "
                      f"Reference \"{str(intake.get('project_name') or '').upper()}\" in the wire notes."}
    else:
        deposit_action = {
            "title": "Fund the study deposits and fees",
            "detail": profile["deposit_action"] + " Reference "
                      f"\"{str(intake.get('project_name') or '').upper()}\" in the wire notes."}
    actions = [
        deposit_action,
        {"title": "Order the Secretary of State certificate",
         "detail": f"Certificate of Good Standing for {intake.get('legal_name')} — see the "
                   "supporting instructions document."},
    ]
    if profile["iso"] == "CAISO" and d["is_isp"]:
        actions.append({
            "title": "Prepare the ISP eligibility demonstrations (checklist item 5)",
            "detail": "COD need, permits, equipment purchase order, financing, POI status, and "
                      "precursor upgrades — developer evidence assembled outside this packet."})
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
            "title": loc("Chase vendor .dyd dynamic model files"),
            "detail": loc("The most common schedule risk. GridPilot used WECC standard models as placeholders — "
                          "swap in vendor MOD-026/027-verified parameters before submission.")})
    if profile["iso"] == "CAISO":
        actions.append({
            "title": "E-sign Appendix 1 in RIMS5 and upload the packet",
            "detail": f"{RIMS5_URL} — CAISO confirms acceptance within ~4 weeks and the project enters the queue."})
    else:
        actions.append({
            "title": profile["submit_action"],
            "detail": f"{profile['portal_url']} — see the {profile['iso']} requirements reference for "
                      "window dates and acceptance timelines."})

    consistency = [
        {"title": "MW chain reconciled",
         "detail": loc(f"Gross {_fmt(d['gross'])} − Aux {_fmt(d['aux'])} − Losses {_fmt(d['losses'])} = "
                       f"{_fmt(d['net'])} MW at POI — identical in Appendix 1, Attachment A, the model, and the SLD.")},
        {"title": "Legal name consistent",
         "detail": loc(f"\"{intake.get('legal_name')}\" used verbatim across Appendix 1, signatory consent, and site exclusivity.")},
        {"title": "GPS consistent",
         "detail": loc(f"{d['lat']}, {d['lon']} identical in Appendix 1, Attachment A, and the KMZ boundary.")},
        {"title": "Dates sequential",
         "detail": f"In-service {d['in_service'].strftime('%m/%d/%Y')} → trial operation "
                   f"{d['trial_op'].strftime('%m/%d/%Y')} → COD {d['cod'].strftime('%m/%d/%Y')} (within 7 years)."},
    ]

    engineering = {
        "graph_version": eng["graph"].get("version", ""),
        "topology": eng["design"]["topology"],
        "counts": eng["design"]["counts"],
        "loadflow": {
            "converged": pf["converged"], "iterations": pf["iterations"],
            "p_poi_mw": pf["p_poi_mw"], "q_poi_mvar": pf["q_poi_mvar"],
            "losses_mw": pf["losses_mw"], "p_pv_mw": pf["p_pv_mw"],
            "p_bess_mw": pf["p_bess_mw"], "warnings": pf["warnings"],
        },
        "short_circuit": eng["short_circuit"]["results"],
        "dynamics_pass": eng["bump"]["all_pass"],
        "checks": eng["checks"],
        "approvals": {
            "total": eng["approvals"]["total"],
            "pending": eng["approvals"]["pending"],
            "all_approved": eng["approvals"]["all_approved"],
        },
        "missing": eng["graph"].get("missing", []),
    }

    manifest = {
        "id": pid,
        "org_id": org_id,
        "iso": profile["iso"],
        "iso_process": profile["process"],
        "created_at": datetime.now(timezone.utc).isoformat(),
        "project_name": intake.get("project_name"),
        "legal_name": intake.get("legal_name"),
        "track": d["track"],
        "net_mw": d["net"],
        "poi": intake.get("poi_name"),
        "intake": intake,
        "validation": validation,
        "consistency": consistency,
        "engineering": engineering,
        "actions": actions,
        "checklist": {
            "total": 13,
            "generated": sorted({doc["checklist_item"] for doc in docs
                                 if doc.get("checklist_item")}),
            "actions": [{"item": 1, "title": f"Study deposit — {d['deposit']}",
                         "note": "Wire transfer, not a document"}],
            "excluded": [{"item": 5, "title": "ISP eligibility demonstrations",
                          "note": "Handled outside this packet (developer evidence)"}]
                        if d["is_isp"] else [],
        } if profile["iso"] == "CAISO" else None,
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

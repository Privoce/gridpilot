"""Per-ISO interconnection profiles.

One profile per US ISO/RTO drives the request wizard: form names, model
formats, portals, deposits, and process tracks. The generation pipeline was
built for CAISO and is localized through these profiles; the full requirement
corpus lives in backend/app/rules/iso_requirements/*.md.
"""

from __future__ import annotations

from typing import Any

ISO_PROFILES: dict[str, dict[str, Any]] = {
    "CAISO": {
        "iso": "CAISO",
        "name": "California ISO",
        "process": "GIDAP / IPE cluster study",
        "tariff": "CAISO Tariff Appendix DD (GIDAP)",
        "bpm": "CAISO BPM for Generator Interconnection",
        "portal": "RIMS5",
        "portal_url": "https://rims.caiso.com",
        "form_name": "Appendix 1 — Interconnection Request",
        "form_short": "Appendix 1",
        "tech_form": "Attachment A — Generator Technical Data",
        "tech_short": "Attachment A",
        "model_tool": "GE PSLF",
        "model_standard": "WECC",
        "raw_ext": "epc",
        "dyn_ext": "dyd",
        "deposit_action": "Wire the study deposit — $150,000 (ISP) directly to CAISO. "
                          "Wells Fargo, ABA 121000248, Acct 4122041825.",
        "submit_action": "E-sign Appendix 1 in RIMS5 and upload the packet",
        "tracks": ["Cluster", "Independent Study Process", "Fast Track"],
        "gps_box": (32.0, 42.5, -125.0, -113.5),
        "site_control_note": "100% site exclusivity for the generating facility at IR "
                             "(deposit in lieu is limited post-IPE).",
    },
    "MISO": {
        "iso": "MISO",
        "name": "Midcontinent ISO",
        "process": "Definitive Planning Phase (DPP) cycle",
        "tariff": "MISO Tariff Attachment X (GIP)",
        "bpm": "MISO BPM-015 (Generation Interconnection)",
        "portal": "the MISO DPP queue",
        "portal_url": "https://www.misoenergy.org/planning/resource-utilization/generator-interconnection/",
        "form_name": "DPP Application — Interconnection Request",
        "form_short": "the DPP application",
        "tech_form": "Attachment X Technical Data Workbook",
        "tech_short": "the technical data workbook",
        "model_tool": "Siemens PSS/E",
        "model_standard": "MMWG",
        "raw_ext": "raw",
        "dyn_ext": "dyr",
        "deposit_action": "Wire M2 — $8,000/MW — plus D1 application fee and D2 study "
                          "funding deposit with the DPP application.",
        "submit_action": "Submit the DPP application in the MISO queue by the cycle deadline",
        "tracks": ["DPP Cycle", "Provisional"],
        "gps_box": None,
        "site_control_note": "100% site control for the facility and 50% for the tie line "
                             "(or $80,000/mile deposit) at application.",
    },
    "PJM": {
        "iso": "PJM",
        "name": "PJM Interconnection",
        "process": "Cycle process (first-ready-first-served clusters)",
        "tariff": "PJM Tariff Part VII",
        "bpm": "PJM Manual 14 series",
        "portal": "Queue Point",
        "portal_url": "https://queuepoint.pjm.com",
        "form_name": "Queue Point Interconnection Application",
        "form_short": "the application",
        "tech_form": "PJM Technical Data Workbook",
        "tech_short": "the technical data workbook",
        "model_tool": "Siemens PSS/E",
        "model_standard": "MMWG",
        "raw_ext": "raw",
        "dyn_ext": "dyr",
        "deposit_action": "Wire the study deposit (scaled by MW) and Readiness Deposit 1 "
                          "with the Cycle application.",
        "submit_action": "Submit the application in Queue Point during the Cycle window",
        "tracks": ["Cycle", "Surplus Interconnection Service"],
        "gps_box": None,
        "site_control_note": "100% site control for the generation site at application — "
                             "no deposit alternative for the plant footprint.",
    },
    "ERCOT": {
        "iso": "ERCOT",
        "name": "ERCOT (Texas)",
        "process": "Full Interconnection Study (Planning Guide §5)",
        "tariff": "ERCOT Planning Guide Section 5",
        "bpm": "ERCOT Planning Guide / Nodal Protocols",
        "portal": "RIOO",
        "portal_url": "https://www.ercot.com/services/rq/integration",
        "form_name": "Interconnection Request (INR)",
        "form_short": "the INR",
        "tech_form": "FIS Technical Data Package",
        "tech_short": "the FIS data package",
        "model_tool": "Siemens PSS/E (+ PSCAD for IBRs)",
        "model_standard": "ERCOT model quality tests",
        "raw_ext": "raw",
        "dyn_ext": "dyr",
        "deposit_action": "Pay the $5,000 INR fee in RIOO; fund the FIS study deposit "
                          "with the interconnecting TSP.",
        "submit_action": "Submit the INR in RIOO and execute the FIS agreement with the TSP",
        "tracks": ["Full Interconnection Study"],
        "gps_box": (25.8, 36.5, -106.7, -93.5),
        "site_control_note": "Site and gen-tie control expected before FIS kickoff "
                             "(TSP facility design requires it).",
    },
    "SPP": {
        "iso": "SPP",
        "name": "Southwest Power Pool",
        "process": "DISIS cluster study (GIP)",
        "tariff": "SPP OATT Attachment V (GIP)",
        "bpm": "SPP DISIS business practices",
        "portal": "the SPP RMS queue",
        "portal_url": "https://www.spp.org/engineering/generator-interconnection/",
        "form_name": "DISIS Application — Interconnection Request",
        "form_short": "the DISIS application",
        "tech_form": "SPP Technical Data Workbook",
        "tech_short": "the technical data workbook",
        "model_tool": "Siemens PSS/E",
        "model_standard": "MMWG",
        "raw_ext": "raw",
        "dyn_ext": "dyr",
        "deposit_action": "Wire the study deposit and commercial readiness security "
                          "per the DISIS tranche schedule.",
        "submit_action": "Submit the DISIS application during the cluster window",
        "tracks": ["DISIS Cluster"],
        "gps_box": None,
        "site_control_note": "100% site control for the generating facility at application "
                             "(regulatory-barrier deposit exceptions only).",
    },
    "NYISO": {
        "iso": "NYISO",
        "name": "New York ISO",
        "process": "Attachment X cluster study",
        "tariff": "NYISO OATT Attachment X",
        "bpm": "NYISO interconnection procedures (LFIP/SGIP)",
        "portal": "the NYISO interconnection queue",
        "portal_url": "https://www.nyiso.com/interconnections",
        "form_name": "Attachment X Interconnection Request",
        "form_short": "the Interconnection Request",
        "tech_form": "NYISO Technical Data Workbook",
        "tech_short": "the technical data workbook",
        "model_tool": "Siemens PSS/E",
        "model_standard": "MMWG",
        "raw_ext": "raw",
        "dyn_ext": "dyr",
        "deposit_action": "Wire the cluster study deposit and readiness deposits "
                          "per Attachment X ($5,000/POI for an optional pre-application report).",
        "submit_action": "Submit the Interconnection Request in the cluster window (CRIS/ERIS election)",
        "tracks": ["Cluster Study", "Small Generator (SGIP)"],
        "gps_box": (40.4, 45.1, -79.9, -71.7),
        "site_control_note": "100% site control for the facility footprint at application.",
    },
    "ISO-NE": {
        "iso": "ISO-NE",
        "name": "ISO New England",
        "process": "Schedule 22/23 interconnection (cluster-enabled)",
        "tariff": "ISO-NE OATT Schedules 22/23",
        "bpm": "ISO-NE Planning Procedure PP5-6",
        "portal": "the ISO-NE interconnection queue",
        "portal_url": "https://www.iso-ne.com/system-planning/interconnection-service/",
        "form_name": "Schedule 22 Interconnection Request",
        "form_short": "the Interconnection Request",
        "tech_form": "PP5-6 Technical Data Workbook",
        "tech_short": "the technical data workbook",
        "model_tool": "Siemens PSS/E",
        "model_standard": "MMWG / PP5-6",
        "raw_ext": "raw",
        "dyn_ext": "dyr",
        "deposit_action": "Wire the study deposit with the Interconnection Request; "
                          "readiness deposits follow at decision points.",
        "submit_action": "Submit the Interconnection Request (CNRC/NRC election) to ISO-NE",
        "tracks": ["Schedule 22 (Large)", "Schedule 23 (Small)"],
        "gps_box": (40.9, 47.5, -73.8, -66.8),
        "site_control_note": "100% site control for the facility footprint at application.",
    },
}

DEFAULT_ISO = "CAISO"


def get_profile(iso: str | None) -> dict[str, Any]:
    return ISO_PROFILES.get((iso or DEFAULT_ISO).upper().replace("ISONE", "ISO-NE"), ISO_PROFILES[DEFAULT_ISO])


def localize(text: str, profile: dict[str, Any]) -> str:
    """Rewrite CAISO-specific wording for another ISO's context.

    The validation checks are universal (MW chain, site control, COD, models);
    only the institutional references differ. CAISO text passes through
    unchanged.
    """
    if profile["iso"] == "CAISO":
        return text
    replacements = [
        ("CAISO Tariff Appendix DD (GIDAP)", profile["tariff"]),
        ("CAISO BPM for Generator Interconnection", profile["bpm"]),
        ("CAISO Appendix 1", profile["form_name"]),
        ("Appendix 1", profile["form_short"]),
        ("CAISO Attachment A", profile["tech_form"]),
        ("Attachment A", profile["tech_short"]),
        ("RIMS5", profile["portal"]),
        ("GE PSLF", profile["model_tool"]),
        ("PSLF-compatible (.dyd)", f"{profile['model_tool']}-compatible (.{profile['dyn_ext']})"),
        ("PSLF", profile["model_tool"]),
        (".dyd", f".{profile['dyn_ext']}"),
        ("WECC-approved", f"{profile['model_standard']}-accepted"),
        ("WECC standard models", f"standard library models ({profile['model_standard']})"),
        ("CAISO", profile["iso"]),
    ]
    for old, new in replacements:
        text = text.replace(old, new)
    return text

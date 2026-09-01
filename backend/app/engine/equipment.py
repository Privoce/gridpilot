"""Phase 2 — Equipment library.

All device parameters load from `backend/app/assets/equipment_specs.json`,
the single source of truth maintained by the system administrator. Each JSON
entry separates `sourced_keys` (verified against the cited OEM datasheet or
the developer ground-truth workbook) from `assumed_keys` (engineering
defaults pending a source). Documents that must never carry unsourced
numbers — Attachment A above all — write a parameter only when it is
sourced; assumed parameters surface as SYSTEM ADMIN alerts instead.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

_SPECS_PATH = Path(__file__).resolve().parents[1] / "assets" / "equipment_specs.json"

with open(_SPECS_PATH, encoding="utf-8") as _f:
    _SPECS: dict[str, Any] = json.load(_f)


def specs_path() -> str:
    return str(_SPECS_PATH)


def is_sourced(entry: dict[str, Any], key: str) -> bool:
    """True when the parameter is verified against the entry's cited source."""
    return key in (entry.get("sourced_keys") or [])


def spec_gaps(entry: dict[str, Any]) -> list[dict[str, str]]:
    """Assumed (unsourced) parameters of a library entry, with admin notes."""
    notes = entry.get("source_notes") or {}
    gaps = []
    for key in entry.get("assumed_keys") or []:
        gaps.append({
            "device": f"{entry.get('vendor', '')} {entry.get('model', entry.get('id', '?'))}".strip(),
            "param": key,
            "note": notes.get(key) or notes.get("_all") or "No source on file — ADMIN: add value + source to equipment_specs.json",
        })
    return gaps


# ---------------------------------------------------------------------------
# Library tables (materialized from the admin-maintained JSON)
# ---------------------------------------------------------------------------

INVERTERS: dict[str, dict[str, Any]] = dict(_SPECS["inverters"])
BESS_UNITS: dict[str, dict[str, Any]] = dict(_SPECS["bess_units"])
PAD_TRANSFORMERS: dict[str, dict[str, Any]] = dict(_SPECS["pad_transformers"])
MAIN_TRANSFORMERS: dict[str, dict[str, Any]] = dict(_SPECS["main_transformers"])
CABLES: dict[str, dict[str, Any]] = dict(_SPECS["cables"])
PV_MODULES: dict[str, dict[str, Any]] = dict(_SPECS.get("pv_modules") or {})

# Gen-tie overhead line constants by voltage class (per mile). JSON keys are
# strings; the engine indexes by integer kV class.
GENTIE_LINES: dict[int, dict[str, Any]] = {
    int(k): v for k, v in _SPECS["gentie_lines"].items()
}
GENTIE_META: dict[str, Any] = _SPECS.get("gentie_lines_meta") or {}


def catalog() -> dict[str, Any]:
    return {
        "inverters": list(INVERTERS.values()),
        "bess_units": list(BESS_UNITS.values()),
        "pad_transformers": list(PAD_TRANSFORMERS.values()),
        "main_transformers": list(MAIN_TRANSFORMERS.values()),
        "cables": list(CABLES.values()),
        "pv_modules": list(PV_MODULES.values()),
    }


# ---------------------------------------------------------------------------
# Matching free-text intake against the library
# ---------------------------------------------------------------------------

_INVERTER_PATTERNS = [
    (r"sg\s*4400|sungrow", "sungrow_sg4400ud_mv"),
    (r"sunny\s*central|sma|sc\s*4600", "sma_sc4600up"),
    (r"fs\s*3430|power\s*electronics", "pe_fs3430k"),
]

# BESS products ship in duration-specific configurations with different PCS
# ratings (per the OEM datasheets), so each pattern maps duration -> entry.
_BESS_PATTERNS: list[tuple[str, dict[str, str]]] = [
    (r"megapack|tesla", {"4h": "tesla_megapack_2xl", "2h": "tesla_megapack_2xl_2h"}),
    (r"powertitan|st5015|sungrow", {"4h": "sungrow_powertitan2_4h", "2h": "sungrow_powertitan2_2h"}),
]


def match_inverter(text: str | None) -> tuple[dict[str, Any], bool]:
    """(entry, matched) — falls back to the generic entry when unmatched."""
    t = (text or "").lower()
    for pat, key in _INVERTER_PATTERNS:
        if re.search(pat, t):
            return INVERTERS[key], True
    return INVERTERS["generic_pv_4mva"], False


def match_bess(text: str | None,
               duration_h: float | None = None) -> tuple[dict[str, Any], bool]:
    """(entry, matched) — the storage duration picks the OEM configuration.

    Durations under 3 hours select the 2-hour datasheet configuration;
    anything longer (or unknown) selects the 4-hour configuration.
    """
    t = (text or "").lower()
    variant = "2h" if (duration_h is not None and duration_h < 3.0) else "4h"
    for pat, variants in _BESS_PATTERNS:
        if re.search(pat, t):
            return BESS_UNITS[variants[variant]], True
    return BESS_UNITS["generic_bess_2mw"], False


# ---------------------------------------------------------------------------
# Customer datasheet entries (ingested, unverified until engineer sign-off)
# ---------------------------------------------------------------------------

def _norm_key(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (text or "").lower())


def match_custom(text: str | None, entries: list[dict[str, Any]] | None,
                 kind: str) -> dict[str, Any] | None:
    """Match intake free text against datasheet-ingested equipment records.

    Records ride inside the intake (`custom_equipment`) so packet generation
    stays stateless. A record matches when its vendor+model appears in the
    intake text.
    """
    t = _norm_key(text or "")
    if not t:
        return None
    for e in entries or []:
        if str(e.get("kind") or "pv_inverter") != kind:
            continue
        vkey = _norm_key(str(e.get("vendor") or ""))
        model_tokens = str(e.get("model") or "").split()
        mkey = _norm_key(model_tokens[0]) if model_tokens else ""
        if vkey and vkey in t and (not mkey or mkey in t):
            return e
    return None


def custom_entry(e: dict[str, Any]) -> dict[str, Any]:
    """Materialize a datasheet record into a full library entry.

    Electrical ratings come from the datasheet; dynamic-model parameters stay
    generic WECC (a datasheet never carries MOD-026/027 control data), and the
    entry is unverified until the engineer of record signs it off.
    """
    import math

    is_bess = str(e.get("kind") or "pv_inverter") == "bess"
    base = BESS_UNITS["generic_bess_2mw"] if is_bess else INVERTERS["generic_pv_4mva"]
    mva = float(e.get("mva") or base["mva"])
    mw = float(e.get("mw") or mva)
    pf = min(max(float(e.get("pf_range") or base.get("pf_range", 0.95)), 0.8), 1.0)
    out: dict[str, Any] = {
        **base,
        "id": f"custom_{_norm_key(str(e.get('vendor', '')))}_{_norm_key(str(e.get('model', '')))}"[:48],
        "vendor": str(e.get("vendor") or "OEM").strip(),
        "model": str(e.get("model") or "Custom unit").strip(),
        "mva": mva, "mw": mw,
        "ac_kv": float(e.get("ac_kv") or base["ac_kv"]),
        "pf_range": pf,
        "q_pu_max": round(math.tan(math.acos(pf)) if pf < 1.0 else 0.0, 3),
        "verified": False,
        "custom": True,
        "datasheet": f"Datasheet upload: {e.get('source') or 'customer datasheet'} — unverified",
        # Uploaded datasheet values count as customer-sourced for the ratings
        # it actually carries; everything else stays assumed.
        "sourced_keys": [k for k in ("mva", "mw", "ac_kv", "pf_range", "mwh") if e.get(k)],
        "assumed_keys": ["fault_current_pu", "q_pu_max", "dyd_params"],
        "source_notes": {"_all": "Customer datasheet upload — engineer of record to verify before filing"},
    }
    if is_bess:
        out["mwh"] = float(e.get("mwh") or e.get("mw") or base["mwh"])
    return out


def pick_main_transformer(required_mva: float) -> dict[str, Any]:
    """Smallest standard family unit that covers the requirement."""
    for key in ("mpt_75mva", "mpt_140mva", "mpt_230mva"):
        if MAIN_TRANSFORMERS[key]["mva"] >= required_mva:
            return MAIN_TRANSFORMERS[key]
    return MAIN_TRANSFORMERS["mpt_230mva"]


def pick_pad_transformer(block_mva: float) -> dict[str, Any]:
    """Smallest standard pad-mount that covers the inverter block MVA."""
    for key in ("pad_5mva", "pad_9mva", "pad_12mva"):
        if PAD_TRANSFORMERS[key]["mva"] >= block_mva:
            return PAD_TRANSFORMERS[key]
    return PAD_TRANSFORMERS["pad_12mva"]


def integrated_pad(inverter: dict[str, Any]) -> dict[str, Any] | None:
    """Pad-transformer entry for a turnkey station's integrated MV transformer.

    Stations like the Sungrow SG4400UD-MV ship with the MV transformer inside
    the unit, so the 'pad' is the OEM-integrated transformer — one per
    inverter — with datasheet impedance instead of a generic family pick.
    """
    x = inverter.get("integrated_xfmr")
    if not x:
        return None
    prefix = "integrated_xfmr."
    sourced = [k[len(prefix):] for k in (inverter.get("sourced_keys") or []) if k.startswith(prefix)]
    assumed = [k[len(prefix):] for k in (inverter.get("assumed_keys") or []) if k.startswith(prefix)]
    notes = {k[len(prefix):]: v for k, v in (inverter.get("source_notes") or {}).items()
             if k.startswith(prefix)}
    return {
        "id": f"{inverter['id']}_integrated_xfmr",
        "mva": float(x["mva"]),
        "z_pct": float(x["z_pct"]),
        "xr": float(x.get("xr") or 9.5),
        "vector": x.get("vector", "Dy11"),
        "cooling": x.get("cooling"),
        "lv_kv": x.get("lv_kv"),
        "integrated": True,
        "vendor": inverter.get("vendor"),
        "model": f"{inverter.get('model')} integrated MV transformer",
        "verified": bool(inverter.get("verified")),
        "datasheet": inverter.get("datasheet"),
        "source": inverter.get("source"),
        "sourced_keys": sourced,
        "assumed_keys": assumed,
        "source_notes": notes,
    }


def gentie_constants(kv: float) -> dict[str, Any]:
    """Nearest standard voltage class at or above the POI voltage."""
    classes = sorted(GENTIE_LINES)
    for c in classes:
        if kv <= c + 1:
            return {**GENTIE_LINES[c], "kv_class": c}
    top = classes[-1]
    return {**GENTIE_LINES[top], "kv_class": top}

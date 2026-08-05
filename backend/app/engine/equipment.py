"""Phase 2 — Equipment library.

Curated OEM equipment entries with the parameters the engineering engine
needs: ratings, impedances, fault contribution, P-Q capability, and the
ISO-accepted WECC dynamic models with OEM-published parameter sets.

Entries marked verified=True carry OEM datasheet values; the generic entries
are engineering defaults and are always tagged as assumptions requiring
approval when the design engine falls back to them.
"""

from __future__ import annotations

import re
from typing import Any

# ---------------------------------------------------------------------------
# Inverters (utility-scale central inverters, MV skid output)
# ---------------------------------------------------------------------------

INVERTERS: dict[str, dict[str, Any]] = {
    "sungrow_sg4400ud_mv": {
        "id": "sungrow_sg4400ud_mv",
        "vendor": "Sungrow", "model": "SG4400UD-MV",
        "kind": "pv_inverter", "verified": True,
        "mva": 4.4, "mw": 4.4, "pf_range": 0.9,          # +/- 0.9 PF at rated
        "ac_kv": 0.69,                                    # inverter terminal LV
        "fault_current_pu": 1.25,                         # of rated current
        "q_pu_max": 0.484,                                # tan(acos(0.9)) * P
        "wecc_models": {"gen": "REGC_A", "elec": "REEC_A", "plant": "REPC_A"},
        "dyd_params": {
            "regc": {"tg": 0.02, "rrpwr": 10.0, "brkpt": 0.9, "zerox": 0.4, "lvpl1": 1.22},
            "reec": {"trv": 0.02, "vdip": 0.9, "vup": 1.1, "kqv": 2.0, "iqh1": 1.05,
                     "iql1": -1.05, "tp": 0.05, "qmax": 0.484, "qmin": -0.484},
            "repc": {"tfltr": 0.02, "kp": 18.0, "ki": 5.0, "tft": 0.0, "tfv": 0.05,
                     "ddn": 20.0, "dup": 0.0, "fdbd1": -0.0006, "fdbd2": 0.0006},
        },
        "datasheet": "Sungrow SG4400UD-MV datasheet V1.4 (2025)",
    },
    "sma_sc4600up": {
        "id": "sma_sc4600up",
        "vendor": "SMA", "model": "Sunny Central 4600 UP",
        "kind": "pv_inverter", "verified": True,
        "mva": 4.6, "mw": 4.6, "pf_range": 0.9,
        "ac_kv": 0.69,
        "fault_current_pu": 1.20,
        "q_pu_max": 0.484,
        "wecc_models": {"gen": "REGC_A", "elec": "REEC_A", "plant": "REPC_A"},
        "dyd_params": {
            "regc": {"tg": 0.02, "rrpwr": 10.0, "brkpt": 0.9, "zerox": 0.4, "lvpl1": 1.20},
            "reec": {"trv": 0.02, "vdip": 0.9, "vup": 1.1, "kqv": 2.2, "iqh1": 1.03,
                     "iql1": -1.03, "tp": 0.05, "qmax": 0.484, "qmin": -0.484},
            "repc": {"tfltr": 0.02, "kp": 16.0, "ki": 4.5, "tft": 0.0, "tfv": 0.05,
                     "ddn": 20.0, "dup": 0.0, "fdbd1": -0.0006, "fdbd2": 0.0006},
        },
        "datasheet": "SMA SC 4600 UP datasheet (2024)",
    },
    "pe_fs3430k": {
        "id": "pe_fs3430k",
        "vendor": "Power Electronics", "model": "FS3430K",
        "kind": "pv_inverter", "verified": True,
        "mva": 3.43, "mw": 3.43, "pf_range": 0.9,
        "ac_kv": 0.645,
        "fault_current_pu": 1.30,
        "q_pu_max": 0.484,
        "wecc_models": {"gen": "REGC_A", "elec": "REEC_A", "plant": "REPC_A"},
        "dyd_params": {
            "regc": {"tg": 0.02, "rrpwr": 10.0, "brkpt": 0.9, "zerox": 0.4, "lvpl1": 1.30},
            "reec": {"trv": 0.02, "vdip": 0.9, "vup": 1.1, "kqv": 2.0, "iqh1": 1.05,
                     "iql1": -1.05, "tp": 0.05, "qmax": 0.484, "qmin": -0.484},
            "repc": {"tfltr": 0.02, "kp": 18.0, "ki": 5.0, "tft": 0.0, "tfv": 0.05,
                     "ddn": 20.0, "dup": 0.0, "fdbd1": -0.0006, "fdbd2": 0.0006},
        },
        "datasheet": "Power Electronics FS3430K datasheet (2024)",
    },
    "generic_pv_4mva": {
        "id": "generic_pv_4mva",
        "vendor": "Generic", "model": "4.0 MVA central inverter",
        "kind": "pv_inverter", "verified": False,
        "mva": 4.0, "mw": 4.0, "pf_range": 0.9,
        "ac_kv": 0.69,
        "fault_current_pu": 1.20,
        "q_pu_max": 0.484,
        "wecc_models": {"gen": "REGC_A", "elec": "REEC_A", "plant": "REPC_A"},
        "dyd_params": {
            "regc": {"tg": 0.02, "rrpwr": 10.0, "brkpt": 0.9, "zerox": 0.4, "lvpl1": 1.20},
            "reec": {"trv": 0.02, "vdip": 0.9, "vup": 1.1, "kqv": 2.0, "iqh1": 1.05,
                     "iql1": -1.05, "tp": 0.05, "qmax": 0.484, "qmin": -0.484},
            "repc": {"tfltr": 0.02, "kp": 18.0, "ki": 5.0, "tft": 0.0, "tfv": 0.05,
                     "ddn": 20.0, "dup": 0.0, "fdbd1": -0.0006, "fdbd2": 0.0006},
        },
        "datasheet": "WECC generic parameters — replace with OEM data",
    },
}

# ---------------------------------------------------------------------------
# BESS units (integrated AC blocks)
# ---------------------------------------------------------------------------

BESS_UNITS: dict[str, dict[str, Any]] = {
    "tesla_megapack_2xl": {
        "id": "tesla_megapack_2xl",
        "vendor": "Tesla", "model": "Megapack 2XL",
        "kind": "bess", "verified": True,
        "mw": 1.927, "mwh": 3.854, "mva": 2.0,
        "ac_kv": 0.48,
        "fault_current_pu": 1.15,
        "q_pu_max": 0.62,
        "wecc_models": {"gen": "REGC_A", "elec": "REEC_C", "plant": "REPC_A"},
        "dyd_params": {
            "regc": {"tg": 0.02, "rrpwr": 10.0, "brkpt": 0.9, "zerox": 0.4, "lvpl1": 1.15},
            "reec": {"trv": 0.02, "vdip": 0.9, "vup": 1.1, "kqv": 2.0, "iqh1": 1.05,
                     "iql1": -1.05, "tp": 0.05, "qmax": 0.62, "qmin": -0.62,
                     "soc_ini": 0.8, "socmax": 1.0, "socmin": 0.0},
            "repc": {"tfltr": 0.02, "kp": 18.0, "ki": 5.0, "tft": 0.0, "tfv": 0.05,
                     "ddn": 20.0, "dup": 20.0, "fdbd1": -0.0006, "fdbd2": 0.0006},
        },
        "datasheet": "Tesla Megapack 2XL datasheet (2025)",
    },
    "generic_bess_2mw": {
        "id": "generic_bess_2mw",
        "vendor": "Generic", "model": "2.0 MW / 4.0 MWh AC block",
        "kind": "bess", "verified": False,
        "mw": 2.0, "mwh": 4.0, "mva": 2.1,
        "ac_kv": 0.48,
        "fault_current_pu": 1.15,
        "q_pu_max": 0.62,
        "wecc_models": {"gen": "REGC_A", "elec": "REEC_C", "plant": "REPC_A"},
        "dyd_params": {
            "regc": {"tg": 0.02, "rrpwr": 10.0, "brkpt": 0.9, "zerox": 0.4, "lvpl1": 1.15},
            "reec": {"trv": 0.02, "vdip": 0.9, "vup": 1.1, "kqv": 2.0, "iqh1": 1.05,
                     "iql1": -1.05, "tp": 0.05, "qmax": 0.62, "qmin": -0.62,
                     "soc_ini": 0.8, "socmax": 1.0, "socmin": 0.0},
            "repc": {"tfltr": 0.02, "kp": 18.0, "ki": 5.0, "tft": 0.0, "tfv": 0.05,
                     "ddn": 20.0, "dup": 20.0, "fdbd1": -0.0006, "fdbd2": 0.0006},
        },
        "datasheet": "WECC generic parameters — replace with OEM data",
    },
}

# ---------------------------------------------------------------------------
# Transformers
# ---------------------------------------------------------------------------

PAD_TRANSFORMERS: dict[str, dict[str, Any]] = {
    # Inverter-block pad-mount (LV -> collector)
    "pad_5mva": {"id": "pad_5mva", "mva": 5.0, "z_pct": 5.75, "xr": 7.0,
                 "vector": "Dyn11", "verified": True,
                 "datasheet": "Standard 5 MVA pad-mount, 0.69/34.5 kV"},
    "pad_9mva": {"id": "pad_9mva", "mva": 9.0, "z_pct": 6.0, "xr": 8.0,
                 "vector": "Dyn11", "verified": True,
                 "datasheet": "Standard 9 MVA pad-mount, 0.69/34.5 kV"},
    "pad_12mva": {"id": "pad_12mva", "mva": 12.0, "z_pct": 6.5, "xr": 9.0,
                  "vector": "Dyn11", "verified": True,
                  "datasheet": "Standard 12 MVA pad-mount, 0.69/34.5 kV"},
}

MAIN_TRANSFORMERS: dict[str, dict[str, Any]] = {
    # Main power transformer families (collector -> transmission)
    "mpt_75mva": {"id": "mpt_75mva", "mva": 75.0, "z_pct": 8.0, "xr": 35.0,
                  "vector": "YNd1", "taps": "±10% / 33 steps (OLTC)", "verified": True},
    "mpt_140mva": {"id": "mpt_140mva", "mva": 140.0, "z_pct": 8.5, "xr": 40.0,
                   "vector": "YNd1", "taps": "±10% / 33 steps (OLTC)", "verified": True},
    "mpt_230mva": {"id": "mpt_230mva", "mva": 230.0, "z_pct": 9.0, "xr": 45.0,
                   "vector": "YNd1", "taps": "±10% / 33 steps (OLTC)", "verified": True},
}

# ---------------------------------------------------------------------------
# Collector cables (34.5 kV class, direct buried, typical spacing)
# ---------------------------------------------------------------------------

CABLES: dict[str, dict[str, Any]] = {
    "al_1000_35kv": {"id": "al_1000_35kv", "desc": "1000 kcmil Al XLPE 35 kV",
                     "ampacity_a": 585, "r_ohm_per_mi": 0.115, "x_ohm_per_mi": 0.205,
                     "verified": True},
    "al_750_35kv": {"id": "al_750_35kv", "desc": "750 kcmil Al XLPE 35 kV",
                    "ampacity_a": 500, "r_ohm_per_mi": 0.148, "x_ohm_per_mi": 0.215,
                    "verified": True},
}

# Gen-tie overhead line constants by voltage class (ACSR bundles, per mile).
GENTIE_LINES: dict[int, dict[str, Any]] = {
    500: {"r_ohm_per_mi": 0.012, "x_ohm_per_mi": 0.55, "ampacity_a": 3000},
    345: {"r_ohm_per_mi": 0.037, "x_ohm_per_mi": 0.58, "ampacity_a": 2000},
    230: {"r_ohm_per_mi": 0.062, "x_ohm_per_mi": 0.75, "ampacity_a": 1200},
    138: {"r_ohm_per_mi": 0.110, "x_ohm_per_mi": 0.79, "ampacity_a": 900},
    115: {"r_ohm_per_mi": 0.120, "x_ohm_per_mi": 0.80, "ampacity_a": 850},
    69:  {"r_ohm_per_mi": 0.280, "x_ohm_per_mi": 0.85, "ampacity_a": 600},
}


def catalog() -> dict[str, Any]:
    return {
        "inverters": list(INVERTERS.values()),
        "bess_units": list(BESS_UNITS.values()),
        "pad_transformers": list(PAD_TRANSFORMERS.values()),
        "main_transformers": list(MAIN_TRANSFORMERS.values()),
        "cables": list(CABLES.values()),
    }


# ---------------------------------------------------------------------------
# Matching free-text intake against the library
# ---------------------------------------------------------------------------

_INVERTER_PATTERNS = [
    (r"sg\s*4400|sungrow", "sungrow_sg4400ud_mv"),
    (r"sunny\s*central|sma|sc\s*4600", "sma_sc4600up"),
    (r"fs\s*3430|power\s*electronics", "pe_fs3430k"),
]

_BESS_PATTERNS = [
    (r"megapack|tesla", "tesla_megapack_2xl"),
]


def match_inverter(text: str | None) -> tuple[dict[str, Any], bool]:
    """(entry, matched) — falls back to the generic entry when unmatched."""
    t = (text or "").lower()
    for pat, key in _INVERTER_PATTERNS:
        if re.search(pat, t):
            return INVERTERS[key], True
    return INVERTERS["generic_pv_4mva"], False


def match_bess(text: str | None) -> tuple[dict[str, Any], bool]:
    t = (text or "").lower()
    for pat, key in _BESS_PATTERNS:
        if re.search(pat, t):
            return BESS_UNITS[key], True
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


def gentie_constants(kv: float) -> dict[str, Any]:
    """Nearest standard voltage class at or above the POI voltage."""
    classes = sorted(GENTIE_LINES)
    for c in classes:
        if kv <= c + 1:
            return {**GENTIE_LINES[c], "kv_class": c}
    top = classes[-1]
    return {**GENTIE_LINES[top], "kv_class": top}

"""OEM vendor dynamic-model file handling (.dyd).

Blueprint rule: GridPilot never invents OEM control parameters — it extracts
them from vendor-supplied model files and integrates them into the plant model
with an `oem_datasheet` source tag. Parsing is deterministic (no LLM): PSLF
.dyd records are tagged text.

`vendor_overrides` normalizes a vendor file into per-fleet parameter blocks:

    {"file": <name>,
     "pv":   {"models": {"gen": "REGC_A", ...}, "params": {"regc": {...}, ...}},
     "bess": {...}}                # present only when the file carries BESS records

The dict is JSON-serializable so it can ride inside the intake (like
`approvals`) and keep packet generation stateless.
"""

from __future__ import annotations

import re
from typing import Any

from backend.app.engine import equipment as lib

DYD_REC_RE = re.compile(
    r'^(\w+)\s+(\d+)\s+"([^"]+)"\s+([\d.]+)\s+"(\d+)"\s*:\s*#9\s*(.*)$')
DYD_PARAM_RE = re.compile(r'(?:"([\w]+)"\s+([-\w.]+))|(?:(\bmva)=([-\d.]+))')

# Writer-managed values — never taken from the vendor file.
_META_PARAMS = {"mva", "pmax", "pmin"}

_ROLE_BY_PREFIX = (("regc", "regc"), ("reec", "reec"), ("repc", "repc"))
_MODEL_KEY = {"regc": "gen", "reec": "elec", "plant": "plant", "repc": "plant"}


def parse_dyd(text: str) -> list[dict[str, Any]]:
    """PSLF .dyd model records: [{model, bus, name, kv, id, params}]."""
    records: list[dict[str, Any]] = []
    for line in text.splitlines():
        m = DYD_REC_RE.match(line.strip())
        if not m:
            continue
        model, bus, name, kv, cid, raw = m.groups()
        params: dict[str, float] = {}
        for pm in DYD_PARAM_RE.finditer(raw):
            key = (pm.group(1) or pm.group(3) or "").lower()
            val = pm.group(2) or pm.group(4)
            try:
                params[key] = float(val)
            except (TypeError, ValueError):
                continue
        records.append({"model": model.lower(), "bus": bus, "name": name.strip(),
                        "kv": float(kv), "id": cid, "params": params})
    return records


def _block_for(model: str) -> str | None:
    for prefix, block in _ROLE_BY_PREFIX:
        if model.startswith(prefix):
            return block
    return None


def _is_bess_record(rec: dict[str, Any]) -> bool:
    if "bess" in rec["name"].lower():
        return True
    if rec["model"].startswith("reec") and rec["model"] != "reec_a":
        return True
    return any(k.startswith("soc") for k in rec["params"])


def vendor_overrides(text: str, filename: str) -> dict[str, Any] | None:
    """Normalize a vendor .dyd into per-fleet parameter overrides, or None."""
    records = parse_dyd(text)
    if not records:
        return None
    out: dict[str, Any] = {"file": filename}
    for rec in records:
        block = _block_for(rec["model"])
        if block is None:
            continue
        fleet = "bess" if _is_bess_record(rec) else "pv"
        grp = out.setdefault(fleet, {"models": {}, "params": {}})
        model_key = "gen" if block == "regc" else ("elec" if block == "reec" else "plant")
        grp["models"][model_key] = rec["model"].upper()
        grp["params"][block] = {
            k: v for k, v in rec["params"].items() if k not in _META_PARAMS
        }
    if not out.get("pv") and not out.get("bess"):
        return None
    return out


def apply_vendor_entry(entry: dict[str, Any], grp: dict[str, Any],
                       filename: str) -> dict[str, Any]:
    """Overlay vendor parameter blocks on a library equipment entry.

    Vendor values win; library values fill any parameters the vendor file
    omits (the .dyr writer needs the full positional set).
    """
    params = {
        blk: {**entry["dyd_params"].get(blk, {}), **grp.get("params", {}).get(blk, {})}
        for blk in ("regc", "reec", "repc")
    }
    return {
        **entry,
        "dyd_params": params,
        "wecc_models": {**entry["wecc_models"], **grp.get("models", {})},
        "verified": True,
        "vendor_file": filename,
        "datasheet": f"Vendor model file {filename}",
    }


def demo_vendor_dyd_text(intake: dict[str, Any]) -> str:
    """The demo's example vendor package: the matched inverter's OEM blocks.

    Used both to preview the preloaded example file and to feed the same
    parser the real path uses, so the demo exercises the identical pipeline.
    """
    inv, _matched = lib.match_inverter(str(intake.get("inverter") or ""))
    wm, dp = inv["wecc_models"], inv["dyd_params"]
    kv = float(inv["ac_kv"])
    unit = re.sub(r"[^A-Za-z0-9]", "", str(inv["model"]))[:8].ljust(8) or "INV-UNIT"
    src = (f"OEM parameter set: {inv['datasheet']}" if inv.get("verified")
           else "GENERIC WECC parameters — replace with OEM MOD-026/027 data")

    def p(params: dict[str, Any]) -> str:
        return " ".join(f'"{k}" {v:g}' for k, v in params.items())

    return "\n".join([
        f"# {inv['vendor']} {inv['model']} — vendor PSLF dynamic model package",
        f"# Per-unit base {inv['mva']:g} MVA at {kv:g} kV — {src}",
        f'{wm["gen"].lower()} 1 "{unit}" {kv:.2f} "1" : #9 '
        f'mva={inv["mva"]:g} {p(dp["regc"])}',
        f'{wm["elec"].lower()} 1 "{unit}" {kv:.2f} "1" : #9 '
        f'mva={inv["mva"]:g} {p(dp["reec"])} "pmax" 1.0 "pmin" 0.0',
        f'{wm["plant"].lower()} 1 "{unit}" {kv:.2f} "1" : #9 '
        f'{p(dp["repc"])} "pmax" 1.0 "pmin" 0.0',
    ]) + "\n"

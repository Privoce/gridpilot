"""Phase 1 — Project graph.

A single, versioned, source-traced data model that every deliverable reads
from. Every parameter carries a source tag:

    developer                       entered/confirmed by the developer
    document_extraction             extracted from an uploaded document
    oem_datasheet                   from the equipment library (OEM data)
    iso_rule                        required/derived from the ISO rule set
    gridpilot_calculation           computed deterministically by GridPilot
    assumption_requiring_approval   GridPilot default pending engineer sign-off

The graph is a pure function of (intake, iso, provenance): the same inputs
always produce the same graph and the same version hash. That keeps the
serverless deployment stateless — any instance can rebuild the graph from the
intake carried in the request.

Mutation history rides inside the intake (`graph_history`) the same way
approvals do — who / what / when for every content-hash change — so the audit
trail survives the ?d= round trip without shared server state.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

SRC_DEV = "developer"
SRC_DOC = "document_extraction"
SRC_OEM = "oem_datasheet"
SRC_ISO = "iso_rule"
SRC_CALC = "gridpilot_calculation"
SRC_ASSUME = "assumption_requiring_approval"

SOURCE_LABELS = {
    SRC_DEV: "Developer",
    SRC_DOC: "Extracted from document",
    SRC_OEM: "OEM datasheet",
    SRC_ISO: "ISO rule",
    SRC_CALC: "GridPilot calculation",
    SRC_ASSUME: "Assumption — requires approval",
}

# Intake keys that are business/site/interconnection facts the developer owns.
_DEVELOPER_FACTS: dict[str, tuple[str, str]] = {
    # key: (label, unit)
    "legal_name": ("Legal entity name", ""),
    "state_of_origin": ("State of origin", ""),
    "signatory_name": ("Authorized signatory", ""),
    "signatory_title": ("Signatory title", ""),
    "contact_email": ("Contact email", ""),
    "contact_phone": ("Contact phone", ""),
    "project_name": ("Project name", ""),
    "gps_lat": ("GPS latitude", "deg"),
    "gps_lon": ("GPS longitude", "deg"),
    "county": ("County", ""),
    "state": ("State", ""),
    "site_acreage": ("Site acreage", "ac"),
    "site_control": ("Site exclusivity type", ""),
    "site_owner": ("Site owner / lessor", ""),
    "poi_name": ("Target POI", ""),
    "poi_voltage_kv": ("POI voltage", "kV"),
    "track": ("Process track", ""),
    "deliverability": ("Requested deliverability", ""),
    "cod": ("Target COD", ""),
    "gentie_mi": ("Gen-tie route length", "mi"),
    "shared_facilities": ("Shared facilities", ""),
    "queue_ref": ("Prior queue / study reference", ""),
    "substation_arrangement": ("Substation arrangement preference", ""),
    "site_constraints": ("Site constraints", ""),
    "project_type": ("Project type", ""),
    "gross_mva": ("Gross capacity", "MVA"),
    "gross_mw": ("Gross output", "MW"),
    "aux_mw": ("Auxiliary load", "MW"),
    "losses_mw": ("Losses to POI (declared)", "MW"),
    "net_mw_poi": ("Requested net MW at POI", "MW"),
    "bess_mw": ("BESS power", "MW"),
    "bess_mwh": ("BESS energy", "MWh"),
    "bess_charging": ("BESS charging source", ""),
    "inverter": ("Inverter selection", ""),
    "module": ("PV module", ""),
    "bess_vendor": ("BESS vendor", ""),
    "dyd_status": ("Vendor dynamic model status", ""),
    "transformer": ("Main transformer data", ""),
    "collector_kv": ("Collector voltage", "kV"),
}


def _num(v: Any) -> float | None:
    try:
        if v is None or v == "":
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


def build_graph(intake: dict[str, Any], iso: str | None = None,
                prov: dict[str, Any] | None = None) -> dict[str, Any]:
    """Build the base project graph from developer intake.

    `prov` maps intake keys to {"file": name} for values that came from AI
    document extraction (the client tracks this during the extraction step).

    Later phases (equipment, design, powerflow) add params/nodes/edges on top
    of the returned graph via their own entry points.
    """
    prov = prov or {}
    params: dict[str, dict[str, Any]] = {}

    for key, (label, unit) in _DEVELOPER_FACTS.items():
        raw = intake.get(key)
        if raw is None or raw == "":
            continue
        if isinstance(raw, dict):  # file metadata lives outside the graph
            continue
        src, origin = SRC_DEV, f"intake:{key}"
        if key in prov and isinstance(prov.get(key), dict) and prov[key].get("file"):
            src, origin = SRC_DOC, f"file:{prov[key]['file']}"
        params[key] = {
            "id": key, "label": label, "value": raw, "unit": unit,
            "source": src, "origin": origin,
        }

    graph: dict[str, Any] = {
        "schema_version": 1,
        "iso": (iso or "CAISO").upper(),
        "params": params,
        "nodes": [],
        "edges": [],
        "missing": [],
        "checks": [],
    }
    graph["version"] = graph_version(intake, iso)
    return graph


def graph_version(intake: dict[str, Any], iso: str | None = None) -> str:
    """Content-derived version id — same intake, same version.

    The history list itself is excluded so recording a mutation doesn't change
    the hash of the content it describes.
    """
    body = {k: v for k, v in intake.items() if k != "graph_history"}
    canonical = json.dumps({"iso": (iso or "CAISO").upper(), "intake": body},
                           sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:12]


# File / structured keys whose names belong in the mutation snapshot.
_HISTORY_FILES = (
    "file_site_control", "file_technical", "file_bess", "file_signatory",
    "file_dyd", "file_boundary", "file_base_case",
)


def _history_snapshot(intake: dict[str, Any]) -> dict[str, Any]:
    """Compact fact snapshot used to compute the next mutation's `changed` list."""
    snap: dict[str, Any] = {}
    for key in _DEVELOPER_FACTS:
        raw = intake.get(key)
        if raw is None or raw == "":
            continue
        if isinstance(raw, dict):
            continue
        snap[key] = raw
    for fk in _HISTORY_FILES:
        meta = intake.get(fk)
        if isinstance(meta, dict) and str(meta.get("name") or "").strip() and not meta.get("staged"):
            snap[fk] = str(meta["name"])
    if isinstance(intake.get("vendor_dyd"), dict):
        snap["vendor_dyd"] = intake["vendor_dyd"].get("file") or "parsed"
    custom = intake.get("custom_equipment")
    if isinstance(custom, list) and custom:
        snap["custom_equipment"] = sorted(
            f"{e.get('vendor', '')} {e.get('model', '')}".strip() for e in custom
            if isinstance(e, dict)
        )
    approvals = intake.get("approvals")
    if isinstance(approvals, dict) and approvals:
        snap["approvals"] = sorted(approvals.keys())
    return snap


def record_history(intake: dict[str, Any], *, by: str,
                   note: str | None = None, iso: str | None = None) -> list[dict[str, Any]]:
    """Append a who/what/when entry when the graph content hash changes.

    Mutates `intake['graph_history']` in place (same pattern as `approvals`).
    Returns the full history list. No-ops when the version is unchanged.
    """
    version = graph_version(intake, iso)
    hist = list(intake.get("graph_history") or [])
    if hist and hist[-1].get("version") == version:
        return hist

    snap = _history_snapshot(intake)
    prev = (hist[-1].get("snapshot") if hist else {}) or {}
    changed = sorted(
        k for k in set(snap) | set(prev)
        if snap.get(k) != prev.get(k)
    )
    if not hist:
        summary = note or "Initial project graph"
    elif note:
        summary = note
    elif changed:
        summary = f"{len(changed)} field(s) updated"
    else:
        summary = "Graph regenerated"

    entry = {
        "version": version,
        "at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "by": (by or "GridPilot").strip() or "GridPilot",
        "note": summary,
        "changed": changed[:48],
        "snapshot": snap,
    }
    # Keep the full snapshot only on the latest entry — older rows need the
    # audit fields, not the bulky fact map (keeps ?d= packet URLs small).
    for prev in hist:
        prev.pop("snapshot", None)
    hist.append(entry)
    if len(hist) > 40:
        hist = hist[-40:]
    intake["graph_history"] = hist
    return hist


def history_public(intake: dict[str, Any]) -> list[dict[str, Any]]:
    """History rows for API / UI — omit the bulky snapshot payload."""
    out = []
    for e in intake.get("graph_history") or []:
        if not isinstance(e, dict):
            continue
        out.append({
            "version": e.get("version", ""),
            "at": e.get("at", ""),
            "by": e.get("by", ""),
            "note": e.get("note", ""),
            "changed": list(e.get("changed") or []),
        })
    return out


def add_param(graph: dict[str, Any], pid: str, label: str, value: Any, unit: str,
              source: str, origin: str, trace: str | None = None) -> dict[str, Any]:
    p = {"id": pid, "label": label, "value": value, "unit": unit,
         "source": source, "origin": origin}
    if trace:
        p["trace"] = trace
    graph["params"][pid] = p
    return p


def add_node(graph: dict[str, Any], nid: str, ntype: str, label: str,
             **attrs: Any) -> dict[str, Any]:
    node = {"id": nid, "type": ntype, "label": label, **attrs}
    graph["nodes"].append(node)
    return node


def add_edge(graph: dict[str, Any], src: str, dst: str, etype: str,
             **attrs: Any) -> dict[str, Any]:
    edge = {"from": src, "to": dst, "type": etype, **attrs}
    graph["edges"].append(edge)
    return edge


def node(graph: dict[str, Any], nid: str) -> dict[str, Any] | None:
    return next((n for n in graph["nodes"] if n["id"] == nid), None)


def assumptions(graph: dict[str, Any]) -> list[dict[str, Any]]:
    """All parameters that require engineer approval, sorted by id."""
    return sorted(
        (p for p in graph["params"].values() if p["source"] == SRC_ASSUME),
        key=lambda p: p["id"],
    )


def approval_state(graph: dict[str, Any], intake: dict[str, Any]) -> dict[str, Any]:
    """Merge the intake's approval record onto the graph's assumption list.

    Approvals ride inside the intake (key `approvals`: {param_id: {by, at}})
    so they survive the stateless ?d= round trip like everything else.
    """
    approved: dict[str, Any] = intake.get("approvals") or {}
    items = []
    for p in assumptions(graph):
        rec = approved.get(p["id"]) if isinstance(approved, dict) else None
        items.append({**p, "approved": bool(rec), "approval": rec or None})
    pending = [i for i in items if not i["approved"]]
    return {"items": items, "pending": len(pending), "total": len(items),
            "all_approved": not pending}


def source_trace(graph: dict[str, Any]) -> list[dict[str, Any]]:
    """Flat, sorted source-trace table for reports and the packet appendix."""
    rows = []
    for p in sorted(graph["params"].values(), key=lambda x: x["id"]):
        rows.append({
            "id": p["id"], "label": p["label"], "value": p["value"],
            "unit": p["unit"], "source": p["source"],
            "source_label": SOURCE_LABELS.get(p["source"], p["source"]),
            "origin": p["origin"], "trace": p.get("trace") or "",
        })
    return rows

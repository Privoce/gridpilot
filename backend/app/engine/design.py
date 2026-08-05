"""Phase 3 — Topology & design engine.

Deterministic plant sizing from the project graph facts:

    inverters -> inverter blocks (pad transformer skids)
              -> collector feeders (ampacity constrained)
              -> collector bus
              -> main transformer(s)
              -> gen-tie
              -> POI

Every derived quantity is written back into the graph as a
`gridpilot_calculation` param with its formula recorded; every engineering
default that a licensed engineer should confirm is written as an
`assumption_requiring_approval` param.
"""

from __future__ import annotations

import math
from typing import Any

from backend.app.engine import equipment as lib
from backend.app.engine import vendor_models as vendor_lib
from backend.app.engine.graph import (
    SRC_ASSUME, SRC_CALC, SRC_DOC, SRC_OEM,
    add_edge, add_node, add_param, _num,
)

# Feeder loading margin per CAISO/utility collector design practice.
FEEDER_LOADING_FACTOR = 0.90
# Main transformer margin above gross MVA.
MPT_MARGIN = 1.05


def design_plant(graph: dict[str, Any], intake: dict[str, Any]) -> dict[str, Any]:
    """Size the plant and write topology into the graph.

    Returns a design summary dict (also used by the API and reports):
    {counts, equipment: schedule rows, missing: [...], topology: text tree}
    """
    missing: list[dict[str, str]] = []

    gross_mw = _num(intake.get("gross_mw")) or 0.0
    gross_mva = _num(intake.get("gross_mva")) or gross_mw * 1.05
    bess_mw = _num(intake.get("bess_mw")) or 0.0
    bess_mwh = _num(intake.get("bess_mwh")) or 0.0
    pv_mw = max(gross_mw - bess_mw, 0.0)
    poi_kv = _num(intake.get("poi_voltage_kv")) or 230.0
    col_kv = _num(intake.get("collector_kv")) or 34.5

    if not _num(intake.get("gross_mw")):
        missing.append({"key": "gross_mw", "label": "Gross output (MW)",
                        "impact": "Plant sizing and all model outputs"})
    if bess_mw > 0 and not bess_mwh:
        missing.append({"key": "bess_mwh", "label": "BESS energy (MWh)",
                        "impact": "BESS unit count and Attachment A storage data"})

    # --- Equipment selection --------------------------------------------
    # Datasheet-ingested records (riding in the intake) win over library
    # matching: the customer explicitly reviewed those ratings. They remain
    # unverified until the engineer of record signs off.
    custom_list = intake.get("custom_equipment")
    custom_list = custom_list if isinstance(custom_list, list) else []

    c_inv = lib.match_custom(str(intake.get("inverter") or ""), custom_list, "pv_inverter")
    if c_inv:
        inverter, inv_matched = lib.custom_entry(c_inv), True
        add_param(graph, "equip.inverter", "Inverter (datasheet entry)",
                  f"{inverter['vendor']} {inverter['model']}", "",
                  SRC_DOC, f"datasheet:{c_inv.get('source') or 'upload'}")
        add_param(graph, "equip.inverter_verify", "Datasheet inverter entry verification",
                  f"{inverter['vendor']} {inverter['model']} — {inverter['mva']:g} MVA, "
                  f"{inverter['ac_kv']:g} kV", "",
                  SRC_ASSUME, "datasheet_ingest",
                  "Ratings extracted from an uploaded datasheet — verify against the OEM "
                  "document; dynamic models remain generic WECC until vendor files arrive")
    else:
        inverter, inv_matched = lib.match_inverter(str(intake.get("inverter") or ""))
        add_param(graph, "equip.inverter", "Inverter (library match)",
                  f"{inverter['vendor']} {inverter['model']}", "",
                  SRC_OEM if inv_matched else SRC_ASSUME,
                  f"library:{inverter['id']}",
                  None if inv_matched else
                  "No library match for the intake inverter text — generic 4.0 MVA unit assumed")
    if not inv_matched and str(intake.get("inverter") or "").strip():
        missing.append({"key": "inverter", "label": "Inverter model (library match)",
                        "impact": "OEM dynamic model parameters — generic WECC set in use"})

    bess_unit = None
    bess_matched = False
    if bess_mw > 0:
        c_bess = lib.match_custom(str(intake.get("bess_vendor") or ""), custom_list, "bess")
        if c_bess:
            bess_unit, bess_matched = lib.custom_entry(c_bess), True
            add_param(graph, "equip.bess", "BESS unit (datasheet entry)",
                      f"{bess_unit['vendor']} {bess_unit['model']}", "",
                      SRC_DOC, f"datasheet:{c_bess.get('source') or 'upload'}")
            add_param(graph, "equip.bess_verify", "Datasheet BESS entry verification",
                      f"{bess_unit['vendor']} {bess_unit['model']} — {bess_unit['mw']:g} MW / "
                      f"{bess_unit['mwh']:g} MWh", "",
                      SRC_ASSUME, "datasheet_ingest",
                      "Ratings extracted from an uploaded datasheet — verify against the OEM "
                      "document before submission")
        else:
            bess_unit, bess_matched = lib.match_bess(str(intake.get("bess_vendor") or ""))
            add_param(graph, "equip.bess", "BESS unit (library match)",
                      f"{bess_unit['vendor']} {bess_unit['model']}", "",
                      SRC_OEM if bess_matched else SRC_ASSUME,
                      f"library:{bess_unit['id']}",
                      None if bess_matched else
                      "No library match for the intake BESS text — generic 2 MW block assumed")

    # --- Vendor OEM model file (parsed at extraction) -----------------------
    # Parameter blocks from an uploaded vendor .dyd replace the library set;
    # library values fill anything the vendor file omits.
    vendor = intake.get("vendor_dyd")
    vendor = vendor if isinstance(vendor, dict) else None
    if vendor:
        vfile = str(vendor.get("file") or "vendor .dyd")
        if vendor.get("pv"):
            inverter = vendor_lib.apply_vendor_entry(inverter, vendor["pv"], vfile)
        if vendor.get("bess") and bess_unit is not None:
            bess_unit = vendor_lib.apply_vendor_entry(bess_unit, vendor["bess"], vfile)
        add_param(graph, "equip.vendor_dyd", "Vendor dynamic model file", vfile, "",
                  SRC_OEM, "intake:file_dyd",
                  "OEM parameter blocks parsed from the vendor-supplied model file")

    # --- PV inverter sizing ----------------------------------------------
    n_inv = math.ceil(pv_mw / inverter["mw"]) if pv_mw > 0 else 0
    if n_inv:
        add_param(graph, "design.n_inverters", "PV inverter count", n_inv, "units",
                  SRC_CALC, "design_engine",
                  f"ceil(PV {pv_mw:g} MW / {inverter['mw']:g} MW per {inverter['model']})")

    # Two inverters per skid is the standard block for this class.
    inv_per_block = 2
    n_blocks = math.ceil(n_inv / inv_per_block) if n_inv else 0
    block_mva = inv_per_block * inverter["mva"]
    pad = lib.pick_pad_transformer(block_mva)
    if n_blocks:
        add_param(graph, "design.n_blocks", "Inverter blocks (skids)", n_blocks, "skids",
                  SRC_CALC, "design_engine",
                  f"ceil({n_inv} inverters / {inv_per_block} per skid)")
        add_param(graph, "design.pad_xfmr", "Pad transformer per block",
                  f"{pad['mva']:g} MVA, {inverter['ac_kv']:g}/{col_kv:g} kV, Z={pad['z_pct']:g}%",
                  "", SRC_OEM, f"library:{pad['id']}")

    # --- BESS sizing -------------------------------------------------------
    n_bess = 0
    if bess_unit and bess_mw > 0:
        by_power = math.ceil(bess_mw / bess_unit["mw"])
        by_energy = math.ceil(bess_mwh / bess_unit["mwh"]) if bess_mwh else 0
        n_bess = max(by_power, by_energy)
        add_param(graph, "design.n_bess", "BESS unit count", n_bess, "units",
                  SRC_CALC, "design_engine",
                  f"max(ceil({bess_mw:g}/{bess_unit['mw']:g} MW), "
                  f"ceil({bess_mwh:g}/{bess_unit['mwh']:g} MWh))")

    # --- Collector feeders ---------------------------------------------
    # PV blocks and the BESS segment are fed separately: feeder count is sized
    # on the PV block MVA; BESS units get their own collector position.
    cable = lib.CABLES["al_1000_35kv"]
    feeder_mva_limit = (math.sqrt(3) * col_kv * cable["ampacity_a"] / 1000.0) * FEEDER_LOADING_FACTOR
    pv_block_mva = n_blocks * block_mva
    total_mva = pv_block_mva + (n_bess * bess_unit["mva"] if bess_unit else 0)
    n_feeders = max(1, math.ceil(pv_block_mva / feeder_mva_limit)) if n_blocks else 0
    if n_feeders:
        add_param(graph, "design.n_feeders", "Collector feeders (PV)", n_feeders, "feeders",
                  SRC_CALC, "design_engine",
                  f"ceil({pv_block_mva:.1f} MVA PV / {feeder_mva_limit:.1f} MVA per feeder "
                  f"({cable['desc']} at {FEEDER_LOADING_FACTOR:.0%} loading))")
        add_param(graph, "design.feeder_cable", "Feeder cable", cable["desc"], "",
                  SRC_OEM, f"library:{cable['id']}")

    # Average feeder length: engineering default from site acreage.
    acres = _num(intake.get("site_acreage")) or 0.0
    if acres:
        # Square site side in miles; average feeder run ~ 60% of the side.
        side_mi = math.sqrt(acres / 640.0)
        feeder_mi = round(0.6 * side_mi, 2)
        origin, src = "design_engine", SRC_CALC
        trace = f"0.6 x sqrt({acres:g} ac / 640) mi — layout-based estimate"
    else:
        feeder_mi, src, origin = 0.75, SRC_ASSUME, "default"
        trace = "No site acreage — 0.75 mi average feeder run assumed"
        missing.append({"key": "site_acreage", "label": "Site acreage",
                        "impact": "Feeder length estimate and site drawing"})
    add_param(graph, "design.feeder_len_mi", "Average feeder length", feeder_mi, "mi",
              src, origin, trace)

    # --- Main transformer(s) ---------------------------------------------
    req_mva = total_mva if total_mva else gross_mva
    req_with_margin = req_mva * MPT_MARGIN
    # Prefer 2 units above 100 MVA for redundancy/transportability; a developer
    # substation-arrangement preference wins when a standard family unit can
    # cover the per-unit rating.
    n_mpt = 2 if req_with_margin > 100 else 1
    pref = str(intake.get("substation_arrangement") or "")
    pref_n = {"Single main transformer": 1, "Two main transformers (N-1)": 2}.get(pref)
    pref_applied = pref_infeasible = False
    if pref_n and pref_n != n_mpt:
        if lib.pick_main_transformer(req_with_margin / pref_n)["mva"] >= req_with_margin / pref_n:
            n_mpt, pref_applied = pref_n, True
        else:
            pref_infeasible = True
    unit_mva = req_with_margin / n_mpt
    mpt = lib.pick_main_transformer(unit_mva)
    if pref_applied:
        add_param(graph, "design.n_mpt", "Main transformer count", n_mpt, "units",
                  "developer", "intake:substation_arrangement",
                  f"Developer preference \"{pref}\" — {req_with_margin:.0f} MVA required, "
                  f"{mpt['mva']:g} MVA family unit covers {unit_mva:.0f} MVA per unit")
    else:
        infeasible_note = (f"; preference \"{pref}\" not feasible with standard families "
                           f"({req_with_margin / pref_n:.0f} MVA per unit needed)"
                           if pref_infeasible else "")
        add_param(graph, "design.n_mpt", "Main transformer count", n_mpt, "units",
                  SRC_CALC, "design_engine",
                  f"{req_with_margin:.0f} MVA required ({req_mva:.0f} x {MPT_MARGIN}) — "
                  f"{'two units above 100 MVA' if n_mpt == 2 else 'single unit'}"
                  + infeasible_note)
    add_param(graph, "design.mpt", "Main transformer",
              f"{n_mpt} x {mpt['mva']:g} MVA, {col_kv:g}/{poi_kv:g} kV, "
              f"Z={mpt['z_pct']:g}%, {mpt['vector']}",
              "", SRC_OEM, f"library:{mpt['id']}")

    # If the developer supplied GSU data in intake, it wins over the family pick
    # for the schedule display, but keeps the library impedance for calc unless
    # parseable (kept simple: intake text is display-only).

    # --- Gen-tie -----------------------------------------------------------
    gentie_mi = _num(intake.get("gentie_mi"))
    gentie_provided = gentie_mi is not None
    if gentie_mi is None:
        gentie_mi = 5.0
        add_param(graph, "design.gentie_mi", "Gen-tie length", gentie_mi, "mi",
                  SRC_ASSUME, "default",
                  "Gen-tie route not provided — 5.0 mi assumed pending routing study")
    else:
        add_param(graph, "design.gentie_mi", "Gen-tie length", gentie_mi, "mi",
                  "developer", "intake:gentie_mi")
    line = lib.gentie_constants(poi_kv)
    add_param(graph, "design.gentie_line", "Gen-tie construction",
              f"{line['kv_class']} kV class OHL, {line['ampacity_a']} A", "",
              SRC_OEM, f"library:gentie_{line['kv_class']}kv")

    # POI short-circuit strength: needed for short-circuit results; default is
    # an assumption until the utility provides the actual value.
    poi_sc_mva = _num(intake.get("poi_sc_mva"))
    if poi_sc_mva is None:
        poi_sc_mva = 5000.0
        add_param(graph, "design.poi_sc_mva", "POI short-circuit strength", poi_sc_mva, "MVA",
                  SRC_ASSUME, "default",
                  "Utility three-phase short-circuit duty at the POI not provided — 5,000 MVA assumed")
    else:
        add_param(graph, "design.poi_sc_mva", "POI short-circuit strength", poi_sc_mva, "MVA",
                  "developer", "intake:poi_sc_mva")

    # --- Topology nodes/edges ---------------------------------------------
    graph["nodes"] = []
    graph["edges"] = []
    add_node(graph, "poi", "poi", str(intake.get("poi_name") or "POI"), kv=poi_kv)
    add_node(graph, "hv_bus", "bus", f"{poi_kv:g} kV project substation bus", kv=poi_kv)
    add_edge(graph, "hv_bus", "poi", "gentie", miles=gentie_mi,
             r_ohm_per_mi=line["r_ohm_per_mi"], x_ohm_per_mi=line["x_ohm_per_mi"])
    add_node(graph, "col_bus", "bus", f"{col_kv:g} kV collector bus", kv=col_kv)
    for i in range(n_mpt):
        nid = f"mpt_{i + 1}"
        add_node(graph, nid, "transformer", f"Main transformer {i + 1} — {mpt['mva']:g} MVA",
                 mva=mpt["mva"], z_pct=mpt["z_pct"], xr=mpt["xr"], vector=mpt["vector"])
        add_edge(graph, "col_bus", nid, "winding", side="lv")
        add_edge(graph, nid, "hv_bus", "winding", side="hv")

    # Even block distribution: first (n_blocks % n_feeders) feeders take one extra.
    base, extra = (n_blocks // n_feeders, n_blocks % n_feeders) if n_feeders else (0, 0)
    bess_assigned = False
    for f in range(n_feeders):
        fid = f"feeder_{f + 1}"
        nb = base + (1 if f < extra else 0)
        add_node(graph, fid, "feeder", f"Collector feeder {f + 1} — {nb} blocks",
                 blocks=nb, cable=cable["id"], miles=feeder_mi)
        add_edge(graph, fid, "col_bus", "cable", miles=feeder_mi,
                 r_ohm_per_mi=cable["r_ohm_per_mi"], x_ohm_per_mi=cable["x_ohm_per_mi"])
    # BESS units get their own collector-bus position.
    if bess_unit and n_bess:
        add_node(graph, "bess_seg", "bess_segment",
                 f"BESS segment — {n_bess} x {bess_unit['model']}",
                 units=n_bess, unit_mw=bess_unit["mw"], unit_mwh=bess_unit["mwh"])
        add_edge(graph, "bess_seg", "col_bus", "cable", miles=round(feeder_mi * 0.5, 2),
                 r_ohm_per_mi=cable["r_ohm_per_mi"], x_ohm_per_mi=cable["x_ohm_per_mi"])
        bess_assigned = True
    add_node(graph, "inv_fleet", "inverter_fleet",
             f"{n_inv} x {inverter['vendor']} {inverter['model']}",
             units=n_inv, unit_mva=inverter["mva"], unit_mw=inverter["mw"],
             blocks=n_blocks, pad_mva=pad["mva"] if n_blocks else 0,
             pad_z_pct=pad["z_pct"] if n_blocks else 0)
    if n_feeders:
        add_edge(graph, "inv_fleet", "feeder_1", "aggregate")

    # --- Equipment schedule -------------------------------------------------
    schedule: list[dict[str, Any]] = []
    if n_inv:
        schedule.append({
            "item": "PV inverter", "make_model": f"{inverter['vendor']} {inverter['model']}",
            "qty": n_inv, "rating": f"{inverter['mva']:g} MVA / {inverter['mw']:g} MW",
            "source": inverter["datasheet"],
            "verified": inverter["verified"] and (inv_matched or bool(inverter.get("vendor_file"))),
        })
        schedule.append({
            "item": "Inverter block pad transformer", "make_model": f"{pad['mva']:g} MVA Dyn11",
            "qty": n_blocks, "rating": f"{inverter['ac_kv']:g}/{col_kv:g} kV, Z={pad['z_pct']:g}%",
            "source": pad["datasheet"], "verified": True,
        })
    if bess_unit and n_bess:
        schedule.append({
            "item": "BESS AC block", "make_model": f"{bess_unit['vendor']} {bess_unit['model']}",
            "qty": n_bess, "rating": f"{bess_unit['mw']:g} MW / {bess_unit['mwh']:g} MWh",
            "source": bess_unit["datasheet"],
            "verified": bess_unit["verified"] and (bess_matched or bool(bess_unit.get("vendor_file"))),
        })
    if n_feeders:
        schedule.append({
            "item": "Collector feeder", "make_model": cable["desc"],
            "qty": n_feeders, "rating": f"{cable['ampacity_a']} A, ~{feeder_mi:g} mi avg",
            "source": "Feeder study", "verified": True,
        })
    schedule.append({
        "item": "Main power transformer", "make_model": f"{mpt['mva']:g} MVA {mpt['vector']} OLTC",
        "qty": n_mpt, "rating": f"{col_kv:g}/{poi_kv:g} kV, Z={mpt['z_pct']:g}% @ {mpt['mva']:g} MVA",
        "source": "Standard family — confirm with procurement", "verified": True,
    })
    schedule.append({
        "item": "Gen-tie line", "make_model": f"{line['kv_class']} kV OHL",
        "qty": 1, "rating": f"{gentie_mi:g} mi, {line['ampacity_a']} A",
        "source": "Developer" if gentie_provided else "Routing assumption",
        "verified": gentie_provided,
    })

    graph["missing"] = missing
    topology_text = _topology_text(n_inv, inverter, n_blocks, n_feeders, col_kv,
                                   n_mpt, mpt, poi_kv, gentie_mi,
                                   n_bess, bess_unit)
    return {
        "counts": {
            "inverters": n_inv, "blocks": n_blocks, "feeders": n_feeders,
            "bess_units": n_bess, "main_transformers": n_mpt,
        },
        "bess_mw": bess_mw, "bess_mwh": bess_mwh, "pv_mw": pv_mw,
        "inverter": inverter, "bess_unit": bess_unit, "pad": pad, "mpt": mpt,
        "cable": cable, "line": line,
        "feeder_mi": feeder_mi, "gentie_mi": gentie_mi,
        "total_mva": round(total_mva, 1), "poi_sc_mva": poi_sc_mva,
        "schedule": schedule,
        "missing": missing,
        "topology": topology_text,
        "bess_assigned": bess_assigned,
    }


def _topology_text(n_inv: int, inverter: dict, n_blocks: int, n_feeders: int,
                   col_kv: float, n_mpt: int, mpt: dict, poi_kv: float,
                   gentie_mi: float, n_bess: int, bess_unit: dict | None) -> str:
    parts = []
    if n_inv:
        parts.append(f"{n_inv} x {inverter['model']} inverters")
        parts.append(f"{n_blocks} inverter blocks")
    if n_bess and bess_unit:
        parts.append(f"{n_bess} x {bess_unit['model']} BESS")
    parts.append(f"{n_feeders} collector feeders")
    parts.append(f"{col_kv:g} kV collector bus")
    parts.append(f"{n_mpt} x {mpt['mva']:g} MVA main transformer{'s' if n_mpt > 1 else ''}")
    parts.append(f"{poi_kv:g} kV substation")
    parts.append(f"{gentie_mi:g}-mile gen-tie")
    parts.append("POI")
    return " -> ".join(parts)

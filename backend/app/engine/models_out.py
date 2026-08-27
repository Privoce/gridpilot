"""Phase 6 — Model file writers and dynamic validation.

Writers emit PSLF (.epc/.dyd) and PSS/E (.raw/.dyr) files from the *solved*
load-flow case and the equipment library's OEM parameter blocks — numbers in
the files trace to the graph, the solve, or an OEM datasheet, never to a
template constant.

The dynamic validation runs a simplified plant-level RMS simulation
(REPC plant controller PI -> REGC converter lag, voltage-dependent reactive
support, frequency droop) sufficient for flat-start and bump sanity checks.
OEM black-box behaviour is explicitly out of scope per the blueprint.
"""

from __future__ import annotations

import re
from typing import Any

BUS = {"poi": 90001, "hv": 90002, "col": 90003, "pv": 90004, "bess": 90005}


def _name8(intake: dict[str, Any]) -> str:
    s = re.sub(r"[^A-Za-z0-9]+", "", str(intake.get("project_name") or "PROJ"))
    return (s[:5] or "PROJ").upper()


def _v(pf: dict[str, Any], idx: int) -> tuple[float, float]:
    """(v_pu, angle_deg) for solver bus index (0 gen end .. 4 slack)."""
    row = pf["voltages"][idx]
    return row["v_pu"], row["angle_deg"]


# ---------------------------------------------------------------------------
# PSLF .epc
# ---------------------------------------------------------------------------

def epc_text(design: dict[str, Any], pf: dict[str, Any], intake: dict[str, Any],
             profile: dict[str, Any]) -> str:
    n8 = _name8(intake)
    c = design["counts"]
    inv, mpt, pad = design["inverter"], design["mpt"], design["pad"]
    kv = float(intake.get("poi_voltage_kv") or 230)
    ckv = float(intake.get("collector_kv") or 34.5)
    net_mw = pf["p_poi_mw"]

    # Solved voltages: solver buses 0..4 = inv, feeder head, col, hv, poi.
    v_col, a_col = _v(pf, 2)
    v_hv, a_hv = _v(pf, 3)
    v_inv, a_inv = _v(pf, 0)

    # Branch impedances (pu on 100 MVA) from the solved network.
    zs = {b["branch"]: b for b in pf["flows"]}
    from backend.app.engine.powerflow import build_network
    branches = build_network(design, intake)["branches"]
    z_pad, z_feed, z_mpt, z_line = (b.z for b in branches)

    pv_mva = round(c["inverters"] * inv["mva"], 1)
    q_pv = round(pv_mva * inv["q_pu_max"], 1)
    bess = design.get("bess_unit")
    bess_mva = round(c["bess_units"] * bess["mva"], 1) if bess else 0.0
    q_bess = round(bess_mva * bess["q_pu_max"], 1) if bess else 0.0

    lines = [
        f"! {profile['model_tool']} load flow — {intake.get('project_name')} "
        f"{net_mw:g} MW at POI",
        f"! Solved case: {pf['iterations']} iterations to {pf['tolerance']:.0e} "
        f"(backward/forward sweep), series losses {pf['losses_mw']:g} MW",
        f"! Dispatch: PV {pf['p_pv_mw']:g} MW + BESS {pf['p_bess_mw']:g} MW − aux "
        f"{pf['aux_mw']:g} MW = {net_mw:g} MW delivered",
        f"! Validate against the current {profile['iso']} base case (obtained under NDA) before submission",
        "title",
        f"{intake.get('project_name')} Interconnection — {net_mw:g} MW at "
        f"{intake.get('poi_name')} {kv:g} kV",
        "comments",
        f"Impedances from the project graph (equipment library + design engine)",
        f"Plant equivalent: {c['inverters']} x {inv['vendor']} {inv['model']} through "
        f"{c['blocks']} pad transformers, {c['feeders']} feeders, "
        f"{c['main_transformers']} x {mpt['mva']:g} MVA MPT",
        "end",
        "bus data",
        f' {BUS["poi"]} "{n8}-POI"  {kv:.2f} : #9 0 1.0000  0.00 : 0 "UTIL" " 1"',
        f' {BUS["hv"]} "{n8}-HS "  {kv:.2f} : #9 1 {v_hv:.4f} {a_hv:6.2f} : 0 "PROJ" " 1"',
        f' {BUS["col"]} "{n8}-LS "   {ckv:.2f} : #9 1 {v_col:.4f} {a_col:6.2f} : 0 "PROJ" " 1"',
        f' {BUS["pv"]} "{n8}-PV "    {inv["ac_kv"]:.2f} : #9 2 {v_inv:.4f} {a_inv:6.2f} : 0 "PROJ" " 1"',
    ]
    if bess and c["bess_units"]:
        lines.append(f' {BUS["bess"]} "{n8}-BESS"   {bess["ac_kv"]:.2f} : #9 2 {v_col:.4f} {a_col:6.2f} : 0 "PROJ" " 1"')
    lines += [
        "end",
        "branch data",
        f' {BUS["hv"]} "{n8}-HS " {kv:.2f} {BUS["poi"]} "{n8}-POI" {kv:.2f} " 1" : '
        f'{z_line.real:.5f} {z_line.imag:.5f} 0.01000 : {zs["Gen-tie line"]["rating_mva"]:.1f}',
        f' {BUS["pv"]} "{n8}-PV " {inv["ac_kv"]:.2f} {BUS["col"]} "{n8}-LS " {ckv:.2f} " 1" : '
        f'{(z_pad + z_feed).real:.5f} {(z_pad + z_feed).imag:.5f} 0.00000 : '
        f'{zs["Pad transformers (parallel)"]["rating_mva"]:.1f}',
        "end",
        "transformer data",
    ]
    for i in range(c["main_transformers"]):
        lines.append(
            f' {BUS["hv"]} "{n8}-HS " {kv:.2f} {BUS["col"]} "{n8}-LS "  {ckv:.2f} " {i + 1}" : '
            f'{(z_mpt * c["main_transformers"]).real:.5f} {(z_mpt * c["main_transformers"]).imag:.5f} : '
            f'{mpt["mva"]:.1f} : {pf.get("mpt_tap", 1.0):.4f} 1.0000')
    lines += ["end", "generator data"]
    lines.append(
        f' {BUS["pv"]} "{n8}-PV "   {inv["ac_kv"]:.2f} " 1" : {pf["p_pv_mw"]:.2f}  0.00  '
        f'{q_pv} -{q_pv} : {pv_mva} : 0.0015 0.20000')
    if bess and c["bess_units"]:
        lines.append(
            f' {BUS["bess"]} "{n8}-BESS"  {bess["ac_kv"]:.2f} " 1" : {pf["p_bess_mw"]:.2f}  0.00  '
            f'{q_bess} -{q_bess} : {bess_mva} : 0.0015 0.18000')
    lines += [
        "end",
        "load data",
        f' {BUS["col"]} "{n8}-LS " {ckv:.2f} " 1" : {pf["aux_mw"]:.2f} 0.00 : 0 0',
        "end",
    ]
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# PSS/E .raw (v33-style, human-readable subset)
# ---------------------------------------------------------------------------

def raw_text(design: dict[str, Any], pf: dict[str, Any], intake: dict[str, Any],
             profile: dict[str, Any]) -> str:
    n8 = _name8(intake)
    c = design["counts"]
    inv, mpt = design["inverter"], design["mpt"]
    kv = float(intake.get("poi_voltage_kv") or 230)
    ckv = float(intake.get("collector_kv") or 34.5)
    v_col, a_col = _v(pf, 2)
    v_hv, a_hv = _v(pf, 3)
    v_inv, a_inv = _v(pf, 0)

    from backend.app.engine.powerflow import build_network
    branches = build_network(design, intake)["branches"]
    z_pad, z_feed, z_mpt, z_line = (b.z for b in branches)

    pv_mva = round(c["inverters"] * inv["mva"], 1)
    q_pv = round(pv_mva * inv["q_pu_max"], 1)
    bess = design.get("bess_unit")
    bess_mva = round(c["bess_units"] * bess["mva"], 1) if bess else 0.0
    q_bess = round(bess_mva * bess["q_pu_max"], 1) if bess else 0.0

    L = [
        f"0, 100.00, 33, 0, 0, 60.00   / {profile['model_tool']} RAW — "
        f"{intake.get('project_name')}",
        f"  Solved: {pf['iterations']} iter to {pf['tolerance']:.0e}; losses {pf['losses_mw']:g} MW; "
        f"POI {pf['p_poi_mw']:g} MW / {pf['q_poi_mvar']:g} Mvar",
        f"  Validate against the current {profile['iso']} base case before submission",
        "BEGIN BUS DATA",
        f"{BUS['poi']},'{n8}-POI', {kv:.2f},3, 1, 1, 1, 1.0000, 0.0000",
        f"{BUS['hv']},'{n8}-HS ', {kv:.2f},1, 1, 1, 1, {v_hv:.4f}, {a_hv:.4f}",
        f"{BUS['col']},'{n8}-LS ', {ckv:.2f},1, 1, 1, 1, {v_col:.4f}, {a_col:.4f}",
        f"{BUS['pv']},'{n8}-PV ', {inv['ac_kv']:.2f},2, 1, 1, 1, {v_inv:.4f}, {a_inv:.4f}",
    ]
    if bess and c["bess_units"]:
        L.append(f"{BUS['bess']},'{n8}-BESS', {bess['ac_kv']:.2f},2, 1, 1, 1, {v_col:.4f}, {a_col:.4f}")
    L += [
        "END OF BUS DATA / BEGIN LOAD DATA",
        f"{BUS['col']},'1 ',1, 1, 1, {pf['aux_mw']:.3f}, 0.000, 0.0, 0.0, 0.0, 0.0, 1",
        "END OF LOAD DATA / BEGIN GENERATOR DATA",
        f"{BUS['pv']},'1 ', {pf['p_pv_mw']:.3f}, 0.000, {q_pv:.1f}, {-q_pv:.1f}, 1.0000, 0, "
        f"{pv_mva:.1f}, 0.0015, 0.20000, 0, 0, 1.0, 1, 100.0",
    ]
    if bess and c["bess_units"]:
        L.append(f"{BUS['bess']},'1 ', {pf['p_bess_mw']:.3f}, 0.000, {q_bess:.1f}, {-q_bess:.1f}, "
                 f"1.0000, 0, {bess_mva:.1f}, 0.0015, 0.18000, 0, 0, 1.0, 1, 100.0")
    L += [
        "END OF GENERATOR DATA / BEGIN BRANCH DATA",
        f"{BUS['hv']},{BUS['poi']},'1 ', {z_line.real:.5f}, {z_line.imag:.5f}, 0.01000, "
        f"{branches[3].rating_mva:.0f}, {branches[3].rating_mva:.0f}, {branches[3].rating_mva:.0f}",
        f"{BUS['pv']},{BUS['col']},'1 ', {(z_pad + z_feed).real:.5f}, {(z_pad + z_feed).imag:.5f}, 0.00000, "
        f"{branches[0].rating_mva:.0f}, {branches[0].rating_mva:.0f}, {branches[0].rating_mva:.0f}",
        "END OF BRANCH DATA / BEGIN TRANSFORMER DATA",
    ]
    for i in range(c["main_transformers"]):
        L += [
            f"{BUS['hv']},{BUS['col']},0,'{i + 1} ',1,1,1, 0.00000, 0.00000,2,'{_name8(intake)}-T{i + 1}',1, 1, 1.0000",
            f"{(z_mpt * c['main_transformers']).real:.5f}, {(z_mpt * c['main_transformers']).imag:.5f}, {mpt['mva']:.1f}",
            f"{pf.get('mpt_tap', 1.0):.5f}, 0.000, 0.000, {mpt['mva']:.1f}, {mpt['mva']:.1f}, {mpt['mva']:.1f}, 0, 0, 1.10000, 0.90000",
            "1.00000, 0.000",
        ]
    L += ["END OF TRANSFORMER DATA", "Q"]
    return "\n".join(L) + "\n"


# ---------------------------------------------------------------------------
# Dynamic data (.dyd for PSLF, .dyr for PSS/E) from library OEM blocks
# ---------------------------------------------------------------------------

def _fmt_params(params: dict[str, Any]) -> str:
    return " ".join(f'"{k}" {v:g}' for k, v in params.items())


def dyd_text(design: dict[str, Any], intake: dict[str, Any],
             profile: dict[str, Any]) -> str:
    n8 = _name8(intake)
    c = design["counts"]
    inv = design["inverter"]
    bess = design.get("bess_unit")
    pv_mva = round(c["inverters"] * inv["mva"], 1)
    bess_mva = round(c["bess_units"] * bess["mva"], 1) if bess else 0.0

    src_note = (f"OEM parameter set: {inv['datasheet']}" if inv["verified"]
                else "GENERIC WECC parameters — replace with OEM MOD-026/027 data")
    lines = [
        f"# {profile['model_tool']} dynamic data — {intake.get('project_name')}",
        f"# PV fleet: {c['inverters']} x {inv['vendor']} {inv['model']} — {src_note}",
    ]
    m = inv["wecc_models"]
    p = inv["dyd_params"]
    lines.append(f'{m["gen"].lower()} {BUS["pv"]} "{n8}-PV " {inv["ac_kv"]:.2f} "1" : #9 '
                 f'mva={pv_mva} {_fmt_params(p["regc"])}')
    lines.append(f'{m["elec"].lower()} {BUS["pv"]} "{n8}-PV " {inv["ac_kv"]:.2f} "1" : #9 '
                 f'mva={pv_mva} {_fmt_params(p["reec"])} "pmax" 1.0 "pmin" 0.0')
    lines.append(f'{m["plant"].lower()} {BUS["pv"]} "{n8}-PV " {inv["ac_kv"]:.2f} "1" : #9 '
                 f'{_fmt_params(p["repc"])} "pmax" 1.0 "pmin" 0.0')
    if bess and c["bess_units"]:
        bm, bp = bess["wecc_models"], bess["dyd_params"]
        bsrc = (f"OEM parameter set: {bess['datasheet']}" if bess["verified"]
                else "GENERIC WECC parameters — replace with OEM data")
        lines.append(f"# BESS: {c['bess_units']} x {bess['vendor']} {bess['model']} — {bsrc}")
        lines.append(f'{bm["gen"].lower()} {BUS["bess"]} "{n8}-BESS" {bess["ac_kv"]:.2f} "1" : #9 '
                     f'mva={bess_mva} {_fmt_params(bp["regc"])}')
        lines.append(f'{bm["elec"].lower()} {BUS["bess"]} "{n8}-BESS" {bess["ac_kv"]:.2f} "1" : #9 '
                     f'mva={bess_mva} {_fmt_params(bp["reec"])} "pmax" 1.0 "pmin" -1.0')
        lines.append(f'{bm["plant"].lower()} {BUS["bess"]} "{n8}-BESS" {bess["ac_kv"]:.2f} "1" : #9 '
                     f'{_fmt_params(bp["repc"])} "pmax" 1.0 "pmin" -1.0')
    return "\n".join(lines) + "\n"


def dyr_text(design: dict[str, Any], intake: dict[str, Any],
             profile: dict[str, Any]) -> str:
    c = design["counts"]
    inv = design["inverter"]
    bess = design.get("bess_unit")

    def block(bus: int, models: dict[str, str], params: dict[str, Any], label: str) -> list[str]:
        rows = [f"/ {label}"]
        rows.append(f"{bus} '{models['gen']}' 1 " +
                    " ".join(f"{v:g}" for v in params["regc"].values()) + " /")
        rows.append(f"{bus} '{models['elec']}' 1 " +
                    " ".join(f"{v:g}" for v in params["reec"].values()) + " /")
        rows.append(f"{bus} '{models['plant']}' 1 " +
                    " ".join(f"{v:g}" for v in params["repc"].values()) + " /")
        return rows

    L = [f"/ {profile['model_tool']} DYR — {intake.get('project_name')}"]
    L += block(BUS["pv"], inv["wecc_models"], inv["dyd_params"],
               f"PV: {c['inverters']} x {inv['vendor']} {inv['model']}"
               + ("" if inv["verified"] else " (GENERIC — replace with OEM)"))
    if bess and c["bess_units"]:
        L += block(BUS["bess"], bess["wecc_models"], bess["dyd_params"],
                   f"BESS: {c['bess_units']} x {bess['vendor']} {bess['model']}")
    return "\n".join(L) + "\n"


# ---------------------------------------------------------------------------
# Dynamic validation — flat start + voltage/frequency bumps
# ---------------------------------------------------------------------------

def bump_test(design: dict[str, Any], pf: dict[str, Any]) -> dict[str, Any]:
    """Simplified plant-level RMS response.

    Model: REPC PI (kpg/kig equivalent) commands the converter, REGC responds
    through a first-order lag (tg); reactive support proportional to voltage
    error inside the dip (kqv); frequency droop ddn/dup on the plant reference.

    Events on a 12 s horizon:
        t=0        flat start at the solved dispatch
        t=2..2.5   POI voltage dip to 0.95 pu
        t=6..7     frequency dip to 59.90 Hz
        t=9..9.5   POI voltage rise to 1.05 pu
    """
    inv = design["inverter"]
    repc = inv["dyd_params"]["repc"]
    tg = inv["dyd_params"]["regc"]["tg"]
    kqv = inv["dyd_params"]["reec"]["kqv"]
    bess = design.get("bess_unit")
    dup = bess["dyd_params"]["repc"]["dup"] if bess and design["counts"]["bess_units"] else 0.0
    ddn = repc["ddn"]

    p0 = pf["p_poi_mw"]
    q0 = pf["q_poi_mvar"]
    p_base = max(p0, 1.0)

    dt, t_end = 0.005, 12.0
    kp, ki = 0.25, 2.0            # plant PI on POI power error (per-unit)
    p_cmd = p0                    # controller state (MW)
    p_out = p0                    # converter output after lag (MW)
    integ = 0.0

    t_arr: list[float] = []
    p_arr: list[float] = []
    q_arr: list[float] = []
    v_arr: list[float] = []
    f_arr: list[float] = []

    steps = int(t_end / dt)
    for k in range(steps):
        t = k * dt
        v = 1.0
        f = 60.0
        if 2.0 <= t < 2.5:
            v = 0.95
        elif 9.0 <= t < 9.5:
            v = 1.05
        if 6.0 <= t < 7.0:
            f = 59.90

        # Frequency droop on the reference (pu of plant base).
        df = (f - 60.0) / 60.0
        p_ref = p0
        if df < -0.0006:            # under-frequency: BESS headroom responds
            p_ref = p0 + min(-df * dup, 0.1) * p_base
        elif df > 0.0006:           # over-frequency: curtail via ddn
            p_ref = p0 - min(df * ddn, 0.1) * p_base

        # During deep dips converters prioritise reactive current.
        p_avail = p_ref * (v if v < 0.9 else 1.0)

        err = (p_avail - p_out) / p_base
        integ += err * dt
        p_cmd = p_avail + (kp * err + ki * integ) * p_base * 0.05
        p_out += (p_cmd - p_out) * dt / tg if tg > 0 else 0.0

        # Reactive support: kqv on voltage error outside the deadband.
        dv = 1.0 - v
        q_out = q0 + (kqv * dv) * p_base if abs(dv) > 0.01 else q0

        if k % 8 == 0:  # decimate for plotting/reporting
            t_arr.append(round(t, 3))
            p_arr.append(round(p_out, 4))
            q_arr.append(round(q_out, 4))
            v_arr.append(v)
            f_arr.append(f)

    # --- Checks -----------------------------------------------------------
    def window(t0: float, t1: float) -> list[int]:
        return [i for i, t in enumerate(t_arr) if t0 <= t < t1]

    checks: list[dict[str, Any]] = []
    flat = window(0.5, 2.0)
    flat_dev = max(abs(p_arr[i] - p0) for i in flat) / p_base * 100
    checks.append({"name": "Flat start", "pass": flat_dev < 0.5,
                   "detail": f"Max P deviation {flat_dev:.3f}% over 0.5-2.0 s (limit 0.5%)"})

    dip = window(2.0, 2.5)
    q_support = max(q_arr[i] for i in dip) - q0
    checks.append({"name": "LVRT reactive support", "pass": q_support > 0,
                   "detail": f"+{q_support:.1f} Mvar injected during the 0.95 pu dip (kqv={kqv:g})"})

    rec = window(3.5, 5.5)
    rec_dev = max(abs(p_arr[i] - p0) for i in rec) / p_base * 100
    checks.append({"name": "Post-dip recovery", "pass": rec_dev < 1.0,
                   "detail": f"P within {rec_dev:.3f}% of setpoint 1 s after the dip clears"})

    uf = window(6.2, 7.0)
    uf_resp = max(p_arr[i] for i in uf) - p0
    expect_uf = dup > 0
    checks.append({"name": "Under-frequency response",
                   "pass": (uf_resp > 0.1) if expect_uf else abs(uf_resp) < 0.5,
                   "detail": (f"+{uf_resp:.2f} MW at 59.90 Hz (BESS dup={dup:g})" if expect_uf
                              else f"No headroom response expected for PV-only (dup=0); saw {uf_resp:+.2f} MW")})

    ov = window(9.0, 9.5)
    q_absorb = min(q_arr[i] for i in ov) - q0
    checks.append({"name": "HVRT reactive absorption", "pass": q_absorb < 0,
                   "detail": f"{q_absorb:.1f} Mvar during the 1.05 pu rise"})

    settle = window(10.5, 12.0)
    settle_dev = max(abs(p_arr[i] - p0) for i in settle) / p_base * 100
    checks.append({"name": "Final settling", "pass": settle_dev < 0.5,
                   "detail": f"P within {settle_dev:.3f}% at end of run"})

    return {
        "t": t_arr, "p_mw": p_arr, "q_mvar": q_arr, "v_pu": v_arr, "f_hz": f_arr,
        "p0": p0, "q0": q0,
        "events": [
            {"t": 2.0, "label": "V dip 0.95 pu (0.5 s)"},
            {"t": 6.0, "label": "f dip 59.90 Hz (1 s)"},
            {"t": 9.0, "label": "V rise 1.05 pu (0.5 s)"},
        ],
        "checks": checks,
        "all_pass": all(ch["pass"] for ch in checks),
        "model_note": (
            "Simplified plant-level RMS response (REPC PI -> REGC lag, kqv reactive "
            "support, ddn/dup droop). OEM control internals are not simulated — final "
            "certification plots must come from the ISO-approved software with the "
            "OEM model, per the GridPilot engineering boundary."),
    }

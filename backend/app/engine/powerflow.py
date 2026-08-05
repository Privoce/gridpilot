"""Phase 5 — Load-flow and short-circuit engine.

The interconnection plant network is strictly radial:

    inverter fleet -> pad transformers -> collector feeders -> collector bus
                   -> main transformer(s) -> gen-tie -> POI (slack)

so a backward/forward sweep power flow converges in a handful of iterations
with no external solver dependency. Everything runs in per-unit on a 100 MVA
base with complex arithmetic; results carry the full audit trail (inputs,
iteration history, tolerances) required by the blueprint.

The solve dispatches the inverter fleet so the requested net MW arrives at
the POI (a small outer secant loop on plant output), then reports gross
generation, series losses, bus voltages, and branch loadings.
"""

from __future__ import annotations

import cmath
import math
from typing import Any

S_BASE = 100.0  # MVA


class Branch:
    """Series element between two buses (impedance in per-unit on S_BASE)."""

    def __init__(self, name: str, z: complex, rating_mva: float | None = None):
        self.name = name
        self.z = z
        self.rating_mva = rating_mva
        self.tap = 1.0                    # off-nominal ratio (OLTC transformers)
        self.flow_mva: complex = 0j       # sending-end flow (into the branch)
        self.loss_mw: float = 0.0
        self.loss_mvar: float = 0.0


def _zpu_from_ohms(r_ohm: float, x_ohm: float, kv: float) -> complex:
    zb = kv * kv / S_BASE
    return complex(r_ohm / zb, x_ohm / zb)


def _zpu_transformer(z_pct: float, xr: float, mva: float) -> complex:
    """Nameplate impedance to system base; split R/X by the X/R ratio."""
    z = (z_pct / 100.0) * (S_BASE / mva)
    theta = math.atan(xr)
    return complex(z * math.cos(theta), z * math.sin(theta))


def build_network(design: dict[str, Any], intake: dict[str, Any]) -> dict[str, Any]:
    """Reduce the plant graph to the equivalent radial chain used for the solve.

    Chain (generation end -> slack):
        gen_bus -[pads]- col_feed -[feeders]- col_bus -[mpts]- hv_bus -[gentie]- poi
    Parallel groups (pads, feeders, main transformers) combine as z/n.
    """
    c = design["counts"]
    col_kv = float(intake.get("collector_kv") or 34.5)
    poi_kv = float(intake.get("poi_voltage_kv") or 230.0)

    pad = design["pad"]
    n_blocks = max(c["blocks"], 1)
    z_pads = _zpu_transformer(pad["z_pct"], pad["xr"], pad["mva"]) / n_blocks

    cable = design["cable"]
    feeder_mi = design["feeder_mi"]
    n_feeders = max(c["feeders"], 1)
    z_feeder = _zpu_from_ohms(cable["r_ohm_per_mi"] * feeder_mi,
                              cable["x_ohm_per_mi"] * feeder_mi, col_kv)
    z_feeders = z_feeder / n_feeders

    mpt = design["mpt"]
    n_mpt = max(c["main_transformers"], 1)
    z_mpts = _zpu_transformer(mpt["z_pct"], mpt["xr"], mpt["mva"]) / n_mpt

    line = design["line"]
    z_gentie = _zpu_from_ohms(line["r_ohm_per_mi"] * design["gentie_mi"],
                              line["x_ohm_per_mi"] * design["gentie_mi"], poi_kv)

    branches = [
        Branch("Pad transformers (parallel)", z_pads, pad["mva"] * n_blocks),
        Branch("Collector feeders (parallel)", z_feeders,
               n_feeders * math.sqrt(3) * col_kv * cable["ampacity_a"] / 1000.0),
        Branch("Main transformers (parallel)", z_mpts, mpt["mva"] * n_mpt),
        Branch("Gen-tie line", z_gentie,
               math.sqrt(3) * poi_kv * line["ampacity_a"] / 1000.0),
    ]
    buses = ["Inverter terminals (equiv.)", f"{col_kv:g} kV feeder head",
             f"{col_kv:g} kV collector bus", f"{poi_kv:g} kV substation bus",
             "POI (slack)"]
    return {"branches": branches, "buses": buses,
            "col_kv": col_kv, "poi_kv": poi_kv}


def _sweep(branches: list[Branch], inj: list[complex],
           v_slack: complex, tol: float, max_iter: int) -> dict[str, Any]:
    """Backward/forward sweep for the radial chain with per-bus injections.

    Bus order: 0 = generation end ... N = slack (POI). `inj[k]` is the complex
    power injected at bus k (negative = load). The flow arriving at the slack
    is the plant's net delivery at the POI.
    """
    n = len(branches)
    v = [v_slack] * (n + 1)          # index 0 = gen end, n = slack
    history: list[float] = []
    for _ in range(max_iter):
        # Backward: accumulate flows and losses from the generation end toward
        # the slack using the current voltage estimates.
        v_new = list(v)
        v_new[n] = v_slack
        s_at = [0j] * (n + 1)
        s_run = inj[0]
        for k, b in enumerate(branches):
            vk = v[k] if abs(v[k]) > 1e-6 else v_slack
            i_conj = (s_run / vk).conjugate()
            loss = (abs(i_conj) ** 2) * b.z
            b.flow_mva = s_run
            b.loss_mw = loss.real * S_BASE
            b.loss_mvar = loss.imag * S_BASE
            s_at[k] = s_run
            # Receiving end = sending end minus series loss, plus any injection
            # at the receiving bus (BESS, auxiliary load).
            s_run = s_run - loss + inj[k + 1]
        s_at[n] = s_run
        # Voltage drop from slack back to the generation end. An off-nominal
        # tap t on a branch (OLTC on the MPT) rescales the generation-side
        # voltage by 1/t — the ideal-ratio part of the transformer model.
        for k in range(n - 1, -1, -1):
            b = branches[k]
            vk1 = v_new[k + 1]
            i = (s_at[k] / v[k]).conjugate() if abs(v[k]) > 1e-6 else 0j
            v_new[k] = (vk1 + i * b.z) / b.tap
        delta = max(abs(v_new[k] - v[k]) for k in range(n + 1))
        v = v_new
        history.append(delta)
        if delta < tol:
            break
    return {"v": v, "s_poi": s_at[n], "history": history,
            "converged": history[-1] < tol if history else False}


def solve(design: dict[str, Any], intake: dict[str, Any]) -> dict[str, Any]:
    """Dispatch the plant so the requested net MW lands at the POI, then report.

    Base case is full export: PV dispatched first up to its capability, the
    BESS discharge making up the remainder. PV injects at the inverter bus;
    BESS and the plant auxiliary load sit at the collector bus (bus 2).
    """
    net = build_network(design, intake)
    branches: list[Branch] = net["branches"]
    n_bus = len(branches) + 1

    p_req = float(intake.get("net_mw_poi") or 0.0)
    aux = float(intake.get("aux_mw") or 0.0)
    gross_cap = float(intake.get("gross_mw") or 0.0)
    pv_cap = float(design.get("pv_mw") or gross_cap)
    tol, max_iter = 1e-8, 40
    v_slack = complex(1.0, 0.0)

    # Outer loop: adjust gross dispatch until POI receipt matches the request.
    # Unity power factor at the POI (Q target 0) — inverters absorb the network
    # Mvar; the reactive capability report covers the +/-0.95 PF envelope.
    result = None
    dispatch_iters: list[dict[str, Any]] = []
    p_gen = p_pv = p_bess = 0.0

    def run_dispatch() -> None:
        nonlocal result, p_gen, p_pv, p_bess
        dispatch_iters.clear()
        p_gen = p_req + aux  # first guess: request + aux, losses added iteratively
        for it in range(12):
            p_pv = min(p_gen, pv_cap)
            p_bess = max(p_gen - p_pv, 0.0)
            q_gen = 0.0
            # Inner refinement: pick Q (on the PV fleet) so that Q at POI ~ 0.
            for _ in range(6):
                inj = [0j] * n_bus
                inj[0] = complex(p_pv / S_BASE, q_gen / S_BASE)
                inj[2] = complex((p_bess - aux) / S_BASE, 0.0)
                result = _sweep(branches, inj, v_slack, tol, max_iter)
                q_poi = result["s_poi"].imag * S_BASE
                if abs(q_poi) < 0.005:
                    break
                q_gen -= q_poi
            p_poi = result["s_poi"].real * S_BASE
            dispatch_iters.append({"iter": it + 1, "p_gen_mw": round(p_gen, 4),
                                   "p_pv_mw": round(p_pv, 4), "p_bess_mw": round(p_bess, 4),
                                   "p_poi_mw": round(p_poi, 4)})
            err = p_req - p_poi
            if abs(err) < 0.001:
                break
            p_gen += err

    # OLTC tap adjustment on the main transformers: if the solved collector-bus
    # voltage leaves the 0.98-1.02 pu band, step the tap (0.625% steps, ±10%
    # range per the MPT nameplate) and re-dispatch. Deterministic: rounding to
    # the step grid converges in a couple of passes.
    mpt_branch = branches[2]
    TAP_STEP, TAP_MAX = 0.00625, 0.10
    for _ in range(4):
        run_dispatch()
        v_col = abs(result["v"][2])
        if 0.98 <= v_col <= 1.02:
            break
        delta = round((v_col - 1.0) / TAP_STEP) * TAP_STEP
        new_tap = min(1.0 + TAP_MAX, max(1.0 - TAP_MAX, mpt_branch.tap + delta))
        if abs(new_tap - mpt_branch.tap) < TAP_STEP / 2:
            break
        mpt_branch.tap = new_tap

    losses_mw = sum(b.loss_mw for b in branches)
    losses_mvar = sum(b.loss_mvar for b in branches)
    p_poi = result["s_poi"].real * S_BASE
    q_poi = result["s_poi"].imag * S_BASE

    voltages = []
    for name, vk in zip(net["buses"], result["v"]):
        voltages.append({"bus": name, "v_pu": round(abs(vk), 4),
                         "angle_deg": round(math.degrees(cmath.phase(vk)), 3)})

    flows = []
    warnings = []
    for b in branches:
        mva = abs(b.flow_mva) * S_BASE
        loading = (mva / b.rating_mva * 100.0) if b.rating_mva else None
        flows.append({
            "branch": b.name, "mva": round(mva, 2),
            "loss_mw": round(b.loss_mw, 3), "loss_mvar": round(b.loss_mvar, 3),
            "rating_mva": round(b.rating_mva, 1) if b.rating_mva else None,
            "loading_pct": round(loading, 1) if loading is not None else None,
        })
        if loading is not None and loading > 100.0:
            warnings.append(f"{b.name} loaded at {loading:.0f}% of rating")
    for vrow in voltages:
        if not 0.95 <= vrow["v_pu"] <= 1.05:
            warnings.append(f"{vrow['bus']} voltage {vrow['v_pu']} pu outside 0.95-1.05")
    if gross_cap and p_gen > gross_cap + 1e-6:
        warnings.append(
            f"Required dispatch {p_gen:.2f} MW exceeds gross capability {gross_cap:.1f} MW — "
            "the requested net MW at POI is not achievable with declared losses")

    declared_losses = float(intake.get("losses_mw") or 0.0)
    return {
        "converged": result["converged"],
        "iterations": len(result["history"]),
        "tolerance": tol,
        "history": [f"{h:.2e}" for h in result["history"]],
        "dispatch": dispatch_iters,
        "p_gen_mw": round(p_gen, 3),
        "p_pv_mw": round(p_pv, 3),
        "p_bess_mw": round(p_bess, 3),
        "aux_mw": aux,
        "p_poi_mw": round(p_poi, 3),
        "q_poi_mvar": round(q_poi, 3),
        "p_requested_mw": p_req,
        "poi_match": abs(p_poi - p_req) < 0.01,
        "losses_mw": round(losses_mw, 3),
        "losses_mvar": round(losses_mvar, 3),
        "losses_declared_mw": declared_losses,
        "loss_delta_mw": round(losses_mw - declared_losses, 3),
        "mpt_tap": round(mpt_branch.tap, 5),
        "mpt_tap_pct": round((mpt_branch.tap - 1.0) * 100.0, 3),
        "voltages": voltages,
        "flows": flows,
        "warnings": warnings,
        "buses": net["buses"],
        "s_base": S_BASE,
    }


# ---------------------------------------------------------------------------
# Short-circuit (three-phase bolted, IEC-style magnitudes)
# ---------------------------------------------------------------------------

def short_circuit(design: dict[str, Any], intake: dict[str, Any]) -> dict[str, Any]:
    """Fault duty at the collector bus and the POI.

    System contribution from the utility Thevenin equivalent (POI short-circuit
    MVA); plant contribution from inverter fault-current limits (current-source
    behaviour, typically 1.1-1.3 pu of rating).
    """
    net = build_network(design, intake)
    branches: list[Branch] = net["branches"]
    poi_kv, col_kv = net["poi_kv"], net["col_kv"]
    c = design["counts"]
    inv, bess = design["inverter"], design.get("bess_unit")

    z_sys = S_BASE / float(design["poi_sc_mva"])           # pu
    z_gentie = branches[3].z
    z_mpts = branches[2].z

    # Plant inverter contribution (constant-current sources).
    i_plant_pu_on_rating = inv["fault_current_pu"]
    plant_mva = c["inverters"] * inv["mva"] * i_plant_pu_on_rating
    if bess and c["bess_units"]:
        plant_mva += c["bess_units"] * bess["mva"] * bess["fault_current_pu"]

    # Collector bus fault: system through gen-tie + MPTs, plus plant injection.
    z_to_col = z_sys + z_gentie + z_mpts
    sys_mva_col = S_BASE / abs(z_to_col)
    duty_col_mva = sys_mva_col + plant_mva
    i_col_ka = duty_col_mva / (math.sqrt(3) * col_kv)

    # POI fault: system direct, plant through MPTs + gen-tie (current limited —
    # transfer impedance does not reduce a current-source contribution below
    # its limit, so keep the conservative full value).
    sys_mva_poi = float(design["poi_sc_mva"])
    duty_poi_mva = sys_mva_poi + plant_mva
    i_poi_ka = duty_poi_mva / (math.sqrt(3) * poi_kv)

    return {
        "assumption": f"POI three-phase duty {design['poi_sc_mva']:.0f} MVA (see approvals)",
        "plant_contribution_mva": round(plant_mva, 1),
        "results": [
            {"location": f"{col_kv:g} kV collector bus",
             "duty_mva": round(duty_col_mva, 0), "duty_ka": round(i_col_ka, 2),
             "breaker_class": "40 kA class" if i_col_ka <= 36 else "50 kA class"},
            {"location": f"{poi_kv:g} kV POI",
             "duty_mva": round(duty_poi_mva, 0), "duty_ka": round(i_poi_ka, 2),
             "breaker_class": "40 kA class" if i_poi_ka <= 36 else "63 kA class"},
        ],
    }

"""Phase 7 — Consistency layer, assumption ledger, and the engine orchestrator.

`run_engineering` is the single entry point: intake in, complete engineering
package out (graph, design, load flow, short circuit, dynamic validation,
cross-checks, approval state). Deterministic and fast enough to run on demand,
so serverless instances never need shared state.

Cross-checks verify two different things:
  1. Developer declarations vs computed results (declared losses vs solved
     losses, requested net MW achievable, MW chain arithmetic).
  2. Rendered artifacts vs the graph (the generated model files and drawings
     actually contain the solved/graph numbers — guards renderer drift).
"""

from __future__ import annotations

from typing import Any

from backend.app.services.iso_profiles import get_profile
from backend.app.engine.design import design_plant
from backend.app.engine.graph import (
    approval_state, build_graph, history_public, record_history, source_trace,
)
from backend.app.engine.models_out import bump_test, dyd_text, epc_text, raw_text
from backend.app.engine.powerflow import short_circuit, solve
from backend.app.engine.sld import build_sld, to_svg


def run_engineering(intake: dict[str, Any], iso: str | None = None,
                    prov: dict[str, Any] | None = None,
                    actor: str | None = None,
                    history_note: str | None = None) -> dict[str, Any]:
    """Full engineering pass. Returns every phase's output keyed by name.

    Records a graph-history entry (who/what/when) when the content hash has
    changed since the last pass. History rides inside the intake so the client
    can persist it alongside approvals.
    """
    profile = get_profile(iso)
    record_history(intake, by=actor or "GridPilot",
                   note=history_note or "Engineering pass", iso=profile["iso"])
    graph = build_graph(intake, profile["iso"], prov)
    design = design_plant(graph, intake)
    pf = solve(design, intake)
    sc = short_circuit(design, intake)
    bump = bump_test(design, pf)
    approvals = approval_state(graph, intake)
    checks = cross_checks(graph, design, pf, intake, profile)
    return {
        "profile": profile,
        "graph": graph,
        "design": design,
        "powerflow": pf,
        "short_circuit": sc,
        "bump": bump,
        "approvals": approvals,
        "checks": checks,
        "source_trace": source_trace(graph),
        "graph_history": history_public(intake),
        "ready": (pf["converged"] and approvals["all_approved"]
                  and not any(c["status"] == "fail" for c in checks)),
    }


def cross_checks(graph: dict[str, Any], design: dict[str, Any], pf: dict[str, Any],
                 intake: dict[str, Any], profile: dict[str, Any]) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []

    def add(name: str, status: str, detail: str) -> None:
        checks.append({"name": name, "status": status, "detail": detail})

    # 1. Declared vs computed ------------------------------------------------
    def fnum(key: str) -> float:
        try:
            return float(intake.get(key) or 0.0)
        except (TypeError, ValueError):
            return 0.0

    gross, aux = fnum("gross_mw"), fnum("aux_mw")
    declared_losses, net_req = fnum("losses_mw"), fnum("net_mw_poi")

    chain = gross - aux - declared_losses
    if abs(chain - net_req) < 0.51:
        add("MW chain arithmetic", "pass",
            f"Gross {gross:g} − aux {aux:g} − losses {declared_losses:g} = {chain:g} "
            f"≈ requested {net_req:g} MW")
    else:
        add("MW chain arithmetic", "fail",
            f"Gross {gross:g} − aux {aux:g} − losses {declared_losses:g} = {chain:g} "
            f"≠ requested {net_req:g} MW at POI")

    if pf["converged"]:
        add("Load flow convergence", "pass",
            f"Converged in {pf['iterations']} iterations to {pf['tolerance']:.0e}")
    else:
        add("Load flow convergence", "fail", "Load flow did not converge")

    if pf["poi_match"]:
        add("Requested MW delivered", "pass",
            f"Solved case delivers {pf['p_poi_mw']:g} MW at the POI "
            f"(requested {pf['p_requested_mw']:g})")
    else:
        add("Requested MW delivered", "fail",
            f"Solved case delivers {pf['p_poi_mw']:g} MW vs requested "
            f"{pf['p_requested_mw']:g} — " + "; ".join(pf["warnings"][:2]))

    delta = pf["loss_delta_mw"]
    if abs(delta) <= max(0.5, 0.5 * max(declared_losses, 0.2)):
        add("Declared losses vs computed", "pass",
            f"Declared {declared_losses:g} MW; computed {pf['losses_mw']:g} MW "
            f"(Δ {delta:+g} MW within tolerance)")
    else:
        add("Declared losses vs computed", "warn",
            f"Declared {declared_losses:g} MW but the solved case shows "
            f"{pf['losses_mw']:g} MW (Δ {delta:+g}). Update the intake losses or "
            "confirm the collector design.")

    overloads = [f for f in pf["flows"]
                 if f["loading_pct"] is not None and f["loading_pct"] > 100]
    if overloads:
        add("Thermal loading", "fail",
            "; ".join(f"{o['branch']} at {o['loading_pct']:g}%" for o in overloads))
    else:
        worst = max((f["loading_pct"] or 0) for f in pf["flows"])
        add("Thermal loading", "pass", f"All branches within rating (worst {worst:g}%)")

    # 2. Rendered artifacts vs graph -----------------------------------------
    try:
        epc = epc_text(design, pf, intake, profile)
        dyd = dyd_text(design, intake, profile)
        raw = raw_text(design, pf, intake, profile)
        svg = to_svg(build_sld(graph, design, intake))
        probes = [
            ("Load-flow model dispatch", f"{pf['p_pv_mw']:.2f}", epc),
            ("Load-flow model losses", f"losses {pf['losses_mw']:g} MW", epc),
            ("Dynamic model inverter", design["inverter"]["model"], dyd),
            ("RAW model dispatch", f"{pf['p_pv_mw']:.3f}", raw),
            ("SLD transformer rating", f"{design['mpt']['mva']:g} MVA", svg),
            ("SLD inverter count",
             f"{design['counts']['inverters']} inverters total", svg),
        ]
        bad = [name for name, needle, hay in probes if needle not in hay]
        if bad:
            add("Artifact/graph consistency", "fail",
                "Rendered artifacts drifted from the graph: " + ", ".join(bad))
        else:
            add("Artifact/graph consistency", "pass",
                f"{len(probes)} sampled values identical across models, drawings, and the graph")
    except Exception as exc:  # pragma: no cover — surfaced as a failed check
        add("Artifact/graph consistency", "fail", f"Renderer error: {exc}")

    # 3. Vendor OEM parameters ------------------------------------------------
    vendor = intake.get("vendor_dyd")
    vendor = vendor if isinstance(vendor, dict) else None
    dyd_meta = intake.get("file_dyd")
    has_dyd_file = (isinstance(dyd_meta, dict) and str(dyd_meta.get("name") or "").strip()
                    and not dyd_meta.get("staged"))
    if vendor:
        n_blocks = sum(len(vendor.get(g, {}).get("params", {})) for g in ("pv", "bess"))
        add("Vendor OEM parameters", "pass",
            f"{n_blocks} parameter blocks integrated from {vendor.get('file', 'vendor file')} "
            "(source: oem_datasheet)")
    elif has_dyd_file:
        add("Vendor OEM parameters", "warn",
            f"{dyd_meta['name']} attached but no parameter records parsed — library OEM set "
            "in use. Re-run extraction, or confirm the file is a PSLF .dyd.")

    # 4. Missing data ----------------------------------------------------------
    if graph.get("missing"):
        add("Missing engineering inputs", "warn",
            "; ".join(f"{m['label']} ({m['impact']})" for m in graph["missing"]))
    else:
        add("Missing engineering inputs", "pass", "No missing-data items")

    return checks

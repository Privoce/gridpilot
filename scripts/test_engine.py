"""Engine test suite — run: .venv/bin/python scripts/test_engine.py

Plain-assert tests, one function per engine phase. Grown phase by phase as
the engine is built; every function must pass before the next phase starts.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.app.services.caiso_packet import DEFAULT_INTAKE  # noqa: E402
from backend.app.engine import equipment as lib  # noqa: E402
from backend.app.engine.design import design_plant  # noqa: E402
from backend.app.engine.graph import (  # noqa: E402
    SRC_ASSUME, SRC_DEV, SRC_DOC,
    approval_state, assumptions, build_graph, graph_version,
    history_public, record_history, source_trace,
)

# A clean intake: Ravenwood defaults with the deliberate demo defects fixed.
INTAKE = {**DEFAULT_INTAKE, "net_mw_poi": 125.0, "bess_mwh": 200.0}

PASS = 0


def ok(cond: bool, msg: str) -> None:
    global PASS
    if not cond:
        print(f"  FAIL: {msg}")
        raise SystemExit(1)
    PASS += 1
    print(f"  ok: {msg}")


def test_phase1_graph() -> None:
    print("[phase 1] project graph")
    g = build_graph(INTAKE, "CAISO")
    ok(g["params"]["gross_mw"]["value"] == 128.0, "developer fact captured")
    ok(g["params"]["gross_mw"]["source"] == SRC_DEV, "developer source tag")
    ok("file_site_control" not in g["params"], "file metadata excluded from graph")

    # Provenance flips the source tag to document_extraction.
    g2 = build_graph(INTAKE, "CAISO", prov={"gross_mw": {"file": "workbook.xlsx"}})
    ok(g2["params"]["gross_mw"]["source"] == SRC_DOC, "extraction provenance tagged")
    ok(g2["params"]["gross_mw"]["origin"] == "file:workbook.xlsx", "origin records the file")

    # Determinism: same intake -> same version; changed intake -> new version.
    ok(graph_version(INTAKE) == g["version"], "version is content-derived")
    ok(graph_version({**INTAKE, "gross_mw": 130.0}) != g["version"], "version changes with intake")

    trace = source_trace(g)
    ok(all(r["source_label"] for r in trace), "source trace rows labelled")


def test_phase2_equipment() -> None:
    print("[phase 2] equipment library")
    inv, m = lib.match_inverter("Sungrow SG4400UD-MV, qty 18")
    ok(m and inv["id"] == "sungrow_sg4400ud_mv", "matches Sungrow from intake text")
    inv2, m2 = lib.match_inverter("TBD")
    ok(not m2 and inv2["id"] == "generic_pv_4mva", "falls back to generic inverter")
    b, mb = lib.match_bess("Tesla Megapack 2XL, qty 50")
    ok(mb and b["id"] == "tesla_megapack_2xl", "matches Megapack")
    mpt = lib.pick_main_transformer(70)
    ok(mpt["id"] == "mpt_75mva", "picks smallest covering MPT")
    lc = lib.gentie_constants(230)
    ok(lc["kv_class"] == 230, "gen-tie class for 230 kV")
    for entry in list(lib.INVERTERS.values()) + list(lib.BESS_UNITS.values()):
        ok(entry["dyd_params"]["reec"]["qmax"] > 0, f"{entry['id']} has REEC params")


def test_phase3_design() -> None:
    print("[phase 3] design engine")
    g = build_graph(INTAKE, "CAISO")
    d = design_plant(g, INTAKE)
    c = d["counts"]
    # 128 gross - 50 BESS = 78 MW PV / 0.9 = 86.7 MVA / 4.4 -> 20 inverters, 10 blocks.
    ok(c["inverters"] == 20, f"20 inverters via MVA = MW / 0.9 rule (got {c['inverters']})")
    ok(c["blocks"] == 10, f"10 skids (got {c['blocks']})")
    # BESS: max(ceil(50/0.9/2.0)=28, ceil(200/3.854)=52) = 52 Megapacks.
    ok(c["bess_units"] == 52, f"52 Megapacks (got {c['bess_units']})")
    ok(c["main_transformers"] == 2, "two main transformers above 100 MVA")
    # 527 A usable per feeder / 147 A per 8.8 MVA block -> 3 blocks/circuit; ceil(10/3) = 4.
    ok(c["feeders"] == 4, f"PV feeders sized by ampacity (got {c['feeders']})")
    ok(any(n["id"] == "bess_seg" for n in g["nodes"]), "BESS has its own collector segment")
    blocks = [n.get("blocks") for n in g["nodes"] if n["type"] == "feeder"]
    ok(min(blocks) >= 1 and sum(blocks) == c["blocks"], f"blocks distributed evenly {blocks}")
    ok(any(n["id"] == "col_bus" for n in g["nodes"]), "collector bus in graph")
    ok(any(e["type"] == "gentie" for e in g["edges"]), "gen-tie edge in graph")
    ok(len(d["schedule"]) >= 5, "equipment schedule rows")
    ok(d["topology"].endswith("POI"), "topology tree ends at POI")

    # Assumptions: gen-tie length and POI SC MVA defaults must require approval.
    ids = [a["id"] for a in assumptions(g)]
    ok("design.gentie_mi" in ids, "gen-tie length is an approval item")
    ok("design.poi_sc_mva" in ids, "POI short-circuit strength is an approval item")

    st = approval_state(g, INTAKE)
    ok(st["pending"] == st["total"] and not st["all_approved"], "approvals start pending")
    st2 = approval_state(g, {**INTAKE, "approvals": {i: {"by": "PE", "at": "now"} for i in ids}})
    ok(st2["all_approved"], "approvals recorded via intake")

    # Missing data: BESS energy missing when nulled.
    g3 = build_graph({**INTAKE, "bess_mwh": None}, "CAISO")
    d3 = design_plant(g3, {**INTAKE, "bess_mwh": None})
    ok(any(m["key"] == "bess_mwh" for m in d3["missing"]), "missing-data list flags BESS MWh")

    # Determinism.
    g4 = build_graph(INTAKE, "CAISO")
    d4 = design_plant(g4, INTAKE)
    ok(d4["counts"] == c, "design is deterministic")


def test_phase4_sld() -> None:
    print("[phase 4] SLD engine")
    import xml.etree.ElementTree as ET
    import fitz
    from backend.app.engine.sld import build_sld, to_dxf, to_pdf, to_svg

    g = build_graph(INTAKE, "CAISO")
    d = design_plant(g, INTAKE)
    prims = build_sld(g, d, INTAKE)
    ok(len(prims) > 80, f"substantial drawing ({len(prims)} primitives)")

    svg = to_svg(prims)
    root = ET.fromstring(svg)  # raises if malformed
    ok(root.tag.endswith("svg"), "SVG parses")
    ok("OWNERSHIP BOUNDARY" in svg, "ownership boundary drawn")
    ok("Revenue metering" in svg, "metering point drawn")
    ok("TYPICAL OF 10 INVERTER BLOCKS" in svg, "typical-of block notation")
    ok(f"{d['counts']['bess_units']} x Megapack 2XL" in svg, "BESS labelled from design")
    ok("Gen-tie — 5 mi" in svg, "gen-tie length labelled")

    out = Path("/tmp/gp_engine")
    out.mkdir(exist_ok=True)
    (out / "sld.svg").write_text(svg)
    to_pdf(prims, out / "sld.pdf")
    doc = fitz.open(str(out / "sld.pdf"))
    ok(doc.page_count == 1, "PDF renders one sheet")
    text = doc[0].get_text()
    ok("Single-Line Diagram" in text, "PDF title block present")
    doc.close()

    dxf = to_dxf(prims)
    (out / "sld.dxf").write_text(dxf)
    ok(dxf.startswith("0\nSECTION") and dxf.rstrip().endswith("EOF"), "DXF structure")
    ok(dxf.count("\nLINE\n") > 40, f"DXF has line entities ({dxf.count(chr(10) + 'LINE' + chr(10))})")
    ok("SLD-BOUNDARY" in dxf, "DXF boundary layer")

    # Deterministic output.
    g2 = build_graph(INTAKE, "CAISO")
    d2 = design_plant(g2, INTAKE)
    ok(to_svg(build_sld(g2, d2, INTAKE)) == svg, "SLD is deterministic")


def test_phase5_powerflow() -> None:
    print("[phase 5] load flow + short circuit")
    from backend.app.engine.powerflow import short_circuit, solve

    g = build_graph(INTAKE, "CAISO")
    d = design_plant(g, INTAKE)
    r = solve(d, INTAKE)

    ok(r["converged"], f"converged in {r['iterations']} iterations")
    ok(r["iterations"] <= 40, "iteration count sane")
    ok(r["poi_match"], f"POI receives requested MW ({r['p_poi_mw']} vs {r['p_requested_mw']})")
    ok(abs(r["q_poi_mvar"]) < 0.05, f"unity PF at POI (Q={r['q_poi_mvar']} Mvar)")

    # Physics: dispatch - aux - losses = POI receipt (power balance).
    balance = r["p_gen_mw"] - r["aux_mw"] - r["losses_mw"] - r["p_poi_mw"]
    ok(abs(balance) < 0.01, f"power balance closes ({balance:+.4f} MW)")
    ok(0.1 < r["losses_mw"] < 5.0, f"series losses plausible ({r['losses_mw']} MW)")
    ok(len(r["voltages"]) == 5, "voltage profile for all buses")
    ok(all(0.9 < v["v_pu"] < 1.1 for v in r["voltages"]), "voltages in a credible band")
    ok(r["voltages"][-1]["v_pu"] == 1.0, "slack held at 1.0 pu")
    # Voltage rises from POI toward the generation end when exporting.
    ok(r["voltages"][0]["v_pu"] > r["voltages"][-1]["v_pu"], "gen-end voltage above slack")
    ok(all(f["loading_pct"] is None or f["loading_pct"] < 100 for f in r["flows"]),
       "no overloads on the base case")

    # Deterministic.
    r2 = solve(design_plant(build_graph(INTAKE, "CAISO"), INTAKE), INTAKE)
    ok(r2["p_gen_mw"] == r["p_gen_mw"] and r2["losses_mw"] == r["losses_mw"],
       "load flow is deterministic")

    # Infeasible request: net > gross must warn.
    bad = {**INTAKE, "net_mw_poi": 200.0}
    rb = solve(design_plant(build_graph(bad, "CAISO"), bad), bad)
    ok(any("exceeds gross capability" in w for w in rb["warnings"]),
       "impossible dispatch flagged")

    sc = short_circuit(d, INTAKE)
    ok(len(sc["results"]) == 2, "fault duty at collector bus and POI")
    col, poi = sc["results"]
    ok(col["duty_ka"] > 10, f"collector duty magnitude sane ({col['duty_ka']} kA)")
    ok(poi["duty_mva"] > 5000, "POI duty includes plant contribution")
    ok(sc["plant_contribution_mva"] > 100, "inverter fleet contributes fault current")


def test_phase6_models() -> None:
    print("[phase 6] model writers + dynamic validation")
    from backend.app.services.iso_profiles import get_profile
    from backend.app.engine.powerflow import solve
    from backend.app.engine.models_out import bump_test, dyd_text, dyr_text, epc_text, raw_text

    g = build_graph(INTAKE, "CAISO")
    d = design_plant(g, INTAKE)
    pf = solve(d, INTAKE)
    prof = get_profile("CAISO")

    epc = epc_text(d, pf, INTAKE, prof)
    ok("bus data" in epc and "generator data" in epc and "transformer data" in epc,
       "EPC has PSLF sections")
    ok(f"{pf['p_pv_mw']:.2f}" in epc, "EPC generator dispatch from the solved case")
    ok(f"losses {pf['losses_mw']:g} MW" in epc, "EPC records solved losses")
    ok("Sungrow SG4400UD-MV" in epc, "EPC names the library inverter")

    raw = raw_text(d, pf, INTAKE, get_profile("MISO"))
    ok(raw.startswith("0, 100.00, 33"), "RAW v33 header")
    ok("BEGIN GENERATOR DATA" in raw and "END OF TRANSFORMER DATA" in raw, "RAW sections")
    ok(f"{pf['p_bess_mw']:.3f}" in raw, "RAW BESS dispatch from the solved case")

    dyd = dyd_text(d, INTAKE, prof)
    ok("regc_a" in dyd and "reec_a" in dyd and "repc_a" in dyd, "DYD WECC model set (PV)")
    ok("reec_c" in dyd, "DYD BESS uses REEC_C")
    ok("OEM parameter set: Sungrow" in dyd, "DYD cites the OEM datasheet")
    dyr = dyr_text(d, INTAKE, get_profile("PJM"))
    ok("'REGC_A' 1" in dyr and "'REEC_C' 1" in dyr, "DYR blocks present")

    # Generic fallback must be labelled as such.
    tbd = {**INTAKE, "inverter": "TBD"}
    d_tbd = design_plant(build_graph(tbd, "CAISO"), tbd)
    ok("GENERIC WECC parameters" in dyd_text(d_tbd, tbd, prof),
       "generic fallback flagged in DYD")

    bt = bump_test(d, pf)
    ok(len(bt["t"]) > 200, f"simulation produced {len(bt['t'])} samples")
    ok(bt["all_pass"], "all dynamic checks pass: " +
       "; ".join(f"{c['name']}={'ok' if c['pass'] else 'FAIL'}" for c in bt["checks"]))
    ok(any("dup" in c["detail"] for c in bt["checks"]), "frequency response references droop")
    ok(bt["p_mw"][0] != 0 and abs(bt["p_mw"][0] - pf["p_poi_mw"]) < 1.0,
       "sim initialises at the solved dispatch")
    ok("OEM control internals are not simulated" in bt["model_note"],
       "engineering boundary stated")


def test_phase7_consistency() -> None:
    print("[phase 7] consistency + approvals")
    from backend.app.engine.consistency import run_engineering

    eng = run_engineering(INTAKE, "CAISO")
    names = {c["name"]: c for c in eng["checks"]}
    ok(names["MW chain arithmetic"]["status"] == "pass", "MW chain check passes on clean intake")
    ok(names["Load flow convergence"]["status"] == "pass", "convergence check")
    ok(names["Requested MW delivered"]["status"] == "pass", "delivery check")
    ok(names["Artifact/graph consistency"]["status"] == "pass",
       "rendered artifacts match the graph: " + names["Artifact/graph consistency"]["detail"])
    ok(names["Thermal loading"]["status"] == "pass", "thermal check")

    # Approval gate: engine not ready until assumptions are approved.
    ok(not eng["ready"] and eng["approvals"]["pending"] >= 2, "packet gated on approvals")
    approved = {**INTAKE,
                "approvals": {a["id"]: {"by": "J. Alvarez, PE", "at": "2026-08-04"}
                              for a in eng["approvals"]["items"]}}
    eng2 = run_engineering(approved, "CAISO")
    ok(eng2["approvals"]["all_approved"], "approvals recorded")
    ok(eng2["ready"], "engine ready once approved and checks pass")

    # Broken MW chain must fail the cross-check and block readiness.
    broken = {**approved, "net_mw_poi": 128.0}
    eng3 = run_engineering(broken, "CAISO")
    n3 = {c["name"]: c for c in eng3["checks"]}
    ok(n3["MW chain arithmetic"]["status"] == "fail", "broken MW chain flagged")
    ok(not eng3["ready"], "readiness blocked on failed check")

    # Declared-vs-computed losses: big declared losses should warn.
    lossy = {**approved, "losses_mw": 6.0, "net_mw_poi": 119.5}
    eng4 = run_engineering(lossy, "CAISO")
    n4 = {c["name"]: c for c in eng4["checks"]}
    ok(n4["Declared losses vs computed"]["status"] == "warn",
       "implausible declared losses warned: " + n4["Declared losses vs computed"]["detail"])

    # Source trace covers developer facts and engine outputs.
    srcs = {r["source"] for r in eng["source_trace"]}
    ok("developer" in srcs and "gridpilot_calculation" in srcs
       and "assumption_requiring_approval" in srcs and "oem_datasheet" in srcs,
       f"source taxonomy present in trace ({sorted(srcs)})")


def test_phase8_packet() -> None:
    print("[phase 8] packet integration")
    import zipfile
    from backend.app.services.caiso_packet import PACKETS_DIR, generate_packet
    from backend.app.engine.consistency import run_engineering

    # Submit the staged demo files and approve all assumptions.
    intake = dict(INTAKE)
    for k, v in list(intake.items()):
        if isinstance(v, dict) and v.get("staged"):
            intake[k] = {**v, "staged": False}
    eng = run_engineering(intake, "CAISO")
    intake["approvals"] = {a["id"]: {"by": "J. Alvarez, PE", "at": "2026-08-04"}
                           for a in eng["approvals"]["items"]}

    m = generate_packet(intake, "org_test", "CAISO")
    keys = {doc["key"] for doc in m["documents"]}
    for want in ("epc", "dyd", "sld", "sld_dxf", "flat_bump", "mw_poi",
                 "equipment_schedule", "assumptions", "source_trace", "portal_fields"):
        ok(want in keys, f"packet contains {want}")

    pdir = PACKETS_DIR / m["id"]
    for doc in m["documents"]:
        ok((pdir / doc["file"]).exists(), f"file exists: {doc['file']}")

    z = zipfile.ZipFile(pdir / m["zip_file"])
    deliverable = [d for d in m["documents"]
                   if d["key"] != "readme" and d["category"] == "checklist"]
    ok(len(z.namelist()) == len(deliverable),
       "zip holds exactly the checklist deliverables (README + supporting docs stay in-app)")
    ok(all(n[:2] not in ("S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8", "S9", "00")
           for n in z.namelist()), "no supporting files in the zip")

    e = m["engineering"]
    ok(e["loadflow"]["converged"], "manifest carries the solved case")
    ok(e["approvals"]["all_approved"], "manifest reflects approvals")
    ok(all(c["status"] != "fail" for c in e["checks"]),
       "no failing checks on the approved intake")
    ok(e["counts"]["inverters"] == 20, "manifest counts from the design engine")

    epc = (pdir / next(d["file"] for d in m["documents"] if d["key"] == "epc")).read_text()
    ok("Solved case" in epc and "backward/forward sweep" in epc,
       "load flow model is computed, not templated")
    dyd = (pdir / next(d["file"] for d in m["documents"] if d["key"] == "dyd")).read_text()
    ok("OEM parameter set: Sungrow" in dyd, "dynamic model carries OEM parameters")
    st = (pdir / next(d["file"] for d in m["documents"] if d["key"] == "source_trace")).read_text()
    ok("assumption_requiring_approval" in st or "Assumption" in st, "source trace lists assumptions")

    # MISO variant produces .raw/.dyr with the same engine.
    m2 = generate_packet(intake, "org_test", "MISO")
    files2 = {doc["key"]: doc["file"] for doc in m2["documents"]}
    ok(files2["epc"].endswith(".raw"), "MISO packet uses .raw")
    ok(files2["dyd"].endswith(".dyr"), "MISO packet uses .dyr")
    raw = (PACKETS_DIR / m2["id"] / files2["epc"]).read_text()
    ok(raw.startswith("0, 100.00, 33"), "MISO raw file is the computed PSS/E case")

    # Missing-data list: absent on the complete intake, present when facts are missing.
    ok("missing_data" not in keys, "no missing-data doc when the intake is complete")
    tbd = {**intake, "inverter": "TBD"}
    eng_tbd = run_engineering(tbd, "CAISO")
    tbd["approvals"] = {a["id"]: {"by": "J. Alvarez, PE", "at": "2026-08-04"}
                        for a in eng_tbd["approvals"]["items"]}
    m3 = generate_packet(tbd, "org_test", "CAISO")
    md_doc = next((d for d in m3["documents"] if d["key"] == "missing_data"), None)
    ok(md_doc is not None, "missing-data doc generated when facts are absent")
    md_text = (PACKETS_DIR / m3["id"] / md_doc["file"]).read_text()
    ok("Inverter model (library match)" in md_text, "missing item listed with label")
    ok("never invents missing engineering truth" in md_text, "engineering boundary stated")
    ok("PENDING approval" in md_text or "approved" in md_text,
       "stand-in assumptions cross-referenced")


def test_vendor_models() -> None:
    print("[vendor] OEM vendor .dyd integration")
    from backend.app.services.iso_profiles import get_profile
    from backend.app.engine.consistency import run_engineering
    from backend.app.engine.models_out import dyd_text
    from backend.app.engine.vendor_models import demo_vendor_dyd_text, vendor_overrides
    from backend.app.services.caiso_packet import extract_from_documents

    # The demo's example package parses into a PV override group.
    ov = vendor_overrides(demo_vendor_dyd_text(INTAKE), "Sungrow_SG4400UD_PSLF_Models.dyd")
    ok(ov is not None and "pv" in ov and "bess" not in ov, "demo package parses as PV fleet")
    ok(set(ov["pv"]["params"]) == {"regc", "reec", "repc"}, "all three parameter blocks parsed")
    ok(ov["pv"]["models"]["gen"] == "REGC_A", "model names captured")
    ok("mva" not in ov["pv"]["params"]["regc"], "writer-managed params stripped")

    # A vendor file with a changed parameter flows into the generated .dyd.
    text = demo_vendor_dyd_text(INTAKE).replace('"kqv" 2', '"kqv" 3.5')
    intake_v = {**INTAKE, "vendor_dyd": vendor_overrides(text, "SG4400UD_rev2.dyd")}
    d = design_plant(build_graph(intake_v, "CAISO"), intake_v)
    dyd = dyd_text(d, intake_v, get_profile("CAISO"))
    ok('"kqv" 3.5' in dyd, "vendor parameter value written to the plant .dyd")
    ok("Vendor model file SG4400UD_rev2.dyd" in dyd, "plant .dyd cites the vendor file")
    ok(d["inverter"]["verified"] and d["inverter"].get("vendor_file"), "entry marked vendor-verified")

    # Unparseable file -> no overrides, library set stays.
    ok(vendor_overrides("# vendor dyd dummy", "x.dyd") is None, "junk file yields no overrides")

    # Demo extraction produces the vendor_dyd field with provenance.
    res = extract_from_documents({"file_dyd": {"name": "Sungrow_SG4400UD_PSLF_Models.dyd",
                                               "size": 18240, "example": True}})
    ok(isinstance(res["fields"].get("vendor_dyd"), dict), "extraction returns vendor_dyd")
    ok(res["provenance"]["vendor_dyd"]["source"] == "file_dyd", "vendor_dyd provenance")
    ok(res["fields"]["dyd_status"] == "Received from vendor", "dyd_status set from the file")

    # Consistency check: integrated -> pass; attached-but-unparsed -> warn.
    eng_v = run_engineering({**intake_v,
                             "file_dyd": {"name": "SG4400UD_rev2.dyd", "size": 100}}, "CAISO")
    n = {c["name"]: c for c in eng_v["checks"]}
    ok(n["Vendor OEM parameters"]["status"] == "pass", "vendor check passes when integrated")
    eng_w = run_engineering({**INTAKE, "file_dyd": {"name": "opaque.dyd", "size": 10}}, "CAISO")
    nw = {c["name"]: c for c in eng_w["checks"]}
    ok(nw["Vendor OEM parameters"]["status"] == "warn", "warns when file attached but unparsed")


def test_intent_facts() -> None:
    print("[intent] gen-tie / shared facilities / queue reference")
    from backend.app.engine.consistency import run_engineering

    eng = run_engineering(INTAKE, "CAISO")
    ids = {a["id"] for a in eng["approvals"]["items"]}
    ok("design.gentie_mi" in ids, "blank gen-tie carried as an approvable assumption")

    with_fact = {**INTAKE, "gentie_mi": 3.2, "queue_ref": "Q-0788 (2024 cluster)"}
    eng2 = run_engineering(with_fact, "CAISO")
    ids2 = {a["id"] for a in eng2["approvals"]["items"]}
    ok("design.gentie_mi" not in ids2, "developer gen-tie removes the routing assumption")
    ok(eng2["design"]["gentie_mi"] == 3.2, "design engine uses the developer value")
    ok(eng2["approvals"]["total"] == eng["approvals"]["total"] - 1,
       "one fewer approval item once the fact is provided")

    g = eng2["graph"]
    ok(g["params"]["gentie_mi"]["source"] == SRC_DEV, "gen-tie tagged developer in the graph")
    ok(g["params"]["shared_facilities"]["value"] == "No shared facilities",
       "shared facilities captured in the graph")
    ok(g["params"]["queue_ref"]["value"].startswith("Q-0788"), "queue reference captured")

    row = next(r for r in eng2["design"]["schedule"] if r["item"] == "Gen-tie line")
    ok(row["source"] == "Developer" and row["verified"], "schedule row credits the developer")
    row0 = next(r for r in eng["design"]["schedule"] if r["item"] == "Gen-tie line")
    ok(row0["source"] == "Routing assumption" and not row0["verified"],
       "schedule row flags the assumption when blank")

    ok("3.2-mile gen-tie" in eng2["design"]["topology"], "topology text uses the fact")


def test_design_preferences() -> None:
    print("[preferences] substation arrangement + site constraints")
    single = {**INTAKE, "substation_arrangement": "Single main transformer"}
    g = build_graph(single, "CAISO")
    d = design_plant(g, single)
    ok(d["counts"]["main_transformers"] == 1, "single-GSU preference honored when feasible")
    ok(d["mpt"]["mva"] == 230.0, "sized up to the 230 MVA family unit")
    ok(g["params"]["design.n_mpt"]["source"] == "developer",
       "GSU count traced to the developer preference")

    # Too big for one standard unit -> engine keeps two and records why.
    big = {**INTAKE, "gross_mw": 300.0, "gross_mva": 315.0, "net_mw_poi": 297.0,
           "substation_arrangement": "Single main transformer"}
    g2 = build_graph(big, "CAISO")
    d2 = design_plant(g2, big)
    ok(d2["counts"]["main_transformers"] == 2, "infeasible preference overridden")
    ok("not feasible" in g2["params"]["design.n_mpt"]["trace"],
       "override reason recorded in the trace")

    # Default keeps the engine recommendation (regression guard).
    d3 = design_plant(build_graph(INTAKE, "CAISO"), INTAKE)
    ok(d3["counts"]["main_transformers"] == 2 and d3["mpt"]["mva"] == 140.0,
       "engine recommendation unchanged by default")

    cons = {**INTAKE, "site_constraints": "100 ft setback along the north fence line"}
    g4 = build_graph(cons, "CAISO")
    ok(g4["params"]["site_constraints"]["value"].startswith("100 ft"),
       "site constraints recorded in the graph")


def test_tap_and_base_case() -> None:
    print("[tap] OLTC tap adjustment + system representation")
    from backend.app.services.iso_profiles import get_profile
    from backend.app.engine.models_out import epc_text
    from backend.app.engine.powerflow import solve

    d = design_plant(build_graph(INTAKE, "CAISO"), INTAKE)
    pf = solve(d, INTAKE)
    ok(pf["mpt_tap"] == 1.0, "nominal tap on the base case (collector in band)")

    # A very long gen-tie pushes the collector bus above 1.02 pu — the OLTC
    # must step the tap and bring it back while still meeting the POI request.
    long_tie = {**INTAKE, "gentie_mi": 80}
    d2 = design_plant(build_graph(long_tie, "CAISO"), long_tie)
    pf2 = solve(d2, long_tie)
    ok(pf2["mpt_tap"] > 1.0, f"tap stepped up ({pf2['mpt_tap']})")
    steps = (pf2["mpt_tap"] - 1.0) / 0.00625
    ok(abs(steps - round(steps)) < 1e-9, "tap lands on the 0.625% step grid")
    v_col = next(v for v in pf2["voltages"] if "collector" in v["bus"])
    ok(0.98 <= v_col["v_pu"] <= 1.02, f"collector bus back in band ({v_col['v_pu']} pu)")
    ok(pf2["poi_match"], "dispatch still meets the POI request with the tap applied")
    pf2b = solve(design_plant(build_graph(long_tie, "CAISO"), long_tie), long_tie)
    ok(pf2b["mpt_tap"] == pf2["mpt_tap"], "tap selection is deterministic")

    epc = epc_text(d2, pf2, long_tie, get_profile("CAISO"))
    ok(f'{pf2["mpt_tap"]:.4f}' in epc, "EPC transformer record carries the tap")


def test_datasheet_ingest() -> None:
    print("[datasheet] ingestion -> unverified custom entry")
    from backend.app.services.iso_profiles import get_profile
    from backend.app.engine.consistency import run_engineering
    from backend.app.engine.models_out import dyd_text
    from backend.app.services.caiso_packet import demo_datasheet_draft

    draft = demo_datasheet_draft("GE_LV5plus_3.6MVA_Datasheet.pdf", "pv_inverter")
    ok(draft["vendor"] == "GE" and draft["mva"] == 3.6, "draft parsed from the filename")
    ok(draft["source"].endswith(".pdf"), "draft records its source document")

    entry = {**draft, "verified": False}
    intake_c = {**INTAKE, "inverter": "GE LV5plus", "custom_equipment": [entry]}
    g = build_graph(intake_c, "CAISO")
    d = design_plant(g, intake_c)
    ok(d["inverter"]["vendor"] == "GE" and d["inverter"]["mva"] == 3.6,
       "design engine uses the datasheet ratings")
    ok(not d["inverter"]["verified"] and d["inverter"].get("custom"),
       "entry stays unverified")
    # PV 78 MW / 0.9 = 86.7 MVA / 3.6 MVA per unit -> 25 inverters (vs 20 with the Sungrow).
    ok(d["counts"]["inverters"] == 25, f"fleet resized ({d['counts']['inverters']} units)")
    ok(g["params"]["equip.inverter"]["source"] == SRC_DOC,
       "graph tags the entry as document extraction")

    eng = run_engineering(intake_c, "CAISO")
    ids = {a["id"] for a in eng["approvals"]["items"]}
    ok("equip.inverter_verify" in ids, "engineer verification queued as an approval")
    dyd = dyd_text(eng["design"], intake_c, get_profile("CAISO"))
    ok("GENERIC WECC parameters" in dyd, "dynamic model stays generic (datasheet has no MOD-026/027)")
    row = next(r for r in eng["design"]["schedule"] if r["item"] == "PV inverter")
    ok(not row["verified"] and "unverified" in row["source"], "schedule row flags the entry")

    # No match when the intake text doesn't reference the entry.
    other = {**INTAKE, "custom_equipment": [entry]}
    d2 = design_plant(build_graph(other, "CAISO"), other)
    ok(d2["inverter"]["vendor"] == "Sungrow", "library match unaffected when text differs")

    # BESS custom entry.
    bdraft = demo_datasheet_draft("CATL_EnerOne_2MW_spec.pdf", "bess")
    intake_b = {**INTAKE, "bess_vendor": "CATL EnerOne", "custom_equipment": [bdraft]}
    eng_b = run_engineering(intake_b, "CAISO")
    ok(eng_b["design"]["bess_unit"]["vendor"] == "CATL", "BESS datasheet entry matched")
    ok("equip.bess_verify" in {a["id"] for a in eng_b["approvals"]["items"]},
       "BESS verification queued")


def test_graph_history() -> None:
    print("[history] project graph mutation audit trail")
    from backend.app.engine.consistency import run_engineering
    from backend.app.services.caiso_packet import generate_packet

    intake = {**INTAKE}
    intake.pop("graph_history", None)
    v0 = graph_version(intake)

    hist = record_history(intake, by="Alex Rivera", note="Initial project graph", iso="CAISO")
    ok(len(hist) == 1, "first mutation recorded")
    ok(hist[0]["version"] == v0, "history version matches content hash")
    ok(hist[0]["by"] == "Alex Rivera" and "Initial" in hist[0]["note"],
       "who/what recorded")
    ok("snapshot" in hist[0], "latest entry keeps a fact snapshot")

    # Same content — no new entry.
    hist2 = record_history(intake, by="Alex Rivera", note="noop", iso="CAISO")
    ok(len(hist2) == 1, "unchanged content does not append")

    # A developer fact change produces a new version with a changed-key list.
    intake["gentie_mi"] = 4.5
    hist3 = record_history(intake, by="Alex Rivera", note="Gen-tie confirmed", iso="CAISO")
    ok(len(hist3) == 2, "content change appends a second entry")
    ok(hist3[-1]["version"] != v0, "new content hash")
    ok("gentie_mi" in hist3[-1]["changed"], "changed key listed")
    ok("snapshot" not in hist3[0], "older snapshots dropped to keep payload small")
    ok(graph_version(intake) == hist3[-1]["version"],
       "history excluded from the content hash")

    # Engineering pass records history and surfaces it publicly.
    eng_intake = {**intake, "queue_ref": "Q-1001"}
    eng = run_engineering(eng_intake, "CAISO", actor="J. Alvarez, PE",
                          history_note="Engineering design review")
    pub = eng["graph_history"]
    ok(len(pub) >= 2, "engineering returns public history")
    ok("snapshot" not in pub[-1], "public rows omit the snapshot")
    ok(pub[-1].get("by") == "J. Alvarez, PE", "actor credited")
    ok(pub[-1].get("note") == "Engineering design review", "note recorded")
    ok("queue_ref" in (pub[-1].get("changed") or []), "engineering change keyed")

    # Source-trace appendix carries the history table.
    packet_intake = {**INTAKE, "net_mw_poi": 125.0, "bess_mwh": 200.0}
    for k, v in list(packet_intake.items()):
        if isinstance(v, dict) and v.get("staged"):
            packet_intake[k] = {**v, "staged": False}
    eng_p = run_engineering(packet_intake, "CAISO", actor="Alex Rivera")
    packet_intake["approvals"] = {a["id"]: {"by": "J. Alvarez, PE", "at": "2026-08-05"}
                                 for a in eng_p["approvals"]["items"]}
    # Approvals change the hash — record once more, then generate.
    run_engineering(packet_intake, "CAISO", actor="J. Alvarez, PE",
                    history_note="Assumptions approved")
    m = generate_packet(packet_intake, "org_hist", "CAISO")
    from backend.app.services.caiso_packet import PACKETS_DIR
    st = next(d for d in m["documents"] if d["key"] == "source_trace")
    text = (PACKETS_DIR / m["id"] / st["file"]).read_text()
    ok("Graph version history" in text, "source trace lists the history section")
    ok("Alex Rivera" in text or "J. Alvarez" in text, "history actors appear in the appendix")
    ok(len(history_public(packet_intake)) >= 2, "approval + engineering left an audit trail")


TESTS = [test_phase1_graph, test_phase2_equipment, test_phase3_design, test_phase4_sld,
         test_phase5_powerflow, test_phase6_models, test_phase7_consistency,
         test_phase8_packet, test_vendor_models, test_intent_facts,
         test_design_preferences, test_tap_and_base_case, test_datasheet_ingest,
         test_graph_history]

if __name__ == "__main__":
    only = sys.argv[1] if len(sys.argv) > 1 else None
    for t in TESTS:
        if only and only not in t.__name__:
            continue
        t()
    print(f"\nALL ENGINE TESTS PASSED ({PASS} assertions)")

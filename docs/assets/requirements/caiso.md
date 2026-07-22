---
iso: CAISO
process: Generator Interconnection and Deliverability Allocation Procedures (GIDAP), as amended by the Interconnection Process Enhancements (IPE)
tariff_basis: CAISO Tariff Appendix DD; Appendix 1 (Interconnection Request); Attachment A (technical data)
portal: RIMS5 (Resource Interconnection Management System)
updated: 2026-07
---

# CAISO — Generator Interconnection Requirements

## 1. Process overview & timeline

- Annual **cluster window** (Interconnection Request submission window, typically April). All IRs received in a window are studied together as a cluster.
- Post-IPE flow: IR validation → scoping → **Phase I / combined cluster study** (system impact + deliverability) → results meeting → **Phase II refinement** → GIA negotiation and execution.
- **Fast Track / Independent Study Process (ISP)** available for small projects (≤ 5 MW inverter-based on distribution-level POIs) with simplified screens instead of cluster study.
- Cluster study cycle from window close to Phase I results is roughly 12 months; GIA execution typically 2–3 years from IR for cluster projects.

## 2. Application / entry requirements

- Completed **Appendix 1** Interconnection Request form, executed by an authorized signatory.
- **Attachment A** technical data workbook, complete for the technology (solar PV, BESS, hybrid, wind, synchronous).
- One point of interconnection per IR; POI must identify substation/line and voltage.
- Proof of **site exclusivity** (or deposit in lieu — see §4).
- Requested **deliverability status**: Full Capacity, Partial, or Energy-Only.
- Commercial operation date within tariff limits (COD generally ≤ 7 years from IR window, extendable with justification).

## 3. Deposits, fees & milestones

- **Study deposit** at IR: $150,000 per request (refundable balance after study costs; higher for larger projects under IPE scoring).
- IPE adds **commercial readiness criteria** — projects are scored (site exclusivity, LSE interest / PPA, financing) and only the top-scoring MW per zone advance to study.
- Interconnection Financial Security (IFS) postings follow GIA execution in three postings tied to network upgrade cost responsibility.

## 4. Site control requirements

- **100% site exclusivity for the generating facility footprint** at IR (lease, option, or ownership), demonstrated by executed documents.
- Exclusivity must cover the full expected term (through COD) and the acreage consistent with technology (≈ 5–10 acres/MW solar PV; ≈ 1 acre/MW BESS is a common review heuristic).
- **Deposit in lieu of site exclusivity** is limited post-IPE; regulatory-restricted lands (e.g., federal land applications) have carve-outs with evidence of application.
- Gen-tie corridors: demonstrate control or a credible routing plan; deficiencies here are a common validation failure.

## 5. Technical data & modeling requirements

- **GE PSLF** load flow model (`.epc`) and dynamic data (`.dyd`) required for all IRs; WECC-approved dynamic models only (REGC/REEC/REPC family for IBRs).
- **PSCAD** model required for inverter-based resources in weak-grid areas (on request).
- Reactive capability: **±0.95 power factor at the POI** across the full output range (FERC Order 827); reactive capability curves (P-Q) required.
- Primary frequency response settings per **FERC Order 842** (droop ≤ 5%, deadband ≤ ±0.036 Hz).
- Voltage ride-through and frequency ride-through per NERC PRC-024 / IEEE 2800 expectations.
- BESS: MWh rating, max charge/discharge, round-trip efficiency, charging source declaration (grid vs co-located).
- Single-line diagram: POI voltage, revenue metering, ownership demarcation, protective relays with ANSI device numbers, CT/PT ratios, GSU data (MVA, %Z, kV ratio).

## 6. Required documents checklist

1. Appendix 1 — Interconnection Request form (executed)
2. Attachment A — technical data workbook
3. Site exclusivity evidence (lease/option/deed) or deposit-in-lieu justification
4. Proof of authorized signatory (secretary certificate / resolution)
5. PSLF `.epc` power flow representation
6. PSLF `.dyd` dynamic model file
7. Reactive capability (P-Q) curves at POI
8. Single-line diagram (breaker-level)
9. Site plan / general arrangement drawing
10. Project boundary KMZ (parcel polygon, POI, gen-tie route)
11. BESS specification sheet (if storage/hybrid)
12. Study deposit wire confirmation
13. LSE interest / commercial readiness evidence (IPE scoring)

## 7. Withdrawal & penalties

- Withdrawal before study commencement: unused study deposit refunded.
- After Phase I results: withdrawal forfeits escalating portions of study deposit and IFS; cost responsibility for restudies may attach.
- Failure to post IFS or meet readiness milestones results in deemed withdrawal.

## 8. Common deficiency triggers

- MW chain inconsistency: inverter total ≠ transformer rating ≠ POI MW ≠ Appendix 1 stated capacity.
- Site exclusivity acreage below technology footprint, or term expiring before COD.
- Missing or non-WECC dynamic models; generic placeholders rejected.
- BESS MWh / charging data absent from Attachment A.
- SLD missing revenue metering, demarcation, or relay ANSI numbers.
- Signatory documents not matching the entity on the IR.

## 9. References

- CAISO Tariff Appendix DD (GIDAP): https://www.caiso.com/rules/Pages/Regulatory/Default.aspx
- CAISO generator interconnection page: https://www.caiso.com/planning/Pages/GeneratorInterconnection/Default.aspx
- RIMS: https://rims.caiso.com
- FERC Orders 827, 842, 2023

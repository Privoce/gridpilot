---
iso: ERCOT
process: Full Interconnection Study (FIS) process — serial, not FERC Order 2023 cluster (ERCOT is not FERC-jurisdictional for interconnection)
tariff_basis: ERCOT Planning Guide Section 5; Nodal Protocols; interconnection handled with the interconnecting TSP
portal: RIOO-IS (Resource Integration and Ongoing Operations — Interconnection Services)
updated: 2026-07
---

# ERCOT — Generator Interconnection Requirements

## 1. Process overview & timeline

- Serial "first-come" process, materially faster than FERC-jurisdictional ISOs (typical **12–18 months** from INR to energization approval for well-prepared projects).
- Steps: **Interconnection Request (INR) via RIOO** → screening study (optional) → **Full Interconnection Study (FIS)** with the Transmission Service Provider (TSP): steady-state, short-circuit, dynamic/stability → **Standard Generation Interconnection Agreement (SGIA)** with the TSP → Quarterly Stability Assessment participation → model acceptance → **Part I–III of the Resource registration** → commissioning approvals (QSE, telemetry, ride-through checks).
- ERCOT reviews and approves models; the TSP executes the SGIA (no ISO-level GIA).

## 2. Application / entry requirements

- INR submitted in RIOO with:
  - Project data: technology, MW (summer/winter net), POI, in-service date
  - **$5,000 INR fee** (screening study fee separate if requested)
  - Contact and legal entity information
- FIS request requires a **security deposit with the TSP** for study costs (varies by TSP; commonly $50k–$100k order of magnitude).
- Air permit / water rights not required at INR (unlike load); generation-specific readiness applies at registration stages.

## 3. Deposits, fees & milestones

- INR fee: **$5,000** (non-refundable).
- FIS study funding: actual TSP + ERCOT study costs, invoiced against deposit.
- No M-series readiness milestones; discipline comes from planning-model inclusion requirements and SGIA terms.
- **Order 2023 does not apply**; there are no cluster decision points or AWPs.

## 4. Site control requirements

- ERCOT itself does not gate the INR on site control evidence the way FERC ISOs do, but the **FIS cannot conclude and the SGIA will not be executed without a defined site and gen-tie**; TSPs require site control for facility design.
- Practical standard: demonstrate control of the plant footprint and gen-tie route before FIS kickoff to avoid restudy.

## 5. Technical data & modeling requirements

- **PSS/E** steady-state and dynamic models required; ERCOT additionally requires **PSCAD models for all IBRs** (mandatory since NOGRR245-era reforms) with vendor-verified parameters.
- **Dynamic model quality checks**: models must pass ERCOT's model quality tests (flat start, disturbance playback) before acceptance.
- **NOGRR245 / IEEE 2800-aligned ride-through requirements** for IBRs — voltage and frequency ride-through settings documented and attested.
- Reactive capability: ±0.95 PF at POI per Nodal Protocols; voltage support obligations (URRE/VSS).
- SSO (sub-synchronous oscillation) screening data near series-compensated lines.
- One-line diagram, GSU data, protection data, metering (EPS metering per Settlement Metering Operating Guide).
- RARF (Resource Asset Registration Form) completeness drives later steps — many data fields (unit reactive limits, inverter firmware, BESS duration) trace back to FIS inputs.

## 6. Required documents checklist

1. INR (RIOO submission) + $5,000 fee
2. FIS study agreement + deposit with TSP
3. PSS/E steady-state case data
4. PSS/E dynamic models (.dyr) with documentation
5. PSCAD model package (IBRs — mandatory)
6. Reactive capability curves
7. One-line diagram with POI/metering/protection
8. Site plan and gen-tie route
9. RARF (registration phase)
10. SGIA (executed with TSP)
11. Commissioning/energization checklists (Part I–III approvals)

## 7. Withdrawal & penalties

- No AWP structure; abandoning a project forfeits fees/study costs incurred.
- Inactive or non-responsive INRs are cancelled administratively; planning-model removal follows.

## 8. Common deficiency triggers

- PSCAD model missing, unverified, or inconsistent with PSS/E model (top cause of FIS delay).
- Dynamic models failing ERCOT quality tests.
- Ride-through parameter attestations missing (NOGRR245).
- RARF fields inconsistent with FIS data (MW, reactive limits, BESS duration).
- One-line missing metering or protection detail required by the TSP.

## 9. References

- ERCOT Planning Guide §5: https://www.ercot.com/mktrules/guides/planning
- RIOO: https://www.ercot.com/services/rq/integration
- ERCOT dynamic model requirements & quality tests; NOGRR245
- TSP-specific interconnection handbooks (Oncor, CenterPoint, AEP, LCRA, etc.)

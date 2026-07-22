---
iso: NYISO
process: OATT Attachment X interconnection procedures (cluster study process post-Order 2023); optional Pre-Application Report
tariff_basis: NYISO OATT Attachments X, Z; Standard Large Facility Interconnection Procedures (LFIP) / Small Generator (SGIP)
portal: NYISO Interconnection queue (queue submissions via DPS/NYISO forms)
updated: 2026-07
---

# NYISO — Generator Interconnection Requirements

## 1. Process overview & timeline

- Post-Order-2023 **cluster study process**: annual application window → validation → **Cluster Study** (system impact, ~1 year) → decision point → **facilities-level studies** → Interconnection Agreement.
- Distinct tracks for **Large Facilities** (> 20 MW, LFIP) and **Small Generating Facilities** (≤ 20 MW, SGIP); expedited screens below 5 MW.
- **Pre-Application Report** (optional, non-binding): a developer may request POI information from NYISO and the Connecting Transmission Owner (CTO) before filing.

## 2. Pre-application (optional but recommended)

From the NYISO Pre-Application Request Form (IITF template):

- Fee: **$5,000 per Point of Interconnection, non-refundable**, wired to NYISO; submit form to SGPreApp@nyiso.com.
- Every question requires a **substantive answer** — "TBD" or "not available" responses are rejected.
- Form contents:
  - Project overview: name, requestor, contact; project type (generation / transmission / combined); energy source(s); nameplate MW and MVA
  - Storage: capacity (MWh), max charging (MWh/hr), max discharging (MWh/hr), max aggregate injection for hybrids; whether storage charges from grid (yes/no)
  - Estimated in-service date
  - Primary and secondary POI: station name, line name, POI location (decimal lat/long), expected POI voltage; conceptual or breaker-level one-line diagram checkbox
  - Project location map relative to POI(s) (layout, property boundaries)
  - New vs existing service; site load (min/max kW current and proposed); intended use (net metering / self-supply / wholesale sales)
  - Whether the project is an uprate to a queued project
  - Requestor signature certifying accuracy
- NYISO forwards the form to the CTO, which completes the **Pre-Application Report** (Appendix A) from readily available data: line name/ID, PSS/e bus numbers and circuit IDs, voltage, networked vs radial, seasonal ratings (Normal/LTE/STE MVA), terminal end stations and distance to POI, substation data, circuit loading and existing/proposed generation (for distribution POIs), known constraints and planned upgrades. Non-binding; confers no rights.

## 3. Application / entry requirements

- Interconnection Request in the cluster window with study deposit, technical data, and requested service: **Capacity Resource Interconnection Service (CRIS)** and/or **Energy Resource Interconnection Service (ERIS)**.
- Site control evidence at application (Order 2023 compliance — 100% facility footprint or regulatory-barrier deposit).
- POI on the New York State Transmission System or Distribution System; CTO identified.

## 4. Deposits, fees & milestones

- Pre-application report: $5,000/POI (optional step).
- Cluster study deposits scaled by project size plus **commercial readiness deposits** that escalate at decision points (Order 2023 pattern); verify the current Attachment X schedule.
- Interconnection financial security at IA execution per Attachment S (System Deliverability Upgrades / SUFs headroom rules are NYISO-specific).

## 5. Technical data & modeling requirements

- **PSS/E** power flow and dynamics (NYISO base-case compatible); IBR models from approved libraries with documentation.
- Reactive capability ±0.95 PF at POI; PFR per Order 842; ride-through per PRC-024 / IEEE 2800 as adopted.
- NYISO-specific deliverability data for CRIS (capacity accreditation interacts with interconnection service level).
- One-line diagram (breaker-level for large facilities), metering, protection, GSU data.
- Storage/hybrid: MWh, charge/discharge limits, grid-charging declaration (mirrors pre-application fields).

## 6. Required documents checklist

1. Interconnection Request form (cluster window)
2. Study + readiness deposit confirmations
3. Site control evidence (100% footprint)
4. Signatory/entity documentation
5. PSS/E raw + dyr models
6. Reactive capability curves
7. One-line diagram
8. Site plan / property boundary map with POI
9. Equipment data sheets (inverter, GSU, BESS)
10. CRIS/ERIS election
11. (Optional) Pre-Application Request Form + $5,000/POI fee

## 7. Withdrawal & penalties

- Escalating forfeiture of readiness deposits at decision points after study results are posted; unexpended study deposits refundable.
- Deficient or non-responsive requests removed from the cluster after cure periods.

## 8. Common deficiency triggers

- "TBD" answers on forms (explicitly disallowed at pre-application; equally fatal at IR validation).
- Missing lat/long or POI voltage; one-line not breaker-level for large facilities.
- Storage charging behavior undeclared for hybrids.
- Site control not matching footprint or COD term.
- CRIS request inconsistent with deliverability data.

## 9. References

- NYISO interconnection process: https://www.nyiso.com/interconnections
- NYISO OATT Attachments X, S, Z
- Pre-Application Request Form (IITF draft, Oct 20, 2023) — source of §2 details
- FERC Order 2023 compliance (NYISO)

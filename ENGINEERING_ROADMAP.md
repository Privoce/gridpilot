# GridPilot Engineering Engine — Implementation Roadmap

Source: `GridPilot_Developer_Input_and_AI_Engineering_Package.pdf` (product blueprint).
Goal: evolve GridPilot from a document-assembly product into a deterministic
engineering engine that turns developer facts into computed, source-traced,
submission-ready interconnection packages.

Guiding principle from the blueprint:

> AI can generate engineering deliverables, but it cannot invent missing
> engineering truth. The LLM extracts, explains, and traces; a deterministic
> engine computes, draws, and validates.

---

## Where we are today (baseline)

| Blueprint layer | Status in current app |
| --- | --- |
| Developer intake (structured form, AI extraction) | Built — per-ISO intake, staged uploads, Grok extraction |
| Document extraction | Built (PDF/XLSX/KMZ → intake fields with provenance) |
| Project Graph | Not built — intake is a flat key/value dict |
| Equipment Library | Not built |
| Design Engine (topology, SLD, site drawing) | Template-generated placeholders, not computed |
| Calculation Engine (load-flow, short-circuit) | Not built — model files are text templates |
| ISO Rule Engine | Partially built — per-ISO profiles, validation rules, requirement citations |
| Consistency Layer | Partially built — intake-level validation only |
| Approval Workflow | Not built |
| Package Generator | Built — 15-doc packet, per-ISO naming, previews |

The MVP boundary from the blueprint matches what we already target:
**solar + BESS, one ISO (CAISO), limited inverter/transformer families.**

---

## Phase 1 — Project Graph (the foundation everything reads from)

**Outcome:** one versioned, source-traced data model that every deliverable
derives from. A parameter changes once; SLD, forms, models, and portal fields
all update.

- Define the graph schema: project → sites → POI → substation → transformers →
  collector feeders → inverter blocks → inverters/BESS units. Nodes carry
  ratings; edges carry impedance/length/ampacity.
- Every value gets a **source tag**: `developer`, `oem_datasheet`, `iso_rule`,
  `gridpilot_calculation`, or `assumption_requiring_approval` — plus a pointer
  to the originating file/page where applicable.
- Version each graph mutation (who/what/when); keep an audit log.
- Migrate the existing intake + extraction pipeline to write into the graph
  instead of a flat dict; keep the current form UI as the editing surface.
- Serialize to JSON; store per project; content-hash for packet regeneration
  (extends the current stateless `?d=` mechanism).

**Effort:** 3–4 weeks. Pure backend + data model, no new math.
**Risk:** low. This is the highest-leverage step and blocks everything below.

## Phase 2 — Equipment Library

**Outcome:** OEM equipment is selected from a curated library, not typed in.

- Seed data: 3–5 inverter families (e.g. Sungrow, SMA, Power Electronics),
  2–3 BESS products (e.g. Tesla Megapack 2XL), standard GSU/main transformer
  ranges, typical 34.5 kV collector cable types.
- Per entry: ratings, fault-current contribution, P-Q capability data,
  approved WECC/ISO model names (REGC_A/REEC_A/REPC_A etc.), `.dyd`/`.dyr`
  parameter blocks, datasheet references.
- Datasheet ingestion: LLM extracts candidate parameters → engineer confirms →
  entry becomes reusable. Never auto-publish unverified OEM parameters.
- Model registry tracks software targets (PSLF vs PSS/E) and versions.

**Effort:** 2–3 weeks for the framework + seed catalog (grows continuously).
**Risk:** medium — data quality. Mitigate with the confirm-before-publish flow.

## Phase 3 — Topology & Design Engine

**Outcome:** from graph facts + design preferences, generate the electrical
topology and equipment schedule deterministically.

- Rules engine sizes the plant: N inverters → inverter blocks (per skid MVA) →
  collector feeders (ampacity + voltage-drop constraints) → collector bus →
  main transformer count/size → gen-tie → POI.
- Inputs: nameplate MW, MWh, POI voltage, collector voltage preference,
  gen-tie length, site constraints (from Phase 1), equipment picks (Phase 2).
- Outputs: complete topology in the graph + equipment schedule (CSV/XLSX)
  + missing-data list when facts are absent.
- Flag every derived value as `gridpilot_calculation` with the formula recorded.

**Effort:** 4–5 weeks including validation against 2–3 real project examples.
**Risk:** medium — needs a power-systems engineer to bless the sizing rules.

## Phase 4 — SLD Engine (first flagship engineering deliverable)

**Outcome:** an editable single-line diagram generated from the topology —
never an image-model drawing.

- Deterministic layout engine over the project graph: buses as horizontal
  rails, bays ordered POI → gen-tie → main transformers → collector bus →
  feeders → representative inverter block (with "typical of N" notation).
- IEEE/ANSI symbol library (breakers, switches, transformers, PTs/CTs,
  metering, grounding).
- Include metering points, protection points, ownership/change-of-ownership
  boundary, and POI marker — the items ISOs actually check.
- Export SVG (native), PDF (print), and DXF (editable in CAD). DWG via DXF is
  acceptable at this stage.
- Regenerate on any graph change; diagram is a view, never hand-edited state.

**Effort:** 5–6 weeks (layout engine is the hard part; symbols are a week).
**Risk:** medium. Start with the fixed solar+BESS template topology from
Phase 3 — a general-purpose SLD engine is not needed for MVP.

## Phase 5 — Calculation Engine (load-flow + short-circuit)

**Outcome:** a real, converged load-flow model and results — not a template.

- Build the plant equivalent model from the graph: impedances from equipment
  library + cable lengths, transformer taps, reactive devices.
- MVP solver: **pandapower or GridCal** (open-source, embeddable, auditable).
  Run flat-start power flow, check convergence, voltages, thermal loading, and
  requested MW/Mvar at the POI.
- Export ISO-format model files: PSLF `.epc` and PSS/E `.raw` writers from the
  solved case (file formats are documented; writers are deterministic code).
- Deliverable is a package: model file + input assumptions + convergence log +
  POI output + warnings + source trace (exactly what the blueprint specifies).
- Short-circuit: IEC/ANSI calculation from fault-current data in the library.
- ISO base cases are licensed/confidential — design for "customer-supplied
  base case in an authorized environment"; never scrape or fabricate one.

**Effort:** 6–8 weeks.
**Risk:** high value, medium-high difficulty. The open-source-solver-first
strategy avoids GE/PTI licensing until customers demand native runs.

## Phase 6 — Dynamic Model Assembly & Validation

**Outcome:** configured, validated OEM dynamic models per project and ISO.

- Map selected equipment to ISO-accepted models from the registry; write
  `.dyd`/`.dyr` with OEM-approved parameters; connect plant controller,
  inverter, and protection models.
- Validation runs: flat-start (no-disturbance) plus voltage/frequency bump
  tests. MVP simulation via **ANDES** (open-source) for sanity checks; native
  PSLF/PSS/E runs in a licensed environment as a later tier.
- Auto-generate validation plots and a review package with warnings.
- Hard boundary (per blueprint): never invent proprietary control behavior,
  protection settings, or EMT internals. Missing OEM data → item on the
  missing-data list, not a guess.
- PSCAD/EMT: integration and benchmarking only, with OEM-supplied models.

**Effort:** 5–7 weeks after Phase 5.
**Risk:** high — this is where "requires OEM evidence" bites. The missing-data
list and approval workflow carry the UX.

## Phase 7 — Consistency Layer + Engineer Approval Workflow

**Outcome:** "submission-ready" per the blueprint's definition — consistent
numbers everywhere, explained warnings, approved assumptions.

- Cross-document checks: every MW/Mvar/kV/impedance value in forms, SLD,
  models, and workbook traces to the same graph node (mostly free once
  Phases 1–6 read from the graph; the check verifies renderers didn't drift).
- Assumption ledger: everything tagged `assumption_requiring_approval` lands
  in a review queue with context, alternatives, and impact.
- Approval UI: engineer reviews → approves/edits → approval recorded with
  name + timestamp; packet generation blocks on unresolved judgment items.
- Legal/PE boundaries stay human: signature and certification tasks are
  tracked in the workflow but executed outside GridPilot.

**Effort:** 3–4 weeks.
**Risk:** low technically; high product value (this is the trust story).

## Phase 8 — Package Generator & Portal Fields

**Outcome:** the existing packet upgraded from templates to computed outputs.

- Replace template `.epc`/`.dyd`/`.raw`/`.dyr` with Phase 5/6 outputs.
- Replace illustrative plots with real flat-run/bump-test plots.
- Add: model validation report, assumptions & approvals log, missing-data
  list, source-trace appendix.
- Portal-ready field export (RIMS5 first): JSON/CSV of every portal field so
  the customer can copy or (later) auto-fill submissions.

**Effort:** 2–3 weeks (generation pipeline already exists).

---

## Sequencing & timeline

Phases 1→2→3 are strictly sequential (~9–12 weeks). Then 4 and 5 can run in
parallel (~6–8 weeks), followed by 6, with 7 and 8 overlapping the tail
(~6–8 weeks). **Total: roughly 6–8 months with 2–3 engineers**, one of whom
must be a power-systems engineer (or a committed fractional PE advisor) —
sizing rules, model mappings, and validation criteria all need professional
sign-off.

Demo-able milestones along the way:

1. **End of Phase 1:** field-level source tags visible in the product ("every
   value knows where it came from") — strong demo, cheap to ship.
2. **End of Phase 4:** editable SLD generated live from intake changes — the
   flagship "consultants don't do this" demo.
3. **End of Phase 5:** converged load-flow with a validation report — the
   moment the models stop being samples.
4. **End of Phase 7:** engineer approval flow — the enterprise trust story.

## Cross-cutting rules (apply to every phase)

- **LLM/engine split:** LLMs only extract, interpret rules, match semantics,
  and draft explanations. All numbers come from deterministic code with
  recorded inputs, formulas, software versions, and outputs.
- **Auditability:** every calculation reproducible from stored inputs; every
  generated file traceable to a graph version.
- **Licensing:** PSLF/PSS/E/PSCAD and ISO base cases are customer- or
  partner-licensed; the product must degrade gracefully to open-source
  solvers + file export when licenses are absent.
- **Scope discipline:** solar + BESS, CAISO, limited equipment families until
  Phase 8 is stable; other ISOs ride on the existing profile system.

## Top risks

| Risk | Mitigation |
| --- | --- |
| Sizing/model rules wrong without PE oversight | Hire/retain power-systems engineer before Phase 3 |
| OEM data unavailable or under NDA | Missing-data list + customer-supplied uploads; never guess |
| Open-source solver results questioned by ISOs | Position as pre-submission validation; native PSLF/PSS/E tier later |
| Scope creep to all ISOs/technologies | Hold the MVP boundary; ISO profiles already isolate localization |
| SLD generality rabbit hole | Fixed solar+BESS template topology only for MVP |

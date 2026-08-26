# CAISO Interconnection Request — Minimum Requirements Checklist

Independent Study Process / Fast Track — all elements below must be submitted for a
project to qualify to be validated. Source: `CAISO Checklist .docx` (official CAISO
form, annotated with team assignments).

| # | Requirement | Owner | GridPilot packet doc | Status |
|---|-------------|-------|----------------------|--------|
| 1 | Interconnection Study Deposit — $150,000 Independent Study / $500 non-refundable Fast Track | Developer (wire) | — (action item only) | **Skipped** per instruction — money wire, not a document |
| 2 | Completed **Appendix 1** (Interconnection Request) | han@faradon.com | `02_Appendix1_*.pdf` — auto-filled from intake, previewable | Generated |
| 3 | Completed **Attachment A to Appendix 1** (Generator Technical Data — Excel). Technical Data tab: no errors, warnings explained. IR Validation & Comments tab: Column A = "Yes"/"N/A" on all items | @Ling | `03_AttachmentA_*.xlsx` — mirrors official .xlsm sheets | Generated |
| 4 | **Evidence of Site Exclusivity** (Site Exclusivity/Control Demonstration Form) | Brian Yang | `04_SiteExclusivity_*.pdf` — official form layout | Generated |
| 5 | Independent Study ONLY — eligibility demonstrations (COD, permits, PO, financing, POI status, precursor upgrades) | — | — | **Skipped** per instruction |
| 6 | **Load Flow Model (.epc)** | Complete | `06_LoadFlowModel_*.epc` — engine output | Kept as-is (already good) |
| 7 | **Dynamic Model (.dyd)** | Complete | `07_DynamicModel_*.dyd` — engine output | Kept as-is (already good) |
| 8 | **Reactive Power capability document** | Brian Yang | `08_ReactivePowerCapability_*.pdf` — tabular calc per CAISO example | Generated |
| 9 | **Site Drawing** | @Lingyu | `09_SiteDrawing_*.pdf` — POI, MW, kV gen-tie, distance | Generated |
| 10 | **Single Line Diagram** | @Lingyu | `10_SingleLineDiagram_*.pdf` (+ `.dxf`) — conceptual SLD, not-for-construction stamp, tie-line data, legend | Generated |
| 11 | **Flat run & bump test plot** from PSLF — no-fault 10 s, 3-phase fault at POI at t=10 s, run 10 more s, plot **Pg and Qg** (screenshot okay) | @Lingyu | `11_FlatRunBumpTest_*.pdf` | Generated |
| 12 | **Plot showing requested MW at POI** from PSLF (screenshot okay) | @Lingyu | `12_RequestedMWatPOI_*.pdf` — generation MW vs limit line | Generated |
| 13 | **IBR Interconnection Request Model Validation Results** — all three: (a) plant controller voltage OR Q-reference step change, (b) plant controller frequency reference step change, (c) voltage ride-through (screenshots okay) | @Lingyu | `13_IBRModelValidation_*.pdf` | Generated |

## Reference files in this folder

| File | What it is |
|------|------------|
| `Appendix 1.docx` | Official blank Appendix 1 Interconnection Request form (item 2) |
| `CAISO Checklist .docx` / `Checklist & Appendix 1.docx` | Official checklist + Appendix 1, with team assignments |
| `3.generating-facility-data-attachment-a-to-appendix-1.xlsm` | Official Attachment A macro workbook v14.5 (item 3) |
| `4. siteexclusivity-controldemonstrationform (1).docx` | Official site exclusivity form (item 4) |
| `8.Reactive Power capability document_.png` | Worked example of the reactive capability calc (item 8) |
| `9.SiteLayout.pdf` | Example site drawing (item 9) |
| `10.SLD.pdf` | Example conceptual single-line diagram (item 10) |
| `11.flatruntestandbumptestplotinstructions.pdf` | Official plot instructions (item 11) |
| `12.png` | Example requested-MW-at-POI plot (item 12) |

## Notes

- Item 8 example calc (from `8.Reactive Power capability document_.png`): inverter count ×
  rated MW/MVA → total; reactive requirement (A) = 0.95 PF at GSU high side; var losses (B) =
  pad-mount + collector + main transformer − line charging; static supply (C) = shunt caps;
  dynamic supply (D) = generator reactive capability at actual output. Overall
  surplus/(shortage) = C + D − A − B; dynamic surplus/(shortage) = D − A.
- Item 11 instructions: transient stability sim — no-fault run 10 s; 3-phase-to-ground fault
  at the POI at t = 10 s; run another 10 s; plot Pg and Qg. Do not hide the generator name.
- Supporting GridPilot work products (KMZ boundary, signatory draft, SOS instructions,
  equipment schedule, assumptions log, source trace, portal fields) are packaged separately
  from the 13 checklist items.

# ISO Interconnection Requirements Library

One markdown file per US ISO/RTO, named to match the rule packs in
`backend/app/rules/` (`caiso.yaml` ↔ `caiso.md`, etc.). These files are the
reference corpus GridPilot feeds to the model when validating intakes,
generating packets, or answering requirement questions outside CAISO.

| File       | ISO / RTO                        | Interconnection process                     |
|------------|----------------------------------|---------------------------------------------|
| `caiso.md` | California ISO                   | GIDAP / IPE cluster study (Tariff App. DD)  |
| `miso.md`  | Midcontinent ISO                 | Definitive Planning Phase (DPP) cycles      |
| `pjm.md`   | PJM Interconnection              | Cycle process (post-2022 reform)            |
| `ercot.md` | ERCOT (Texas)                    | Full Interconnection Study (Planning Guide) |
| `spp.md`   | Southwest Power Pool             | DISIS cluster study (GIP)                   |
| `nyiso.md` | New York ISO                     | OATT Attachment X cluster study             |
| `isone.md` | ISO New England                  | Cluster-enabled interconnection (Sch. 22/23)|

## File structure

Every file uses the same sections so a model can align them:

1. YAML front matter — `iso`, `process`, `tariff_basis`, `portal`, `updated`
2. Process overview & timeline
3. Application / entry requirements
4. Deposits, fees & milestones
5. Site control requirements
6. Technical data & modeling requirements
7. Required documents checklist
8. Withdrawal & penalties
9. Common deficiency triggers
10. References

## Accuracy notes

Figures reflect published tariffs and business practice manuals as of the
`updated` date in each file, including FERC Order 2023 compliance changes.
Deposit amounts and study timelines change between cluster cycles — verify
against the ISO source in the references before relying on a number for a
live filing.

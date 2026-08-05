"""GridPilot deterministic engineering engine.

Implements the product blueprint: developer facts go into a source-traced
project graph; deterministic code (not an LLM) derives topology, drawings,
and power-system models from it.

Modules
-------
graph        Phase 1 — source-tagged, versioned project graph
equipment    Phase 2 — OEM equipment library and matching
design       Phase 3 — topology sizing and equipment schedule
sld          Phase 4 — deterministic single-line diagram (SVG/PDF/DXF)
powerflow    Phase 5 — radial load-flow solver and short-circuit
models_out   Phase 6 — model file writers and dynamic validation
consistency  Phase 7 — cross-document checks and assumption ledger
"""

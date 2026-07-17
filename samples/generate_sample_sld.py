#!/usr/bin/env python3
"""Generate a synthetic utility-scale SLD PDF with intentional compliance gaps."""

from __future__ import annotations

from pathlib import Path

import fitz


def main() -> Path:
    out = Path(__file__).resolve().parent / "cedar_ridge_sld_demo.pdf"
    doc = fitz.open()
    page = doc.new_page(width=792, height=612)  # landscape letter

    # Background
    page.draw_rect(fitz.Rect(0, 0, 792, 612), color=(0.95, 0.94, 0.90), fill=(0.95, 0.94, 0.90))

    # Title block
    page.insert_text((36, 36), "CEDAR RIDGE SOLAR + STORAGE", fontsize=16, fontname="helv", color=(0.06, 0.12, 0.10))
    page.insert_text((36, 56), "SINGLE-LINE DIAGRAM (SLD) — INTERCONNECTION EXHIBIT", fontsize=10, fontname="helv", color=(0.25, 0.30, 0.28))
    page.insert_text((36, 74), "Project: 120 MWAC Solar | POI Voltage: 138 kV | County: Example, IN | Rev: A", fontsize=9, fontname="helv", color=(0.2, 0.25, 0.22))
    page.insert_text((520, 36), "GRIDPILOT DEMO DRAWING", fontsize=9, fontname="helv", color=(0.45, 0.2, 0.1))
    page.insert_text((520, 52), "Intentional deficiencies for audit demo", fontsize=8, fontname="helv", color=(0.45, 0.25, 0.15))

    # Utility bus
    page.draw_line(fitz.Point(120, 140), fitz.Point(670, 140), color=(0.1, 0.1, 0.1), width=2.2)
    page.insert_text((280, 128), "UTILITY 138 kV BUS / POI", fontsize=10, fontname="helv")

    # Revenue meter
    page.draw_circle(fitz.Point(400, 140), 14, color=(0.1, 0.1, 0.1), width=1.5)
    page.insert_text((388, 144), "M", fontsize=11, fontname="helv")
    page.insert_text((360, 168), "Revenue Meter", fontsize=8, fontname="helv")
    page.insert_text((355, 180), "Point of Interconnection", fontsize=8, fontname="helv")

    # Breaker (missing kA intentionally)
    page.draw_rect(fitz.Rect(385, 200, 415, 230), color=(0.1, 0.1, 0.1), width=1.5)
    page.draw_line(fitz.Point(400, 140), fitz.Point(400, 200), width=1.5)
    page.draw_line(fitz.Point(400, 230), fitz.Point(400, 270), width=1.5)
    page.insert_text((424, 218), "52-POI Breaker", fontsize=8, fontname="helv")
    page.insert_text((424, 230), "Interrupting: ____ kA  (MISSING)", fontsize=8, fontname="helv", color=(0.55, 0.15, 0.1))

    # GSU transformer
    page.draw_circle(fitz.Point(400, 300), 22, color=(0.1, 0.1, 0.1), width=1.4)
    page.draw_circle(fitz.Point(400, 330), 22, color=(0.1, 0.1, 0.1), width=1.4)
    page.draw_line(fitz.Point(400, 270), fitz.Point(400, 278), width=1.4)
    page.insert_text((432, 310), "GSU-1  150 MVA", fontsize=9, fontname="helv")
    page.insert_text((432, 324), "34.5 / 138 kV", fontsize=8, fontname="helv")
    page.insert_text((432, 338), "%Z: ____   X/R: ____  (MISSING)", fontsize=8, fontname="helv", color=(0.55, 0.15, 0.1))

    # Collector bus
    page.draw_line(fitz.Point(180, 390), fitz.Point(620, 390), width=1.8)
    page.draw_line(fitz.Point(400, 352), fitz.Point(400, 390), width=1.4)
    page.insert_text((250, 378), "34.5 kV COLLECTOR BUS", fontsize=9, fontname="helv")

    # Inverter banks
    boxes = [
        (200, "INV Bank A", "16 x SG3600UD", "57.6 MWAC"),
        (360, "INV Bank B", "16 x SG3600UD", "57.6 MWAC"),
        (520, "BESS PCS", "optional", "50 MW / 200 MWh"),
    ]
    for x, title, model, rating in boxes:
        page.draw_rect(fitz.Rect(x, 430, x + 110, 500), color=(0.1, 0.1, 0.1), width=1.2)
        page.draw_line(fitz.Point(x + 55, 390), fitz.Point(x + 55, 430), width=1.2)
        page.insert_text((x + 10, 450), title, fontsize=8, fontname="helv")
        page.insert_text((x + 10, 466), model, fontsize=7, fontname="helv")
        page.insert_text((x + 10, 480), rating, fontsize=7, fontname="helv")

    page.insert_text(
        (36, 530),
        "NOTES:",
        fontsize=9,
        fontname="helv",
    )
    notes = [
        "1. Ownership demarcation at high-side of 52-POI.",
        "2. Inverter LVRT / HVRT setpoints: NOT SHOWN (intentional demo gap).",
        "3. SCADA / RTU / ICCP telemetry path: NOT SHOWN (intentional demo gap).",
        "4. Grounding transformer: NOT SHOWN (intentional demo gap).",
        "5. Standards: (IEEE 1547 citation intentionally omitted).",
    ]
    y = 544
    for n in notes:
        page.insert_text((36, y), n, fontsize=7.5, fontname="helv", color=(0.2, 0.22, 0.2))
        y += 12

    doc.save(out)
    doc.close()
    print(f"Wrote {out}")
    return out


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Generate a synthetic AES Indiana / MISO interconnection SLD with intentional gaps."""

from __future__ import annotations

from pathlib import Path

import fitz


def main() -> Path:
    out = Path(__file__).resolve().parent / "cedar_ridge_sld_demo.pdf"
    doc = fitz.open()
    page = doc.new_page(width=792, height=612)  # landscape letter

    page.draw_rect(fitz.Rect(0, 0, 792, 612), color=(0.95, 0.94, 0.90), fill=(0.95, 0.94, 0.90))

    # Title block
    page.insert_text((36, 36), "CEDAR RIDGE SOLAR + STORAGE", fontsize=16, fontname="helv", color=(0.06, 0.12, 0.10))
    page.insert_text((36, 56), "SINGLE-LINE DIAGRAM — AES INDIANA INTERCONNECTION EXHIBIT", fontsize=10, fontname="helv", color=(0.25, 0.30, 0.28))
    page.insert_text(
        (36, 74),
        "120 MWAC Solar + BESS | MISO DPP | TO: AES Indiana | County: Marion, IN | Rev: A | Date: ____",
        fontsize=8.5,
        fontname="helv",
        color=(0.2, 0.25, 0.22),
    )
    page.insert_text((500, 36), "GRIDPILOT DEMO DRAWING", fontsize=9, fontname="helv", color=(0.45, 0.2, 0.1))
    page.insert_text((500, 52), "AES Indiana Facilities Connection gaps", fontsize=8, fontname="helv", color=(0.45, 0.25, 0.15))

    # Utility bus
    page.draw_line(fitz.Point(120, 140), fitz.Point(670, 140), color=(0.1, 0.1, 0.1), width=2.2)
    page.insert_text((220, 128), "AES INDIANA 138 kV BUS / POINT OF INTERCONNECTION", fontsize=10, fontname="helv")

    # Revenue meter — missing CT/PT
    page.draw_circle(fitz.Point(400, 140), 14, color=(0.1, 0.1, 0.1), width=1.5)
    page.insert_text((388, 144), "M", fontsize=11, fontname="helv")
    page.insert_text((348, 168), "Revenue Meter (bidirectional?)", fontsize=8, fontname="helv")
    page.insert_text((348, 180), "CT: ____ / PT: ____  (MISSING)", fontsize=8, fontname="helv", color=(0.55, 0.15, 0.1))

    # Breaker
    page.draw_rect(fitz.Rect(385, 200, 415, 230), color=(0.1, 0.1, 0.1), width=1.5)
    page.draw_line(fitz.Point(400, 140), fitz.Point(400, 200), width=1.5)
    page.draw_line(fitz.Point(400, 230), fitz.Point(400, 270), width=1.5)
    page.insert_text((424, 218), "52-POI Breaker  40 kA", fontsize=8, fontname="helv")
    page.insert_text((424, 232), "Ownership demarcation (AES Indiana / IC)", fontsize=7.5, fontname="helv")

    # Protection — missing ANSI numbers
    page.draw_rect(fitz.Rect(520, 188, 670, 248), color=(0.1, 0.1, 0.1), width=1.1)
    page.insert_text((528, 204), "POI PROTECTION PACKAGE", fontsize=8, fontname="helv")
    page.insert_text((528, 218), "Relays: ____  (ANSI # MISSING)", fontsize=8, fontname="helv", color=(0.55, 0.15, 0.1))
    page.insert_text((528, 232), "Expect 27 / 59 / 81 / 67 labels", fontsize=7.5, fontname="helv", color=(0.55, 0.15, 0.1))

    # GSU
    page.draw_circle(fitz.Point(400, 300), 22, color=(0.1, 0.1, 0.1), width=1.4)
    page.draw_circle(fitz.Point(400, 330), 22, color=(0.1, 0.1, 0.1), width=1.4)
    page.draw_line(fitz.Point(400, 270), fitz.Point(400, 278), width=1.4)
    page.insert_text((432, 310), "GSU-1  150 MVA", fontsize=9, fontname="helv")
    page.insert_text((432, 324), "34.5 / 138 kV   %Z 8.5%   X/R 22", fontsize=8, fontname="helv")

    # Collector
    page.draw_line(fitz.Point(180, 390), fitz.Point(620, 390), width=1.8)
    page.draw_line(fitz.Point(400, 352), fitz.Point(400, 390), width=1.4)
    page.insert_text((250, 378), "34.5 kV COLLECTOR BUS", fontsize=9, fontname="helv")

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

    page.insert_text((36, 522), "NOTES (AES Indiana / MISO demo):", fontsize=9, fontname="helv")
    notes = [
        "1. R-POI-01 OK: AES Indiana 138 kV POI + ownership at 52-POI shown.",
        "2. R-PROTECT-01 GAP: Relay ANSI function numbers not labeled.",
        "3. R-METER-01 GAP: CT/PT ratios blank at revenue meter.",
        "4. R-IBR-01 GAP: P-Q / capability curves, PFR droop, VAR-002 AVC not shown.",
        "5. R-TITLE-01 GAP: As-built date blank — AES Indiana requires as-built one-lines before energization.",
        "6. Filing path: MISO DPP queue + AES Indiana PowerClerk (aesindianainterconnection.powerclerk.com).",
    ]
    y = 536
    for n in notes:
        page.insert_text((36, y), n, fontsize=7.2, fontname="helv", color=(0.2, 0.22, 0.2))
        y += 11

    doc.save(out)
    # Browser PDF iframes are flaky — keep a PNG preview for the guided demo.
    preview = Path(__file__).resolve().parents[1] / "backend" / "app" / "static" / "img" / "cedar_ridge_sld_demo.png"
    preview.parent.mkdir(parents=True, exist_ok=True)
    pix = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
    pix.save(preview)
    doc.close()
    print(f"Wrote {out}")
    print(f"Wrote {preview}")
    return out


if __name__ == "__main__":
    main()

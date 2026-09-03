"""Create the /tmp/gp_fixtures files used by the real-app E2E tests.

Run before real_flow_test.mjs / trajectory_test.mjs:
    PYTHONPATH=. .venv/bin/python scripts/make_fixtures.py
"""
from __future__ import annotations

from pathlib import Path

import fitz  # PyMuPDF
from openpyxl import Workbook

FIX = Path("/tmp/gp_fixtures")
FIX.mkdir(parents=True, exist_ok=True)


def make_lease() -> None:
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    y = 72
    lines = [
        ("GROUND LEASE AGREEMENT — EXECUTED", 14, True),
        ("Sunrise Ranch — Riverside County, California", 10, False),
        ("", 9, False),
        ("This Ground Lease Agreement (\"Lease\") is entered into as of March 14, 2026", 9, False),
        ("between Sunrise Ranch Holdings LP, a California limited partnership (\"Lessor\"),", 9, False),
        ("and Acme Energy E2E LLC, a Delaware limited liability company (\"Lessee\").", 9, False),
        ("", 9, False),
        ("1. PREMISES. Lessor leases to Lessee approximately 820 acres of real property", 9, False),
        ("   in Riverside County, California, APN 668-210-014, for the development of a", 9, False),
        ("   solar photovoltaic and battery energy storage facility (\"Acme Desert One\").", 9, False),
        ("", 9, False),
        ("2. TERM. The initial term is forty (40) years from the Commercial Operation", 9, False),
        ("   Date, with two (2) five-year extension options at Lessee's election", 9, False),
        ("   (Section 2.3). Expiration of the initial term: June 30, 2068.", 9, False),
        ("", 9, False),
        ("3. SITE CONTROL. This executed Lease constitutes evidence of site exclusivity", 9, False),
        ("   for the purposes of the CAISO interconnection request.", 9, False),
        ("", 9, False),
        ("IN WITNESS WHEREOF, executed by the duly authorized representatives:", 9, False),
        ("", 9, False),
        ("Lessor: Sunrise Ranch Holdings LP        Lessee: Acme Energy E2E LLC", 9, False),
        ("By: Maria Delgado, General Partner       By: Jordan Lee, VP Development", 9, False),
        ("Date: 03/14/2026                         Date: 03/14/2026", 9, False),
    ]
    for text, size, bold in lines:
        page.insert_text((72, y), text, fontsize=size,
                         fontname="hebo" if bold else "helv")
        y += size + 7
    doc.save(FIX / "Acme_Lease_SunriseRanch_Executed.pdf")
    doc.close()


def make_technical() -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "Project Data"
    rows = [
        ("Field", "Value"),
        ("Project name", "Acme Desert One"),
        ("Legal name of interconnection customer", "Acme Energy E2E LLC"),
        ("State of organization", "Delaware"),
        ("Project type", "Solar PV + BESS (AC-coupled)"),
        ("Requested net output at POI (MW)", 105),
        ("Gross generating facility output (MW)", 107.6),
        ("Auxiliary load (MW)", 1.8),
        ("Anticipated losses to POI (MW)", 0.8),
        ("PV module", "JinkoSolar Tiger Neo 620W bifacial"),
        ("PV inverter", "Sungrow SG4400UD-MV"),
        ("Inverter count", 30),
        ("Point of interconnection", "Devers Substation (SCE)"),
        ("POI voltage (kV)", 115),
        ("County", "Riverside"),
        ("State", "CA"),
        ("Latitude", 33.9284),
        ("Longitude", -116.3945),
        ("Proposed in-service date", "10/15/2028"),
        ("Proposed commercial operation date", "05/30/2029"),
        ("Interconnection process", "Independent Study Process"),
        ("Deliverability status", "Full Capacity"),
    ]
    for r in rows:
        ws.append(r)
    wb.save(FIX / "Acme_TechnicalData_Workbook.xlsx")


def make_bess() -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "BESS Spec"
    rows = [
        ("Field", "Value"),
        ("BESS supplier", "Tesla"),
        ("BESS product", "Megapack 2XL"),
        ("BESS power (MW)", 40),
        ("BESS energy (MWh)", 160),
        ("Duration (hours)", 4),
        ("Coupling", "AC-coupled at 34.5 kV collector"),
        ("PCS rating per unit (MW)", 1.927),
        ("Number of Megapack units", 21),
    ]
    for r in rows:
        ws.append(r)
    wb.save(FIX / "Acme_BESS_Spec.xlsx")


def make_sld_png() -> None:
    doc = fitz.open()
    page = doc.new_page(width=792, height=612)
    ink = (0.1, 0.12, 0.15)
    page.insert_text((60, 50), "ACME DESERT ONE — SINGLE LINE DIAGRAM (REV B)",
                     fontsize=13, fontname="hebo", color=ink)
    page.insert_text((60, 66), "105 MW PV + 40 MW / 160 MWh BESS — Devers 115 kV",
                     fontsize=9, fontname="helv", color=ink)
    # Utility bus
    page.draw_line(fitz.Point(200, 120), fitz.Point(600, 120), color=ink, width=3)
    page.insert_text((210, 112), "Devers Substation (SCE) — 115 kV", fontsize=8,
                     fontname="helv", color=ink)
    # Gen-tie
    page.draw_line(fitz.Point(400, 120), fitz.Point(400, 220), color=ink, width=1.5)
    page.insert_text((408, 175), "115 kV gen-tie — 2.5 mi", fontsize=8, fontname="helv", color=ink)
    # Main transformer
    page.draw_circle(fitz.Point(400, 240), 16, color=ink, width=1.5)
    page.draw_circle(fitz.Point(400, 262), 16, color=ink, width=1.5)
    page.insert_text((425, 252), "GSU 120 MVA, 34.5/115 kV, Z=8.5%", fontsize=8,
                     fontname="helv", color=ink)
    # Collector bus
    page.draw_line(fitz.Point(250, 330), fitz.Point(550, 330), color=ink, width=3)
    page.insert_text((255, 322), "34.5 kV collector bus", fontsize=8, fontname="helv", color=ink)
    page.draw_line(fitz.Point(400, 278), fitz.Point(400, 330), color=ink, width=1.5)
    # Feeders
    for i, x in enumerate((300, 400, 500)):
        page.draw_line(fitz.Point(x, 330), fitz.Point(x, 400), color=ink, width=1.2)
        page.insert_text((x - 22, 415), f"FDR-{i + 1} (PV)", fontsize=8, fontname="helv", color=ink)
    page.draw_line(fitz.Point(550, 330), fitz.Point(550, 400), color=ink, width=1.2)
    page.insert_text((520, 415), "BESS 40 MW", fontsize=8, fontname="helv", color=ink)
    page.insert_text((60, 560), "NOT FOR CONSTRUCTION — INTERCONNECTION APPLICATION ONLY",
                     fontsize=9, fontname="hebo", color=(0.7, 0.2, 0.2))
    pix = page.get_pixmap(dpi=110)
    pix.save(FIX / "Acme_SLD_RevB.png")
    doc.close()


if __name__ == "__main__":
    make_lease()
    make_technical()
    make_bess()
    make_sld_png()
    print("fixtures written to", FIX)
    for f in sorted(FIX.iterdir()):
        print(" ", f.name, f.stat().st_size, "bytes")

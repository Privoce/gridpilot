"""Phase 4 — Single-line diagram engine.

Deterministic drawing generation from the project graph topology. The
diagram is built as a list of geometry primitives once, then rendered to
SVG (native), PDF (via PyMuPDF), and DXF R12 (for CAD import). It is a view
of the graph — regenerate on any change, never hand-edit.

Primitive forms:
    ("line",   x1, y1, x2, y2, weight)          weight: 1 thin, 2 medium, 3 bus
    ("dash",   x1, y1, x2, y2)                  dashed line (ownership boundary)
    ("circle", cx, cy, r, filled)
    ("rect",   x, y, w, h, filled)
    ("text",   x, y, size, text, anchor)        anchor: start|middle|end
    ("poly",   [(x,y), ...], closed)            thin polyline (symbols)
"""

from __future__ import annotations

from datetime import date
from typing import Any

import fitz

W, H = 820, 1120
CX = W // 2  # main vertical spine

Prim = tuple


class _Sheet:
    def __init__(self) -> None:
        self.prims: list[Prim] = []

    def line(self, x1, y1, x2, y2, w=1):
        self.prims.append(("line", x1, y1, x2, y2, w))

    def dash(self, x1, y1, x2, y2):
        self.prims.append(("dash", x1, y1, x2, y2))

    def circle(self, cx, cy, r, filled=False):
        self.prims.append(("circle", cx, cy, r, filled))

    def rect(self, x, y, w, h, filled=False):
        self.prims.append(("rect", x, y, w, h, filled))

    def text(self, x, y, size, s, anchor="start"):
        self.prims.append(("text", x, y, size, s, anchor))

    def poly(self, pts, closed=False):
        self.prims.append(("poly", pts, closed))

    # -- composite electrical symbols (drop-in, oriented vertically) -------

    def breaker(self, x, y, s=9):
        """Drawout breaker square centered at (x, y)."""
        self.rect(x - s / 2, y - s / 2, s, s, filled=True)

    def disconnect(self, x, y):
        """Disconnect switch: blade drawn open-angled."""
        self.line(x, y - 10, x, y - 4)
        self.line(x, y - 4, x + 8, y + 6)
        self.circle(x, y + 8, 1.6)
        self.line(x, y + 8, x, y + 14)

    def transformer2w(self, x, y, r=13):
        """Two-winding transformer: overlapping circles, vertical."""
        self.circle(x, y - r + 4, r)
        self.circle(x, y + r - 4, r)

    def meter(self, x, y):
        self.circle(x, y, 8)
        self.text(x, y + 3.2, 9, "M", "middle")

    def ct(self, x, y):
        """CT: small circle clamped on the conductor."""
        self.circle(x, y, 4.5)

    def pt(self, x, y):
        """PT tap: line to small two-circle set."""
        self.line(x, y, x + 14, y)
        self.circle(x + 19, y, 4.5)
        self.circle(x + 26, y, 4.5)

    def ground(self, x, y):
        self.line(x, y, x, y + 7)
        self.line(x - 7, y + 7, x + 7, y + 7)
        self.line(x - 4.5, y + 10, x + 4.5, y + 10)
        self.line(x - 2, y + 13, x + 2, y + 13)

    def inverter(self, x, y, s=18):
        """Inverter box with DC/AC split diagonal."""
        self.rect(x - s / 2, y - s / 2, s, s)
        self.line(x - s / 2, y + s / 2, x + s / 2, y - s / 2)
        self.text(x - s / 2 + 3, y - 2, 5.5, "DC")
        self.text(x + 1.5, y + s / 2 - 2.5, 5.5, "AC")

    def battery(self, x, y):
        self.line(x - 9, y - 3, x + 9, y - 3, 2)
        self.line(x - 4.5, y + 3, x + 4.5, y + 3, 2)


def build_sld(graph: dict[str, Any], design: dict[str, Any],
              intake: dict[str, Any]) -> list[Prim]:
    """Layout the SLD top (POI) to bottom (inverter block detail)."""
    s = _Sheet()
    c = design["counts"]
    poi_kv = float(next((n["kv"] for n in graph["nodes"] if n["id"] == "poi"), 230))
    col_kv = float(next((n["kv"] for n in graph["nodes"] if n["id"] == "col_bus"), 34.5))
    mpt, pad, inv = design["mpt"], design["pad"], design["inverter"]
    n_mpt, n_feed = c["main_transformers"], c["feeders"]
    project = str(intake.get("project_name") or "Project")
    poi_name = str(intake.get("poi_name") or "POI")

    # --- Frame + title block ---------------------------------------------
    s.rect(18, 18, W - 36, H - 36)
    tb_y = H - 92
    s.line(18, tb_y, W - 18, tb_y)
    s.text(30, tb_y + 20, 11, f"{project} — Single-Line Diagram")
    s.text(30, tb_y + 36, 8.5, f"Generated from project graph {graph.get('version', '')}")
    s.text(30, tb_y + 50, 8.5,
           f"Rev A · {date.today().strftime('%m/%d/%Y')} · "
           "NOT FOR CONSTRUCTION: FOR INTERCONNECTION APPLICATION ONLY")
    s.text(W - 30, tb_y + 20, 9, f"POI: {poi_name}", "end")
    s.text(W - 30, tb_y + 36, 9, f"{poi_kv:g} kV / {col_kv:g} kV", "end")
    s.text(W - 30, tb_y + 50, 9, "Sheet 1 of 1", "end")

    # --- General notes (per the CAISO example SLD) --------------------------
    net_mw = float(intake.get("net_mw_poi") or 0)
    lat, lon = intake.get("gps_lat"), intake.get("gps_lon")
    notes_x = W - 245
    s.text(notes_x, 40, 9, "GENERAL NOTES")
    s.line(notes_x, 45, W - 40, 45)
    for i, note in enumerate([
        f"1. MAXIMUM NET FACILITY OUTPUT LIMITED TO {net_mw:g} MW @ ±0.95 PF.",
        f"2. FACILITY CAPABLE OF {net_mw:g} MW AT GRID VOLTAGE RANGE",
        "    OF 0.90 PU TO 1.10 PU.",
        "3. EQUIPMENT SPECIFICATIONS ARE PROVIDED FOR INTERCONNECTION",
        "    STUDY PURPOSES AND ARE SUBJECT TO CHANGE BASED ON",
        "    ENGINEERING AND PROCUREMENT CONSTRAINTS.",
    ]):
        s.text(notes_x, 58 + i * 11, 6.5, note)
    if lat is not None and lon is not None:
        s.text(notes_x, 58 + 6 * 11 + 4, 6.5,
               f"POI COORDINATES: ({lat}, {lon})")

    # --- Utility bus / POI --------------------------------------------------
    y = 66
    s.line(CX - 190, y, CX + 150, y, 3)
    s.text(CX - 190, y - 10, 9.5, f"{poi_name} — {poi_kv:g} kV (utility)")
    s.line(CX, y, CX, y + 22)

    # Revenue metering at the POI.
    s.ct(CX, y + 30)
    s.pt(CX, y + 44)
    s.meter(CX + 40, y + 44)
    s.line(CX + 14, y + 44, CX + 32, y + 44)
    s.text(CX + 54, y + 47, 7.5, "Revenue metering (CT/PT)")
    s.line(CX, y + 35, CX, y + 58)

    # Ownership / change-of-ownership boundary.
    ob_y = y + 70
    s.dash(40, ob_y, W - 40, ob_y)
    s.text(44, ob_y - 6, 7.5, "OWNERSHIP BOUNDARY — utility")
    s.text(44, ob_y + 13, 7.5, "Interconnection Customer")

    # --- Gen-tie -----------------------------------------------------------
    gt_top = ob_y + 12
    gt_bot = ob_y + 74
    s.line(CX, gt_top, CX, gt_bot, 2)
    s.text(CX + 10, (gt_top + gt_bot) / 2 - 6, 8.5,
           f"Gen-tie — {design['gentie_mi']:g} mi, {design['line']['kv_class']} kV OHL")
    # Tie-line impedance on a 100 MVA base — shown per the CAISO SLD example.
    z_base = poi_kv * poi_kv / 100.0
    r_pu = design["line"]["r_ohm_per_mi"] * design["gentie_mi"] / z_base
    x_pu = design["line"]["x_ohm_per_mi"] * design["gentie_mi"] / z_base
    s.text(CX + 10, (gt_top + gt_bot) / 2 + 8, 7.5,
           f"Tie-line data (100 MVA base): R={r_pu:.5f} pu  X={x_pu:.5f} pu")

    # --- Project HV substation ---------------------------------------------
    s.disconnect(CX, gt_bot + 12)
    s.text(CX + 14, gt_bot + 14, 7.5, "89L line disconnect")
    s.line(CX, gt_bot + 26, CX, gt_bot + 38)
    s.breaker(CX, gt_bot + 46)
    s.text(CX + 14, gt_bot + 49, 7.5, f"52H — {poi_kv:g} kV breaker")
    s.line(CX, gt_bot + 54, CX, gt_bot + 72)

    hv_y = gt_bot + 78
    s.line(CX - 210, hv_y, CX + 210, hv_y, 3)
    s.text(CX - 210, hv_y - 8, 9, f"{poi_kv:g} kV project substation bus")
    s.ground(CX + 200, hv_y)

    # --- Main transformers ---------------------------------------------------
    xf_span = 150 if n_mpt > 1 else 0
    xf_xs = [CX - xf_span / 2 + i * (xf_span / max(n_mpt - 1, 1)) for i in range(n_mpt)] \
        if n_mpt > 1 else [CX]
    col_y = hv_y + 150
    for i, x in enumerate(xf_xs):
        s.line(x, hv_y, x, hv_y + 14)
        s.breaker(x, hv_y + 21)
        s.line(x, hv_y + 28, x, hv_y + 40)
        s.transformer2w(x, hv_y + 62)
        s.text(x + 18, hv_y + 58, 7.5, f"T{i + 1} — {mpt['mva']:g} MVA")
        s.text(x + 18, hv_y + 69, 7.5, f"{col_kv:g}/{poi_kv:g} kV, Z={mpt['z_pct']:g}%, {mpt['vector']}")
        s.line(x, hv_y + 84, x, col_y - 16)
        s.breaker(x, col_y - 9)
        s.line(x, col_y - 2, x, col_y)

    # --- Collector bus -------------------------------------------------------
    bus_half = 240
    s.line(CX - bus_half, col_y, CX + bus_half, col_y, 3)
    s.text(CX - bus_half, col_y - 8, 9, f"{col_kv:g} kV collector bus")
    s.ground(CX + bus_half - 8, col_y)

    # Station auxiliary load tap — shown per the CAISO example SLD.
    aux_mw = float(intake.get("aux_mw") or 0)
    if aux_mw:
        ax = CX + bus_half - 46
        s.line(ax, col_y, ax, col_y - 22)
        s.line(ax - 5, col_y - 22, ax + 5, col_y - 22, 2)
        s.text(ax + 9, col_y - 24, 7, f"AUX LOAD — {aux_mw:g} MW @ ~0.95 PF")

    # --- Feeders -------------------------------------------------------------
    n_slots = n_feed + (1 if design.get("bess_assigned") else 0)
    slot_w = (bus_half * 2 - 60) / max(n_slots, 1)
    fd_y = col_y + 34
    first_fx = None
    for f in range(n_feed):
        x = CX - bus_half + 40 + f * slot_w
        if first_fx is None:
            first_fx = x
        s.line(x, col_y, x, fd_y - 14)
        s.breaker(x, fd_y - 7)
        s.line(x, fd_y, x, fd_y + 10)
        nb = next((n.get("blocks", 0) for n in graph["nodes"] if n["id"] == f"feeder_{f + 1}"), 0)
        s.text(x + 8, fd_y + 4, 7, f"FDR-{f + 1} · {nb} blk")

    # BESS slot on the far right.
    if design.get("bess_assigned") and design.get("bess_unit"):
        bx = CX - bus_half + 40 + n_feed * slot_w
        bu = design["bess_unit"]
        s.line(bx, col_y, bx, fd_y - 14)
        s.breaker(bx, fd_y - 7)
        s.line(bx, fd_y, bx, fd_y + 16)
        s.battery(bx, fd_y + 22)
        s.text(bx + 12, fd_y + 22, 7,
               f"BESS — {c['bess_units']} x {bu['model']} "
               f"({design.get('bess_mw', 0):g} MW / {design.get('bess_mwh', 0):g} MWh)")

    # --- Representative inverter block (typical-of) ---------------------------
    ib_x = first_fx if first_fx is not None else CX
    ib_y = fd_y + 60
    s.line(ib_x, fd_y + 10, ib_x, ib_y - 20, 1)
    s.text(ib_x - 10, ib_y - 26, 7.5,
           f"Feeder detail — TYPICAL OF {c['blocks']} INVERTER BLOCKS")
    s.transformer2w(ib_x, ib_y + 4, r=10)
    s.text(ib_x + 15, ib_y + 2, 7,
           f"{pad['mva']:g} MVA pad, {inv['ac_kv']:g}/{col_kv:g} kV, Z={pad['z_pct']:g}%")
    s.line(ib_x, ib_y + 18, ib_x, ib_y + 30)
    # Two inverters per block.
    for k, dx in enumerate((-34, 34)):
        s.line(ib_x, ib_y + 30, ib_x + dx, ib_y + 30)
        s.line(ib_x + dx, ib_y + 30, ib_x + dx, ib_y + 44)
        s.inverter(ib_x + dx, ib_y + 55)
        s.text(ib_x + dx - 16, ib_y + 78, 6.5, f"{inv['model']}")
        s.text(ib_x + dx - 16, ib_y + 87, 6.5, f"{inv['mva']:g} MVA")
    s.text(ib_x - 10, ib_y + 104, 7, f"{c['inverters']} inverters total — {inv['vendor']} {inv['model']}")

    # --- Legend ----------------------------------------------------------------
    lg_x, lg_y = W - 250, col_y + 170
    s.rect(lg_x, lg_y, 210, 96)
    s.text(lg_x + 10, lg_y + 16, 8, "LEGEND")
    s.breaker(lg_x + 18, lg_y + 32, 7)
    s.text(lg_x + 32, lg_y + 35, 7, "Circuit breaker")
    s.circle(lg_x + 18, lg_y + 48, 5)
    s.text(lg_x + 32, lg_y + 51, 7, "Transformer winding")
    s.dash(lg_x + 10, lg_y + 64, lg_x + 26, lg_y + 64)
    s.text(lg_x + 32, lg_y + 67, 7, "Ownership boundary")
    s.circle(lg_x + 18, lg_y + 80, 6)
    s.text(lg_x + 15, lg_y + 83, 6.5, "M")
    s.text(lg_x + 32, lg_y + 83, 7, "Revenue meter")

    return s.prims


# ---------------------------------------------------------------------------
# Renderers
# ---------------------------------------------------------------------------

def to_svg(prims: list[Prim]) -> str:
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" '
           f'font-family="Helvetica, Arial, sans-serif">',
           f'<rect width="{W}" height="{H}" fill="white"/>']
    stroke = "#111111"
    for p in prims:
        kind = p[0]
        if kind == "line":
            _, x1, y1, x2, y2, w = p
            sw = {1: 1.0, 2: 1.6, 3: 3.2}[w]
            out.append(f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" '
                       f'stroke="{stroke}" stroke-width="{sw}"/>')
        elif kind == "dash":
            _, x1, y1, x2, y2 = p
            out.append(f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" '
                       f'stroke="{stroke}" stroke-width="1" stroke-dasharray="7 5"/>')
        elif kind == "circle":
            _, cx, cy, r, filled = p
            fill = stroke if filled else "none"
            out.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{r:.1f}" '
                       f'stroke="{stroke}" stroke-width="1.1" fill="{fill}"/>')
        elif kind == "rect":
            _, x, y, w_, h_, filled = p
            fill = stroke if filled else "none"
            out.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{w_:.1f}" height="{h_:.1f}" '
                       f'stroke="{stroke}" stroke-width="1.1" fill="{fill}"/>')
        elif kind == "text":
            _, x, y, size, txt, anchor = p
            esc = (str(txt).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))
            out.append(f'<text x="{x:.1f}" y="{y:.1f}" font-size="{size}" '
                       f'text-anchor="{anchor}" fill="{stroke}">{esc}</text>')
        elif kind == "poly":
            _, pts, closed = p
            d = " ".join(f"{x:.1f},{y:.1f}" for x, y in pts)
            tag = "polygon" if closed else "polyline"
            out.append(f'<{tag} points="{d}" stroke="{stroke}" stroke-width="1.1" fill="none"/>')
    out.append("</svg>")
    return "\n".join(out)


def to_pdf(prims: list[Prim], path) -> None:
    """Render primitives straight onto a PDF page (no rasterizing)."""
    doc = fitz.open()
    page = doc.new_page(width=W, height=H)
    black = (0.07, 0.07, 0.07)
    for p in prims:
        kind = p[0]
        if kind == "line":
            _, x1, y1, x2, y2, w = p
            sw = {1: 0.9, 2: 1.5, 3: 3.0}[w]
            page.draw_line((x1, y1), (x2, y2), color=black, width=sw)
        elif kind == "dash":
            _, x1, y1, x2, y2 = p
            page.draw_line((x1, y1), (x2, y2), color=black, width=0.9, dashes="[7 5] 0")
        elif kind == "circle":
            _, cx, cy, r, filled = p
            page.draw_circle((cx, cy), r, color=black, width=1.0,
                             fill=black if filled else None)
        elif kind == "rect":
            _, x, y, w_, h_, filled = p
            page.draw_rect(fitz.Rect(x, y, x + w_, y + h_), color=black, width=1.0,
                           fill=black if filled else None)
        elif kind == "text":
            _, x, y, size, txt, anchor = p
            t = str(txt)
            tw = fitz.get_text_length(t, fontname="helv", fontsize=size)
            if anchor == "middle":
                x -= tw / 2
            elif anchor == "end":
                x -= tw
            page.insert_text((x, y), t, fontsize=size, fontname="helv", color=black)
        elif kind == "poly":
            _, pts, closed = p
            for a, b in zip(pts, pts[1:]):
                page.draw_line(a, b, color=black, width=1.0)
            if closed and len(pts) > 2:
                page.draw_line(pts[-1], pts[0], color=black, width=1.0)
    doc.save(str(path))
    doc.close()


def to_dxf(prims: list[Prim]) -> str:
    """Minimal DXF R12 — LINE/CIRCLE/TEXT entities, editable in CAD tools.

    DXF Y axis points up; flip against sheet height.
    """
    e: list[str] = []

    def fy(y: float) -> float:
        return H - y

    def add(code: int | str, val: Any) -> None:
        e.append(str(code))
        e.append(str(val))

    def line(x1, y1, x2, y2, layer="SLD"):
        add(0, "LINE"); add(8, layer)
        add(10, round(x1, 2)); add(20, round(fy(y1), 2)); add(30, 0)
        add(11, round(x2, 2)); add(21, round(fy(y2), 2)); add(31, 0)

    for p in prims:
        kind = p[0]
        if kind == "line":
            _, x1, y1, x2, y2, w = p
            line(x1, y1, x2, y2, "SLD-BUS" if w == 3 else "SLD")
        elif kind == "dash":
            _, x1, y1, x2, y2 = p
            line(x1, y1, x2, y2, "SLD-BOUNDARY")
        elif kind == "circle":
            _, cx, cy, r, _f = p
            add(0, "CIRCLE"); add(8, "SLD")
            add(10, round(cx, 2)); add(20, round(fy(cy), 2)); add(30, 0)
            add(40, round(r, 2))
        elif kind == "rect":
            _, x, y, w_, h_, _f = p
            line(x, y, x + w_, y); line(x + w_, y, x + w_, y + h_)
            line(x + w_, y + h_, x, y + h_); line(x, y + h_, x, y)
        elif kind == "text":
            _, x, y, size, txt, anchor = p
            add(0, "TEXT"); add(8, "SLD-TEXT")
            add(10, round(x, 2)); add(20, round(fy(y), 2)); add(30, 0)
            add(40, round(size, 2)); add(1, str(txt))
            if anchor in ("middle", "end"):
                add(72, 1 if anchor == "middle" else 2)
                add(11, round(x, 2)); add(21, round(fy(y), 2)); add(31, 0)
        elif kind == "poly":
            _, pts, closed = p
            seq = list(pts) + ([pts[0]] if closed and len(pts) > 2 else [])
            for a, b in zip(seq, seq[1:]):
                line(a[0], a[1], b[0], b[1])

    body = "\n".join(e)
    return (
        "0\nSECTION\n2\nHEADER\n9\n$ACADVER\n1\nAC1009\n0\nENDSEC\n"
        "0\nSECTION\n2\nTABLES\n0\nTABLE\n2\nLAYER\n70\n4\n"
        "0\nLAYER\n2\nSLD\n70\n0\n62\n7\n6\nCONTINUOUS\n"
        "0\nLAYER\n2\nSLD-BUS\n70\n0\n62\n7\n6\nCONTINUOUS\n"
        "0\nLAYER\n2\nSLD-TEXT\n70\n0\n62\n7\n6\nCONTINUOUS\n"
        "0\nLAYER\n2\nSLD-BOUNDARY\n70\n0\n62\n7\n6\nDASHED\n"
        "0\nENDTAB\n0\nENDSEC\n"
        "0\nSECTION\n2\nENTITIES\n" + body + "\n0\nENDSEC\n0\nEOF\n"
    )

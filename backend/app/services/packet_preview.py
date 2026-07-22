"""In-browser preview pages for generated CAISO packet files.

Every document type gets an inline preview: PDFs are embedded, spreadsheets are
rendered as tables, KMZ boundaries are drawn as a map figure, PSLF model files
get a syntax-styled code view, and markdown is converted to HTML.
"""

from __future__ import annotations

import html
import re
import zipfile
from pathlib import Path
from typing import Any

PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>{title} — GridPilot</title>
<link rel="preconnect" href="https://fonts.googleapis.com" />
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet" />
<style>
  :root {{
    --ink: #1c211e; --muted: #6b7370; --line: #dfe3df; --soft: #f4f5f3;
    --accent: #2159c0; --ok: #1d7a44; --warn-bg: #fdf6e3; --canvas: #fafbf9;
  }}
  * {{ box-sizing: border-box; }}
  body {{ margin: 0; background: var(--canvas); color: var(--ink);
    font: 14px/1.55 Inter, system-ui, sans-serif; }}
  header {{ position: sticky; top: 0; z-index: 5; display: flex; flex-wrap: wrap;
    align-items: center; gap: 10px 16px; padding: 12px 22px; background: #fffffff2;
    border-bottom: 1px solid var(--line); backdrop-filter: blur(6px); }}
  header .t {{ min-width: 0; flex: 1; }}
  header h1 {{ margin: 0; font-size: 15px; font-weight: 600; letter-spacing: -0.01em; }}
  header .f {{ font-family: "JetBrains Mono", monospace; font-size: 11px; color: var(--muted); }}
  .chip {{ display: inline-block; padding: 2px 9px; border: 1px solid var(--line);
    border-radius: 99px; font-family: "JetBrains Mono", monospace; font-size: 10px;
    text-transform: uppercase; letter-spacing: 0.06em; color: var(--muted); background: var(--soft); }}
  .chip.ok {{ color: var(--ok); border-color: #bcd9c6; background: #eef7f0; }}
  .btn {{ display: inline-block; padding: 7px 16px; border-radius: 99px; text-decoration: none;
    font-family: "JetBrains Mono", monospace; font-size: 11px; text-transform: uppercase;
    letter-spacing: 0.07em; }}
  .btn.primary {{ background: var(--ink); color: #fff; }}
  .btn.ghost {{ border: 1px solid var(--line); color: var(--ink); background: #fff; }}
  main {{ max-width: 1060px; margin: 0 auto; padding: 22px; }}
  .note {{ margin: 0 0 16px; padding: 10px 14px; border: 1px solid var(--line);
    border-radius: 10px; background: var(--soft); color: var(--muted); font-size: 12.5px; }}
  iframe.pdf {{ width: 100%; height: calc(100vh - 130px); border: 1px solid var(--line);
    border-radius: 10px; background: #fff; }}
  h2.sheet {{ margin: 26px 0 10px; font-size: 13px; text-transform: uppercase;
    letter-spacing: 0.08em; color: var(--accent); font-family: "JetBrains Mono", monospace; }}
  table {{ width: 100%; border-collapse: collapse; background: #fff; border: 1px solid var(--line);
    border-radius: 10px; overflow: hidden; }}
  td, th {{ padding: 7px 12px; border-bottom: 1px solid var(--line); text-align: left;
    vertical-align: top; font-size: 13px; }}
  tr:last-child td {{ border-bottom: none; }}
  tr.section td {{ background: var(--soft); font-weight: 600; font-size: 11.5px;
    text-transform: uppercase; letter-spacing: 0.05em; color: var(--accent); }}
  td.k {{ color: var(--muted); width: 34%; }}
  td.c {{ color: var(--muted); font-size: 12px; }}
  th {{ background: var(--soft); font-size: 11.5px; text-transform: uppercase;
    letter-spacing: 0.05em; color: var(--muted); }}
  pre.code {{ margin: 0; padding: 18px; background: #14211a; color: #d8e6dc; border-radius: 10px;
    overflow-x: auto; font: 12px/1.7 "JetBrains Mono", monospace; }}
  pre.code .cm {{ color: #6f8f7c; }}
  pre.code .kw {{ color: #8ec5ff; }}
  pre.code .num {{ color: #ffd08a; }}
  .md h1 {{ font-size: 22px; letter-spacing: -0.01em; margin: 0 0 14px; }}
  .md h2 {{ font-size: 16px; margin: 24px 0 10px; }}
  .md p {{ margin: 0 0 10px; }}
  .md li {{ margin: 3px 0; }}
  figure.map {{ margin: 0 0 18px; padding: 16px; background: #fff; border: 1px solid var(--line);
    border-radius: 10px; }}
  figure.map > svg {{ width: 100%; height: auto; display: block; }}
  figcaption {{ margin-top: 10px; font-size: 12px; color: var(--muted); }}
  .grid2 {{ display: grid; gap: 14px; grid-template-columns: 1fr; }}
  @media (min-width: 860px) {{ .grid2 {{ grid-template-columns: 3fr 2fr; }} }}
</style>
</head>
<body>
<header>
  <div class="t">
    <h1>{title}</h1>
    <div class="f">{filename} · {project}</div>
  </div>
  <span class="chip {chip_class}">{status_label}</span>
  {actions}
</header>
<main>{body}</main>
</body>
</html>"""


def _e(v: Any) -> str:
    return html.escape(str(v if v is not None else ""))


# ---------------------------------------------------------------------------
# Renderers by type
# ---------------------------------------------------------------------------

def _pdf_body(inline_url: str) -> str:
    return f'<iframe class="pdf" src="{_e(inline_url)}" title="PDF preview"></iframe>'


def _xlsx_body(path: Path) -> str:
    import openpyxl

    wb = openpyxl.load_workbook(path, data_only=True)
    parts: list[str] = []
    for ws in wb.worksheets:
        rows = []
        for row in ws.iter_rows(values_only=True):
            cells = ["" if v is None else str(v) for v in row]
            while cells and cells[-1] == "":
                cells.pop()
            if cells:
                rows.append(cells)
        if not rows:
            continue
        width = max(len(r) for r in rows)
        body_rows = []
        for r in rows:
            padded = r + [""] * (width - len(r))
            # Single-cell rows read as section banners.
            if sum(1 for c in padded if c.strip()) == 1 and padded[0].strip():
                body_rows.append(
                    f'<tr class="section"><td colspan="{width}">{_e(padded[0])}</td></tr>'
                )
                continue
            tds = []
            for i, c in enumerate(padded):
                cls = "k" if i == 0 else ("c" if i == width - 1 and width > 2 else "")
                tds.append(f'<td class="{cls}">{_e(c)}</td>')
            body_rows.append(f"<tr>{''.join(tds)}</tr>")
        parts.append(f'<h2 class="sheet">{_e(ws.title)}</h2><table>{"".join(body_rows)}</table>')
    parts.append(
        '<p class="note" style="margin-top:16px">Transfer this data into CAISO\'s official '
        "Attachment A (.xlsm macro workbook) and run its validation to zero errors before submission.</p>"
    )
    return "".join(parts)


def _code_body(text: str, kind: str) -> str:
    lines_out = []
    for line in text.splitlines():
        esc = _e(line)
        if line.lstrip().startswith(("!", "#")):
            lines_out.append(f'<span class="cm">{esc}</span>')
        else:
            esc = re.sub(
                r"^(\w[\w_]*)",
                r'<span class="kw">\1</span>',
                esc,
            )
            lines_out.append(esc)
    label = {
        ".epc": "GE PSLF load-flow model (.epc) — steady-state buses, branches, transformers, generators.",
        ".dyd": "GE PSLF dynamic model (.dyd) — WECC REGC_A / REEC / REPC_A controller records.",
        ".raw": "Siemens PSS/E load-flow model (.raw) — steady-state buses, branches, transformers, generators.",
        ".dyr": "Siemens PSS/E dynamic model (.dyr) — standard-library controller records.",
    }.get(kind, "Plain-text model file.")
    return (
        f'<p class="note">{_e(label)} Validate against the current ISO base case '
        f'before submission.</p><pre class="code">{chr(10).join(lines_out)}</pre>'
    )


def _markdown_body(text: str) -> str:
    def inline(s: str) -> str:
        s = _e(s)
        s = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
        return s

    out: list[str] = []
    lines = text.splitlines()
    i = 0
    in_list = False
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if stripped.startswith("|"):
            if in_list:
                out.append("</ul>")
                in_list = False
            rows = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                rows.append([c.strip() for c in lines[i].strip().strip("|").split("|")])
                i += 1
            header, body = rows[0], [r for r in rows[1:] if not set("".join(r)) <= set("-: ")]
            out.append("<table><tr>" + "".join(f"<th>{inline(c)}</th>" for c in header) + "</tr>")
            for r in body:
                out.append("<tr>" + "".join(f"<td>{inline(c)}</td>" for c in r) + "</tr>")
            out.append("</table>")
            continue
        if stripped.startswith("- "):
            if not in_list:
                out.append("<ul>")
                in_list = True
            out.append(f"<li>{inline(stripped[2:])}</li>")
        else:
            if in_list:
                out.append("</ul>")
                in_list = False
            if stripped.startswith("## "):
                out.append(f"<h2>{inline(stripped[3:])}</h2>")
            elif stripped.startswith("# "):
                out.append(f"<h1>{inline(stripped[2:])}</h1>")
            elif stripped:
                out.append(f"<p>{inline(stripped)}</p>")
        i += 1
    if in_list:
        out.append("</ul>")
    return f'<div class="md">{"".join(out)}</div>'


def _kmz_body(path: Path, manifest: dict) -> str:
    try:
        with zipfile.ZipFile(path) as z:
            kml = z.read("doc.kml").decode("utf-8")
    except Exception:
        return '<p class="note">Could not read KMZ contents — use Download and open in Google Earth.</p>'

    coord_blocks = re.findall(r"<coordinates>(.*?)</coordinates>", kml, re.S)
    polygon: list[tuple[float, float]] = []
    center: tuple[float, float] | None = None
    for block in coord_blocks:
        pts = []
        for token in block.split():
            parts = token.split(",")
            if len(parts) >= 2:
                pts.append((float(parts[0]), float(parts[1])))
        if len(pts) >= 4:
            polygon = pts
        elif len(pts) == 1:
            center = pts[0]

    name_m = re.search(r"<name>(.*?)</name>", kml)
    desc_m = re.search(r"<description>(.*?)</description>", kml)

    map_html = '<p class="note">No polygon found in KMZ.</p>'
    if polygon:
        # Leaflet map over satellite imagery — the polygon sits on the real terrain.
        latlngs = ",".join(f"[{la:.6f},{lo:.6f}]" for lo, la in polygon)
        center_js = f"[{center[1]:.6f},{center[0]:.6f}]" if center else "null"
        map_html = f"""
        <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
        <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
        <div id="bdy-map" style="height:420px;border-radius:8px;border:1px solid var(--line);background:#e8ebe6"></div>
        <script>
        (function () {{
          var poly = [{latlngs}];
          var map = L.map("bdy-map", {{ scrollWheelZoom: false }});
          L.tileLayer("https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{{z}}/{{y}}/{{x}}", {{
            maxZoom: 19,
            attribution: "Imagery &copy; Esri, Maxar, Earthstar Geographics",
          }}).addTo(map);
          var boundary = L.polygon(poly, {{
            color: "#37d067", weight: 3, dashArray: "8 5", fillColor: "#37d067", fillOpacity: 0.12,
          }}).addTo(map);
          var c = {center_js};
          if (c) {{
            L.circleMarker(c, {{ radius: 6, color: "#fff", weight: 2, fillColor: "#2159c0", fillOpacity: 1 }})
              .addTo(map).bindTooltip("Site centroid", {{ direction: "top", offset: [0, -8] }});
          }}
          map.fitBounds(boundary.getBounds().pad(0.6));
        }})();
        </script>"""

    rows = [
        ("Placemark", name_m.group(1) if name_m else path.stem),
        ("Description", desc_m.group(1) if desc_m else "—"),
    ]
    if center:
        rows.append(("Site centroid (lat, lon)", f"{center[1]:.6f}, {center[0]:.6f}"))
    if polygon:
        rows.append(("Boundary vertices", ", ".join(f"({la:.4f}, {lo:.4f})" for lo, la in polygon[:-1])))
    table = "<table>" + "".join(
        f'<tr><td class="k">{_e(k)}</td><td>{_e(v)}</td></tr>' for k, v in rows
    ) + "</table>"

    return f"""
    <div class="grid2">
      <figure class="map">{map_html}
        <figcaption>KMZ boundary polygon over satellite terrain. Download and open in Google Earth Pro
        for the interactive view CAISO reviewers use.</figcaption>
      </figure>
      <div>{table}</div>
    </div>"""


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def render_preview(manifest: dict, doc: dict, path: Path, download_url: str) -> str:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        body = _pdf_body(download_url)
    elif suffix == ".xlsx":
        body = _xlsx_body(path)
    elif suffix in (".epc", ".dyd", ".raw", ".dyr"):
        body = _code_body(path.read_text(encoding="utf-8"), suffix)
    elif suffix == ".md":
        body = _markdown_body(path.read_text(encoding="utf-8"))
    elif suffix == ".kmz":
        body = _kmz_body(path, manifest)
    else:
        body = '<p class="note">No inline preview for this file type — use Download.</p>'

    return PAGE.format(
        title=_e(doc.get("title") or path.name),
        filename=_e(doc.get("file") or path.name),
        project=_e(manifest.get("project_name") or ""),
        status_label=_e(doc.get("status_label") or ""),
        chip_class="ok" if doc.get("status") == "generated" else "",
        actions=f'<a class="btn ghost" href="{_e(download_url)}" download>Download</a>',
        body=body,
    )


# ---------------------------------------------------------------------------
# Kickoff-document previews (the developer-provided example files in Step 2)
# ---------------------------------------------------------------------------

HL_CSS = """<style>
  mark.vhl { background: #fef3c7; box-shadow: 0 0 0 2px #fef3c7; border-bottom: 2px solid #f59e0b;
    border-radius: 2px; color: inherit; }
  .vhl-note { max-width: 720px; margin: 0 auto 14px; padding: 9px 14px; border: 1px solid #f59e0b66;
    background: #fffbeb; border-radius: 8px; font-size: 12.5px; color: #92400e; }
</style>
<script>
  addEventListener("DOMContentLoaded", () => {
    const m = document.querySelector("mark.vhl, tr.vhl-row");
    if (m) setTimeout(() => m.scrollIntoView({ block: "center", behavior: "smooth" }), 150);
  });
</script>"""


def _mark(active: bool, html: str) -> str:
    """Wrap a fragment in the validation highlight when this section is under review."""
    return f'<mark class="vhl">{html}</mark>' if active else html


def _hl_note(hl: list[str]) -> str:
    if not hl:
        return ""
    return ('<div class="vhl-note">Highlighted below: the part of this document examined by the '
            "validation check that opened this preview.</div>")


DOC_CSS = """<style>
  .paper { max-width: 720px; margin: 0 auto; padding: 42px 48px; background: #fff;
    border: 1px solid var(--line); border-radius: 10px; box-shadow: 0 1px 8px rgba(0,0,0,0.04); }
  .paper h1 { font-size: 17px; text-align: center; letter-spacing: 0.02em; margin: 0 0 4px;
    text-transform: uppercase; }
  .paper .sub { text-align: center; font-size: 12px; color: var(--muted); margin: 0 0 26px; }
  .paper h2 { font-size: 12px; text-transform: uppercase; letter-spacing: 0.07em;
    color: var(--accent); margin: 24px 0 8px; font-family: "JetBrains Mono", monospace; }
  .paper p { margin: 0 0 10px; font-size: 13.5px; }
  .paper .sig { display: grid; gap: 28px; grid-template-columns: 1fr 1fr; margin-top: 34px; }
  .paper .sig div { border-top: 1px solid var(--ink); padding-top: 6px; font-size: 12px;
    color: var(--muted); }
  .paper .sig strong { display: block; color: var(--ink); font-size: 13px; }
  .stamp { float: right; margin: -6px 0 10px 14px; padding: 5px 12px; border: 2px solid #b23b3b;
    border-radius: 6px; color: #b23b3b; font-family: "JetBrains Mono", monospace; font-size: 10px;
    text-transform: uppercase; letter-spacing: 0.1em; transform: rotate(2deg); }
</style>"""


def _lease_body(intake: dict, hl: list[str] | None = None) -> str:
    hl = hl or []
    return DOC_CSS + HL_CSS + f"""
    <p class="note">Example document preloaded by the demo — in production this is the developer's own
    executed agreement, uploaded at kickoff.</p>
    {_hl_note(hl)}
    <div class="paper">
      <span class="stamp">Executed copy</span>
      <h1>Solar Ground Lease Agreement</h1>
      <p class="sub">Dated as of March 14, 2026</p>
      <h2>1 · Parties</h2>
      <p>This Ground Lease ("Lease") is entered into between <strong>{_e(intake.get('site_owner'))}</strong>,
      a California limited partnership ("Lessor"), and {_mark('legal_name' in hl,
      f"<strong>{_e(intake.get('legal_name'))}</strong>, a {_e(intake.get('state_of_origin'))} limited liability company")}
      ("Lessee").</p>
      <h2>2 · Premises</h2>
      <p>Approximately <strong>{_e(intake.get('site_acreage'))} acres</strong> of real property in
      {_e(intake.get('county'))} County, {_e(intake.get('state'))}, centered near
      {_mark('gps' in hl, f"{_e(intake.get('gps_lat'))}, {_e(intake.get('gps_lon'))}")}, as further described in Exhibit A
      (legal description) and depicted in Exhibit B (parcel map).</p>
      <h2>3 · Purpose and exclusivity</h2>
      <p>{_mark('exclusivity' in hl,
      "Lessee shall have the <strong>exclusive right</strong> to use the Premises for the development, "
      "construction, and operation of a solar photovoltaic and battery energy storage facility, including "
      "interconnection facilities. Lessor shall not grant any interest in the Premises inconsistent with "
      "Lessee's exclusive rights during the Term.")}</p>
      <h2>4 · Term</h2>
      <p>A development term of five (5) years from the Effective Date, followed upon commercial operation
      by an operating term of thirty (30) years with two (2) five-year extension options.</p>
      <h2>5 · Assignment for interconnection</h2>
      <p>{_mark('exclusivity' in hl,
      "Lessor acknowledges that Lessee may present this Lease to the California Independent System "
      "Operator as evidence of site exclusivity in connection with its interconnection request.")}</p>
      <div class="sig">
        <div><strong>{_e(intake.get('site_owner'))}</strong>By: T. Willow, General Partner<br/>Date: 03/14/2026</div>
        <div><strong>{_e(intake.get('legal_name'))}</strong>By: {_e(intake.get('signatory_name'))}, {_e(intake.get('signatory_title'))}<br/>Date: 03/14/2026</div>
      </div>
    </div>"""


def _signatory_body(intake: dict, hl: list[str] | None = None) -> str:
    hl = hl or []
    return DOC_CSS + HL_CSS + f"""
    <p class="note">Example document preloaded by the demo — in production this is the developer's own
    officer certificate or board resolution.</p>
    {_hl_note(hl)}
    <div class="paper">
      <h1>Certificate of Authorized Signatory</h1>
      <p class="sub">{_mark('legal_name' in hl,
      f"{_e(intake.get('legal_name'))} — a {_e(intake.get('state_of_origin'))} limited liability company")}</p>
      <p>The undersigned, being the Secretary of {_mark('legal_name' in hl,
      f"<strong>{_e(intake.get('legal_name'))}</strong>")} (the
      "Company"), hereby certifies that:</p>
      <h2>1 · Authorization</h2>
      <p>{_mark('signatory' in hl,
      f"<strong>{_e(intake.get('signatory_name'))}</strong>, {_e(intake.get('signatory_title'))} of the "
      "Company, is duly authorized to execute and deliver, on behalf of the Company, any and all "
      "applications, agreements, and instruments in connection with the Company's generator "
      "interconnection request to the California Independent System Operator Corporation, including "
      "Appendix 1 (Interconnection Request) and submissions through the RIMS5 system.")}</p>
      <h2>2 · Incumbency</h2>
      <p>The signature set forth beside the officer's name below is such officer's true signature.</p>
      <div class="sig">
        <div><strong>{_e(intake.get('signatory_name'))}</strong>{_e(intake.get('signatory_title'))} — specimen signature</div>
        <div><strong>M. Chen</strong>Secretary — certifying officer<br/>Date: 03/02/2026</div>
      </div>
    </div>"""


# Rows of the developer technical data workbook: (intake key, sheet label, unit).
_WORKBOOK_ROWS: list[tuple[str, list[tuple[str, str, str]]]] = [
    ("Project technical parameters", [
        ("project_type", "Project type", ""),
        ("gross_mva", "Gross capacity", "MVA"),
        ("gross_mw", "Gross output", "MW"),
        ("aux_mw", "Auxiliary (station) load", "MW"),
        ("losses_mw", "Electrical losses to POI", "MW"),
        ("net_mw_poi", "Requested net output at POI", "MW"),
    ]),
    ("Equipment", [
        ("inverter", "Inverter manufacturer / model / qty", ""),
        ("module", "PV module", ""),
        ("transformer", "Main transformer (GSU)", ""),
        ("collector_kv", "Collector system voltage", "kV"),
    ]),
]

# Rows of the storage vendor's BESS specification sheet.
_BESS_ROWS: list[tuple[str, list[tuple[str, str, str]]]] = [
    ("Storage system", [
        ("bess_vendor", "Manufacturer / model", ""),
        ("bess_mw", "Power rating", "MW"),
        ("bess_mwh", "Energy capacity", "MWh"),
        ("bess_charging", "Charging configuration", ""),
    ]),
]

WORKBOOK_CSS = """<style>
  .wb { max-width: 720px; margin: 0 auto; background: #fff; border: 1px solid var(--line);
    border-radius: 10px; overflow: hidden; box-shadow: 0 1px 8px rgba(0,0,0,0.04); }
  .wb table { width: 100%; border-collapse: collapse; font-size: 13px; }
  .wb th { text-align: left; font-family: "JetBrains Mono", monospace; font-size: 10px;
    text-transform: uppercase; letter-spacing: 0.08em; color: var(--muted);
    background: var(--soft); padding: 8px 14px; border-bottom: 1px solid var(--line); }
  .wb td { padding: 8px 14px; border-bottom: 1px solid var(--line); vertical-align: top; }
  .wb td.val { font-family: "JetBrains Mono", monospace; white-space: nowrap; }
  .wb tr.sec td { background: var(--soft); font-family: "JetBrains Mono", monospace;
    font-size: 10.5px; text-transform: uppercase; letter-spacing: 0.08em; color: var(--accent); }
  .wb tr.vhl-row td { background: #fffbeb; box-shadow: inset 3px 0 0 #f59e0b; }
  .wb td .blank { color: #b23b3b; font-style: italic; }
</style>"""


def _sheet_body(intake: dict, sections: list, note: str, hl: list[str] | None = None) -> str:
    """Spreadsheet-style preview shared by the technical workbook and BESS spec sheet."""
    hl = hl or []
    rows_html = ""
    for section, rows in sections:
        rows_html += f'<tr class="sec"><td colspan="3">{_e(section)}</td></tr>'
        for key, rlabel, unit in rows:
            v = intake.get(key)
            if isinstance(v, float) and v.is_integer():
                v = int(v)
            blank = v is None or str(v).strip() == ""
            val = '<span class="blank">— blank —</span>' if blank else _e(v)
            cls = ' class="vhl-row"' if key in hl else ""
            rows_html += (f"<tr{cls}><td>{_e(rlabel)}</td>"
                          f'<td class="val">{val}</td><td class="val">{_e(unit)}</td></tr>')
    return WORKBOOK_CSS + HL_CSS + f"""
    <p class="note">{note}</p>
    {_hl_note(hl)}
    <div class="wb">
      <table>
        <thead><tr><th>Parameter</th><th>Value</th><th>Unit</th></tr></thead>
        <tbody>{rows_html}</tbody>
      </table>
    </div>"""


def _workbook_body(intake: dict, hl: list[str] | None = None) -> str:
    return _sheet_body(
        intake, _WORKBOOK_ROWS,
        "Developer technical data workbook — the source of the technical parameters in the "
        "intake form. Values shown reflect the file currently attached to the intake.", hl)


def _bess_body(intake: dict, hl: list[str] | None = None) -> str:
    return _sheet_body(
        intake, _BESS_ROWS,
        "Storage vendor specification sheet — the source of the storage parameters in the "
        "intake form. Values shown reflect the file currently attached to the intake.", hl)


def render_requirement_preview(rule_id: str, req: dict) -> str:
    """Preview page for the ISO requirement (ground truth) behind a validation check."""
    paras = "".join(f"<p>{_e(p)}</p>" for p in req.get("paragraphs", []))
    return PAGE.format(
        title=_e(req.get("title") or "Requirement"),
        filename=_e(req.get("source") or rule_id),
        project="CAISO requirement",
        status_label="Ground truth",
        chip_class="ok",
        actions="",
        body=DOC_CSS + HL_CSS + f"""
        <p class="note">Requirement summary drafted for this demo from the cited CAISO provision —
        the operative clause enforced by the validation check is highlighted.</p>
        <div class="paper">
          <h1>{_e(req.get('title'))}</h1>
          <p class="sub">{_e(req.get('source'))}</p>
          {paras}
          <h2>Operative clause</h2>
          <p><mark class="vhl">{_e(req.get('clause'))}</mark></p>
        </div>""",
    )


def render_kickoff_preview(key: str, intake: dict, meta: dict, hl: list[str] | None = None) -> str:
    """Preview page for a kickoff document (Step 2 uploads), with optional highlights."""
    hl = hl or []
    if key == "file_site_control":
        title, body = "Executed Site Exclusivity Agreement", _lease_body(intake, hl)
    elif key == "file_signatory":
        title, body = "Proof of Authorized Signatory", _signatory_body(intake, hl)
    elif key == "file_technical":
        title, body = "Technical Data Workbook", _workbook_body(intake, hl)
    elif key == "file_bess":
        title, body = "BESS Specification Sheet", _bess_body(intake, hl)
    elif key == "file_boundary":
        import tempfile
        from backend.app.services.caiso_packet import _derived, _gen_kmz

        with tempfile.NamedTemporaryFile(suffix=".kmz") as tmp:
            path = Path(tmp.name)
            _gen_kmz(intake, _derived(intake), path)
            body = (
                '<p class="note">Example boundary file preloaded by the demo — rendered from the parcel '
                "polygon. In production this is the developer's own KMZ or parcel map.</p>"
                + (HL_CSS + _hl_note(hl) if hl else "")
                + _kmz_body(path, {})
            )
        title = "Project Boundary (KMZ)"
    else:
        title = "Kickoff document"
        body = '<p class="note">No inline preview available for this document.</p>'

    return PAGE.format(
        title=_e(title),
        filename=_e(meta.get("name") or key),
        project=_e(intake.get("project_name") or ""),
        status_label="Example file — demo" if meta.get("example") else "Uploaded document",
        chip_class="",
        actions="",
        body=body,
    )

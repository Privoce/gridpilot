from __future__ import annotations

import json
from pathlib import Path

from jinja2 import Template

from backend.app.config import settings
from backend.app.models import AuditReport, Severity

REPORT_TEMPLATE = Template(
    """
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <title>GridPilot Interconnection Readiness Report — {{ report.project_name }}</title>
  <style>
    :root {
      --ink: #1c2430;
      --navy: #0b2a4a;
      --muted: #5b6775;
      --paper: #f4f6f8;
      --card: #ffffff;
      --line: #d5dbe3;
      --red: #a11a1a;
      --amber: #8a5a00;
      --green: #1f6b3a;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: "IBM Plex Sans", "Segoe UI", "Helvetica Neue", Arial, sans-serif;
      color: var(--ink);
      background: var(--paper);
      line-height: 1.45;
      font-size: 14px;
    }
    .wrap { max-width: 920px; margin: 0 auto; padding: 36px 28px 56px; background: #fff; border-left: 1px solid var(--line); border-right: 1px solid var(--line); min-height: 100vh; }
    .brand {
      display: flex; justify-content: space-between; align-items: baseline;
      border-bottom: 2px solid var(--navy); padding-bottom: 12px; margin-bottom: 24px;
    }
    .brand h1 { margin: 0; font-size: 20px; font-weight: 600; color: var(--navy); letter-spacing: 0; }
    .brand span { color: var(--muted); font-size: 12px; font-weight: 500; text-transform: uppercase; letter-spacing: 0.04em; }
    h2 { font-size: 15px; margin: 24px 0 10px; font-weight: 600; color: var(--navy); }
    .meta { display: grid; grid-template-columns: repeat(2, 1fr); gap: 10px 24px; margin-bottom: 18px; }
    .meta div { font-size: 13px; }
    .meta b { display: block; color: var(--muted); font-weight: 600; font-size: 11px; text-transform: uppercase; letter-spacing: 0.04em; }
    .scorebox {
      background: var(--paper); border: 1px solid var(--line); padding: 16px 18px; margin: 16px 0;
      display: flex; gap: 22px; align-items: center;
    }
    .score {
      font-size: 36px; font-weight: 600; color: var(--navy);
      min-width: 90px; font-variant-numeric: tabular-nums;
    }
    .score small { display: block; font-size: 11px; color: var(--muted); font-weight: 600; text-transform: uppercase; letter-spacing: 0.04em; }
    .summary { font-size: 14px; color: #3a4553; }
    .badge {
      display: inline-block; padding: 3px 8px; font-size: 11px; font-weight: 600;
      text-transform: uppercase; letter-spacing: 0.03em; border: 1px solid transparent;
    }
    .badge.not_ready { background: #f8e8e8; color: var(--red); border-color: #e2bcbc; }
    .badge.needs_review { background: #f8f0de; color: var(--amber); border-color: #e2d3a8; }
    .badge.ready { background: #e6f2ea; color: var(--green); border-color: #b9d8c4; }
    .finding {
      background: var(--card); border: 1px solid var(--line);
      padding: 12px 14px; margin: 8px 0;
    }
    .finding h3 { margin: 0 0 6px; font-size: 14px; font-weight: 600; }
    .finding p { margin: 4px 0; font-size: 13px; color: #3a4553; }
    .sev { font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.03em; }
    .sev.blocking { color: var(--red); }
    .sev.warning { color: var(--amber); }
    .sev.ready { color: var(--green); }
    table { width: 100%; border-collapse: collapse; font-size: 13px; }
    th, td { border-bottom: 1px solid var(--line); text-align: left; padding: 8px 6px; vertical-align: top; }
    th { color: var(--muted); font-weight: 600; font-size: 11px; text-transform: uppercase; letter-spacing: 0.04em; background: #f8fafb; }
    .foot { margin-top: 32px; font-size: 11px; color: var(--muted); border-top: 1px solid var(--line); padding-top: 12px; }
  </style>
</head>
<body>
  <div class="wrap">
    <div class="brand">
      <h1>GridPilot</h1>
      <span>Interconnection Readiness &amp; Compliance Report</span>
    </div>

    <div class="meta">
      <div><b>Project</b>{{ report.project_name }}</div>
      <div><b>ISO / RTO</b>{{ report.iso.value }}</div>
      <div><b>Source file</b>{{ report.filename }}</div>
      <div><b>Report ID</b>{{ report.report_id }} · {{ report.created_at }}</div>
    </div>

    <div class="scorebox">
      <div class="score">{{ report.readiness_score }}<small>Readiness</small></div>
      <div>
        <span class="badge {{ report.status }}">{{ report.status.replace('_', ' ') }}</span>
        <p class="summary">{{ report.summary }}</p>
        <p style="font-size:12px;color:var(--muted);margin:0">
          {{ blocking }} blocking · {{ warnings }} warnings · {{ ready }} ready ·
          {{ report.pages_analyzed }} page(s) · model {{ report.model }} ({{ report.mode }})
        </p>
      </div>
    </div>

    <h2>Findings</h2>
    {% for f in report.findings %}
      <div class="finding {{ f.severity.value }}">
        <div class="sev {{ f.severity.value }}">
          {% if f.severity.value == 'blocking' %}Red — Blocking{% elif f.severity.value == 'warning' %}Yellow — Warning{% else %}Green — Ready{% endif %}
          {% if f.rule_id %} · {{ f.rule_id }}{% endif %}
        </div>
        <h3>{{ f.title }}</h3>
        <p>{{ f.detail }}</p>
        {% if f.location %}<p><b>Location:</b> {{ f.location }}</p>{% endif %}
        {% if f.recommendation %}<p><b>Recommendation:</b> {{ f.recommendation }}</p>{% endif %}
        {% if f.evidence %}<p><b>Evidence:</b> {{ f.evidence }}</p>{% endif %}
      </div>
    {% endfor %}

    <h2>Extracted equipment</h2>
    <table>
      <thead><tr><th>Type</th><th>Label</th><th>Rating</th><th>Notes</th></tr></thead>
      <tbody>
      {% for eq in report.extract.equipment %}
        <tr>
          <td>{{ eq.type }}</td>
          <td>{{ eq.label or '—' }}</td>
          <td>{{ eq.rating or '—' }}</td>
          <td>{{ eq.notes or '—' }}</td>
        </tr>
      {% else %}
        <tr><td colspan="4">No structured equipment extracted.</td></tr>
      {% endfor %}
      </tbody>
    </table>

    <h2>Rules checked</h2>
    <p style="font-size:13px;color:var(--muted)">{{ report.rules_checked | join(', ') }}</p>

    <div class="foot">
      GridPilot is an engineering co-pilot, not a substitute for PE stamp or ISO formal review.
      Generated by Nerviom · Utility-scale renewable interconnection AI.
    </div>
  </div>
</body>
</html>
"""
)


def write_report_artifacts(report: AuditReport) -> tuple[Path, Path]:
    html_path = settings.report_dir / f"{report.report_id}.html"
    json_path = settings.report_dir / f"{report.report_id}.json"

    blocking = sum(1 for f in report.findings if f.severity == Severity.BLOCKING)
    warnings = sum(1 for f in report.findings if f.severity == Severity.WARNING)
    ready = sum(1 for f in report.findings if f.severity == Severity.READY)

    html = REPORT_TEMPLATE.render(
        report=report,
        blocking=blocking,
        warnings=warnings,
        ready=ready,
    )
    html_path.write_text(html, encoding="utf-8")
    json_path.write_text(
        json.dumps(report.model_dump(mode="json"), indent=2),
        encoding="utf-8",
    )
    return html_path, json_path

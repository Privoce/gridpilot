from __future__ import annotations

import json
import re
from typing import Any, Optional

import httpx

from backend.app.config import settings
from backend.app.models import AuditExtract, EquipmentItem, Finding, Severity
from backend.app.services.pdf_extract import PageImage


class GrokError(RuntimeError):
    pass


def _extract_output_text(payload: dict[str, Any]) -> str:
    if isinstance(payload.get("output_text"), str) and payload["output_text"].strip():
        return payload["output_text"]

    chunks: list[str] = []
    for item in payload.get("output") or []:
        if item.get("type") == "message":
            for content in item.get("content") or []:
                if content.get("type") in {"output_text", "text"} and content.get("text"):
                    chunks.append(content["text"])
        elif item.get("type") in {"output_text", "text"} and item.get("text"):
            chunks.append(item["text"])
    if chunks:
        return "\n".join(chunks)

    # Fallbacks seen in some SDK shapes
    for key in ("content", "text", "response"):
        val = payload.get(key)
        if isinstance(val, str) and val.strip():
            return val
    raise GrokError(f"Could not parse model output: keys={list(payload.keys())}")


def _parse_json_block(text: str) -> dict[str, Any]:
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fence:
        return json.loads(fence.group(1))

    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        return json.loads(text[start : end + 1])
    raise GrokError("Model did not return valid JSON")


async def analyze_sld(
    *,
    iso: str,
    rules_pack: dict[str, Any],
    pages: list[PageImage],
    ocr_text: str,
    project_hint: str = "",
) -> tuple[AuditExtract, list[Finding], str]:
    if not settings.xai_api_key:
        raise GrokError("XAI_API_KEY is not configured")

    rule_lines = []
    for r in rules_pack.get("rules", []):
        rule_lines.append(
            f"- {r['id']} [{r['severity']}]: {r['title']} — {r.get('description', '')}"
        )
    rules_text = "\n".join(rule_lines)

    prompt = f"""You are GridPilot, an expert utility-scale renewable interconnection auditor.
You review Single-Line Diagrams (SLD) for {iso} interconnection readiness.

TASK:
1) Extract electrical equipment and key ratings visible on the drawing(s).
2) Audit against the {iso} rule pack below.
3) Return STRICT JSON only (no markdown) with this schema:
{{
  "extract": {{
    "project_name": string|null,
    "capacity_mw": number|null,
    "interconnection_voltage_kv": number|null,
    "inverter_models": [string],
    "transformers": [string],
    "equipment": [{{"type": string, "label": string|null, "rating": string|null, "notes": string|null}}],
    "observed_notes": [string],
    "raw_summary": string
  }},
  "findings": [
    {{
      "id": string,
      "severity": "blocking"|"warning"|"ready",
      "title": string,
      "detail": string,
      "rule_id": string|null,
      "location": string|null,
      "recommendation": string|null,
      "evidence": string|null
    }}
  ],
  "summary": string
}}

Severity guide:
- blocking: will cause interconnection application rejection / requeue
- warning: likely deficiency / study risk, should fix before filing
- ready: requirement appears satisfied

Be conservative: if something is not clearly labeled, treat it as missing.
This is a co-pilot for engineers — flag issues; do not invent equipment that is not visible.

ISO RULE PACK ({iso} v{rules_pack.get('version', 'n/a')}):
{rules_text}

References: {', '.join(rules_pack.get('references', []))}

Project hint: {project_hint or 'n/a'}

OCR / embedded text from PDF (may be incomplete):
\"\"\"
{ocr_text[:12000]}
\"\"\"
"""

    content: list[dict[str, Any]] = [{"type": "input_text", "text": prompt}]
    for page in pages[: settings.max_pages]:
        content.append(
            {
                "type": "input_image",
                "image_url": page.data_url,
                "detail": "high",
            }
        )

    body = {
        "model": settings.xai_model,
        "input": [{"role": "user", "content": content}],
    }

    async with httpx.AsyncClient(timeout=180.0) as client:
        resp = await client.post(
            f"{settings.xai_base_url.rstrip('/')}/responses",
            headers={
                "Authorization": f"Bearer {settings.xai_api_key}",
                "Content-Type": "application/json",
            },
            json=body,
        )
        if resp.status_code >= 400:
            raise GrokError(f"xAI API {resp.status_code}: {resp.text[:800]}")
        payload = resp.json()

    text = _extract_output_text(payload)
    data = _parse_json_block(text)

    extract_raw = data.get("extract") or {}
    equipment = [
        EquipmentItem(**eq) if isinstance(eq, dict) else EquipmentItem(type=str(eq))
        for eq in extract_raw.get("equipment") or []
    ]
    extract = AuditExtract(
        project_name=extract_raw.get("project_name"),
        capacity_mw=extract_raw.get("capacity_mw"),
        interconnection_voltage_kv=extract_raw.get("interconnection_voltage_kv"),
        inverter_models=list(extract_raw.get("inverter_models") or []),
        transformers=list(extract_raw.get("transformers") or []),
        equipment=equipment,
        observed_notes=list(extract_raw.get("observed_notes") or []),
        raw_summary=extract_raw.get("raw_summary") or "",
    )

    findings: list[Finding] = []
    for f in data.get("findings") or []:
        try:
            findings.append(
                Finding(
                    id=str(f.get("id") or f"AI-{len(findings)+1}"),
                    severity=Severity(f.get("severity", "warning")),
                    title=str(f.get("title") or "Finding"),
                    detail=str(f.get("detail") or ""),
                    rule_id=f.get("rule_id"),
                    location=f.get("location"),
                    recommendation=f.get("recommendation"),
                    evidence=f.get("evidence"),
                )
            )
        except Exception:
            continue

    summary = str(data.get("summary") or extract.raw_summary or "Audit complete.")
    return extract, findings, summary


async def smoke_test() -> Optional[str]:
    if not settings.xai_api_key:
        return None
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(
            f"{settings.xai_base_url.rstrip('/')}/responses",
            headers={
                "Authorization": f"Bearer {settings.xai_api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": settings.xai_model,
                "input": "Reply with exactly: GRIDPILOT_OK",
            },
        )
        if resp.status_code >= 400:
            raise GrokError(f"xAI API {resp.status_code}: {resp.text[:400]}")
        return _extract_output_text(resp.json())

# GridPilot

**Pre-filing interconnection QA for renewable developers.**

US power markets have no national grid company. Three roles matter:

| Role | Who | What they do |
|------|-----|----------------|
| **Utility** | AES Indiana, etc. | Wires / retail; primary counterparty for many distribution filings (e.g. PowerClerk) |
| **Developer** | IPPs, project cos | Site, design, and **assemble the application** to connect a plant |
| **ISO + FERC** | MISO, PJM, ERCOT… | Market operator + federal frame; large / transmission projects enter the ISO queue |

Developers today hire consultants for 3–6 months to build packets, then wait another 3–6 months for utility/ISO review — with no guarantee of acceptance. AI is starting to help **utilities/ISOs review inbound filings**. Almost nothing helps the **developer check the same public requirements before submit**. That is GridPilot.

MVP: audit the **single-line diagram (SLD)** against published utility + ISO rule packs → triage blockers → export a readiness report → *then* file outside GridPilot.

## Guided demo (AES Indiana)

Concrete TO example used for interviews / GTM credibility:

1. You play a **developer** interconnection manager (not the utility)
2. Project: Cedar Ridge Solar + Storage · **120 MW** · Indiana
3. Path: **MISO DPP** (transmission-scale) with **AES Indiana** as TO
4. Audit against AES Indiana Facilities Connection gaps (`R-PROTECT-01`, `R-METER-01`, `R-IBR-01`, …)
5. Export report — filing to [AES Indiana](https://www.aesindiana.com/interconnections) / [PowerClerk](https://aesindianainterconnection.powerclerk.com) is out of band

Demo login (shown on demo page): `demo@gridpilot.dev` / `gridpilot`

## Quick start

```bash
git clone https://github.com/Privoce/gridpilot.git
cd gridpilot
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # set XAI_API_KEY + SECRET_KEY

python samples/generate_sample_sld.py
./run.sh
```

- Marketing: http://127.0.0.1:8000  
- App: http://127.0.0.1:8000/app  
- Guided demo: http://127.0.0.1:8000/app#/demo  

**Live (Vercel):** https://gridpilot-three.vercel.app  

## Product surface

| Area | What you get |
|------|----------------|
| Auth + orgs | Signup creates a developer org; session cookies |
| Projects | Utility/ISO target, capacity, POI metadata |
| Drawings | Versioned SLD uploads per project |
| Audits | Vision + rule packs; async locally, inline on Vercel |
| Findings | Acknowledge / resolve / dismiss triage |
| Filing gate | Blocked until open blockers = 0 |
| Billing | Metered pre-filing audits |

## Design system

- Tokens: `backend/app/static/css/theme.css` (`--gp-*`)
- Tailwind bridge: `backend/app/static/js/theme-config.js`
- Recipes: `backend/app/static/js/ui.js`

## Deploy (Vercel)

Entrypoint: `main.py`. Set `XAI_API_KEY` + `SECRET_KEY` in the Vercel project. SQLite/uploads under `/tmp` on Vercel (demo reseeds on cold start).

## Roadmap

- **Now:** Developer pre-filing SLD audit (this repo) · AES Indiana / MISO demo
- **Next:** More utility rule packs + distribution vs transmission pathing; Chrome assist for portal forms
- **Later:** Congestion / curtailment analytics (DaaS)

## Security

Keep keys in `.env` only. Rotate any key pasted into chat. Uploads stay under `uploads/` (or `/tmp/gridpilot` on Vercel).

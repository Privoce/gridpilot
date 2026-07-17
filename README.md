# GridPilot

Interconnection readiness platform for utility-scale renewables.

Not a chat demo. A workspace for developers and EPCs to:

1. Manage **projects** (ISO, capacity, POI)
2. Version **SLD drawings**
3. Run **queued audits** (Vision + ISO rule packs)
4. **Triage findings** until the filing gate clears
5. Track **plan usage** (Free / Pro)

## Design system

UI uses **Tailwind CSS** with tokens mirrored from [x.ai/api](https://x.ai/api):

- Tokens: `backend/app/static/css/theme.css` (`--gp-*` variables)
- Tailwind bridge: `backend/app/static/js/theme-config.js`
- Component recipes: `backend/app/static/js/ui.js`

Change colors/fonts in `theme.css` to restyle the whole product. Optional dark mode: set `<html data-theme="dark">`.

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
- Demo credentials (shown on demo page): `demo@gridpilot.dev` / `gridpilot`

### Guided demo path

1. **Try Demo** → scenario brief + intentional SLD defects  
2. One-click enter workspace (sample `cedar_ridge_sld_demo.pdf` attached)  
3. Review drawing → run PJM audit → triage blockers → export readiness report  
4. Use **Reset demo audits** in the Demo guide to re-run cleanly

## Product surface

| Area | What you get |
|------|----------------|
| Auth + orgs | Signup creates an org; session cookies |
| Projects | ISO target, capacity, POI metadata |
| Drawings | Versioned SLD uploads per project |
| Audits | Async jobs with queued → running → completed |
| Findings | Acknowledge / resolve / dismiss triage |
| Filing gate | Blocked until open blockers = 0 |
| Billing | Metered audits + demo Pro upgrade |

## API (authenticated)

- `POST /api/auth/signup|login|logout` · `GET /api/auth/me`
- `GET|POST /api/projects` · `GET /api/projects/{id}`
- `POST /api/projects/{id}/drawings` · `POST /api/projects/{id}/audits`
- `GET /api/audits` · `GET /api/audits/{id}`
- `PATCH /api/audits/{id}/findings/{finding_id}`
- `GET /api/dashboard` · `GET /api/billing`

## Roadmap

- **Now:** Audit Engine SaaS spine (this repo)
- **Next:** Chrome auto-filler for ISO portals
- **Later:** Congestion / curtailment analytics (DaaS)

## Security

Keep keys in `.env` only. Rotate any key that was pasted into chat. Drawing uploads stay on local disk under `uploads/{org}/{project}/`.

## GitHub Pages

Marketing site: https://privoce.github.io/gridpilot/

The full app (audits, Vision, auth) runs locally via `./run.sh` — GitHub Pages hosts the static landing only.

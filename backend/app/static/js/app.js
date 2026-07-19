import { api } from "./api.js";
import { button, field, label, panel, pill as uiPill, table } from "./ui.js";

const root = document.getElementById("root");
// Files attached during this session (bytes live in memory only; intake stores metadata).
const sessionFiles = {};
const ONBOARD_KEY = "gp_demo_onboard_v4";
const INTAKE_KEY = "gp_caiso_intake_v1";
const EXTRACT_KEY = "gp_caiso_extract_v1";
const WIZARD_META = [
  { n: 1, label: "Scenario" },
  { n: 2, label: "Documents" },
  { n: 3, label: "Intake" },
  { n: 4, label: "Validate" },
  { n: 5, label: "Generate" },
  { n: 6, label: "Packet" },
];
const WIZARD_LAST = 6;

let state = {
  me: null,
  toast: null,
  modal: null,
  demoCtx: null,
  lastAuditId: null,
  /** CAISO demo: intake schema, validation result, generated packet manifest. */
  caisoSchema: null,
  validation: null,
  packet: null,
  /** Client-side packet-generation progress UI. */
  genUi: null,
  /** Client-side document-extraction progress UI. */
  extractUi: null,
  /** In-card re-extract + revalidate progress on the Validate step. */
  fixUi: null,
  /** Simulated upload progress per file slot: {key: {name, size, startedAt}}. */
  uploadUi: {},
  /** Real-app request wizard: busy overlay, validation result, packet manifest. */
  reqBusy: null,
  reqValidation: null,
  reqPacket: null,
};

// Simulated upload duration for file widgets.
const UPLOAD_MS = 1100;

// Stage labels for the in-card fix pass (corrected upload on a red validation item).
const FIX_STAGES = [
  { at: 0, label: "Reading the document…" },
  { at: 800, label: "Extracting fields into the intake…" },
  { at: 1600, label: "Re-running validation checks…" },
];
const FIX_MIN_MS = 2400;

// Stage labels for the AI document-extraction pass (Step 2 → Step 3).
const EXTRACT_STAGES = [
  { at: 0, label: "Reading site exclusivity agreement — parties, premises, term…" },
  { at: 850, label: "Reading technical data workbook — MW chain, equipment…" },
  { at: 1700, label: "Reading BESS specification sheet — power, energy, charging…" },
  { at: 2500, label: "Parsing certificate of authorized signatory…" },
  { at: 3200, label: "Reading boundary file — polygon, centroid, acreage…" },
  { at: 3900, label: "Cross-checking the legal name across documents…" },
  { at: 4550, label: "Populating the intake form…" },
];
const EXTRACT_MIN_MS = 5400;

// The consulting-firm workstream GridPilot performs (Demo流程 Phase 2, Steps A–G).
const GEN_STAGES = [
  { at: 0, label: "Kickoff — validating intake & confirming POI…" },
  { at: 800, label: "Building load flow model (.epc) — generator, GSU, collector, POI…" },
  { at: 1800, label: "Integrating dynamic models (.dyd) — REGC_A / REEC_A / REPC_A…" },
  { at: 2800, label: "Running flat run + bump test — fault cleared after 5 cycles…" },
  { at: 3700, label: "Generating reactive power capability curve (±0.95 PF)…" },
  { at: 4600, label: "Drafting single-line diagram & scaled site drawing…" },
  { at: 5400, label: "Plotting project boundary KMZ…" },
  { at: 6100, label: "Filling Appendix 1 & Attachment A…" },
  { at: 6950, label: "QC — cross-checking MW chain, legal name, GPS across all documents…" },
];
const GEN_MIN_MS = 7800;

// Static scenario copy for the guided demo (Ravenwood, fictional).
const CAISO_SCENARIO = {
  company: "Ravenwood Energy LLC",
  project: "Ravenwood",
  type: "125 MW Solar PV + 50 MW / 200 MWh BESS",
  poi: "Whirlwind Substation (SCE) — 230 kV",
  track: "Independent Study Process",
  cod: "06/30/2028",
  county: "Kern County, CA",
};

function toast(msg) {
  state.toast = msg;
  render();
  setTimeout(() => {
    if (state.toast === msg) {
      state.toast = null;
      render();
    }
  }, 2800);
}

function route() {
  const hash = location.hash.replace(/^#\/?/, "") || "dashboard";
  const [name, id] = hash.split("/");
  return { name, id };
}

function navigate(path) {
  location.hash = `#/${path}`;
}

function esc(s) {
  return String(s ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function fmtDate(d) {
  if (!d) return "—";
  try {
    return new Date(d).toLocaleString();
  } catch {
    return String(d);
  }
}

function pill(status) {
  return uiPill(status);
}

function loadOnboard() {
  try {
    return JSON.parse(localStorage.getItem(ONBOARD_KEY) || "{}");
  } catch {
    return {};
  }
}

function saveOnboard(patch) {
  const next = { ...loadOnboard(), ...patch, updatedAt: Date.now() };
  localStorage.setItem(ONBOARD_KEY, JSON.stringify(next));
  return next;
}

function clearOnboard() {
  localStorage.removeItem(ONBOARD_KEY);
}

function loadIntake() {
  const defaults = state.caisoSchema?.defaults || {};
  try {
    return { ...defaults, ...JSON.parse(localStorage.getItem(INTAKE_KEY) || "{}") };
  } catch {
    return { ...defaults };
  }
}

function saveIntake(values) {
  localStorage.setItem(INTAKE_KEY, JSON.stringify(values));
}

function clearIntake() {
  localStorage.removeItem(INTAKE_KEY);
}

function loadExtract() {
  try {
    return JSON.parse(localStorage.getItem(EXTRACT_KEY) || "{}");
  } catch {
    return {};
  }
}

function saveExtract(prov) {
  localStorage.setItem(EXTRACT_KEY, JSON.stringify(prov || {}));
}

function clearExtract() {
  localStorage.removeItem(EXTRACT_KEY);
}

function getWizardStep() {
  return Math.min(WIZARD_LAST + 1, Math.max(1, Number(loadOnboard().wizardStep || 1)));
}

function setWizardStep(n) {
  saveOnboard({ wizardStep: n, started: true });
}

async function ensureAuth(required = true) {
  if (state.me) return state.me;
  try {
    state.me = await api.me();
    return state.me;
  } catch {
    state.me = null;
    if (required) navigate("login");
    return null;
  }
}

const DEMO_SCENARIO_FALLBACK = {
  project: "Cedar Ridge Solar + Storage",
  capacity_mw: 120,
  iso: "MISO",
  utility: "AES Indiana",
  poi: "AES Indiana — Cedar Ridge 138 kV",
  state: "IN",
};

function demoScenario(ctx = state.demoCtx) {
  const s = { ...DEMO_SCENARIO_FALLBACK, ...(ctx?.scenario || {}) };
  for (const key of Object.keys(DEMO_SCENARIO_FALLBACK)) {
    if (s[key] == null || String(s[key]).trim() === "") {
      s[key] = DEMO_SCENARIO_FALLBACK[key];
    }
  }
  return s;
}

async function refreshDemoCtx() {
  if (!state.me?.is_demo) {
    state.demoCtx = null;
    return null;
  }
  try {
    const next = await api.demoContext();
    const sessionAudit = state.lastAuditId || loadOnboard().lastAuditId || null;
    // Keep last-good scenario fields across toast re-renders / transient API blips.
    // Do not let a prior account audit leak into the wizard until this session runs one.
    state.demoCtx = {
      ...(state.demoCtx || {}),
      ...next,
      scenario: demoScenario(next),
      latest_audit_id: sessionAudit || null,
      latest_audit_status: sessionAudit ? next.latest_audit_status : null,
      readiness_score: sessionAudit ? next.readiness_score : null,
      open_blocking: sessionAudit ? next.open_blocking : null,
      can_file: sessionAudit ? next.can_file : false,
    };
    return state.demoCtx;
  } catch {
    return state.demoCtx;
  }
}

function demoChipHtml() {
  if (!state.me?.is_demo || loadOnboard().completed || route().name === "onboarding") return "";
  const step = Math.min(getWizardStep(), WIZARD_LAST);
  return `
  <div class="${panel} mb-4 flex flex-wrap items-center justify-between gap-3 px-4 py-3">
    <div>
      <strong class="block text-[13px] tracking-tightish">Guided demo</strong>
      <span class="text-[12px] text-muted">Step ${step} of ${WIZARD_LAST} · ${esc(WIZARD_META[step - 1]?.label || "")}</span>
    </div>
    <a class="${button("primary", "sm")}" href="#/onboarding">Continue setup</a>
  </div>`;
}

function shell(title, bodyHtml, { showChip = true } = {}) {
  const org = state.me?.org;
  const user = state.me?.user;
  const r = route().name;
  const nav = [
    ...(state.me?.is_demo ? [["onboarding", "Demo setup"]] : []),
    ["dashboard", "Dashboard"],
    ["projects", "Projects"],
    ["audits", "Audits"],
    ["billing", "Billing"],
  ];
  const chip = showChip ? demoChipHtml() : "";

  return `
  <div class="flex min-h-screen bg-canvas">
    <aside class="flex w-[220px] shrink-0 flex-col border-r border-line bg-soft">
      <div class="flex items-center gap-2.5 border-b border-line px-4 py-4">
        <img src="/assets/img/logo.svg" alt="" class="h-7 w-7" />
        <div>
          <div class="text-[14px] tracking-tightish">GridPilot</div>
          <div class="font-mono text-[10px] uppercase tracking-[0.1em] text-muted">Interconnection</div>
        </div>
      </div>
      <nav class="flex flex-col gap-0.5 p-2">
        ${nav
          .map(([k, label]) => {
            const active =
              r === k ||
              (k === "projects" && r === "project") ||
              (k === "audits" && r === "audit");
            return `<a href="#/${k}" class="rounded-input px-3 py-2 text-[13px] ${
              active ? "bg-surface text-ink" : "text-muted hover:bg-surface hover:text-ink"
            }">${label}</a>`;
          })
          .join("")}
      </nav>
      <div class="mt-auto border-t border-line p-4 text-[12px] text-muted">
        <strong class="mb-1 block text-[13px] text-ink">${esc(org?.name || "")}</strong>
        <span class="rounded-pill border border-line px-2 py-0.5 font-mono text-[10px] uppercase tracking-[0.08em]">${esc(org?.plan || "free")}</span>
        ${state.me?.is_demo ? `<span class="ml-1 rounded-pill border border-line px-2 py-0.5 font-mono text-[10px] uppercase tracking-[0.08em]">Demo</span>` : ""}
        <div class="mt-2">${esc(org?.audits_used_period ?? 0)} / ${esc(org?.audit_limit ?? 0)} audits</div>
      </div>
    </aside>
    <div class="flex min-w-0 flex-1 flex-col">
      <header class="sticky top-0 z-10 flex h-14 items-center justify-between border-b border-line bg-canvas/90 px-5 backdrop-blur">
        <h2 class="text-[16px] tracking-tightish">${esc(title)}</h2>
        <div class="text-[13px] text-muted">${esc(user?.name || "")} · <a href="#" id="logout-link" class="text-ink underline-offset-2 hover:underline">Sign out</a></div>
      </header>
      <div class="p-5">${chip}${bodyHtml}</div>
    </div>
  </div>
  ${
    state.toast
      ? `<div class="fixed bottom-4 right-4 z-30 rounded-pill bg-primary px-4 py-2 font-mono text-[12px] uppercase tracking-[0.08em] text-primary-fg">${esc(state.toast)}</div>`
      : ""
  }
  ${state.modal || ""}`;
}

function bindShell() {
  document.getElementById("logout-link")?.addEventListener("click", async (e) => {
    e.preventDefault();
    await api.logout();
    state.me = null;
    state.demoCtx = null;
    navigate("login");
  });
  bindDrawerTriggers();
}

/* ---------- Preview drawer (slide-over, replaces new-tab previews) ---------- */
function closeDrawer() {
  const rootEl = document.getElementById("gp-drawer");
  if (!rootEl) return;
  rootEl.querySelector(".gp-drawer-panel")?.classList.add("closing");
  rootEl.querySelector(".gp-drawer-backdrop")?.classList.add("closing");
  window.setTimeout(() => rootEl.remove(), 190);
}

function openDrawer({ title, file, url, downloadUrl, html }) {
  document.getElementById("gp-drawer")?.remove();
  const el = document.createElement("div");
  el.id = "gp-drawer";
  el.className = "fixed inset-0 z-50";
  el.innerHTML = `
    <div class="gp-drawer-backdrop absolute inset-0 bg-ink/40" data-drawer-dismiss></div>
    <aside class="gp-drawer-panel absolute inset-y-0 right-0 flex w-full flex-col border-l border-line bg-canvas shadow-2xl sm:w-[min(880px,92vw)]" role="dialog" aria-label="Preview">
      <div class="flex items-center justify-between gap-3 border-b border-line bg-soft px-5 py-3">
        <div class="min-w-0">
          <strong class="block truncate text-[14px] tracking-tightish">${esc(title || "Preview")}</strong>
          ${file ? `<span class="block truncate font-mono text-[11px] text-muted">${esc(file)}</span>` : ""}
        </div>
        <div class="flex shrink-0 gap-2">
          ${url ? `<a class="${button("ghost", "sm")}" href="${esc(url)}" target="_blank" rel="noopener">Open in tab</a>` : ""}
          ${downloadUrl ? `<a class="${button("ghost", "sm")}" href="${esc(downloadUrl)}">Download</a>` : ""}
          <button type="button" class="${button("primary", "sm")}" data-drawer-dismiss>Close</button>
        </div>
      </div>
      ${
        url
          ? `<iframe class="min-h-0 w-full flex-1 bg-white" src="${esc(url)}" title="Preview"></iframe>`
          : `<div class="min-h-0 flex-1 overflow-auto p-6">${html || ""}</div>`
      }
    </aside>`;
  el.querySelectorAll("[data-drawer-dismiss]").forEach((n) => n.addEventListener("click", closeDrawer));
  document.body.appendChild(el);
}

document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") closeDrawer();
});
window.addEventListener("hashchange", closeDrawer);

function bindDrawerTriggers() {
  document.querySelectorAll("[data-drawer-url]").forEach((btn) => {
    btn.addEventListener("click", () => {
      openDrawer({
        title: btn.getAttribute("data-drawer-title") || "Preview",
        file: btn.getAttribute("data-drawer-file") || "",
        url: btn.getAttribute("data-drawer-url"),
        downloadUrl: btn.getAttribute("data-drawer-download") || "",
      });
    });
  });
}

function wizardStepperHtml(active) {
  return `
  <ol class="mb-6 flex items-start justify-between gap-1">
    ${WIZARD_META.map((s, idx) => {
      const done = active > s.n;
      const current = active === s.n;
      return `
      <li class="flex min-w-0 flex-1 items-start">
        <button type="button" data-goto="${s.n}" class="w-full text-center disabled:opacity-40" ${active < s.n && !done ? "disabled" : ""}>
          <span class="mx-auto mb-1.5 flex h-7 w-7 items-center justify-center rounded-full border text-[11px] font-mono ${
            current
              ? "border-ink bg-ink text-primary-fg"
              : done
                ? "border-ok/40 bg-ok-soft text-ok"
                : "border-line bg-surface text-muted"
          }">${done ? "✓" : s.n}</span>
          <span class="hidden text-[11px] font-mono uppercase tracking-[0.08em] sm:block ${current ? "text-ink" : "text-muted"}">${esc(s.label)}</span>
        </button>
        ${idx < WIZARD_META.length - 1 ? `<span class="mt-3.5 h-px min-w-[8px] flex-1 bg-line"></span>` : ""}
      </li>`;
    }).join("")}
  </ol>`;
}

/* ---------- Demo entry ---------- */
async function renderDemo() {
  let info;
  try {
    info = await api.demoInfo();
  } catch (err) {
    root.innerHTML = `<div class="grid min-h-screen place-items-center p-6"><div class="${panel} max-w-md p-6"><h1 class="mb-2 text-xl">Demo unavailable</h1><p class="text-danger">${esc(err.message)}</p></div></div>`;
    return;
  }
  const s = CAISO_SCENARIO;
  root.innerHTML = `
  <div class="grid min-h-screen place-items-center bg-canvas p-6">
    <div class="${panel} w-full max-w-lg p-8">
      <p class="mb-3 font-mono text-[12px] uppercase tracking-[0.12em] text-muted">Product demo · CAISO interconnection request</p>
      <h1 class="mb-3 text-3xl tracking-tightish">Interconnection request packet generation</h1>
      <p class="mb-6 text-[15px] leading-relaxed text-muted">
        This walkthrough prepares a complete CAISO submission packet for an example project.
        The scope a consulting firm typically delivers in <strong class="text-ink">2–4 weeks for ~$10,000</strong>
        — PSLF models, drawings, forms, and QC — is generated in minutes from the same kickoff inputs.
      </p>
      <div class="mb-4 overflow-hidden rounded-card border border-line">
        <div class="flex justify-between gap-3 border-b border-line px-3 py-2.5 text-[13px]"><span class="text-muted">Applicant</span><strong>${esc(s.company)}</strong></div>
        <div class="flex justify-between gap-3 border-b border-line px-3 py-2.5 text-[13px]"><span class="text-muted">Project</span><strong class="text-right">${esc(s.project)} · ${esc(s.type)}</strong></div>
        <div class="flex justify-between gap-3 border-b border-line px-3 py-2.5 text-[13px]"><span class="text-muted">POI</span><strong class="text-right">${esc(s.poi)}</strong></div>
        <div class="flex justify-between gap-3 border-b border-line px-3 py-2.5 text-[13px]"><span class="text-muted">Track</span><strong class="text-right">${esc(s.track)} · COD ${esc(s.cod)}</strong></div>
        <div class="flex justify-between gap-3 px-3 py-2.5 text-[13px]"><span class="text-muted">Deliverable</span><strong class="text-right">Complete RIMS5 submission packet (15 documents)</strong></div>
      </div>
      <div class="mb-4 flex flex-wrap gap-x-4 gap-y-1 text-[12px]">
        <a class="text-ink underline-offset-2 hover:underline" href="https://www.caiso.com/library/interconnection-request-technical-data-forms" target="_blank" rel="noopener">CAISO IR technical data forms</a>
        <a class="text-ink underline-offset-2 hover:underline" href="https://rimspub.caiso.com/rims5/logon.do" target="_blank" rel="noopener">RIMS5 portal</a>
      </div>
      <div class="mb-5 rounded-card border border-line bg-soft px-4 py-3 text-[13px]">
        <strong>Demo sign-in</strong>
        <div class="mt-1.5 text-muted">Email <code class="rounded border border-line bg-surface px-1.5 py-0.5 font-mono text-[12px] text-ink">${esc(info.email)}</code>
        · Password <code class="rounded border border-line bg-surface px-1.5 py-0.5 font-mono text-[12px] text-ink">${esc(info.password)}</code></div>
      </div>
      <div class="flex flex-wrap gap-2">
        <button type="button" class="${button("primary")}" id="start-demo-btn">Start demo</button>
        <a class="${button("ghost")}" href="#/login">Sign in instead</a>
      </div>
      <p class="mt-3 font-mono text-[12px] text-muted" id="demo-start-status"></p>
      <p class="mt-6 text-[12px] text-muted"><a href="/" class="text-ink hover:underline">← Product overview</a></p>
    </div>
  </div>`;

  document.getElementById("start-demo-btn")?.addEventListener("click", async () => {
    const status = document.getElementById("demo-start-status");
    const btn = document.getElementById("start-demo-btn");
    btn.disabled = true;
    status.textContent = "Setting up your demo workspace…";
    try {
      const res = await api.startDemo();
      state.me = { user: res.user, org: res.org, is_demo: true };
      state.lastAuditId = null;
      state.genUi = null;
      state.packet = null;
      state.validation = null;
      state.extractUi = null;
      state.demoCtx = { is_demo: true, ...res, scenario: demoScenario(res) };
      clearOnboard();
      clearIntake();
      clearExtract();
      setWizardStep(1);
      navigate("onboarding");
      refreshDemoCtx().catch(() => {});
    } catch (err) {
      status.textContent = err.message;
      btn.disabled = false;
    }
  });
}

/* ---------- Wizard (CAISO IR packet: scenario → documents → intake → validate → generate → packet) ---------- */
function paintOnboarding(step) {
  root.innerHTML = shell(
    "Guided demo",
    `<div class="mx-auto max-w-4xl">
      ${wizardStepperHtml(Math.min(step, WIZARD_LAST))}
      <div class="${panel} flex min-h-[420px] flex-col overflow-hidden">
        ${renderWizardStep(step)}
      </div>
    </div>`,
    { showChip: false }
  );
  bindShell();
  bindWizard(step);
}

/** Sync paint for the generation animation — never await network first. */
function paintGenRunningNow() {
  setWizardStep(5);
  paintOnboarding(5);
}

async function ensureCaisoSchema() {
  if (state.caisoSchema) return state.caisoSchema;
  state.caisoSchema = await api.caisoIntake();
  return state.caisoSchema;
}

async function renderOnboarding() {
  const me = await ensureAuth();
  if (!me) return;
  if (!me.is_demo) return navigate("dashboard");

  // While generation or extraction is running, paint immediately — no network awaits first.
  if (state.genUi?.running) {
    paintGenRunningNow();
    return;
  }
  if (state.extractUi?.running) {
    paintOnboarding(2);
    return;
  }

  try {
    await ensureCaisoSchema();
  } catch (err) {
    root.innerHTML = shell(
      "Guided demo",
      `<div class="${panel} max-w-md p-6"><h2 class="mb-2 text-lg">Demo unavailable</h2><p class="text-danger">${esc(err.message)}</p></div>`
    );
    bindShell();
    return;
  }

  let step = getWizardStep();

  // Step 4 needs a fresh validation of the current intake.
  if (step === 4) {
    try {
      state.validation = await api.caisoValidate(loadIntake());
    } catch {
      state.validation = null;
    }
    if (state.genUi?.running) {
      paintGenRunningNow();
      return;
    }
  }

  // Step 6 needs the packet manifest; packets are ephemeral on serverless.
  if (step >= 6 && !state.packet) {
    const pid = loadOnboard().packetId;
    if (pid) {
      try {
        state.packet = await api.caisoPacket(pid, loadOnboard().packetD);
      } catch {
        state.packet = null;
      }
    }
  }
  if (step === 5 && !state.genUi?.running && state.packet) {
    step = 6;
    setWizardStep(6);
  }

  paintOnboarding(step);
}

function fmtBytes(n) {
  if (!Number.isFinite(n) || n <= 0) return "";
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(0)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

// Corrected example files the demo provides for one-click fixes on red validation
// items. Each seeded defect lives in its own document, so each corrected revision
// clears exactly one finding. No "example" flag → extraction returns corrected values.
const FIX_EXAMPLES = {
  file_technical: {
    meta: { name: "Ravenwood_TechnicalData_Workbook_v2_CORRECTED.xlsx", size: 88_410 },
    label: "Use corrected example file",
  },
  file_bess: {
    meta: { name: "Ravenwood_BESS_Spec_Megapack2XL_v2_CORRECTED.xlsx", size: 54_890 },
    label: "Use corrected example file",
  },
  file_dyd: {
    meta: { name: "Sungrow_SG4400UD_PSLF_Models.dyd", size: 18_240 },
    label: "Use example vendor file",
  },
};

/** The example file the demo can apply as a fix for this upload slot, if any. */
function fixExampleMeta(key) {
  const fix = FIX_EXAMPLES[key];
  if (fix) return { ...fix.meta, label: fix.label };
  const dflt = state.caisoSchema?.defaults?.[key];
  if (dflt && typeof dflt === "object" && dflt.name) {
    return { ...dflt, label: "Use example file" };
  }
  return null;
}

/** Simulated upload: progress in the widget, then the file lands staged
 *  (uploaded, not yet submitted). `meta` may carry example/other flags. */
function startSimulatedUpload(key, meta, repaint) {
  state.uploadUi[key] = { name: meta.name, size: meta.size, meta, startedAt: Date.now() };
  repaint();
  const tick = window.setInterval(() => {
    const ui = state.uploadUi[key];
    if (!ui) {
      window.clearInterval(tick);
      return;
    }
    if (Date.now() - ui.startedAt >= UPLOAD_MS) {
      window.clearInterval(tick);
      delete state.uploadUi[key];
      const values = loadIntake();
      values[key] = { ...ui.meta, staged: true };
      saveIntake(values);
      toast(`${ui.name} uploaded — review, then submit`);
    }
    repaint();
  }, 180);
}

/** Attach a file (picked or example) to an upload slot, then re-extract and
 *  revalidate — with staged progress shown inside the validation card itself. */
async function applyValidationFix(key, meta) {
  if (state.fixUi) return;
  const values = loadIntake();
  values[key] = meta;
  saveIntake(values);
  state.fixUi = { key, file: meta.name, stage: 0, startedAt: Date.now() };
  paintOnboarding(4);

  const tick = window.setInterval(() => {
    const ui = state.fixUi;
    if (!ui) {
      window.clearInterval(tick);
      return;
    }
    const elapsed = Date.now() - ui.startedAt;
    let stage = 0;
    for (let i = 0; i < FIX_STAGES.length; i++) {
      if (elapsed >= FIX_STAGES[i].at) stage = i;
    }
    if (stage !== ui.stage) {
      ui.stage = stage;
      if (route().name === "onboarding" && getWizardStep() === 4) paintOnboarding(4);
    }
  }, 160);

  try {
    const intake = loadIntake();
    const extractCall = api.caisoExtract({
      file_site_control: intake.file_site_control,
      file_technical: intake.file_technical,
      file_bess: intake.file_bess,
      file_signatory: intake.file_signatory,
      file_dyd: intake.file_dyd,
      file_boundary: intake.file_boundary,
    });
    const waitMin = new Promise((r) => setTimeout(r, FIX_MIN_MS));
    const [res] = await Promise.all([extractCall, waitMin]);
    saveIntake({ ...loadIntake(), ...(res.fields || {}) });
    saveExtract(res.provenance || {});
    state.validation = await api.caisoValidate(loadIntake());
    window.clearInterval(tick);
    state.fixUi = null;
    toast(`Re-extracted from ${meta.name} — revalidated`);
    paintOnboarding(4);
  } catch (err) {
    window.clearInterval(tick);
    state.fixUi = null;
    toast(err.message);
    paintOnboarding(4);
  }
}

/** Server-rendered kickoff-document preview, carrying current intake values and highlights. */
function kickoffPreviewUrl(key, { hl = [], file = null } = {}) {
  const params = new URLSearchParams();
  for (const [k, v] of Object.entries(loadIntake())) {
    if (v == null || typeof v === "object") continue;
    params.set(k, String(v));
  }
  if (hl.length) params.set("hl", hl.join(","));
  if (file) params.set("file", file);
  return `/api/caiso/kickoff/${encodeURIComponent(key)}/preview?${params.toString()}`;
}

function intakeFieldHtml(f, values, prov = null, errs = null) {
  const val = values[f.key] ?? "";
  const req = f.required ? `<span class="text-danger">*</span>` : "";
  const fieldErr = errs?.[f.key] || null;
  const errRing = fieldErr ? " border-danger ring-1 ring-danger/40" : "";
  const errNote = fieldErr
    ? `<p class="mt-1 flex items-start gap-1 text-[11.5px] leading-snug text-danger">
         <span class="mt-px shrink-0 font-mono">✕</span><span>${esc(fieldErr)}</span>
       </p>`
    : "";
  const provNote = prov?.[f.key]
    ? `<p class="mt-1 flex items-start gap-1 text-[11px] leading-snug text-focus">
         <span class="mt-px shrink-0 rounded-pill border border-focus/30 bg-info-soft px-1.5 font-mono text-[9px] uppercase tracking-[0.06em]">AI</span>
         <span>Extracted from ${esc(prov[f.key].file)} — review before validating</span>
       </p>`
    : "";
  if (f.type === "file") {
    const file = val && typeof val === "object" && val.name ? val : null;
    const uploading = state.uploadUi?.[f.key] || null;
    let body;
    if (uploading) {
      // Simulated upload in progress.
      const pct = Math.min(100, Math.round(((Date.now() - uploading.startedAt) / UPLOAD_MS) * 100));
      body = `
        <div class="min-w-0 flex-1">
          <div class="flex items-center gap-2.5">
            <div class="gp-spin h-3.5 w-3.5 shrink-0 rounded-full border-2 border-focus/30 border-t-focus"></div>
            <p class="truncate text-[13px] text-ink" title="${esc(uploading.name)}">${esc(uploading.name)}</p>
            <span class="ml-auto font-mono text-[11px] text-muted">${pct}%</span>
          </div>
          <div class="mt-2 h-1 overflow-hidden rounded-pill bg-line"><div class="h-full rounded-pill bg-focus" style="width:${pct}%"></div></div>
          <p class="mt-1 font-mono text-[11px] text-muted">Uploading…</p>
        </div>`;
    } else if (file) {
      const staged = !!file.staged;
      const statusChip = staged
        ? `<span class="rounded-pill border border-warn/40 bg-warn-soft px-1.5 font-mono text-[9px] uppercase tracking-[0.06em]">Uploaded — not submitted</span>`
        : `<span class="rounded-pill border border-ok/30 bg-ok-soft px-1.5 font-mono text-[9px] uppercase tracking-[0.06em] text-ok">Submitted</span>`;
      body = `
        <div class="flex min-w-0 flex-1 items-center gap-2.5">
           <span class="grid h-8 w-8 shrink-0 place-items-center rounded-card border border-line bg-white font-mono text-[10px] uppercase text-muted">${esc((file.name.split(".").pop() || "doc").slice(0, 4))}</span>
           <div class="min-w-0">
             <p class="flex items-center gap-2 truncate text-[13px] text-ink" title="${esc(file.name)}"><span class="truncate">${esc(file.name)}</span>${statusChip}</p>
             <p class="font-mono text-[11px] text-muted">${esc(fmtBytes(file.size))}${file.example ? " · example file" : ""}</p>
           </div>
         </div>
         <div class="flex shrink-0 flex-wrap justify-end gap-1.5">
           <button type="button" class="${button("ghost", "sm")}" data-file-preview="${esc(f.key)}" data-file-preview-label="${esc(f.label)}">Preview</button>
           ${staged ? `<button type="button" class="${button("primary", "sm")}" data-file-submit="${esc(f.key)}">Submit</button>` : `<button type="button" class="${button("ghost", "sm")}" data-file-attach="${esc(f.key)}">Replace</button>`}
           <button type="button" class="${button("ghost", "sm")}" data-file-remove="${esc(f.key)}">Remove</button>
         </div>`;
    } else {
      body = `<span class="flex-1 text-[13px] text-muted">No file attached</span>
         <button type="button" class="${button("ghost", "sm")}" data-file-attach="${esc(f.key)}">Choose file</button>`;
    }
    const boxTone = uploading
      ? "border-focus/30 bg-info-soft"
      : file?.staged
        ? "border-warn/40 bg-warn-soft/40"
        : file
          ? "border-line bg-soft"
          : f.required
            ? "border-danger/40 bg-danger-soft/40"
            : "border-line bg-soft";
    return `
      <div>
        <label class="${label}">${esc(f.label)} ${req}</label>
        <div class="flex items-center gap-3 rounded-card border border-dashed ${boxTone} px-3 py-2.5">
          ${body}
          <input type="file" class="hidden" data-file-input="${esc(f.key)}" ${f.accept ? `accept="${esc(f.accept)}"` : ""} />
        </div>
        ${f.hint ? `<p class="mt-1 text-[11px] leading-snug text-muted">${esc(f.hint)}</p>` : ""}
      </div>`;
  }
  let control;
  if (f.type === "select") {
    control = `<select class="${field}${errRing}" data-intake="${esc(f.key)}">
      ${(f.options || [])
        .map((o) => `<option value="${esc(o)}" ${String(val) === o ? "selected" : ""}>${esc(o)}</option>`)
        .join("")}
    </select>`;
  } else {
    control = `<input class="${field}${errRing}" data-intake="${esc(f.key)}" type="${f.type === "number" ? "number" : "text"}" ${f.type === "number" ? 'step="any"' : ""} value="${esc(val)}" />`;
  }
  return `
    <div${fieldErr ? ` data-field-error="${esc(f.key)}"` : ""}>
      <label class="${label}">${esc(f.label)} ${req}</label>
      ${control}
      ${errNote}
      ${provNote}
      ${f.hint ? `<p class="mt-1 text-[11px] leading-snug text-muted">${esc(f.hint)}</p>` : ""}
    </div>`;
}

const PACKET_CATEGORIES = [
  ["application", "Application forms"],
  ["models", "Power system models"],
  ["simulations", "PSLF simulation plots"],
  ["drawings", "Drawings & GIS"],
  ["legal", "Legal & site documents"],
  ["reference", "Reference"],
];

/** base64url-encode the intake so packet URLs are self-contained.
 *  Serverless instances don't share storage; the server regenerates the packet
 *  from this parameter when it doesn't have the files locally. */
function encodeIntakeParam(intake) {
  try {
    const json = JSON.stringify(intake);
    const bytes = new TextEncoder().encode(json);
    let bin = "";
    bytes.forEach((b) => { bin += String.fromCharCode(b); });
    return btoa(bin).replaceAll("+", "-").replaceAll("/", "_").replace(/=+$/, "");
  } catch {
    return "";
  }
}

/** Query string carrying the intake behind the current packet (may be empty). */
function packetQS() {
  const d = loadOnboard().packetD;
  return d ? `?d=${d}` : "";
}

function packetDocRowHtml(pid, doc, qs = null) {
  const q = qs == null ? packetQS() : qs;
  const ok = doc.status === "generated";
  const chip = ok
    ? `<span class="rounded-pill border border-ok/30 bg-ok-soft px-2 py-0.5 font-mono text-[10px] uppercase tracking-[0.06em] text-ok">${esc(doc.status_label)}</span>`
    : `<span class="rounded-pill border border-warn/30 bg-warn-soft px-2 py-0.5 font-mono text-[10px] uppercase tracking-[0.06em]">${esc(doc.status_label)}</span>`;
  return `
    <article class="flex flex-wrap items-start justify-between gap-3 rounded-card border border-line p-3.5">
      <div class="min-w-0 flex-1">
        <div class="flex flex-wrap items-center gap-2">
          <strong class="text-[14px] tracking-tightish">${esc(doc.title)}</strong>
          ${chip}
        </div>
        <p class="mt-0.5 font-mono text-[11px] text-muted">${esc(doc.file)}</p>
        ${doc.note ? `<p class="mt-1 text-[12px] text-muted">${esc(doc.note)}</p>` : ""}
      </div>
      <button type="button" class="${button("ghost", "sm")}"
        data-drawer-url="/api/caiso/packets/${esc(pid)}/preview/${encodeURIComponent(doc.file)}${q}"
        data-drawer-download="/api/caiso/packets/${esc(pid)}/files/${encodeURIComponent(doc.file)}${q}"
        data-drawer-title="${esc(doc.title)}" data-drawer-file="${esc(doc.file)}">Preview</button>
    </article>`;
}

function renderWizardStep(step) {
  const footer = (left, right) => `
    <div class="flex items-center justify-between gap-3 border-t border-line bg-soft px-6 py-3.5">
      <div>${left || ""}</div>
      <div class="flex flex-wrap justify-end gap-2">${right || ""}</div>
    </div>`;
  const s = CAISO_SCENARIO;

  if (step > WIZARD_LAST || loadOnboard().completed) {
    const p = state.packet;
    return `
      <div class="flex-1 p-7">
        <p class="mb-2 font-mono text-[12px] uppercase tracking-[0.12em] text-muted">Complete</p>
        <h2 class="mb-3 text-2xl tracking-tightish">Submission packet complete</h2>
        <p class="mb-6 max-w-xl text-[15px] leading-relaxed text-muted">
          The full workflow — document upload, AI extraction, intake, validation, generation, and packet review — is complete.
          The workspace also provides pre-filing SLD audits for uploaded drawings.
        </p>
        <div class="grid gap-3 sm:grid-cols-3">
          <div class="rounded-card border border-line bg-soft p-4"><span class="font-mono text-[11px] uppercase tracking-[0.08em] text-muted">Project</span><strong class="mt-1 block text-[14px]">${esc(p?.project_name || s.project)}</strong></div>
          <div class="rounded-card border border-line bg-soft p-4"><span class="font-mono text-[11px] uppercase tracking-[0.08em] text-muted">Documents</span><strong class="mt-1 block text-[14px]">${esc(p?.documents?.length ?? "15")} generated</strong></div>
          <div class="rounded-card border border-line bg-soft p-4"><span class="font-mono text-[11px] uppercase tracking-[0.08em] text-muted">Next step</span><strong class="mt-1 block text-[14px]">Submit via RIMS5</strong></div>
        </div>
      </div>
      ${footer(
        `<button type="button" class="${button("ghost", "sm")}" id="wiz-reset">Restart demo</button>`,
        `${p ? `<a class="${button("ghost")}" href="/api/caiso/packets/${esc(p.id)}/files/${encodeURIComponent(p.zip_file)}${packetQS()}">Download packet (.zip)</a>` : ""}
         <a class="${button("primary")}" href="#/dashboard">Open workspace</a>`
      )}`;
  }

  if (step === 1) {
    return `
      <div class="flex-1 p-7">
        <p class="mb-2 font-mono text-[12px] uppercase tracking-[0.12em] text-muted">Step 1 of ${WIZARD_LAST}</p>
        <h2 class="mb-3 text-2xl tracking-tightish">Project scenario</h2>
        <p class="mb-4 max-w-2xl text-[15px] leading-relaxed text-muted">
          <strong class="text-ink">${esc(s.company)}</strong> is developing <strong class="text-ink">${esc(s.project)}</strong>
          (${esc(s.type)}, ${esc(s.county)}) and requires a CAISO interconnection request under the
          <strong class="text-ink">${esc(s.track)}</strong> to support a ${esc(s.cod)} commercial operation date.
        </p>
        <p class="mb-5 max-w-2xl text-[14px] leading-relaxed text-muted">
          This preparation work is conventionally outsourced to a consulting firm at
          <strong class="text-ink">2–4 weeks and ~$10,000 per application</strong> — PSLF models, drawings,
          and CAISO forms. GridPilot performs the same workstream from the same kickoff inputs.
        </p>
        <div class="mb-5 grid gap-3 sm:grid-cols-2">
          <div class="rounded-card border border-line bg-soft p-4"><span class="font-mono text-[11px] uppercase tracking-[0.08em] text-muted">Project</span><strong class="mt-1 block">${esc(s.type)}</strong></div>
          <div class="rounded-card border border-line bg-soft p-4"><span class="font-mono text-[11px] uppercase tracking-[0.08em] text-muted">POI</span><strong class="mt-1 block">${esc(s.poi)}</strong></div>
          <div class="rounded-card border border-line bg-soft p-4"><span class="font-mono text-[11px] uppercase tracking-[0.08em] text-muted">Track</span><strong class="mt-1 block">${esc(s.track)} ($150k deposit)</strong></div>
          <div class="rounded-card border border-line bg-soft p-4"><span class="font-mono text-[11px] uppercase tracking-[0.08em] text-muted">Target COD</span><strong class="mt-1 block">${esc(s.cod)}</strong></div>
        </div>
        <div class="mb-3 grid gap-3 sm:grid-cols-2">
          <div class="rounded-card border border-line bg-soft px-4 py-3 text-[13px]">
            <strong class="mb-1 block text-ink">Generated by GridPilot (the consulting scope)</strong>
            <ul class="list-disc space-y-0.5 pl-4 text-muted">
              <li>Appendix 1 + Attachment A technical data</li>
              <li>Load flow (.epc) & dynamic (.dyd) models</li>
              <li>Reactive power curve, flat run / bump test plots</li>
              <li>Single-line diagram, site drawing, KMZ boundary</li>
              <li>ISP eligibility & legal document drafts, QC checklist</li>
            </ul>
          </div>
          <div class="rounded-card border border-line bg-soft px-4 py-3 text-[13px]">
            <strong class="mb-1 block text-ink">Remains with the developer (cannot be outsourced)</strong>
            <ul class="list-disc space-y-0.5 pl-4 text-muted">
              <li>Secretary of State certificate (official document)</li>
              <li>Executed site exclusivity agreement — LOIs are not accepted</li>
              <li>Vendor .dyd model files (obtained from the equipment vendor)</li>
              <li>Study deposit wire to CAISO</li>
              <li>Electronic signature in RIMS5</li>
            </ul>
          </div>
        </div>
      </div>
      ${footer(`<span class="text-[12px] text-muted">Estimated time: 3–5 minutes</span>`, `<button type="button" class="${button("primary")}" id="wiz-next">Upload documents</button>`)}`;
  }

  if (step === 2) {
    const docSection = (state.caisoSchema?.sections || []).find((sec) => sec.id === "documents");
    const values = loadIntake();
    const ui = state.extractUi;
    if (ui?.running) {
      const stageIdx = ui.stage ?? 0;
      const stageLabel = EXTRACT_STAGES[Math.min(stageIdx, EXTRACT_STAGES.length - 1)].label;
      return `
        <div class="flex-1 p-7">
          <p class="mb-2 font-mono text-[12px] uppercase tracking-[0.12em] text-muted">Step 2 of ${WIZARD_LAST}</p>
          <h2 class="mb-3 text-2xl tracking-tightish">Extracting data from the documents</h2>
          <p class="mb-5 max-w-2xl text-[15px] leading-relaxed text-muted">
            Key project data is being read from the uploaded documents and used to populate the intake form.
          </p>
          <div class="rounded-card border border-focus/20 bg-info-soft p-4">
            <div class="mb-3 flex gap-3">
              <div class="gp-spin mt-0.5 h-4 w-4 shrink-0 rounded-full border-2 border-focus/30 border-t-focus"></div>
              <div>
                <strong class="block text-ink">AI document extraction</strong>
                <p class="mt-1 font-mono text-[12px] text-muted">${esc(stageLabel)}</p>
              </div>
            </div>
            <div class="gp-audit-progress" aria-hidden="true"><span></span></div>
            <ol class="mt-3 space-y-1.5 font-mono text-[11px] uppercase tracking-[0.08em]">
              ${EXTRACT_STAGES.map((g, i) => {
                const active = i === stageIdx;
                const doneStep = i < stageIdx;
                return `<li class="${doneStep ? "text-ok" : active ? "text-ink" : "text-muted"}">${doneStep ? "✓" : active ? "●" : "○"} ${esc(g.label)}</li>`;
              }).join("")}
            </ol>
          </div>
        </div>
        ${footer("", `<button type="button" class="${button("primary")}" disabled>Extracting…</button>`)}`;
    }
    return `
      <div class="flex-1 p-7">
        <p class="mb-2 font-mono text-[12px] uppercase tracking-[0.12em] text-muted">Step 2 of ${WIZARD_LAST}</p>
        <h2 class="mb-3 text-2xl tracking-tightish">Kickoff documents</h2>
        <p class="mb-5 max-w-2xl text-[15px] leading-relaxed text-muted">
          The documents a consulting firm collects at the kickoff meeting. Example files for
          ${esc(s.project)} are already uploaded and awaiting submission — preview each document, then
          submit it to include it in the intake. Submitted documents are read by GridPilot to populate
          the intake form in the next step; every value remains editable there.
        </p>
        <div class="grid gap-x-4 gap-y-3">
          ${(docSection?.fields || []).map((f) => intakeFieldHtml(f, values)).join("")}
        </div>
      </div>
      ${footer(
        `<button type="button" class="${button("ghost")}" id="wiz-back">Back</button>`,
        `<button type="button" class="${button("primary")}" id="wiz-extract">Extract data & continue</button>`
      )}`;
  }

  if (step === 3) {
    const sections = (state.caisoSchema?.sections || []).filter((sec) => sec.id !== "documents");
    const values = loadIntake();
    const prov = loadExtract();
    // Returning from a failed validation: flag the failing fields inline.
    const errs = {};
    for (const e of state.validation?.errors || []) {
      if (e.field && !errs[e.field]) errs[e.field] = e.title;
    }
    const errCount = Object.keys(errs).length;
    return `
      <div class="flex-1 p-7">
        <p class="mb-2 font-mono text-[12px] uppercase tracking-[0.12em] text-muted">Step 3 of ${WIZARD_LAST}</p>
        <h2 class="mb-3 text-2xl tracking-tightish">Developer intake</h2>
        <p class="mb-5 max-w-2xl text-[15px] leading-relaxed text-muted">
          Fields marked <span class="rounded-pill border border-focus/30 bg-info-soft px-1.5 font-mono text-[10px] uppercase tracking-[0.06em] text-focus">AI</span>
          were populated from the uploaded documents; the remainder are standard kickoff inputs, pre-filled
          for ${esc(s.project)}. All fields are editable. Validation flags inconsistencies such as a MW
          chain that does not reconcile or a Letter of Intent offered as site control.
        </p>
        ${errCount ? `
        <div class="mb-5 max-w-2xl rounded-card border border-danger/30 bg-danger-soft p-4">
          <strong class="block text-danger">${errCount} blocking issue${errCount > 1 ? "s" : ""} from validation</strong>
          <p class="text-[13px] text-muted">The affected fields are flagged in red below. Correct them, then validate again.</p>
        </div>` : ""}
        <form id="intake-form" class="space-y-6">
          ${sections
            .map(
              (sec) => `
            <fieldset>
              <div class="mb-3 border-b border-line pb-2">
                <h3 class="text-[14px] tracking-tightish">${esc(sec.title)}</h3>
                ${sec.hint ? `<p class="text-[12px] text-muted">${esc(sec.hint)}</p>` : ""}
              </div>
              <div class="grid gap-x-4 gap-y-3 sm:grid-cols-2">
                ${sec.fields.map((f) => intakeFieldHtml(f, values, prov, errs)).join("")}
              </div>
            </fieldset>`
            )
            .join("")}
        </form>
      </div>
      ${footer(
        `<button type="button" class="${button("ghost")}" id="wiz-back">Back to documents</button>
         <button type="button" class="${button("ghost")}" id="wiz-intake-reset">Reset to example</button>`,
        `<button type="button" class="${button("primary")}" id="wiz-validate">Validate inputs</button>`
      )}`;
  }

  if (step === 4) {
    const v = state.validation;
    if (!v) {
      return `
        <div class="flex-1 p-7">
          <p class="mb-2 font-mono text-[12px] uppercase tracking-[0.12em] text-muted">Step 4 of ${WIZARD_LAST}</p>
          <h2 class="mb-3 text-2xl tracking-tightish">Kickoff data validation</h2>
          <div class="rounded-card border border-danger/30 bg-danger-soft p-4 text-[13px]">Could not reach the validation service. Check your connection and retry.</div>
        </div>
        ${footer(
          `<button type="button" class="${button("ghost")}" id="wiz-back">Back to intake</button>`,
          `<button type="button" class="${button("primary")}" id="wiz-revalidate">Retry validation</button>`
        )}`;
    }
    // Each check links its ground truth (the CAISO requirement) and the examined
    // document; red items additionally accept a corrected upload in place.
    const refButtons = (it, kind) => {
      const btns = [];
      if (it.rule) {
        btns.push(
          `<button type="button" class="${button("ghost", "sm")}"
             data-drawer-url="/api/caiso/requirements/${esc(it.rule.id)}/preview"
             data-drawer-title="ISO requirement — ${esc(it.rule.title)}"
             data-drawer-file="${esc(it.rule.source)}">Requirement</button>`
        );
      }
      if (it.evidence?.attached) {
        btns.push(
          `<button type="button" class="${button("ghost", "sm")}"
             data-drawer-url="${esc(kickoffPreviewUrl(it.evidence.key, { hl: it.evidence.hl || [], file: it.evidence.file }))}"
             data-drawer-title="Examined file"
             data-drawer-file="${esc(it.evidence.file)}">Examined file</button>`
        );
      }
      if (kind === "error" && it.evidence) {
        const fix = fixExampleMeta(it.evidence.key);
        btns.push(
          `<button type="button" class="${button("primary", "sm")}" data-fix-upload="${esc(it.evidence.key)}">
             ${it.evidence.attached ? "Upload corrected file" : "Attach file"}
           </button>
           <input type="file" class="hidden" data-fix-input="${esc(it.evidence.key)}" />
           ${fix ? `<button type="button" class="${button("ghost", "sm")}" data-fix-example="${esc(it.evidence.key)}" title="${esc(fix.name)}">${esc(fix.label)}</button>` : ""}`
        );
      }
      return btns.length ? `<div class="mt-2.5 flex flex-wrap items-center gap-1.5">${btns.join("")}</div>` : "";
    };
    // In-card progress while a corrected document is re-extracted and revalidated.
    const fixProgress = (fu) => `
      <div class="mt-2.5 rounded-card border border-focus/20 bg-info-soft px-3.5 py-2.5">
        <div class="flex items-center gap-2.5">
          <div class="gp-spin h-3.5 w-3.5 shrink-0 rounded-full border-2 border-focus/30 border-t-focus"></div>
          <span class="truncate font-mono text-[11px] text-ink">${esc(fu.file)}</span>
        </div>
        <ol class="mt-2 space-y-1 font-mono text-[10.5px] uppercase tracking-[0.07em]">
          ${FIX_STAGES.map((g, i) => {
            const active = i === (fu.stage ?? 0);
            const doneStep = i < (fu.stage ?? 0);
            return `<li class="${doneStep ? "text-ok" : active ? "text-ink" : "text-muted"}">${doneStep ? "✓" : active ? "●" : "○"} ${esc(g.label)}</li>`;
          }).join("")}
        </ol>
      </div>`;
    // In-card simulated upload progress (corrected document being uploaded).
    const uploadProgress = (up) => {
      const pct = Math.min(100, Math.round(((Date.now() - up.startedAt) / UPLOAD_MS) * 100));
      return `
      <div class="mt-2.5 rounded-card border border-focus/20 bg-info-soft px-3.5 py-2.5">
        <div class="flex items-center gap-2.5">
          <div class="gp-spin h-3.5 w-3.5 shrink-0 rounded-full border-2 border-focus/30 border-t-focus"></div>
          <span class="truncate font-mono text-[11px] text-ink">${esc(up.name)}</span>
          <span class="ml-auto font-mono text-[11px] text-muted">${pct}%</span>
        </div>
        <div class="mt-2 h-1 overflow-hidden rounded-pill bg-line"><div class="h-full rounded-pill bg-focus" style="width:${pct}%"></div></div>
        <p class="mt-1 font-mono text-[10.5px] uppercase tracking-[0.07em] text-muted">Uploading…</p>
      </div>`;
    };
    // Uploaded-but-not-submitted replacement: preview it, then submit to revalidate.
    const stagedRow = (it, meta) => `
      <div class="mt-2.5 rounded-card border border-warn/40 bg-warn-soft/60 px-3.5 py-2.5">
        <div class="flex flex-wrap items-center gap-2">
          <span class="truncate font-mono text-[11px] text-ink" title="${esc(meta.name)}">${esc(meta.name)}</span>
          <span class="rounded-pill border border-warn/40 bg-warn-soft px-1.5 font-mono text-[9px] uppercase tracking-[0.06em]">Uploaded — not submitted</span>
          <div class="ml-auto flex gap-1.5">
            <button type="button" class="${button("ghost", "sm")}"
              data-drawer-url="${esc(kickoffPreviewUrl(it.evidence.key, { hl: it.evidence.hl || [], file: meta.name }))}"
              data-drawer-title="Uploaded document — review before submitting"
              data-drawer-file="${esc(meta.name)}">Preview</button>
            <button type="button" class="${button("primary", "sm")}" data-fix-submit="${esc(it.evidence.key)}">Submit &amp; revalidate</button>
          </div>
        </div>
      </div>`;
    const intakeNow = loadIntake();
    const checkCard = (it) => {
      const kind = it.status || "ok";
      const tone =
        kind === "error"
          ? ["border-danger/30 bg-danger-soft", "text-danger", "✕"]
          : kind === "warn"
            ? ["border-warn/30 bg-warn-soft", "text-ink", "!"]
            : ["border-ok/20 bg-ok-soft", "text-ok", "✓"];
      const label =
        kind === "error" ? "Blocking" : kind === "warn" ? "Advisory" : "Passed";
      let action = refButtons(it, kind);
      if (kind === "error" && it.evidence) {
        const key = it.evidence.key;
        const meta = intakeNow[key];
        if (state.fixUi && key === state.fixUi.key) {
          action = fixProgress(state.fixUi);
        } else if (state.uploadUi?.[key]) {
          action = uploadProgress(state.uploadUi[key]);
        } else if (meta && typeof meta === "object" && meta.staged) {
          action = stagedRow(it, meta);
        }
      }
      return `
        <article class="rounded-card border ${tone[0]} p-3.5">
          <div class="flex items-start gap-2.5">
            <span class="mt-0.5 font-mono text-[12px] ${tone[1]}">${tone[2]}</span>
            <div class="min-w-0 flex-1">
              <div class="flex flex-wrap items-center gap-2">
                <strong class="text-[13.5px] tracking-tightish">${esc(it.title)}</strong>
                <span class="rounded-pill border px-1.5 font-mono text-[9px] uppercase tracking-[0.07em] ${kind === "error" ? "border-danger/30 text-danger" : kind === "warn" ? "border-warn/40 text-ink" : "border-ok/30 text-ok"}">${label}</span>
              </div>
              <p class="mt-0.5 text-[12.5px] leading-snug text-muted">${esc(it.detail)}</p>
              ${it.evidence && !it.evidence.attached ? `<p class="mt-1 font-mono text-[11px] text-muted">Examined file: none attached</p>` : ""}
              ${action}
            </div>
          </div>
        </article>`;
    };
    // Checks render in their canonical run order — a fixed item turns green in place.
    const checks =
      v.checks ||
      [...v.errors.map((it) => ({ ...it, status: "error" })),
       ...v.warnings.map((it) => ({ ...it, status: "warn" })),
       ...v.passed.map((it) => ({ ...it, status: "ok" }))];
    return `
      <div class="flex-1 p-7">
        <p class="mb-2 font-mono text-[12px] uppercase tracking-[0.12em] text-muted">Step 4 of ${WIZARD_LAST}</p>
        <h2 class="mb-3 text-2xl tracking-tightish">Kickoff data validation</h2>
        <p class="mb-4 max-w-2xl text-[15px] leading-relaxed text-muted">
          The intake is checked against the consistency rules that most commonly trigger CAISO deficiency
          review — the review a consulting firm performs during the first week of an engagement.
          Each check cites the CAISO requirement it enforces and the document it examined; both preview
          inline with the relevant part highlighted. Blocking items accept a corrected upload directly.
        </p>
        <div class="mb-4 rounded-card border p-4 ${v.ok ? "border-ok/30 bg-ok-soft" : "border-danger/30 bg-danger-soft"}">
          <strong class="block ${v.ok ? "text-ok" : "text-danger"}">${v.ok ? "Intake is clean — ready to generate" : "Blocking issues found"}</strong>
          <p class="text-[13px] text-muted">${esc(v.summary)}</p>
        </div>
        <div class="space-y-2.5">
          ${checks.map(checkCard).join("")}
        </div>
      </div>
      ${footer(
        `<button type="button" class="${button("ghost")}" id="wiz-back">Fix intake</button>`,
        v.ok
          ? `<button type="button" class="${button("primary")}" id="wiz-generate">Generate submission packet</button>`
          : `<button type="button" class="${button("primary")}" id="wiz-back-2">Fix intake to continue</button>`
      )}`;
  }

  if (step === 5) {
    const ui = state.genUi;
    if (ui?.running) {
      const stageIdx = ui.stage ?? 0;
      const stageLabel = GEN_STAGES[Math.min(stageIdx, GEN_STAGES.length - 1)].label;
      return `
        <div class="flex-1 p-7">
          <p class="mb-2 font-mono text-[12px] uppercase tracking-[0.12em] text-muted">Step 5 of ${WIZARD_LAST}</p>
          <h2 class="mb-3 text-2xl tracking-tightish">Generating the submission packet</h2>
          <p class="mb-5 max-w-2xl text-[15px] leading-relaxed text-muted">
            All fifteen packet documents are generated from the validated intake — work a consulting
            engagement typically spreads across several weeks.
          </p>
          <div class="rounded-card border border-focus/20 bg-info-soft p-4">
            <div class="mb-3 flex gap-3">
              <div class="gp-spin mt-0.5 h-4 w-4 shrink-0 rounded-full border-2 border-focus/30 border-t-focus"></div>
              <div>
                <strong class="block text-ink">Generating submission packet</strong>
                <p class="mt-1 font-mono text-[12px] text-muted">${esc(stageLabel)}</p>
              </div>
            </div>
            <div class="gp-audit-progress" aria-hidden="true"><span></span></div>
            <ol class="mt-3 space-y-1.5 font-mono text-[11px] uppercase tracking-[0.08em]">
              ${GEN_STAGES.map((g, i) => {
                const active = i === stageIdx;
                const doneStep = i < stageIdx;
                return `<li class="${doneStep ? "text-ok" : active ? "text-ink" : "text-muted"}">${doneStep ? "✓" : active ? "●" : "○"} ${esc(g.label)}</li>`;
              }).join("")}
            </ol>
          </div>
        </div>
        ${footer(`<span class="font-mono text-[12px] text-muted">Consulting equivalent: 2–4 weeks · ~$10k</span>`, `<button type="button" class="${button("primary")}" disabled>Generating…</button>`)}`;
    }
    return `
      <div class="flex-1 p-7">
        <p class="mb-2 font-mono text-[12px] uppercase tracking-[0.12em] text-muted">Step 5 of ${WIZARD_LAST}</p>
        <h2 class="mb-3 text-2xl tracking-tightish">Generate the submission packet</h2>
        <div class="rounded-card border border-line bg-soft p-4"><strong class="block">Ready to generate</strong><p class="text-[13px] text-muted">All 15 packet documents will be generated from the validated intake.</p></div>
      </div>
      ${footer(
        `<button type="button" class="${button("ghost")}" id="wiz-back">Back</button>`,
        `<button type="button" class="${button("primary")}" id="wiz-generate">Generate submission packet</button>`
      )}`;
  }

  // Step 6 — packet review & submission
  const p = state.packet;
  if (!p) {
    return `
      <div class="flex-1 p-7">
        <p class="mb-2 font-mono text-[12px] uppercase tracking-[0.12em] text-muted">Step 6 of ${WIZARD_LAST}</p>
        <h2 class="mb-3 text-2xl tracking-tightish">Packet expired</h2>
        <p class="mb-5 max-w-xl text-[15px] leading-relaxed text-muted">
          Generated packets are retained temporarily in the demo environment. The packet can be
          regenerated from the saved intake in a few seconds.
        </p>
      </div>
      ${footer(
        `<button type="button" class="${button("ghost")}" id="wiz-back">Back</button>`,
        `<button type="button" class="${button("primary")}" id="wiz-generate">Regenerate packet</button>`
      )}`;
  }
  const zipUrl = `/api/caiso/packets/${esc(p.id)}/files/${encodeURIComponent(p.zip_file)}${packetQS()}`;
  return `
    <div class="flex-1 p-7">
      <p class="mb-2 font-mono text-[12px] uppercase tracking-[0.12em] text-muted">Step 6 of ${WIZARD_LAST}</p>
      <h2 class="mb-3 text-2xl tracking-tightish">CAISO submission packet — ${esc(p.project_name)}</h2>
      <p class="mb-4 max-w-2xl text-[15px] leading-relaxed text-muted">
        ${esc(p.documents.length)} documents mapped to the CAISO ISP/Fast Track minimum-requirements checklist,
        generated from one intake so every value stays consistent.
      </p>
      <div class="mb-5 grid gap-3 sm:grid-cols-4">
        <div class="rounded-card border border-line bg-soft p-4"><span class="font-mono text-[11px] uppercase tracking-[0.08em] text-muted">Net at POI</span><strong class="mt-1 block">${esc(p.net_mw)} MW</strong></div>
        <div class="rounded-card border border-line bg-soft p-4"><span class="font-mono text-[11px] uppercase tracking-[0.08em] text-muted">POI</span><strong class="mt-1 block text-[13px]">${esc(p.poi)}</strong></div>
        <div class="rounded-card border border-line bg-soft p-4"><span class="font-mono text-[11px] uppercase tracking-[0.08em] text-muted">Track</span><strong class="mt-1 block text-[13px]">${esc(p.track)}</strong></div>
        <div class="rounded-card border border-line bg-soft p-4"><span class="font-mono text-[11px] uppercase tracking-[0.08em] text-muted">Deposit</span><strong class="mt-1 block text-[13px]">${esc(p.deposit)}</strong></div>
      </div>
      <div class="mb-5 rounded-card border border-ok/30 bg-ok-soft p-4">
        <strong class="mb-2 block text-ok">Consistency QC — passed</strong>
        <ul class="space-y-1 text-[13px] text-muted">
          ${p.consistency.map((c) => `<li><strong class="text-ink">${esc(c.title)}:</strong> ${esc(c.detail)}</li>`).join("")}
        </ul>
      </div>
      ${PACKET_CATEGORIES.map(([key, title]) => {
        const docs = p.documents.filter((doc) => doc.category === key);
        if (!docs.length) return "";
        return `
          <div class="mb-4">
            <h3 class="mb-2 font-mono text-[11px] uppercase tracking-[0.08em] text-muted">${esc(title)}</h3>
            <div class="space-y-2">${docs.map((doc) => packetDocRowHtml(p.id, doc)).join("")}</div>
          </div>`;
      }).join("")}
      <div class="mb-4 rounded-card border border-warn/30 bg-warn-soft p-4">
        <strong class="mb-2 block">Remaining developer actions</strong>
        <ol class="list-decimal space-y-1.5 pl-5 text-[13px] text-muted">
          ${p.actions.map((a) => `<li><strong class="text-ink">${esc(a.title)}.</strong> ${esc(a.detail)}</li>`).join("")}
        </ol>
      </div>
      <div class="rounded-card border border-line bg-soft px-4 py-3 text-[13px] text-muted">
        <strong class="mb-1 block text-ink">Submit</strong>
        Upload the packet and e-sign Appendix 1 in
        <a class="text-ink underline-offset-2 hover:underline" href="${esc(p.rims5_url)}" target="_blank" rel="noopener">RIMS5</a>.
        CAISO confirms acceptance within ~4 weeks and the project enters the queue.
        Official forms: <a class="text-ink underline-offset-2 hover:underline" href="${esc(p.caiso_forms_url)}" target="_blank" rel="noopener">caiso.com</a>.
      </div>
    </div>
    ${footer(
      `<button type="button" class="${button("ghost")}" id="wiz-back-2">Edit intake</button>
       <button type="button" class="${button("ghost")}" id="wiz-generate">Regenerate</button>`,
      `<a class="${button("ghost")}" href="${zipUrl}">Download packet (.zip)</a>
       <button type="button" class="${button("primary")}" id="wiz-finish">Finish demo</button>`
    )}`;
}

function collectIntakeForm() {
  const values = loadIntake();
  document.querySelectorAll("[data-intake]").forEach((el) => {
    const key = el.getAttribute("data-intake");
    if (el.type === "number") {
      values[key] = el.value === "" ? "" : Number(el.value);
    } else {
      values[key] = el.value;
    }
  });
  saveIntake(values);
  return values;
}

async function startWizardGeneration() {
  if (state.genUi?.running) return;
  const intake = loadIntake();
  state.genUi = { running: true, stage: 0, startedAt: Date.now() };
  state.packet = null;
  saveOnboard({ packetId: null });
  // Paint the animation in this same turn — before any network await.
  paintGenRunningNow();

  const tick = window.setInterval(() => {
    const ui = state.genUi;
    if (!ui?.running) {
      window.clearInterval(tick);
      return;
    }
    const elapsed = Date.now() - ui.startedAt;
    let stage = 0;
    for (let i = 0; i < GEN_STAGES.length; i++) {
      if (elapsed >= GEN_STAGES[i].at) stage = i;
    }
    if (stage !== ui.stage) {
      ui.stage = stage;
      if (route().name === "onboarding" && getWizardStep() === 5) {
        paintGenRunningNow();
      }
    }
  }, 160);

  try {
    const apiCall = api.caisoGenerate(intake);
    const waitMin = new Promise((r) => setTimeout(r, GEN_MIN_MS));
    const [res] = await Promise.all([apiCall, waitMin]);
    window.clearInterval(tick);
    state.genUi = null;

    if (!res?.ok) {
      state.validation = res?.validation || null;
      setWizardStep(4);
      toast("Intake has blocking issues — fix and retry");
      paintOnboarding(4);
      return;
    }
    state.packet = res.packet;
    saveOnboard({ packetId: res.packet.id, packetD: encodeIntakeParam(intake) });
    setWizardStep(6);
    toast(`Packet ready — ${res.packet.documents.length} documents`);
    paintOnboarding(6);
  } catch (err) {
    window.clearInterval(tick);
    state.genUi = null;
    toast(err.message);
    setWizardStep(4);
    await renderOnboarding();
  }
}

async function startExtraction() {
  if (state.extractUi?.running) return;
  state.extractUi = { running: true, stage: 0, startedAt: Date.now() };
  // Paint the animation in this same turn — before any network await.
  paintOnboarding(2);

  const tick = window.setInterval(() => {
    const ui = state.extractUi;
    if (!ui?.running) {
      window.clearInterval(tick);
      return;
    }
    const elapsed = Date.now() - ui.startedAt;
    let stage = 0;
    for (let i = 0; i < EXTRACT_STAGES.length; i++) {
      if (elapsed >= EXTRACT_STAGES[i].at) stage = i;
    }
    if (stage !== ui.stage) {
      ui.stage = stage;
      if (route().name === "onboarding" && getWizardStep() === 2) {
        paintOnboarding(2);
      }
    }
  }, 160);

  try {
    const intake = loadIntake();
    const files = {
      file_site_control: intake.file_site_control,
      file_technical: intake.file_technical,
      file_bess: intake.file_bess,
      file_signatory: intake.file_signatory,
      file_dyd: intake.file_dyd,
      file_boundary: intake.file_boundary,
    };
    const apiCall = api.caisoExtract(files);
    const waitMin = new Promise((r) => setTimeout(r, EXTRACT_MIN_MS));
    const [res] = await Promise.all([apiCall, waitMin]);
    window.clearInterval(tick);
    state.extractUi = null;
    state.validation = null;
    saveIntake({ ...loadIntake(), ...(res.fields || {}) });
    saveExtract(res.provenance || {});
    setWizardStep(3);
    toast(res.summary || "Extraction complete");
    paintOnboarding(3);
  } catch (err) {
    window.clearInterval(tick);
    state.extractUi = null;
    toast(err.message);
    paintOnboarding(2);
  }
}

function bindWizard(step) {
  document.querySelectorAll("[data-goto]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const n = Number(btn.getAttribute("data-goto"));
      if (n >= 1 && n <= step && !state.genUi?.running && !state.extractUi?.running && !state.fixUi) {
        setWizardStep(n);
        render();
      }
    });
  });
  document.getElementById("wiz-back")?.addEventListener("click", () => {
    setWizardStep(Math.max(1, step - 1));
    render();
  });
  document.getElementById("wiz-back-2")?.addEventListener("click", () => {
    setWizardStep(3);
    render();
  });
  document.getElementById("wiz-next")?.addEventListener("click", () => {
    setWizardStep(Math.min(WIZARD_LAST + 1, step + 1));
    render();
  });
  document.getElementById("wiz-extract")?.addEventListener("click", () => {
    const values = loadIntake();
    const staged = ["file_site_control", "file_technical", "file_bess", "file_signatory", "file_dyd", "file_boundary"]
      .filter((k) => values[k] && typeof values[k] === "object" && values[k].staged);
    if (staged.length) {
      toast(`${staged.length} uploaded document(s) awaiting submission — submit or remove them first`);
      return;
    }
    startExtraction();
  });
  document.getElementById("wiz-validate")?.addEventListener("click", () => {
    collectIntakeForm();
    state.validation = null;
    setWizardStep(4);
    render();
  });
  document.getElementById("wiz-revalidate")?.addEventListener("click", () => render());
  document.getElementById("wiz-intake-reset")?.addEventListener("click", () => {
    clearIntake();
    clearExtract();
    toast("Intake reset to the Ravenwood example");
    render();
  });
  document.getElementById("wiz-generate")?.addEventListener("click", () => startWizardGeneration());
  document.getElementById("wiz-finish")?.addEventListener("click", () => {
    saveOnboard({ completed: true, wizardStep: WIZARD_LAST + 1 });
    toast("Demo complete");
    navigate("dashboard");
  });
  document.getElementById("wiz-reset")?.addEventListener("click", () => {
    clearOnboard();
    clearIntake();
    clearExtract();
    state.packet = null;
    state.validation = null;
    setWizardStep(1);
    toast("Demo restarted");
    render();
  });
  // Persist form edits (Step 3) — survives refreshes and step hops.
  if (step === 3) {
    document.querySelectorAll("[data-intake]").forEach((el) => {
      el.addEventListener("change", () => collectIntakeForm());
    });
    // Returning from a failed validation: bring the first flagged field into view.
    document.querySelector("[data-field-error]")?.scrollIntoView({ block: "center", behavior: "smooth" });
  }
  // Step 4: red items accept a corrected document — upload lands staged in the card;
  // the user previews it, then submits to re-extract and revalidate in place.
  if (step === 4) {
    const repaint = () => paintOnboarding(4);
    document.querySelectorAll("[data-fix-upload]").forEach((btn) => {
      btn.addEventListener("click", () => {
        document.querySelector(`[data-fix-input="${btn.getAttribute("data-fix-upload")}"]`)?.click();
      });
    });
    document.querySelectorAll("[data-fix-input]").forEach((inp) => {
      inp.addEventListener("change", () => {
        const f = inp.files?.[0];
        if (!f) return;
        const key = inp.getAttribute("data-fix-input");
        sessionFiles[key] = f;
        startSimulatedUpload(key, { name: f.name, size: f.size }, repaint);
      });
    });
    document.querySelectorAll("[data-fix-example]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const key = btn.getAttribute("data-fix-example");
        const fix = fixExampleMeta(key);
        if (!fix) return;
        delete sessionFiles[key];
        const { label, ...meta } = fix;
        startSimulatedUpload(key, meta, repaint);
      });
    });
    document.querySelectorAll("[data-fix-submit]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const key = btn.getAttribute("data-fix-submit");
        const values = loadIntake();
        const meta = values[key];
        if (!meta || typeof meta !== "object") return;
        applyValidationFix(key, { ...meta, staged: false });
      });
    });
  }
  // File upload components live on Step 2 (kickoff documents).
  if (step === 2) {
    const repaint = () => {
      const y = window.scrollY;
      paintOnboarding(2);
      window.scrollTo(0, y);
    };
    document.querySelectorAll("[data-file-attach]").forEach((btn) => {
      btn.addEventListener("click", () => {
        document.querySelector(`[data-file-input="${btn.getAttribute("data-file-attach")}"]`)?.click();
      });
    });
    document.querySelectorAll("[data-file-input]").forEach((inp) => {
      inp.addEventListener("change", () => {
        const f = inp.files?.[0];
        if (!f) return;
        const key = inp.getAttribute("data-file-input");
        sessionFiles[key] = f;
        startSimulatedUpload(key, { name: f.name, size: f.size }, repaint);
      });
    });
    document.querySelectorAll("[data-file-submit]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const key = btn.getAttribute("data-file-submit");
        const values = loadIntake();
        const meta = values[key];
        if (!meta || typeof meta !== "object") return;
        values[key] = { ...meta, staged: false };
        saveIntake(values);
        toast(`${meta.name} submitted`);
        repaint();
      });
    });
    document.querySelectorAll("[data-file-remove]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const key = btn.getAttribute("data-file-remove");
        delete sessionFiles[key];
        delete state.uploadUi[key];
        const values = collectIntakeForm();
        values[key] = null;
        saveIntake(values);
        repaint();
      });
    });
    document.querySelectorAll("[data-file-preview]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const key = btn.getAttribute("data-file-preview");
        const title = btn.getAttribute("data-file-preview-label") || "Kickoff document";
        const meta = loadIntake()[key];
        const f = sessionFiles[key];
        if (key === "file_technical" || key === "file_bess") {
          // Always server-render spreadsheets from current intake values —
          // spreadsheet bytes have no useful native browser preview.
          openDrawer({ title, file: meta?.name, url: kickoffPreviewUrl(key, { file: meta?.name }) });
          return;
        }
        if (f) {
          // File attached this session — preview the actual bytes.
          const previewable =
            f.type === "application/pdf" || f.type.startsWith("image/") || f.type.startsWith("text/") ||
            /\.(dyd|epc|txt|md|csv|kml)$/i.test(f.name);
          if (previewable) {
            const blob = f.type ? f : new Blob([f], { type: "text/plain" });
            openDrawer({ title, file: f.name, url: URL.createObjectURL(blob) });
          } else {
            openDrawer({
              title, file: f.name,
              html: `<div class="rounded-card border border-line bg-soft p-5 text-[13.5px] leading-relaxed text-muted">
                <strong class="mb-1 block text-ink">${esc(f.name)}</strong>
                ${esc(fmtBytes(f.size))} — attached and recorded in the intake. Inline preview is available
                for PDF, image, and text files; this file will be carried into the submission as-is.
              </div>`,
            });
          }
        } else if (meta?.example) {
          openDrawer({ title, file: meta.name, url: `/api/caiso/kickoff/${encodeURIComponent(key)}/preview` });
        } else if (meta?.name) {
          openDrawer({
            title, file: meta.name,
            html: `<div class="rounded-card border border-line bg-soft p-5 text-[13.5px] leading-relaxed text-muted">
              <strong class="mb-1 block text-ink">${esc(meta.name)}</strong>
              ${esc(fmtBytes(meta.size))} — recorded in the intake. The file contents are not kept by the
              demo between sessions; re-attach the file to preview it.
            </div>`,
          });
        }
      });
    });
  }
}

/* ---------- Auth ---------- */
function authView(mode) {
  const isSignup = mode === "signup";
  return `
  <div class="grid min-h-screen place-items-center bg-canvas p-6">
    <form class="${panel} w-full max-w-md p-8" id="auth-form">
      <h1 class="mb-2 text-2xl tracking-tightish">${isSignup ? "Create organization" : "Sign in to GridPilot"}</h1>
      <p class="mb-6 text-[14px] text-muted">${
        isSignup
          ? "Register your organization to manage interconnection audits."
          : 'Prefer the walkthrough? <a class="text-ink underline-offset-2 hover:underline" href="#/demo">Open the guided demo</a>'
      }</p>
      <div id="auth-error" class="mb-3 hidden rounded-card border border-danger/30 bg-danger-soft px-3 py-2 text-[13px] text-danger"></div>
      ${
        isSignup
          ? `<div class="mb-3"><label class="${label}">Full name</label><input class="${field}" name="name" required /></div>
             <div class="mb-3"><label class="${label}">Organization</label><input class="${field}" name="org_name" required placeholder="Northwind Renewables" /></div>`
          : ""
      }
      <div class="mb-3"><label class="${label}">Email</label><input class="${field}" name="email" type="email" required /></div>
      <div class="mb-5"><label class="${label}">Password</label><input class="${field}" name="password" type="password" required minlength="8" /></div>
      <button class="${button("primary", "block")}" type="submit">${isSignup ? "Create organization" : "Sign in"}</button>
      <p class="mt-4 text-[13px] text-muted">
        ${
          isSignup
            ? `Already registered? <a class="text-ink hover:underline" href="#/login">Sign in</a>`
            : `Need an account? <a class="text-ink hover:underline" href="#/signup">Request access</a> · <a class="text-ink hover:underline" href="#/demo">Try Demo</a>`
        }
      </p>
    </form>
  </div>`;
}

async function renderLogin() {
  root.innerHTML = authView("login");
  bindAuth("login");
}
async function renderSignup() {
  root.innerHTML = authView("signup");
  bindAuth("signup");
}

function bindAuth(mode) {
  document.getElementById("auth-form")?.addEventListener("submit", async (e) => {
    e.preventDefault();
    const body = Object.fromEntries(new FormData(e.target).entries());
    const errEl = document.getElementById("auth-error");
    errEl.classList.add("hidden");
    try {
      state.me = mode === "login" ? await api.login(body) : await api.signup(body);
      if (state.me.is_demo) {
        if (!loadOnboard().wizardStep) setWizardStep(1);
        await refreshDemoCtx();
        navigate("onboarding");
      } else navigate("dashboard");
    } catch (err) {
      errEl.textContent = err.message;
      errEl.classList.remove("hidden");
    }
  });
}

/* ---------- App pages ---------- */
async function openProjectModal() {
  state.modal = `
  <div class="fixed inset-0 z-20 grid place-items-center bg-ink/40 p-5" id="modal">
    <form class="${panel} w-full max-w-md p-6" id="project-form">
      <h3 class="mb-4 text-lg tracking-tightish">Add project</h3>
      <div class="mb-3"><label class="${label}">Project name</label><input class="${field}" name="name" required /></div>
      <div class="mb-3"><label class="${label}">ISO / RTO</label><select class="${field}" name="iso"><option>CAISO</option><option>PJM</option><option>MISO</option><option>ERCOT</option></select></div>
      <div class="mb-3"><label class="${label}">Capacity (MW)</label><input class="${field}" name="capacity_mw" type="number" step="0.1" /></div>
      <div class="mb-3"><label class="${label}">State</label><input class="${field}" name="state" placeholder="IN" /></div>
      <div class="mb-5"><label class="${label}">POI substation</label><input class="${field}" name="poi_substation" /></div>
      <div class="flex justify-end gap-2">
        <button type="button" class="${button("ghost")}" id="modal-cancel">Cancel</button>
        <button type="submit" class="${button("primary")}">Create</button>
      </div>
    </form>
  </div>`;
  await render();
}

// Modal events are delegated at the document level: re-renders replace the DOM
// nodes, so per-render listeners can be lost when a repaint races the binding.
document.addEventListener("click", (e) => {
  const t = e.target;
  if (t?.id === "modal-cancel" || t?.id === "modal") {
    state.modal = null;
    render();
  }
});
document.addEventListener("submit", async (e) => {
  if (e.target?.id !== "project-form") return;
  e.preventDefault();
  const body = Object.fromEntries(new FormData(e.target).entries());
  if (body.capacity_mw) body.capacity_mw = Number(body.capacity_mw);
  else delete body.capacity_mw;
  try {
    const p = await api.createProject(body);
    state.modal = null;
    toast("Project created");
    navigate(`project/${p.id}`);
  } catch (err) {
    toast(err.message);
  }
});

async function renderDashboard() {
  const me = await ensureAuth();
  if (!me) return;
  await refreshDemoCtx();
  if (me.is_demo && !loadOnboard().completed && getWizardStep() <= WIZARD_LAST) {
    navigate("onboarding");
    return;
  }
  const data = await api.dashboard();
  root.innerHTML = shell(
    "Dashboard",
    `
    <div class="mb-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
      ${[
        ["Projects", data.projects],
        ["Audits this period", `${data.audits_this_period} / ${data.audit_limit}`],
        ["Open blockers", data.open_blocking],
        ["Open warnings", data.open_warnings],
      ]
        .map(
          ([k, v]) => `
        <div class="${panel} p-4">
          <div class="font-mono text-[11px] uppercase tracking-[0.08em] text-muted">${k}</div>
          <div class="mt-1 text-2xl tracking-tightish tabular-nums ${k.includes("blocker") && v ? "text-danger" : ""}">${v}</div>
        </div>`
        )
        .join("")}
    </div>
    <div class="${panel} mb-4 p-4">
      <div class="mb-3 flex items-center justify-between border-b border-line pb-3">
        <h3 class="text-[15px] tracking-tightish">Projects</h3>
        <button class="${button("primary", "sm")}" id="new-project-btn">Add project</button>
      </div>
      ${
        data.recent_projects.length
          ? `<table class="${table.wrap}"><thead><tr><th class="${table.th}">Name</th><th class="${table.th}">ISO</th><th class="${table.th}">Capacity</th><th class="${table.th}">Latest audit</th><th class="${table.th}"></th></tr></thead><tbody>
          ${data.recent_projects
            .map(
              (p) => `<tr>
              <td class="${table.td}"><strong>${esc(p.name)}</strong><div class="font-mono text-[11px] text-muted">${esc(p.poi_substation || p.state || "")}</div></td>
              <td class="${table.td}">${esc(p.iso)}</td>
              <td class="${table.td}">${p.capacity_mw != null ? esc(p.capacity_mw) + " MW" : "—"}</td>
              <td class="${table.td}">${p.latest_audit ? `${pill(p.latest_audit.readiness_status || p.latest_audit.status)} <span class="font-mono text-[12px]">${p.latest_audit.readiness_score ?? "—"}</span>` : '<span class="text-muted">No audits</span>'}</td>
              <td class="${table.td}"><a class="text-ink hover:underline" href="#/project/${p.id}">Open →</a></td>
            </tr>`
            )
            .join("")}
          </tbody></table>`
          : `<div class="rounded-card border border-dashed border-line py-10 text-center text-muted">No projects yet</div>`
      }
    </div>
    <div class="${panel} p-4">
      <div class="mb-3 flex items-center justify-between border-b border-line pb-3">
        <h3 class="text-[15px] tracking-tightish">Recent audits</h3>
        <a class="text-[13px] text-muted hover:text-ink" href="#/audits">View all</a>
      </div>
      ${
        data.recent_audits.length
          ? `<table class="${table.wrap}"><thead><tr><th class="${table.th}">When</th><th class="${table.th}">ISO</th><th class="${table.th}">Status</th><th class="${table.th}">Score</th><th class="${table.th}">Blockers</th><th class="${table.th}"></th></tr></thead><tbody>
          ${data.recent_audits
            .map(
              (a) => `<tr>
              <td class="${table.td} font-mono text-[12px]">${esc(fmtDate(a.created_at))}</td>
              <td class="${table.td}">${esc(a.iso)}</td>
              <td class="${table.td}">${pill(a.status)}</td>
              <td class="${table.td} font-mono">${a.readiness_score ?? "—"}</td>
              <td class="${table.td}">${a.blocking_open}</td>
              <td class="${table.td}"><a class="text-ink hover:underline" href="#/audit/${a.id}">Open →</a></td>
            </tr>`
            )
            .join("")}
          </tbody></table>`
          : `<div class="rounded-card border border-dashed border-line py-10 text-center text-muted">No audits yet</div>`
      }
    </div>`
  );
  bindShell();
  document.getElementById("new-project-btn")?.addEventListener("click", () => openProjectModal());
}

async function renderProjects() {
  const me = await ensureAuth();
  if (!me) return;
  await refreshDemoCtx();
  const { projects } = await api.projects();
  root.innerHTML = shell(
    "Projects",
    `<div class="${panel} p-4">
      <div class="mb-3 flex items-center justify-between border-b border-line pb-3">
        <h3 class="text-[15px] tracking-tightish">All projects</h3>
        <button class="${button("primary", "sm")}" id="new-project-btn">Add project</button>
      </div>
      ${
        projects.length
          ? `<table class="${table.wrap}"><thead><tr><th class="${table.th}">Name</th><th class="${table.th}">ISO</th><th class="${table.th}">MW</th><th class="${table.th}">Drawing</th><th class="${table.th}">Gate</th><th class="${table.th}"></th></tr></thead><tbody>
          ${projects
            .map(
              (p) => `<tr>
              <td class="${table.td}"><strong>${esc(p.name)}</strong></td>
              <td class="${table.td}">${esc(p.iso)}</td>
              <td class="${table.td}">${p.capacity_mw ?? "—"}</td>
              <td class="${table.td} font-mono text-[12px]">${esc(p.latest_drawing?.filename || "—")}</td>
              <td class="${table.td}">${p.open_blocking ? pill("not_ready") : p.latest_audit ? pill(p.latest_audit.readiness_status || "ready") : "—"}</td>
              <td class="${table.td}"><a class="text-ink hover:underline" href="#/project/${p.id}">Open →</a></td>
            </tr>`
            )
            .join("")}
          </tbody></table>`
          : `<div class="py-10 text-center text-muted">No projects</div>`
      }
    </div>`
  );
  bindShell();
  document.getElementById("new-project-btn")?.addEventListener("click", () => openProjectModal());
}

/* ---------- Real-app CAISO request wizard (per project, real AI extraction) ----------
 * User flow: project → upload kickoff documents → AI extraction (Grok reads the
 * actual files) → editable intake → validation against CAISO rules → packet
 * generation → download. Same engine as the guided demo, but with the user's
 * own documents and a real model call.
 */
const REQ_META = [
  { n: 1, label: "Documents" },
  { n: 2, label: "Intake" },
  { n: 3, label: "Validate" },
  { n: 4, label: "Packet" },
];
const reqFiles = {}; // slot -> File (bytes live only in this browser session)

function reqStorageKey(pid) {
  return `gp_request_${pid}`;
}

function loadReq(pid) {
  try {
    return JSON.parse(localStorage.getItem(reqStorageKey(pid)) || "{}");
  } catch {
    return {};
  }
}

function saveReq(pid, patch) {
  const next = { ...loadReq(pid), ...patch, updatedAt: Date.now() };
  localStorage.setItem(reqStorageKey(pid), JSON.stringify(next));
  return next;
}

/** Blank intake for real projects — no demo defaults, selects on first option. */
function blankIntake(project) {
  const intake = {};
  for (const section of state.caisoSchema?.sections || []) {
    for (const f of section.fields) {
      if (f.type === "file") continue;
      intake[f.key] = f.type === "select" ? (f.options?.[0] ?? "") : "";
      // "Received from vendor" requires the file — pending is the honest blank state.
      if (f.key === "dyd_status" && f.options?.includes("Requested — pending")) {
        intake[f.key] = "Requested — pending";
      }
    }
  }
  if (project) {
    intake.project_name = project.name || "";
    if (project.capacity_mw) intake.net_mw_poi = project.capacity_mw;
    if (project.poi_substation) intake.poi_name = project.poi_substation;
  }
  return intake;
}

function reqStepperHtml(active) {
  return `
  <ol class="mb-6 flex items-start justify-between gap-1">
    ${REQ_META.map((s, idx) => {
      const done = active > s.n;
      const current = active === s.n;
      return `
      <li class="flex min-w-0 flex-1 items-start">
        <div class="w-full text-center">
          <span class="mx-auto mb-1.5 flex h-7 w-7 items-center justify-center rounded-full border text-[11px] font-mono ${
            current ? "border-ink bg-ink text-primary-fg" : done ? "border-ok/40 bg-ok-soft text-ok" : "border-line bg-surface text-muted"
          }">${done ? "✓" : s.n}</span>
          <span class="hidden text-[11px] font-mono uppercase tracking-[0.08em] sm:block ${current ? "text-ink" : "text-muted"}">${esc(s.label)}</span>
        </div>
        ${idx < REQ_META.length - 1 ? `<span class="mt-3.5 h-px min-w-[8px] flex-1 bg-line"></span>` : ""}
      </li>`;
    }).join("")}
  </ol>`;
}

function reqFileSlotHtml(f, meta) {
  const picked = reqFiles[f.key] || null;
  const has = picked || (meta && meta.name);
  const name = picked?.name || meta?.name || "";
  const size = picked?.size ?? meta?.size ?? 0;
  const stale = !picked && meta?.name; // metadata from a previous session; bytes gone
  return `
    <div>
      <label class="${label}">${esc(f.label)} ${f.required ? '<span class="text-danger">*</span>' : ""}</label>
      <div class="flex items-center gap-3 rounded-card border border-dashed px-3 py-2.5 ${has ? "border-line bg-soft" : f.required ? "border-danger/40 bg-danger-soft/40" : "border-line bg-soft"}">
        ${
          has
            ? `<div class="min-w-0 flex-1">
                 <p class="truncate text-[13px] text-ink" title="${esc(name)}">${esc(name)}</p>
                 <p class="font-mono text-[11px] text-muted">${esc(fmtBytes(size))}${stale ? " · re-attach to extract again" : ""}</p>
               </div>
               <button type="button" class="${button("ghost", "sm")}" data-req-attach="${esc(f.key)}">Replace</button>
               <button type="button" class="${button("ghost", "sm")}" data-req-remove="${esc(f.key)}">Remove</button>`
            : `<span class="flex-1 text-[13px] text-muted">No file attached</span>
               <button type="button" class="${button("ghost", "sm")}" data-req-attach="${esc(f.key)}">Choose file</button>`
        }
        <input type="file" class="hidden" data-req-input="${esc(f.key)}" ${f.accept ? `accept="${esc(f.accept)}"` : ""} />
      </div>
      ${f.hint ? `<p class="mt-1 text-[11px] leading-snug text-muted">${esc(f.hint)}</p>` : ""}
    </div>`;
}

async function renderRequest(projectId) {
  const me = await ensureAuth();
  if (!me) return;
  await ensureCaisoSchema();

  let project = null;
  try {
    project = (await api.project(projectId)).project;
  } catch (err) {
    toast(err.message);
    return navigate("projects");
  }

  const req = loadReq(projectId);
  const step = Math.min(4, Math.max(1, Number(req.step || 1)));
  const intake = { ...blankIntake(project), ...(req.intake || {}) };
  const prov = req.prov || {};
  // Arriving at Validate without a result (e.g. after a refresh) — validate now.
  if (step === 3 && !state.reqValidation && !state.reqBusy) {
    try {
      state.reqValidation = await api.caisoValidate(intake);
    } catch {
      state.reqValidation = null;
    }
  }
  const docSection = (state.caisoSchema?.sections || []).find((s) => s.id === "documents");

  const footer = (left, right) => `
    <div class="flex items-center justify-between gap-3 border-t border-line bg-soft px-6 py-3.5">
      <div class="flex flex-wrap gap-2">${left || ""}</div>
      <div class="flex flex-wrap justify-end gap-2">${right || ""}</div>
    </div>`;

  let body = "";

  if (state.reqBusy) {
    body = `
      <div class="flex-1 p-7">
        <p class="mb-2 font-mono text-[12px] uppercase tracking-[0.12em] text-muted">${esc(state.reqBusy.title)}</p>
        <h2 class="mb-3 text-2xl tracking-tightish">${esc(state.reqBusy.heading)}</h2>
        <div class="rounded-card border border-focus/20 bg-info-soft p-4">
          <div class="flex gap-3">
            <div class="gp-spin mt-0.5 h-4 w-4 shrink-0 rounded-full border-2 border-focus/30 border-t-focus"></div>
            <p class="text-[14px] text-ink">${esc(state.reqBusy.detail)}</p>
          </div>
          <div class="gp-audit-progress mt-4"><span></span></div>
        </div>
      </div>`;
  } else if (step === 1) {
    const files = (docSection?.fields || []).map((f) => reqFileSlotHtml(f, intake[f.key])).join("");
    const attached = Object.keys(reqFiles).length;
    body = `
      <div class="flex-1 p-7">
        <p class="mb-2 font-mono text-[12px] uppercase tracking-[0.12em] text-muted">Step 1 of 4</p>
        <h2 class="mb-3 text-2xl tracking-tightish">Kickoff documents</h2>
        <p class="mb-5 max-w-2xl text-[15px] leading-relaxed text-muted">
          Attach the documents you already have — executed site agreement, technical workbook,
          storage specification, signatory proof, vendor models, parcel boundary. GridPilot reads
          them and populates the intake form; every value remains editable.
        </p>
        <div class="grid gap-x-4 gap-y-3">${files}</div>
      </div>
      ${footer(
        `<a class="${button("ghost")}" href="#/project/${esc(projectId)}">Back to project</a>`,
        `<button type="button" class="${button("ghost")}" id="req-skip">Enter data manually</button>
         <button type="button" class="${button("primary")}" id="req-extract" ${attached ? "" : "disabled"}>Extract data with AI</button>`
      )}`;
  } else if (step === 2) {
    const sections = (state.caisoSchema?.sections || []).filter((s) => s.id !== "documents");
    const v = state.reqValidation;
    const errs = {};
    for (const e of v?.errors || []) if (e.field) errs[e.field] = e.title;
    body = `
      <div class="flex-1 p-7">
        <p class="mb-2 font-mono text-[12px] uppercase tracking-[0.12em] text-muted">Step 2 of 4</p>
        <h2 class="mb-3 text-2xl tracking-tightish">Intake</h2>
        <p class="mb-5 max-w-2xl text-[15px] leading-relaxed text-muted">
          Fields marked <span class="rounded-pill border border-focus/30 bg-info-soft px-1.5 font-mono text-[10px] uppercase tracking-[0.06em] text-focus">AI</span>
          were extracted from your documents — review them before validating.
        </p>
        <form id="req-intake-form" class="space-y-6">
          ${sections
            .map(
              (sec) => `
            <fieldset>
              <legend class="mb-3 border-b border-line pb-1.5 font-mono text-[11px] uppercase tracking-[0.1em] text-muted">${esc(sec.title)}</legend>
              <div class="grid gap-x-4 gap-y-3 sm:grid-cols-2">
                ${sec.fields.map((f) => intakeFieldHtml(f, intake, prov, errs)).join("")}
              </div>
            </fieldset>`
            )
            .join("")}
        </form>
      </div>
      ${footer(
        `<button type="button" class="${button("ghost")}" id="req-back-1">Back to documents</button>`,
        `<button type="button" class="${button("primary")}" id="req-validate">Validate inputs</button>`
      )}`;
  } else if (step === 3) {
    const v = state.reqValidation;
    const checks = v?.checks || [];
    const errCount = (v?.errors || []).length;
    const cards = checks
      .map((it) => {
        const kind = it.status === "error" ? "error" : it.status === "warn" ? "warn" : "ok";
        const [tone, itone, icon] =
          kind === "error"
            ? ["border-danger/25 bg-danger-soft", "text-danger", "✕"]
            : kind === "warn"
              ? ["border-warn/30 bg-warn-soft", "text-ink", "!"]
              : ["border-ok/20 bg-ok-soft", "text-ok", "✓"];
        const reqBtn = it.rule
          ? `<button type="button" class="${button("ghost", "sm")}"
               data-drawer-url="/api/caiso/requirements/${esc(it.rule.id)}/preview"
               data-drawer-title="ISO requirement — ${esc(it.rule.title)}"
               data-drawer-file="${esc(it.rule.source)}">Requirement</button>`
          : "";
        return `
        <article class="rounded-card border ${tone} p-3.5">
          <div class="flex gap-2.5">
            <span class="mt-0.5 font-mono text-[13px] ${itone}">${icon}</span>
            <div class="min-w-0 flex-1">
              <div class="flex flex-wrap items-center gap-2">
                <strong class="text-[13.5px] tracking-tightish">${esc(it.title)}</strong>
                <span class="rounded-pill border px-1.5 font-mono text-[9px] uppercase tracking-[0.07em] ${kind === "error" ? "border-danger/30 text-danger" : kind === "warn" ? "border-warn/40 text-ink" : "border-ok/30 text-ok"}">${kind === "error" ? "Blocking" : kind === "warn" ? "Advisory" : "Passed"}</span>
              </div>
              <p class="mt-0.5 text-[12.5px] leading-snug text-muted">${esc(it.detail)}</p>
              ${reqBtn ? `<div class="mt-2">${reqBtn}</div>` : ""}
            </div>
          </div>
        </article>`;
      })
      .join("");
    body = `
      <div class="flex-1 p-7">
        <p class="mb-2 font-mono text-[12px] uppercase tracking-[0.12em] text-muted">Step 3 of 4</p>
        <h2 class="mb-3 text-2xl tracking-tightish">Validation</h2>
        ${
          errCount
            ? `<div class="mb-4 rounded-card border border-danger/25 bg-danger-soft p-4"><strong class="text-danger">Blocking issues found</strong><p class="mt-0.5 text-[13px] text-muted">${errCount} blocking issue(s) — edit the intake or re-attach corrected documents, then revalidate.</p></div>`
            : `<div class="mb-4 rounded-card border border-ok/25 bg-ok-soft p-4"><strong class="text-ok">Intake is clean</strong><p class="mt-0.5 text-[13px] text-muted">All blocking checks passed — the packet can be generated.</p></div>`
        }
        <div class="space-y-2">${cards}</div>
      </div>
      ${footer(
        `<button type="button" class="${button("ghost")}" id="req-back-2">Edit intake</button>
         <button type="button" class="${button("ghost")}" id="req-back-1">Documents</button>`,
        errCount
          ? `<button type="button" class="${button("primary")}" id="req-back-2b">Fix intake</button>`
          : `<button type="button" class="${button("primary")}" id="req-generate">Generate packet</button>`
      )}`;
  } else {
    // Step 4 — packet
    let p = state.reqPacket;
    if (!p && req.packetId) {
      try {
        p = state.reqPacket = await api.caisoPacket(req.packetId, req.packetD);
      } catch {
        p = null;
      }
    }
    if (!p) {
      body = `
        <div class="flex-1 p-7">
          <h2 class="mb-3 text-2xl tracking-tightish">Packet unavailable</h2>
          <p class="mb-5 max-w-xl text-[15px] text-muted">Regenerate the packet from the saved intake.</p>
        </div>
        ${footer(
          `<button type="button" class="${button("ghost")}" id="req-back-3">Back</button>`,
          `<button type="button" class="${button("primary")}" id="req-generate">Regenerate packet</button>`
        )}`;
    } else {
      const qs = req.packetD ? `?d=${req.packetD}` : "";
      const zipUrl = `/api/caiso/packets/${esc(p.id)}/files/${encodeURIComponent(p.zip_file)}${qs}`;
      body = `
        <div class="flex-1 p-7">
          <p class="mb-2 font-mono text-[12px] uppercase tracking-[0.12em] text-muted">Step 4 of 4</p>
          <h2 class="mb-3 text-2xl tracking-tightish">CAISO submission packet — ${esc(p.project_name)}</h2>
          <div class="mb-5 grid gap-3 sm:grid-cols-4">
            <div class="rounded-card border border-line bg-soft p-4"><span class="font-mono text-[11px] uppercase tracking-[0.08em] text-muted">Net at POI</span><strong class="mt-1 block">${esc(p.net_mw)} MW</strong></div>
            <div class="rounded-card border border-line bg-soft p-4"><span class="font-mono text-[11px] uppercase tracking-[0.08em] text-muted">POI</span><strong class="mt-1 block text-[13px]">${esc(p.poi)}</strong></div>
            <div class="rounded-card border border-line bg-soft p-4"><span class="font-mono text-[11px] uppercase tracking-[0.08em] text-muted">Track</span><strong class="mt-1 block text-[13px]">${esc(p.track)}</strong></div>
            <div class="rounded-card border border-line bg-soft p-4"><span class="font-mono text-[11px] uppercase tracking-[0.08em] text-muted">Deposit</span><strong class="mt-1 block text-[13px]">${esc(p.deposit)}</strong></div>
          </div>
          ${PACKET_CATEGORIES.map(([key, title]) => {
            const docs = p.documents.filter((doc) => doc.category === key);
            if (!docs.length) return "";
            return `
              <div class="mb-4">
                <h3 class="mb-2 font-mono text-[11px] uppercase tracking-[0.08em] text-muted">${esc(title)}</h3>
                <div class="space-y-2">${docs.map((doc) => packetDocRowHtml(p.id, doc, qs)).join("")}</div>
              </div>`;
          }).join("")}
          <div class="rounded-card border border-warn/30 bg-warn-soft p-4">
            <strong class="mb-2 block">Remaining developer actions</strong>
            <ol class="list-decimal space-y-1.5 pl-5 text-[13px] text-muted">
              ${p.actions.map((a) => `<li><strong class="text-ink">${esc(a.title)}.</strong> ${esc(a.detail)}</li>`).join("")}
            </ol>
          </div>
        </div>
        ${footer(
          `<button type="button" class="${button("ghost")}" id="req-back-2">Edit intake</button>
           <button type="button" class="${button("ghost")}" id="req-generate">Regenerate</button>`,
          `<a class="${button("ghost")}" href="${zipUrl}">Download packet (.zip)</a>
           <a class="${button("primary")}" href="#/project/${esc(projectId)}">Done</a>`
        )}`;
    }
  }

  root.innerHTML = shell(
    `Interconnection request — ${project.name}`,
    `<div class="mx-auto max-w-4xl">
      ${reqStepperHtml(step)}
      <div class="${panel} flex min-h-[420px] flex-col overflow-hidden">${body}</div>
    </div>`,
    { showChip: false }
  );
  bindShell();
  bindRequest(projectId, step, intake);
}

function reqRepaint(projectId) {
  const y = window.scrollY;
  renderRequest(projectId).then(() => window.scrollTo(0, y));
}

async function reqRunExtraction(projectId, intake) {
  const fd = new FormData();
  for (const [slot, file] of Object.entries(reqFiles)) fd.append(slot, file, file.name);
  state.reqBusy = {
    title: "AI extraction",
    heading: "Reading your documents",
    detail: "Grok is reading the attached documents and mapping their contents onto the intake form…",
  };
  reqRepaint(projectId);
  try {
    const res = await api.caisoExtractFiles(fd);
    const merged = { ...intake, ...(res.fields || {}) };
    for (const [slot, file] of Object.entries(reqFiles)) {
      merged[slot] = { name: file.name, size: file.size };
    }
    saveReq(projectId, { intake: merged, prov: res.provenance || {}, step: 2 });
    state.reqBusy = null;
    toast(res.summary || "Extraction complete");
  } catch (err) {
    state.reqBusy = null;
    toast(`Extraction failed: ${err.message}`);
  }
  reqRepaint(projectId);
}

async function reqRunGeneration(projectId, intake) {
  state.reqBusy = {
    title: "Packet generation",
    heading: "Generating the submission packet",
    detail: "All fifteen packet documents are generated from the validated intake…",
  };
  reqRepaint(projectId);
  try {
    const res = await api.caisoGenerate(intake);
    if (!res?.ok) {
      state.reqBusy = null;
      state.reqValidation = res?.validation || null;
      saveReq(projectId, { step: 3 });
      toast("Intake has blocking issues — fix and retry");
    } else {
      state.reqBusy = null;
      state.reqPacket = res.packet;
      saveReq(projectId, {
        step: 4,
        packetId: res.packet.id,
        packetD: encodeIntakeParam(intake),
      });
      toast(`Packet ready — ${res.packet.documents.length} documents`);
    }
  } catch (err) {
    state.reqBusy = null;
    toast(err.message);
  }
  reqRepaint(projectId);
}

function collectReqIntake(projectId, intake) {
  const values = { ...intake };
  document.querySelectorAll("[data-intake]").forEach((el) => {
    const key = el.getAttribute("data-intake");
    values[key] = el.type === "number" ? (el.value === "" ? "" : Number(el.value)) : el.value;
  });
  saveReq(projectId, { intake: values });
  return values;
}

function bindRequest(projectId, step, intake) {
  const repaint = () => reqRepaint(projectId);

  if (step === 1) {
    document.querySelectorAll("[data-req-attach]").forEach((btn) => {
      btn.addEventListener("click", () => {
        document.querySelector(`[data-req-input="${btn.getAttribute("data-req-attach")}"]`)?.click();
      });
    });
    document.querySelectorAll("[data-req-input]").forEach((inp) => {
      inp.addEventListener("change", () => {
        const f = inp.files?.[0];
        if (!f) return;
        const key = inp.getAttribute("data-req-input");
        reqFiles[key] = f;
        // Record the attachment in the intake immediately so validation sees the
        // file even on the manual (no-extraction) path.
        const next = { ...intake, [key]: { name: f.name, size: f.size } };
        saveReq(projectId, { intake: next });
        intake[key] = next[key];
        repaint();
      });
    });
    document.querySelectorAll("[data-req-remove]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const key = btn.getAttribute("data-req-remove");
        delete reqFiles[key];
        const next = { ...intake };
        delete next[key];
        saveReq(projectId, { intake: next });
        repaint();
      });
    });
    document.getElementById("req-extract")?.addEventListener("click", () => {
      reqRunExtraction(projectId, intake);
    });
    document.getElementById("req-skip")?.addEventListener("click", () => {
      saveReq(projectId, { step: 2 });
      repaint();
    });
  }

  if (step === 2) {
    document.getElementById("req-back-1")?.addEventListener("click", () => {
      collectReqIntake(projectId, intake);
      saveReq(projectId, { step: 1 });
      repaint();
    });
    document.getElementById("req-validate")?.addEventListener("click", async () => {
      const values = collectReqIntake(projectId, intake);
      try {
        state.reqValidation = await api.caisoValidate(values);
        saveReq(projectId, { step: 3 });
      } catch (err) {
        toast(err.message);
      }
      repaint();
    });
  }

  if (step === 3) {
    const goto2 = () => {
      saveReq(projectId, { step: 2 });
      repaint();
    };
    document.getElementById("req-back-2")?.addEventListener("click", goto2);
    document.getElementById("req-back-2b")?.addEventListener("click", goto2);
    document.getElementById("req-back-1")?.addEventListener("click", () => {
      saveReq(projectId, { step: 1 });
      repaint();
    });
    document.getElementById("req-generate")?.addEventListener("click", () => {
      reqRunGeneration(projectId, intake);
    });
  }

  if (step === 4) {
    document.getElementById("req-back-2")?.addEventListener("click", () => {
      saveReq(projectId, { step: 2 });
      repaint();
    });
    document.getElementById("req-back-3")?.addEventListener("click", () => {
      saveReq(projectId, { step: 3 });
      repaint();
    });
    document.getElementById("req-generate")?.addEventListener("click", () => {
      state.reqPacket = null;
      reqRunGeneration(projectId, intake);
    });
  }
}

async function renderProject(id) {
  const me = await ensureAuth();
  if (!me) return;
  await refreshDemoCtx();
  const data = await api.project(id);
  const p = data.project;
  root.innerHTML = shell(
    p.name,
    `
    <div class="${panel} mb-4 p-4">
      <div class="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 class="text-[17px] tracking-tightish">${esc(p.name)}</h3>
          <div class="mt-1 font-mono text-[12px] text-muted">${esc(p.iso)} · ${p.capacity_mw != null ? esc(p.capacity_mw) + " MW" : "—"} · ${esc(p.poi_substation || p.state || "")}</div>
        </div>
        <div class="flex flex-wrap gap-2">
          <a class="${button("primary", "sm")}" href="#/request/${esc(p.id)}">Interconnection request</a>
          <label class="${button("ghost", "sm")} cursor-pointer">Upload SLD<input id="draw-file" type="file" accept=".pdf,image/png,image/jpeg" hidden /></label>
          <button class="${button("ghost", "sm")}" id="run-audit" ${data.drawings.length ? "" : "disabled"}>Run SLD audit</button>
        </div>
      </div>
    </div>
    ${
      data.drawings[0]
        ? `<div class="${panel} mb-4 overflow-hidden">
            <div class="flex items-center justify-between border-b border-line px-4 py-3"><h3 class="text-[14px]">Latest drawing</h3><span class="font-mono text-[11px] text-muted">${esc(data.drawings[0].filename)}</span></div>
            <button type="button" class="block w-full cursor-zoom-in bg-soft" data-drawer-url="/api/projects/${esc(p.id)}/drawings/${esc(data.drawings[0].id)}/file" data-drawer-title="Latest drawing" data-drawer-file="${esc(data.drawings[0].filename)}">
              <img class="max-h-[480px] w-full object-contain object-top bg-white" alt="SLD preview" src="/api/projects/${esc(p.id)}/drawings/${esc(data.drawings[0].id)}/preview.png" onerror="this.onerror=null;this.src='/assets/img/cedar_ridge_sld_demo.png'" />
            </button>
          </div>`
        : ""
    }
    <div class="grid gap-4 lg:grid-cols-2">
      <div class="${panel} p-4">
        <h3 class="mb-3 border-b border-line pb-2 text-[14px]">Drawings</h3>
        ${
          data.drawings.length
            ? `<table class="${table.wrap}"><thead><tr><th class="${table.th}">File</th><th class="${table.th}">Version</th><th class="${table.th}">Uploaded</th></tr></thead><tbody>
            ${data.drawings
              .map(
                (d) => `<tr>
                <td class="${table.td}"><button type="button" class="text-left hover:underline" data-drawer-url="/api/projects/${p.id}/drawings/${d.id}/file" data-drawer-title="Drawing" data-drawer-file="${esc(d.filename)}">${esc(d.filename)}</button></td>
                <td class="${table.td}">${esc(d.version_label)}</td>
                <td class="${table.td} font-mono text-[12px]">${esc(fmtDate(d.created_at))}</td>
              </tr>`
              )
              .join("")}
            </tbody></table>`
            : `<p class="text-muted">No drawings yet</p>`
        }
      </div>
      <div class="${panel} p-4">
        <h3 class="mb-3 border-b border-line pb-2 text-[14px]">Audit history</h3>
        ${
          data.audits.length
            ? `<table class="${table.wrap}"><thead><tr><th class="${table.th}">When</th><th class="${table.th}">Status</th><th class="${table.th}">Score</th><th class="${table.th}"></th></tr></thead><tbody>
            ${data.audits
              .map(
                (a) => `<tr>
                <td class="${table.td} font-mono text-[12px]">${esc(fmtDate(a.created_at))}</td>
                <td class="${table.td}">${pill(a.status)}</td>
                <td class="${table.td} font-mono">${a.readiness_score ?? "—"}</td>
                <td class="${table.td}"><a class="hover:underline" href="#/audit/${a.id}">Open →</a></td>
              </tr>`
              )
              .join("")}
            </tbody></table>`
            : `<p class="text-muted">No audits yet</p>`
        }
      </div>
    </div>`
  );
  bindShell();
  document.getElementById("run-audit")?.addEventListener("click", async () => {
    try {
      toast("Queuing audit…");
      const a = await api.startAudit(p.id);
      navigate(`audit/${a.id}`);
    } catch (err) {
      toast(err.message);
    }
  });
  document.getElementById("draw-file")?.addEventListener("change", async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    try {
      await api.uploadDrawing(p.id, file, `Rev ${data.drawings.length + 1}`);
      toast("Drawing uploaded");
      render();
    } catch (err) {
      toast(err.message);
    }
  });
}

async function renderAudits() {
  const me = await ensureAuth();
  if (!me) return;
  await refreshDemoCtx();
  const { audits } = await api.audits();
  root.innerHTML = shell(
    "Audits",
    `<div class="${panel} p-4">
      ${
        audits.length
          ? `<table class="${table.wrap}"><thead><tr><th class="${table.th}">When</th><th class="${table.th}">Drawing</th><th class="${table.th}">ISO</th><th class="${table.th}">Status</th><th class="${table.th}">Score</th><th class="${table.th}">Blockers</th><th class="${table.th}"></th></tr></thead><tbody>
          ${audits
            .map(
              (a) => `<tr>
              <td class="${table.td} font-mono text-[12px]">${esc(fmtDate(a.created_at))}</td>
              <td class="${table.td}">${esc(a.drawing_filename || a.drawing_id)}</td>
              <td class="${table.td}">${esc(a.iso)}</td>
              <td class="${table.td}">${pill(a.status)}</td>
              <td class="${table.td} font-mono">${a.readiness_score ?? "—"}</td>
              <td class="${table.td}">${a.blocking_open}</td>
              <td class="${table.td}"><a class="hover:underline" href="#/audit/${a.id}">Open →</a></td>
            </tr>`
            )
            .join("")}
          </tbody></table>`
          : `<div class="py-10 text-center text-muted">No audits yet</div>`
      }
    </div>`
  );
  bindShell();
}

async function renderAudit(id) {
  const me = await ensureAuth();
  if (!me) return;
  await refreshDemoCtx();
  const a = await api.audit(id);

  if (a.status === "queued" || a.status === "running") {
    root.innerHTML = shell(
      "Audit in progress",
      `<div class="${panel} p-6">
        <div class="mb-2">${pill(a.status)}</div>
        <p class="text-muted">Analyzing SLD against the ${esc(a.iso)} rule pack…</p>
        <p class="mt-2 font-mono text-[12px] text-muted">Run ${esc(a.id)} · ${esc(a.drawing_filename || "")}</p>
      </div>`
    );
    bindShell();
    setTimeout(() => render(), 2500);
    return;
  }

  if (a.status === "failed") {
    root.innerHTML = shell(
      "Audit failed",
      `<div class="${panel} p-6"><div class="mb-3 rounded-card border border-danger/30 bg-danger-soft px-3 py-2 text-danger">${esc(a.error || "Unknown error")}</div>
       <a class="${button("ghost")}" href="#/project/${esc(a.project_id || "")}">Back to project</a></div>`
    );
    bindShell();
    return;
  }

  const gate = a.filing_gate || {};
  const findings = a.findings || [];
  const equipment = a.extract?.equipment || [];

  const demoBack =
    me.is_demo && !loadOnboard().completed
      ? `<button type="button" class="${button("ghost", "sm")}" id="back-to-demo">← Back to demo setup</button>`
      : `<a class="${button("ghost", "sm")}" href="#/audits">All audits</a>`;

  root.innerHTML = shell(
    `Audit ${a.id}`,
    `
    <div class="mb-3 flex flex-wrap items-center justify-between gap-2">${demoBack}</div>
    <div class="${panel} mb-4 flex flex-wrap items-center justify-between gap-4 p-5">
      <div>
        <h3 class="text-[17px] tracking-tightish">${gate.can_file ? "Ready to file" : "Filing blocked"}</h3>
        <p class="mt-1 max-w-2xl text-[14px] text-muted">${esc(a.summary || "")}</p>
      </div>
      <div class="text-right">
        <div class="text-3xl tracking-tightish tabular-nums">${a.readiness_score ?? "—"}</div>
        <div class="font-mono text-[11px] uppercase tracking-[0.08em] text-muted">Readiness</div>
        <div class="mt-2 font-mono text-[11px] text-muted">${gate.open_blocking || 0} blockers · ${gate.open_warnings || 0} warnings</div>
        <button type="button" class="${button("ghost", "sm")} mt-3" data-drawer-url="/api/audits/${a.id}/report.html" data-drawer-title="Audit report" data-drawer-file="report.html">HTML report</button>
      </div>
    </div>
    <div class="grid gap-4 lg:grid-cols-2">
      <div class="space-y-4">
        <div class="${panel} overflow-hidden">
          <div class="flex items-center justify-between border-b border-line px-4 py-3"><h3 class="text-[14px]">Drawing</h3><span class="font-mono text-[11px] text-muted">${esc(a.drawing_filename || "")}</span></div>
          ${
            a.project_id && a.drawing_id
              ? `<button type="button" class="block w-full cursor-zoom-in bg-soft" data-drawer-url="/api/projects/${esc(a.project_id)}/drawings/${esc(a.drawing_id)}/file" data-drawer-title="Drawing" data-drawer-file="${esc(a.drawing_filename || "")}">
                   <img class="max-h-[480px] w-full object-contain object-top bg-white" alt="SLD preview" src="/api/projects/${esc(a.project_id)}/drawings/${esc(a.drawing_id)}/preview.png" onerror="this.onerror=null;this.src='/assets/img/cedar_ridge_sld_demo.png'" />
                 </button>`
              : `<img class="max-h-[480px] w-full object-contain object-top bg-white" alt="SLD preview" src="/assets/img/cedar_ridge_sld_demo.png" />`
          }
        </div>
        <div class="${panel} p-4">
          <h3 class="mb-3 border-b border-line pb-2 text-[14px]">Extracted equipment</h3>
          <table class="${table.wrap}"><thead><tr><th class="${table.th}">Type</th><th class="${table.th}">Label</th><th class="${table.th}">Rating</th><th class="${table.th}">Notes</th></tr></thead><tbody>
            ${
              equipment.length
                ? equipment
                    .map(
                      (eq) => `<tr><td class="${table.td}">${esc(eq.type)}</td><td class="${table.td}">${esc(eq.label || "—")}</td><td class="${table.td}">${esc(eq.rating || "—")}</td><td class="${table.td}">${esc(eq.notes || "—")}</td></tr>`
                    )
                    .join("")
                : `<tr><td class="${table.td} text-muted" colspan="4">No equipment extracted</td></tr>`
            }
          </tbody></table>
        </div>
      </div>
      <div class="${panel} p-4">
        <div class="mb-3 flex items-center justify-between border-b border-line pb-2">
          <h3 class="text-[14px]">Findings triage</h3>
          <span class="text-[12px] text-muted">${findings.filter((f) => f.severity === "blocking").length} blockers · ${findings.filter((f) => f.severity === "warning").length} warnings</span>
        </div>
        ${findingsTriageSectionsHtml(findings)}
      </div>
    </div>`
  );
  bindShell();
  document.getElementById("back-to-demo")?.addEventListener("click", () => {
    navigate("onboarding");
  });
  root.querySelectorAll("[data-triage]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const article = btn.closest("[data-id]");
      const triage = btn.getAttribute("data-triage");
      const findingId = article?.dataset?.id;
      if (!findingId || !triage) return;
      btn.disabled = true;
      try {
        await api.triage(a.id, findingId, { triage });
        toast(triage === "open" ? "Reopened" : `Marked ${triage}`);
        await renderAudit(a.id);
      } catch (err) {
        btn.disabled = false;
        toast(err.message);
      }
    });
  });
}

function triageActionsHtml(f, { required = true } = {}) {
  const cleared = f.triage === "resolved" || f.triage === "dismissed";
  if (cleared) {
    return `<div class="mt-2.5 flex flex-wrap gap-1.5">
      <button type="button" class="${button("primary", "sm")}" data-triage="open">Reopen</button>
    </div>`;
  }
  if (!required) {
    // Warnings / ready — same list as the report, but not the guided-demo resolve loop.
    return `<div class="mt-2.5 flex flex-wrap gap-1.5">
      <button type="button" class="${button("ghost", "sm")}" data-triage="dismissed">Dismiss</button>
      <button type="button" class="${button("ghost", "sm")}" data-triage="acknowledged">Acknowledge</button>
    </div>`;
  }
  return `<div class="mt-2.5 flex flex-wrap gap-1.5">
    <button type="button" class="${button("ghost", "sm")}" data-triage="acknowledged">Acknowledge</button>
    <button type="button" class="${button("primary", "sm")}" data-triage="resolved">Resolve</button>
    <button type="button" class="${button("ghost", "sm")}" data-triage="dismissed">Dismiss</button>
  </div>`;
}

function findingCardHtml(f, { required = true } = {}) {
  return `
    <article class="rounded-card border border-line p-3.5" data-id="${esc(f.id)}">
      <div class="mb-1 font-mono text-[10px] uppercase tracking-[0.08em] text-muted">${esc(f.severity)} · ${esc(f.rule_id || "custom")} · ${pill(f.triage)}</div>
      <h4 class="mb-1 text-[14px] tracking-tightish">${esc(f.title)}</h4>
      <p class="text-[13px] text-muted">${esc(f.detail)}</p>
      ${f.recommendation ? `<p class="mt-1 text-[13px]"><strong>Fix:</strong> ${esc(f.recommendation)}</p>` : ""}
      ${triageActionsHtml(f, { required })}
    </article>`;
}

function findingsTriageSectionsHtml(findings) {
  const blockers = findings.filter((f) => f.severity === "blocking");
  const warnings = findings.filter((f) => f.severity === "warning");
  const ready = findings.filter((f) => f.severity === "ready");
  const section = (title, hint, items, required) => {
    if (!items.length) return "";
    return `
      <div class="mb-4 last:mb-0">
        <div class="mb-2">
          <h4 class="text-[13px] tracking-tightish">${esc(title)}</h4>
          <p class="text-[12px] text-muted">${esc(hint)}</p>
        </div>
        <div class="space-y-2.5">${items.map((f) => findingCardHtml(f, { required })).join("")}</div>
      </div>`;
  };
  return `
    ${section("Blockers — clear these to file", "Same list as guided-demo step 4. Filing stays blocked until these are resolved or dismissed.", blockers, true)}
    ${section("Warnings — do not block filing", "Shown in the full report; optional to triage. Not part of the guided resolve loop.", warnings, false)}
    ${section("Ready checks", "Requirements that already look satisfied on the drawing.", ready, false)}`;
}

async function renderBilling() {
  const me = await ensureAuth();
  if (!me) return;
  await refreshDemoCtx();
  const b = await api.billing();
  root.innerHTML = shell(
    "Billing",
    `
    <div class="mb-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
      <div class="${panel} p-4"><div class="font-mono text-[11px] uppercase tracking-[0.08em] text-muted">Plan</div><div class="mt-1 text-xl capitalize">${esc(b.plan)}</div></div>
      <div class="${panel} p-4"><div class="font-mono text-[11px] uppercase tracking-[0.08em] text-muted">Audits used</div><div class="mt-1 text-xl">${b.audits_used_period} / ${b.audit_limit}</div></div>
      <div class="${panel} p-4"><div class="font-mono text-[11px] uppercase tracking-[0.08em] text-muted">Projects</div><div class="mt-1 text-xl">${b.project_count} / ${b.project_limit}</div></div>
      <div class="${panel} p-4"><div class="font-mono text-[11px] uppercase tracking-[0.08em] text-muted">Period start</div><div class="mt-1 text-[14px]">${esc(fmtDate(b.period_start))}</div></div>
    </div>
    <div class="${panel} p-5">
      <div class="mb-3 flex items-center justify-between">
        <h3 class="text-[15px]">Plan features</h3>
        ${b.plan === "free" ? `<button class="${button("primary", "sm")}" id="upgrade-btn">Upgrade to Pro</button>` : pill("ready")}
      </div>
      <ul class="list-disc space-y-1 pl-5 text-[14px] text-muted">${b.features.map((f) => `<li>${esc(f)}</li>`).join("")}</ul>
    </div>`
  );
  bindShell();
  document.getElementById("upgrade-btn")?.addEventListener("click", async () => {
    await api.upgrade();
    state.me = await api.me();
    toast("Upgraded to Pro");
    render();
  });
}

async function render() {
  const r = route();
  try {
    if (r.name === "demo") return renderDemo();
    if (r.name === "login") return renderLogin();
    if (r.name === "signup") return renderSignup();
    if (r.name === "onboarding") return renderOnboarding();
    if (r.name === "projects") return renderProjects();
    if (r.name === "project" && r.id) return renderProject(r.id);
    if (r.name === "request" && r.id) return renderRequest(r.id);
    if (r.name === "audits") return renderAudits();
    if (r.name === "audit" && r.id) return renderAudit(r.id);
    if (r.name === "billing") return renderBilling();
    return renderDashboard();
  } catch (err) {
    if (err.status === 401) {
      state.me = null;
      return renderLogin();
    }
    root.innerHTML = `<div class="grid min-h-screen place-items-center p-6"><div class="${panel} max-w-md p-6"><h1 class="mb-2 text-xl">Something broke</h1><p class="text-danger">${esc(err.message)}</p><a class="mt-4 inline-block text-ink hover:underline" href="#/dashboard">Back</a></div></div>`;
  }
}

window.addEventListener("hashchange", render);
render();

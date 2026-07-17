import { api } from "./api.js";
import { button, field, label, panel, pill as uiPill, table } from "./ui.js";

const root = document.getElementById("root");
const ONBOARD_KEY = "gp_demo_onboard_v2";
const WIZARD_META = [
  { n: 1, label: "Role" },
  { n: 2, label: "SLD" },
  { n: 3, label: "Pre-file" },
  { n: 4, label: "Triage" },
  { n: 5, label: "Report" },
];

let state = { me: null, toast: null, modal: null, demoCtx: null, lastAuditId: null };

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

function getWizardStep() {
  return Math.min(6, Math.max(1, Number(loadOnboard().wizardStep || 1)));
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

async function refreshDemoCtx() {
  if (!state.me?.is_demo) {
    state.demoCtx = null;
    return null;
  }
  try {
    state.demoCtx = await api.demoContext();
    return state.demoCtx;
  } catch {
    state.demoCtx = null;
    return null;
  }
}

function demoChipHtml() {
  if (!state.me?.is_demo || loadOnboard().completed || route().name === "onboarding") return "";
  const step = Math.min(getWizardStep(), 5);
  return `
  <div class="${panel} mb-4 flex flex-wrap items-center justify-between gap-3 px-4 py-3">
    <div>
      <strong class="block text-[13px] tracking-tightish">Guided demo</strong>
      <span class="text-[12px] text-muted">Step ${step} of 5 · ${esc(WIZARD_META[step - 1]?.label || "")}</span>
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
        <span class="inline-flex h-7 w-7 items-center justify-center rounded-full border border-line font-mono text-[10px] tracking-widest">GP</span>
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
  const s = info.scenario;
  root.innerHTML = `
  <div class="grid min-h-screen place-items-center bg-canvas p-6">
    <div class="${panel} w-full max-w-lg p-8">
      <p class="mb-3 font-mono text-[12px] uppercase tracking-[0.12em] text-muted">Developer demo · AES Indiana</p>
      <h1 class="mb-3 text-3xl tracking-tightish">Pre-filing QA before you submit</h1>
      <p class="mb-6 text-[15px] leading-relaxed text-muted">
        You are the <strong class="text-ink">developer</strong> — not the utility.
        Walk the loop consultants do manually: check the SLD against AES Indiana / ${esc(s.iso)} published rules,
        clear blockers, then export a report <em>before</em> PowerClerk or the ISO queue.
      </p>
      <div class="mb-4 overflow-hidden rounded-card border border-line">
        <div class="flex justify-between gap-3 border-b border-line px-3 py-2.5 text-[13px]"><span class="text-muted">Your role</span><strong>Developer interconnection manager</strong></div>
        <div class="flex justify-between gap-3 border-b border-line px-3 py-2.5 text-[13px]"><span class="text-muted">Project</span><strong>${esc(s.project)}</strong></div>
        <div class="flex justify-between gap-3 border-b border-line px-3 py-2.5 text-[13px]"><span class="text-muted">File to</span><strong class="text-right">${esc(s.utility || "AES Indiana")} (TO) · ${esc(s.iso)} DPP · ${esc(s.capacity_mw)} MW</strong></div>
        <div class="flex justify-between gap-3 border-b border-line px-3 py-2.5 text-[13px]"><span class="text-muted">POI</span><strong class="text-right">${esc(s.poi)}</strong></div>
        <div class="flex justify-between gap-3 px-3 py-2.5 text-[13px]"><span class="text-muted">Sample SLD</span><strong class="font-mono text-[12px]">${esc(info.sample_drawing)}</strong></div>
      </div>
      <div class="mb-4 flex flex-wrap gap-x-4 gap-y-1 text-[12px]">
        <a class="text-ink underline-offset-2 hover:underline" href="${esc(info.links?.aes_indiana_interconnections || "https://www.aesindiana.com/interconnections")}" target="_blank" rel="noopener">AES Indiana interconnections</a>
        <a class="text-ink underline-offset-2 hover:underline" href="${esc(info.links?.powerclerk || "https://aesindianainterconnection.powerclerk.com")}" target="_blank" rel="noopener">PowerClerk portal</a>
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
      clearOnboard();
      setWizardStep(1);
      await refreshDemoCtx();
      navigate("onboarding");
    } catch (err) {
      status.textContent = err.message;
      btn.disabled = false;
    }
  });
}

/* ---------- Wizard ---------- */
async function renderOnboarding() {
  const me = await ensureAuth();
  if (!me) return;
  if (!me.is_demo) return navigate("dashboard");

  const ctx = (await refreshDemoCtx()) || state.demoCtx || {};
  if (ctx.latest_audit_id) state.lastAuditId = ctx.latest_audit_id;
  const auditId = ctx.latest_audit_id || state.lastAuditId || loadOnboard().lastAuditId || null;

  let step = getWizardStep();
  // Only fall back to pre-file when we truly have no audit — never bounce off triage mid-resolve.
  if (step >= 4 && !auditId) {
    step = 3;
  }

  let auditDetail = null;
  if (auditId && step >= 3) {
    try {
      auditDetail = await api.audit(auditId);
      if (auditDetail?.id) {
        state.lastAuditId = auditDetail.id;
        saveOnboard({ lastAuditId: auditDetail.id });
      }
    } catch {
      auditDetail = null;
    }
  }

  root.innerHTML = shell(
    "Demo setup",
    `<div class="mx-auto max-w-3xl">
      ${wizardStepperHtml(Math.min(step, 5))}
      <div class="${panel} flex min-h-[420px] flex-col overflow-hidden">
        ${renderWizardStep(step, ctx, auditDetail)}
      </div>
    </div>`,
    { showChip: false }
  );
  bindShell();
  bindWizard(step, ctx, auditDetail);
}

function renderWizardStep(step, ctx, auditDetail) {
  const footer = (left, right) => `
    <div class="flex items-center justify-between gap-3 border-t border-line bg-soft px-6 py-3.5">
      <div>${left || ""}</div>
      <div class="flex flex-wrap justify-end gap-2">${right || ""}</div>
    </div>`;

  if (step >= 6 || loadOnboard().completed) {
    return `
      <div class="flex-1 p-7">
        <p class="mb-2 font-mono text-[12px] uppercase tracking-[0.12em] text-muted">Complete</p>
        <h2 class="mb-3 text-2xl tracking-tightish">You are ready to explore the workspace</h2>
        <p class="mb-6 max-w-xl text-[15px] leading-relaxed text-muted">You have walked the core loop: review drawing → audit → triage → report.</p>
        <div class="grid gap-3 sm:grid-cols-3">
          <div class="rounded-card border border-line bg-soft p-4"><span class="font-mono text-[11px] uppercase tracking-[0.08em] text-muted">Project</span><strong class="mt-1 block text-[14px]">${esc(ctx.scenario?.project)}</strong></div>
          <div class="rounded-card border border-line bg-soft p-4"><span class="font-mono text-[11px] uppercase tracking-[0.08em] text-muted">Readiness</span><strong class="mt-1 block text-[14px]">${esc(ctx.readiness_score ?? "—")}</strong></div>
          <div class="rounded-card border border-line bg-soft p-4"><span class="font-mono text-[11px] uppercase tracking-[0.08em] text-muted">Filing gate</span><strong class="mt-1 block text-[14px]">${ctx.can_file ? "Ready to file" : "Needs review"}</strong></div>
        </div>
      </div>
      ${footer(
        `<button type="button" class="${button("ghost", "sm")}" id="wiz-reset">Restart demo</button>`,
        `<a class="${button("ghost")}" href="#/dashboard">Dashboard</a><a class="${button("primary")}" href="#/project/${esc(ctx.project_id)}">Open project</a>`
      )}`;
  }

  if (step === 1) {
    return `
      <div class="flex-1 p-7">
        <p class="mb-2 font-mono text-[12px] uppercase tracking-[0.12em] text-muted">Step 1 of 5</p>
        <h2 class="mb-3 text-2xl tracking-tightish">You are the developer</h2>
        <p class="mb-4 max-w-xl text-[15px] leading-relaxed text-muted">
          At <strong class="text-ink">Northwind Renewables</strong> you build plants — you are not AES Indiana and not MISO.
          <strong class="text-ink">${esc(ctx.scenario?.project)}</strong> is ${esc(ctx.scenario?.capacity_mw)} MW, so the primary queue is
          <strong class="text-ink">${esc(ctx.scenario?.iso)} DPP</strong>, with
          <strong class="text-ink">${esc(ctx.scenario?.utility || "AES Indiana")}</strong> as transmission owner reviewing Facilities Connection Requirements.
        </p>
        <p class="mb-5 max-w-xl text-[14px] leading-relaxed text-muted">
          ${esc(ctx.scenario?.why_this_demo || "Run the public-rules checklist before another consultant cycle or queue RFI.")}
        </p>
        <div class="mb-5 grid gap-3 sm:grid-cols-2">
          <div class="rounded-card border border-line bg-soft p-4"><span class="font-mono text-[11px] uppercase tracking-[0.08em] text-muted">Capacity</span><strong class="mt-1 block">${esc(ctx.scenario?.capacity_mw)} MW</strong></div>
          <div class="rounded-card border border-line bg-soft p-4"><span class="font-mono text-[11px] uppercase tracking-[0.08em] text-muted">POI</span><strong class="mt-1 block">${esc(ctx.scenario?.poi)}</strong></div>
          <div class="rounded-card border border-line bg-soft p-4"><span class="font-mono text-[11px] uppercase tracking-[0.08em] text-muted">Utility (TO)</span><strong class="mt-1 block">${esc(ctx.scenario?.utility || "AES Indiana")}</strong></div>
          <div class="rounded-card border border-line bg-soft p-4"><span class="font-mono text-[11px] uppercase tracking-[0.08em] text-muted">ISO queue</span><strong class="mt-1 block">${esc(ctx.scenario?.iso)} DPP</strong></div>
        </div>
        <div class="mb-3 flex flex-wrap gap-x-4 gap-y-1 text-[12px]">
          <a class="text-ink underline-offset-2 hover:underline" href="${esc(ctx.links?.aes_indiana_interconnections || "https://www.aesindiana.com/interconnections")}" target="_blank" rel="noopener">AES Indiana interconnections →</a>
          <a class="text-ink underline-offset-2 hover:underline" href="${esc(ctx.links?.powerclerk || "https://aesindianainterconnection.powerclerk.com")}" target="_blank" rel="noopener">PowerClerk (utility portal) →</a>
        </div>
        <div class="rounded-card border border-line bg-soft px-4 py-3 text-[13px] text-muted">
          <strong class="mb-1 block text-ink">What GridPilot replaces in this loop</strong>
          Not the PE stamp or the ISO study — the weeks of manual “did we miss ANSI numbers / CT ratios / IBR curves?” before you file.
        </div>
      </div>
      ${footer(`<span class="text-[12px] text-muted">About 5–8 minutes</span>`, `<button type="button" class="${button("primary")}" id="wiz-next">Continue</button>`)}`;
  }

  if (step === 2) {
    return `
      <div class="flex-1 p-7">
        <p class="mb-2 font-mono text-[12px] uppercase tracking-[0.12em] text-muted">Step 2 of 5</p>
        <h2 class="mb-3 text-2xl tracking-tightish">Review the sample single-line diagram</h2>
        <p class="mb-4 max-w-xl text-[15px] leading-relaxed text-muted">
          This CAD-exported PDF includes intentional AES Indiana gaps (missing ANSI relay numbers, blank CT/PT ratios, no IBR P-Q curves) so the audit has clear findings.
        </p>
        <div class="overflow-hidden rounded-card border border-line bg-soft">
          <img
            class="max-h-[420px] w-full object-contain object-top bg-white"
            alt="Sample AES Indiana interconnection SLD"
            src="${esc(ctx.drawing_preview_url || ctx.sample_preview_url || "/assets/img/cedar_ridge_sld_demo.png")}"
          />
        </div>
        <p class="mt-2 font-mono text-[12px] text-muted">${esc(ctx.drawing_filename)} ·
          <a class="text-ink hover:underline" href="${esc(ctx.drawing_url || ctx.sample_pdf_url)}" target="_blank" rel="noopener">Open PDF</a>
          · <a class="text-ink hover:underline" href="${esc(ctx.sample_pdf_url)}" target="_blank" rel="noopener">Sample PDF</a>
        </p>
      </div>
      ${footer(
        `<button type="button" class="${button("ghost")}" id="wiz-back">Back</button>`,
        `<button type="button" class="${button("primary")}" id="wiz-next">I have reviewed the drawing</button>`
      )}`;
  }

  if (step === 3) {
    const status = auditDetail?.status;
    const running = status === "queued" || status === "running";
    const done = status === "completed";
    const failed = status === "failed";
    const statusBox = running
      ? `<div class="mb-4 flex gap-3 rounded-card border border-focus/20 bg-info-soft p-4"><div class="gp-spin mt-0.5 h-4 w-4 rounded-full border-2 border-focus/30 border-t-focus"></div><div><strong class="block text-ink">Audit in progress</strong><p class="text-[13px] text-muted">Usually 20–60 seconds.</p></div></div>`
      : done
        ? `<div class="mb-4 rounded-card border border-ok/30 bg-ok-soft p-4"><strong class="block text-ok">Audit complete</strong><p class="text-[13px] text-muted">Score <strong class="text-ink">${esc(auditDetail.readiness_score)}</strong> · ${esc(auditDetail.blocking_open)} blocker(s) · ${esc(auditDetail.warning_open)} warning(s).</p></div>`
        : failed
          ? `<div class="mb-4 rounded-card border border-danger/30 bg-danger-soft p-4"><strong class="block text-danger">Audit failed</strong><p class="text-[13px]">${esc(auditDetail.error || "Please try again.")}</p></div>`
          : `<div class="mb-4 rounded-card border border-line bg-soft p-4"><strong class="block">Ready to run</strong><p class="text-[13px] text-muted">Audit <span class="font-mono">${esc(ctx.drawing_filename)}</span> against ${esc(ctx.scenario?.iso)}.</p></div>`;

    return `
      <div class="flex-1 p-7">
        <p class="mb-2 font-mono text-[12px] uppercase tracking-[0.12em] text-muted">Step 3 of 5</p>
        <h2 class="mb-3 text-2xl tracking-tightish">Pre-filing audit (before you submit)</h2>
        <p class="mb-5 max-w-xl text-[15px] leading-relaxed text-muted">
          GridPilot reads the SLD with a vision model and scores it against published
          AES Indiana Facilities Connection Requirements (${esc(ctx.scenario?.iso || "MISO")} pack).
          This is the developer-side check — utilities/ISOs may use other tools after you file.
        </p>
        ${statusBox}
      </div>
      ${footer(
        `<button type="button" class="${button("ghost")}" id="wiz-back" ${running ? "disabled" : ""}>Back</button>`,
        done
          ? `<button type="button" class="${button("primary")}" id="wiz-next">Continue to triage</button>`
          : `<button type="button" class="${button("primary")}" id="wiz-run-audit" ${running ? "disabled" : ""}>${failed ? "Retry audit" : running ? "Running…" : "Run audit"}</button>`
      )}`;
  }

  if (step === 4) {
    const findings = (auditDetail?.findings || []).filter((f) => f.severity === "blocking");
    const openBlockers = findings.filter((f) => f.triage === "open");
    const gateClear = Boolean(auditDetail?.filing_gate?.can_file);

    return `
      <div class="flex-1 p-7">
        <p class="mb-2 font-mono text-[12px] uppercase tracking-[0.12em] text-muted">Step 4 of 5</p>
        <h2 class="mb-3 text-2xl tracking-tightish">Clear blocking findings</h2>
        <p class="mb-4 max-w-xl text-[15px] leading-relaxed text-muted">Mark each blocker <strong class="text-ink">Resolved</strong> to simulate engineering sign-off.</p>
        <div class="mb-4 rounded-card border p-4 ${gateClear ? "border-ok/30 bg-ok-soft" : "border-warn/30 bg-warn-soft"}">
          <strong class="block">${gateClear ? "Filing gate clear" : "Filing blocked"}</strong>
          <p class="text-[13px] text-muted">${gateClear ? "You can export the report next." : `${openBlockers.length} open blocker(s) remaining.`}</p>
        </div>
        <div class="space-y-2.5">
          ${
            findings.length
              ? findings
                  .map(
                    (f) => `
              <article class="rounded-card border border-line p-4">
                <div class="mb-2 flex flex-wrap items-center gap-2">${pill(f.triage)}<strong class="text-[14px]">${esc(f.title)}</strong></div>
                <p class="mb-3 text-[13px] text-muted">${esc(f.detail)}</p>
                ${
                  f.triage === "open"
                    ? `<button type="button" class="${button("primary", "sm")}" data-resolve="${esc(f.id)}">Mark resolved</button>`
                    : `<span class="text-[12px] text-muted">Signed off in demo</span>`
                }
              </article>`
                  )
                  .join("")
              : `<p class="text-muted">No blocking findings. Continue to the report.</p>`
          }
        </div>
      </div>
      ${footer(
        `<button type="button" class="${button("ghost")}" id="wiz-back">Back</button>`,
        `${
          auditDetail?.id || ctx.latest_audit_id
            ? `<button type="button" class="${button("ghost")}" id="wiz-full-triage">Full triage view</button>`
            : ""
        }
         <button type="button" class="${button("primary")}" id="wiz-next" ${!gateClear && openBlockers.length ? "disabled" : ""}>${gateClear || !openBlockers.length ? "Continue" : "Resolve blockers to continue"}</button>`
      )}`;
  }

  return `
    <div class="flex-1 p-7">
      <p class="mb-2 font-mono text-[12px] uppercase tracking-[0.12em] text-muted">Step 5 of 5</p>
      <h2 class="mb-3 text-2xl tracking-tightish">Export — then file outside GridPilot</h2>
      <p class="mb-5 max-w-xl text-[15px] leading-relaxed text-muted">
        Share this readiness report with your consultant or internal PE. Next real step: submit to
        <strong class="text-ink">${esc(ctx.scenario?.utility || "AES Indiana")}</strong> / <strong class="text-ink">${esc(ctx.scenario?.iso || "MISO")}</strong>
        — GridPilot stops at pre-filing QA.
      </p>
      <div class="mb-5 grid gap-3 sm:grid-cols-3">
        <div class="rounded-card border border-line bg-soft p-4"><span class="font-mono text-[11px] uppercase tracking-[0.08em] text-muted">Score</span><strong class="mt-1 block text-xl">${esc(auditDetail?.readiness_score ?? ctx.readiness_score ?? "—")}</strong></div>
        <div class="rounded-card border border-line bg-soft p-4"><span class="font-mono text-[11px] uppercase tracking-[0.08em] text-muted">Status</span><strong class="mt-1 block">${esc(auditDetail?.readiness_status || "—")}</strong></div>
        <div class="rounded-card border border-line bg-soft p-4"><span class="font-mono text-[11px] uppercase tracking-[0.08em] text-muted">Rule pack</span><strong class="mt-1 block">${esc(ctx.scenario?.utility || "AES")} / ${esc(ctx.scenario?.iso)}</strong></div>
      </div>
    </div>
    ${footer(
      `<button type="button" class="${button("ghost")}" id="wiz-back">Back</button>`,
      `${ctx.latest_audit_id ? `<a class="${button("ghost")}" href="/api/audits/${esc(ctx.latest_audit_id)}/report.html" target="_blank">Open HTML report</a>` : ""}
       <button type="button" class="${button("primary")}" id="wiz-finish">Finish demo</button>`
    )}`;
}

function bindWizard(step, ctx, auditDetail) {
  document.querySelectorAll("[data-goto]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const n = Number(btn.getAttribute("data-goto"));
      if (n >= 1 && n <= step) {
        setWizardStep(n);
        render();
      }
    });
  });
  document.getElementById("wiz-back")?.addEventListener("click", () => {
    setWizardStep(Math.max(1, step - 1));
    render();
  });
  document.getElementById("wiz-next")?.addEventListener("click", () => {
    const next = Math.min(6, step + 1);
    if (auditDetail?.id) {
      state.lastAuditId = auditDetail.id;
      saveOnboard({ lastAuditId: auditDetail.id, wizardStep: next });
    } else {
      setWizardStep(next);
    }
    render();
  });
  document.getElementById("wiz-full-triage")?.addEventListener("click", () => {
    const id = auditDetail?.id || ctx.latest_audit_id;
    if (!id) {
      toast("No audit available yet — run the audit first");
      return;
    }
    navigate(`audit/${id}`);
  });
  document.getElementById("wiz-finish")?.addEventListener("click", () => {
    saveOnboard({ completed: true, wizardStep: 6 });
    toast("Demo complete");
    navigate("dashboard");
  });
  document.getElementById("wiz-reset")?.addEventListener("click", async () => {
    try {
      await api.resetDemo();
      clearOnboard();
      setWizardStep(1);
      await refreshDemoCtx();
      toast("Demo reset");
      render();
    } catch (err) {
      toast(err.message);
    }
  });
  document.getElementById("wiz-run-audit")?.addEventListener("click", async () => {
    try {
      toast("Starting audit…");
      const started = await api.startAudit(ctx.project_id, ctx.drawing_id);
      if (started?.id) {
        state.lastAuditId = started.id;
        saveOnboard({ lastAuditId: started.id });
      }
      setWizardStep(3);
      render();
    } catch (err) {
      toast(err.message);
    }
  });
  document.querySelectorAll("[data-resolve]").forEach((btn) => {
    btn.addEventListener("click", async (ev) => {
      ev.preventDefault();
      ev.stopPropagation();
      const findingId = btn.getAttribute("data-resolve");
      const id = auditDetail?.id || ctx.latest_audit_id || state.lastAuditId;
      if (!id || !findingId) {
        toast("Missing audit finding — try Full triage view");
        return;
      }
      try {
        btn.disabled = true;
        await api.triage(id, findingId, {
          triage: "resolved",
          note: "Resolved during guided demo",
        });
        toast("Finding resolved");
        setWizardStep(4);
        saveOnboard({ lastAuditId: id, wizardStep: 4 });
        render();
      } catch (err) {
        btn.disabled = false;
        toast(err.message);
      }
    });
  });
  if (step === 3 && auditDetail && ["queued", "running"].includes(auditDetail.status)) {
    setTimeout(() => {
      if (route().name === "onboarding" && getWizardStep() === 3) render();
    }, 2500);
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
function openProjectModal() {
  state.modal = `
  <div class="fixed inset-0 z-20 grid place-items-center bg-ink/40 p-5" id="modal">
    <form class="${panel} w-full max-w-md p-6" id="project-form">
      <h3 class="mb-4 text-lg tracking-tightish">Add project</h3>
      <div class="mb-3"><label class="${label}">Project name</label><input class="${field}" name="name" required /></div>
      <div class="mb-3"><label class="${label}">ISO / RTO</label><select class="${field}" name="iso"><option>PJM</option><option>MISO</option><option>ERCOT</option></select></div>
      <div class="mb-3"><label class="${label}">Capacity (MW)</label><input class="${field}" name="capacity_mw" type="number" step="0.1" /></div>
      <div class="mb-3"><label class="${label}">State</label><input class="${field}" name="state" placeholder="IN" /></div>
      <div class="mb-5"><label class="${label}">POI substation</label><input class="${field}" name="poi_substation" /></div>
      <div class="flex justify-end gap-2">
        <button type="button" class="${button("ghost")}" id="modal-cancel">Cancel</button>
        <button type="submit" class="${button("primary")}">Create</button>
      </div>
    </form>
  </div>`;
  render();
  document.getElementById("modal-cancel")?.addEventListener("click", () => {
    state.modal = null;
    render();
  });
  document.getElementById("project-form")?.addEventListener("submit", async (e) => {
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
}

async function renderDashboard() {
  const me = await ensureAuth();
  if (!me) return;
  await refreshDemoCtx();
  if (me.is_demo && !loadOnboard().completed && getWizardStep() < 6) {
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
          <label class="${button("ghost", "sm")} cursor-pointer">Upload SLD<input id="draw-file" type="file" accept=".pdf,image/png,image/jpeg" hidden /></label>
          <button class="${button("primary", "sm")}" id="run-audit" ${data.drawings.length ? "" : "disabled"}>Run audit</button>
        </div>
      </div>
    </div>
    ${
      data.drawings[0]
        ? `<div class="${panel} mb-4 overflow-hidden">
            <div class="flex items-center justify-between border-b border-line px-4 py-3"><h3 class="text-[14px]">Latest drawing</h3><span class="font-mono text-[11px] text-muted">${esc(data.drawings[0].filename)}</span></div>
            <a href="/api/projects/${esc(p.id)}/drawings/${esc(data.drawings[0].id)}/file" target="_blank" rel="noopener" class="block bg-soft">
              <img class="max-h-[480px] w-full object-contain object-top bg-white" alt="SLD preview" src="/api/projects/${esc(p.id)}/drawings/${esc(data.drawings[0].id)}/preview.png" />
            </a>
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
                <td class="${table.td}"><a class="hover:underline" href="/api/projects/${p.id}/drawings/${d.id}/file" target="_blank">${esc(d.filename)}</a></td>
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
        <a class="${button("ghost", "sm")} mt-3" href="/api/audits/${a.id}/report.html" target="_blank">HTML report</a>
      </div>
    </div>
    <div class="grid gap-4 lg:grid-cols-2">
      <div class="space-y-4">
        <div class="${panel} overflow-hidden">
          <div class="flex items-center justify-between border-b border-line px-4 py-3"><h3 class="text-[14px]">Drawing</h3><span class="font-mono text-[11px] text-muted">${esc(a.drawing_filename || "")}</span></div>
          ${
            a.project_id && a.drawing_id
              ? `<a href="/api/projects/${esc(a.project_id)}/drawings/${esc(a.drawing_id)}/file" target="_blank" rel="noopener" class="block bg-soft">
                   <img class="max-h-[480px] w-full object-contain object-top bg-white" alt="SLD preview" src="/api/projects/${esc(a.project_id)}/drawings/${esc(a.drawing_id)}/preview.png" />
                 </a>`
              : ""
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
          <span class="text-[12px] text-muted">${findings.length} items</span>
        </div>
        <div class="space-y-2.5">
          ${findings
            .map(
              (f) => `
            <article class="rounded-card border border-line p-3.5" data-id="${esc(f.id)}">
              <div class="mb-1 font-mono text-[10px] uppercase tracking-[0.08em] text-muted">${esc(f.severity)} · ${esc(f.rule_id || "custom")} · ${pill(f.triage)}</div>
              <h4 class="mb-1 text-[14px] tracking-tightish">${esc(f.title)}</h4>
              <p class="text-[13px] text-muted">${esc(f.detail)}</p>
              ${f.recommendation ? `<p class="mt-1 text-[13px]"><strong>Fix:</strong> ${esc(f.recommendation)}</p>` : ""}
              ${
                f.severity !== "ready"
                  ? `<div class="mt-2.5 flex flex-wrap gap-1.5">
                      <button class="${button("ghost", "sm")}" data-triage="acknowledged">Acknowledge</button>
                      <button class="${button("primary", "sm")}" data-triage="resolved">Resolve</button>
                      <button class="${button("ghost", "sm")}" data-triage="dismissed">Dismiss</button>
                      <button class="${button("ghost", "sm")}" data-triage="open">Reopen</button>
                    </div>`
                  : ""
              }
            </article>`
            )
            .join("")}
        </div>
      </div>
    </div>`
  );
  bindShell();
  document.getElementById("back-to-demo")?.addEventListener("click", () => {
    setWizardStep(4);
    navigate("onboarding");
  });
  root.querySelectorAll("[data-triage]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const article = btn.closest("[data-id]");
      try {
        await api.triage(a.id, article.dataset.id, { triage: btn.getAttribute("data-triage") });
        toast(`Marked ${btn.getAttribute("data-triage")}`);
        render();
      } catch (err) {
        toast(err.message);
      }
    });
  });
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

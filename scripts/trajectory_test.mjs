// Exhaustive user-trajectory test for the real app + demo extras.
//   A. Auth: duplicate signup, wrong password, logout, re-login (account restore)
//   B. Manual wizard path: attach files, NO AI extraction, hand-filled intake,
//      validate → generate → all 15 previews + zip
//   C. Wizard navigation: back buttons, refresh persistence, remove file
//   D. PNG SLD upload → REAL AI audit → every triage action → HTML report
//   E. Billing upgrade (free → pro)
//   F. Demo extras: restart, stepper back-navigation, kickoff/requirement previews
// Usage: node scripts/trajectory_test.mjs [base_url]
import { chromium } from "playwright-core";
import { mkdirSync } from "fs";

const BASE = process.argv[2] || "http://127.0.0.1:8000";
const shots = "/tmp/gp_traj";
mkdirSync(shots, { recursive: true });
const FIX = "/tmp/gp_fixtures";
let failures = 0;
const check = (name, ok) => {
  console.log(`${ok ? "PASS" : "FAIL"}  ${name}`);
  if (!ok) failures++;
};

const browser = await chromium.launch({
  executablePath: "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
});
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
page.on("pageerror", (e) => console.log("PAGEERROR:", e.message));
page.on("console", (m) => {
  if (m.type() === "error") console.log("CONSOLE ERR:", m.text());
});

const email = `traj-${Date.now()}@acme-energy.com`;
const password = "sunny-12345";

/* ================= A. Auth trajectories ================= */
await page.goto(BASE + "/app#/signup");
await page.waitForSelector("#auth-form");
await page.fill('[name="name"]', "Jordan Lee");
await page.fill('[name="org_name"]', "Acme Trajectories");
await page.fill('[name="email"]', email);
await page.fill('[name="password"]', password);
await page.click('button[type="submit"]');
await page.waitForSelector("#new-project-btn", { timeout: 20000 });
check("A1 signup → dashboard", true);

// duplicate signup shows an error
await page.click("#logout-link");
await page.waitForSelector("#auth-form");
await page.goto(BASE + "/app#/signup");
await page.waitForSelector('[name="org_name"]');
await page.fill('[name="name"]', "Jordan Lee");
await page.fill('[name="org_name"]', "Acme Again");
await page.fill('[name="email"]', email);
await page.fill('[name="password"]', password);
await page.click('button[type="submit"]');
await page.waitForSelector("#auth-error:not(.hidden)", { timeout: 15000 });
check("A2 duplicate signup shows error", (await page.textContent("#auth-error")).includes("already registered"));

// wrong password shows an error
await page.goto(BASE + "/app#/login");
await page.waitForSelector('[name="email"]');
await page.fill('[name="email"]', email);
await page.fill('[name="password"]', "wrong-password");
await page.click('button[type="submit"]');
await page.waitForSelector("#auth-error:not(.hidden)", { timeout: 15000 });
check("A3 wrong password shows error", (await page.textContent("#auth-error")).includes("Invalid"));

// correct login works (account-restore path on serverless)
await page.fill('[name="password"]', password);
await page.click('button[type="submit"]');
await page.waitForSelector("#new-project-btn", { timeout: 20000 });
check("A4 re-login after logout", true);

/* ================= B. Manual wizard path (no AI) ================= */
await page.click("#new-project-btn");
await page.waitForSelector("#project-form");
await page.fill('#project-form [name="name"]', "Manual Path Solar");
await page.selectOption('#project-form [name="iso"]', "CAISO");
await page.fill('#project-form [name="capacity_mw"]', "105");
await page.click('#project-form button[type="submit"]');
await page.waitForSelector('a:has-text("Interconnection request")', { timeout: 15000 });
await page.click('a:has-text("Interconnection request")');
await page.waitForSelector("#req-extract", { timeout: 15000 });

// attach the two required documents, skip AI
await page.setInputFiles('[data-req-input="file_site_control"]', `${FIX}/Acme_Lease_SunriseRanch_Executed.pdf`);
await page.setInputFiles('[data-req-input="file_technical"]', `${FIX}/Acme_TechnicalData_Workbook.xlsx`);
await page.waitForTimeout(400);
await page.click("#req-skip");
await page.waitForSelector("#req-intake-form", { timeout: 15000 });
check("B1 manual path reaches intake", true);

const fillIntake = async (vals) => {
  for (const [k, v] of Object.entries(vals)) {
    const el = page.locator(`[data-intake="${k}"]`);
    if ((await el.evaluate((n) => n.tagName)) === "SELECT") await el.selectOption(v);
    else await el.fill(String(v));
  }
};
await fillIntake({
  legal_name: "Acme Desert One LLC", state_of_origin: "Delaware",
  signatory_name: "Jordan Lee", signatory_title: "VP, Development",
  contact_email: email, contact_phone: "(760) 555-0100",
  project_name: "Manual Path Solar", gps_lat: 33.7415, gps_lon: -115.9821,
  county: "Riverside", state: "CA", site_acreage: 640,
  site_control: "Lease Agreement", site_owner: "Sunrise Ranch Holdings LP",
  poi_name: "Devers Substation (SCE)", poi_voltage_kv: 115,
  track: "Independent Study Process", cod: "2028-12-31",
  project_type: "Solar PV", gross_mva: 112, gross_mw: 108,
  aux_mw: 2, losses_mw: 1, net_mw_poi: 105,
  inverter: "TBD", dyd_status: "Requested — pending",
});
await page.click("#req-validate");
await page.waitForSelector("#req-generate, #req-back-2b", { timeout: 20000 });
const manualClean = (await page.locator("text=Intake is clean").count()) > 0;
check("B2 manual intake validates clean", manualClean);
if (!manualClean) {
  console.log("   validation body:", (await page.textContent("body")).slice(0, 1200));
  await page.screenshot({ path: shots + "/B2_validation.png", fullPage: true });
}

await page.click("#req-generate");
await page.waitForSelector("text=CAISO submission packet", { timeout: 120000 });
check("B3 manual path generates packet", true);

// every packet document preview + download resolves
const urls = await page.$$eval("[data-drawer-url]", (ns) =>
  ns.map((n) => ({ p: n.getAttribute("data-drawer-url"), d: n.getAttribute("data-drawer-download") }))
);
let previewsOk = 0;
for (const u of urls) {
  const pr = await page.request.get(BASE + u.p);
  const dr = await page.request.get(BASE + u.d);
  if (pr.status() === 200 && dr.status() === 200) previewsOk++;
  else console.log("   preview/download failed:", u.p, pr.status(), dr.status());
}
check(`B4 all ${urls.length} packet previews + downloads 200`, previewsOk === urls.length && urls.length >= 14);
const zipHref = await page.getAttribute('a:has-text("Download packet (.zip)")', "href");
const zipRes = await page.request.get(BASE + zipHref);
check("B5 zip download", zipRes.status() === 200 && (await zipRes.body()).length > 10000);

/* ================= C. Wizard navigation ================= */
await page.click("#req-back-2");
await page.waitForSelector("#req-intake-form", { timeout: 15000 });
check("C1 packet → edit intake", true);
await page.click("#req-back-1");
await page.waitForSelector("#req-extract", { timeout: 15000 });
check("C2 intake → documents", true);

// remove a file slot
await page.locator('[data-req-remove="file_site_control"]').click();
await page.waitForTimeout(400);
check("C3 remove file", (await page.locator('[data-req-attach="file_site_control"]').count()) === 1);
await page.setInputFiles('[data-req-input="file_site_control"]', `${FIX}/Acme_Lease_SunriseRanch_Executed.pdf`);
await page.waitForTimeout(400);

// refresh persistence: reload should come back to the same step with data intact
await page.reload();
await page.waitForSelector("#req-extract", { timeout: 15000 });
await page.click("#req-skip");
await page.waitForSelector("#req-intake-form", { timeout: 15000 });
const persistedLegal = await page.inputValue('[data-intake="legal_name"]');
check("C4 refresh keeps intake data", persistedLegal === "Acme Desert One LLC");

/* ================= D. PNG SLD upload → real AI audit → triage ================= */
await page.goto(BASE + "/app#/projects");
await page.click('a:has-text("Open →")');
await page.waitForSelector("#draw-file", { state: "attached", timeout: 15000 });
await page.setInputFiles("#draw-file", `${FIX}/Acme_SLD_RevB.png`);
await page.waitForSelector("text=Drawing uploaded", { timeout: 60000 });
check("D1 PNG drawing upload (converted to PDF)", true);
await page.click("#run-audit");
console.log("   … real Grok vision audit running");
await page.waitForSelector("text=Readiness", { timeout: 300000 });
check("D2 real AI audit completes", true);
await page.screenshot({ path: shots + "/D2_audit.png", fullPage: true });

// triage: resolve → reopen → acknowledge → dismiss
const triage = async (kind) => {
  const btn = page.locator(`[data-triage="${kind}"]`).first();
  if ((await btn.count()) === 0) return false;
  await btn.click();
  await page.waitForTimeout(1200);
  return true;
};
check("D3 resolve finding", await triage("resolved"));
check("D4 reopen finding", await triage("open"));
check("D5 acknowledge finding", await triage("acknowledged"));
check("D6 dismiss finding", await triage("dismissed"));

const reportBtn = page.locator('[data-drawer-url*="report.html"]');
const reportUrl = await reportBtn.getAttribute("data-drawer-url");
const rep = await page.request.get(BASE + reportUrl);
check("D7 HTML report renders", rep.status() === 200 && (await rep.text()).includes("GridPilot"));

/* ================= E. Billing upgrade ================= */
await page.goto(BASE + "/app#/billing");
await page.waitForSelector("#upgrade-btn", { timeout: 15000 });
await page.click("#upgrade-btn");
await page.waitForSelector("#upgrade-btn", { state: "detached", timeout: 15000 });
const planCard = await page.textContent("body");
check("E1 upgrade free → pro", planCard.includes("pro"));

/* ================= F. Demo extras ================= */
await page.click("#logout-link");
await page.waitForSelector("#auth-form", { timeout: 15000 });
await page.goto(BASE + "/app#/demo");
await page.waitForSelector("#start-demo-btn");
await page.click("#start-demo-btn");
await page.waitForSelector("#wiz-next", { timeout: 20000 });

// documents step: kickoff preview of a staged example file
await page.click("#wiz-next");
await page.waitForSelector("#wiz-extract", { timeout: 15000 });
await page.click('[data-file-preview="file_site_control"]');
await page.waitForSelector("#gp-drawer iframe", { timeout: 10000 });
const leaseSrc = await page.getAttribute("#gp-drawer iframe", "src");
const leaseHtml = await (await page.request.get(BASE + leaseSrc)).text();
check("F1 kickoff lease preview renders", leaseHtml.includes("GROUND LEASE") || leaseHtml.toLowerCase().includes("lease"));
await page.keyboard.press("Escape");
await page.waitForTimeout(300);

// stepper: jump back to step 1 and forward again
await page.click('[data-goto="1"]');
await page.waitForSelector("#wiz-next", { timeout: 10000 });
check("F2 stepper back-navigation", true);
await page.click("#wiz-next");
await page.waitForSelector("#wiz-extract", { timeout: 10000 });

// requirement preview endpoint (ground truth behind a validation rule)
const reqPrev = await page.request.get(BASE + "/api/caiso/requirements/mw-chain/preview");
check("F3 requirement preview endpoint", reqPrev.status() === 200);

// restart demo from step 2
await page.goto(BASE + "/app#/onboarding");
await page.waitForSelector("#wiz-extract, #wiz-next", { timeout: 15000 });
// walk to completion is covered elsewhere; here test restart via completed-screen path
await page.evaluate(() => {
  localStorage.setItem("gp_demo_onboard_v4", JSON.stringify({ completed: true, wizardStep: 7 }));
});
await page.goto(BASE + "/app#/onboarding");
await page.waitForSelector("#wiz-reset", { timeout: 15000 });
await page.click("#wiz-reset");
await page.waitForSelector("#wiz-next", { timeout: 15000 });
check("F4 restart demo returns to step 1", true);

await browser.close();
console.log(failures === 0 ? "TRAJECTORY TEST DONE — ALL PASS" : `TRAJECTORY TEST DONE — ${failures} FAILURE(S)`);
process.exit(failures === 0 ? 0 : 1);

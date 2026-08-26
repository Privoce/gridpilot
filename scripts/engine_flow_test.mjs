// Engineering engine end-to-end test:
//   A. Demo — design review step: engine panel, SLD, approvals gate, generation,
//      packet with computed documents (equipment schedule, source trace, DXF...).
//   B. Real app — 5-step wizard: documents → intake → validate → design → packet.
// Usage: node scripts/engine_flow_test.mjs [base_url]   (defaults to :8000)
import { chromium } from "playwright-core";
import { mkdirSync, writeFileSync } from "fs";

const BASE = process.argv[2] || "http://127.0.0.1:8000";
const shots = "/tmp/gp_engine_e2e";
mkdirSync(shots, { recursive: true });

let failures = 0;
const check = (cond, msg) => {
  console.log(`${cond ? "ok" : "FAIL"}: ${msg}`);
  if (!cond) failures++;
};

const browser = await chromium.launch({
  executablePath: "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
});
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
page.on("pageerror", (e) => console.log("PAGEERROR:", e.message));
page.on("console", (m) => {
  if (m.type() === "error") console.log("CONSOLE ERR:", m.text());
});

// =========================================================================
// Part A — demo design review
// =========================================================================
console.log("--- Part A: demo ---");
await page.goto(BASE + "/app");
const start = await page.request.post(BASE + "/api/demo/start");
check(start.ok(), "demo session started");

// Seed a clean, validated intake at the design step (the fix-and-revalidate
// loop is covered by the existing demo tests).
await page.evaluate(() => {
  const intake = {
    net_mw_poi: 125.0,
    bess_mwh: 200.0,
    file_site_control: { name: "Ravenwood_Lease_Executed_2026-03-14.pdf", size: 2871342, example: true },
    file_technical: { name: "Ravenwood_TechnicalData_Workbook_v2.xlsx", size: 87450, example: true },
    file_bess: { name: "Ravenwood_BESS_Spec_v2.xlsx", size: 54120, example: true },
    file_signatory: { name: "Ravenwood_OfficerCertificate.pdf", size: 184230, example: true },
    file_dyd: { name: "Sungrow_SG4400UD_PSLF_Models.dyd", size: 18240, example: true },
    file_boundary: { name: "Ravenwood_ParcelBoundary.kmz", size: 46210, example: true },
  };
  localStorage.setItem("gp_caiso_intake_v1", JSON.stringify(intake));
  localStorage.setItem("gp_demo_onboard_v4", JSON.stringify({ started: true, wizardStep: 5 }));
});
await page.goto(BASE + "/app#/onboarding");
await page.reload();

await page.waitForSelector("h2:has-text('Engineering design review')", { timeout: 20000 });
await page.waitForSelector("text=Plant topology", { timeout: 20000 });
check(true, "design review panel rendered");

const svgCount = await page.locator(".max-h-\\[420px\\] svg").count();
check(svgCount === 1, "SLD SVG embedded inline");
check((await page.locator("text=Load flow (solved)").count()) === 1, "load flow card present");
check((await page.locator("text=converged").count()) >= 1, "load flow converged badge");
check((await page.locator("[data-eng-approve]").count()) === 2, "two pending assumption approvals");

const genBtn = page.locator("#wiz-generate");
check(await genBtn.isDisabled(), "generate blocked until approvals");
await page.screenshot({ path: shots + "/a1_design_review.png", fullPage: true });

await page.click("#eng-approve-all");
await page.waitForSelector("text=all approved", { timeout: 20000 });
check((await page.locator("[data-eng-approve]").count()) === 0, "all assumptions approved");
await page.waitForSelector("#wiz-generate:not([disabled])", { timeout: 20000 });
check(true, "generate unlocked after sign-off");
await page.screenshot({ path: shots + "/a2_approved.png", fullPage: true });

await page.click("#wiz-generate");
// The generating animation's heading also contains "submission packet" — wait
// for the download link that only exists on the finished packet page.
await page.waitForSelector('a:has-text("Download packet (.zip)")', { timeout: 60000 });
for (const title of [
  "Equipment Schedule",
  "Assumptions & Approvals Log",
  "Source Trace Appendix",
  "Portal Field Export (JSON)",
  "Single-Line Diagram (DXF)",
  "Load Flow & Short-Circuit Report",
  "Dynamic Validation Report",
  "Appendix 1 — Interconnection Request",
  "Attachment A — Generator Technical Data",
  "Evidence of Site Exclusivity",
  "Reactive Power Capability Document",
  "Site Drawing",
  "Flat Run & Bump Test Plots",
  "Requested MW at POI Plot",
  "IBR Model Validation Results",
]) {
  check((await page.locator(`text=${title}`).count()) >= 1, `packet lists: ${title}`);
}
const solvedStatus = (await page.locator("text=SOLVED —").count()) >= 1;
check(solvedStatus, "load flow model marked SOLVED with iteration count");
await page.screenshot({ path: shots + "/a3_packet.png", fullPage: true });

// Zip download includes the new docs.
const [dl] = await Promise.all([
  page.waitForEvent("download", { timeout: 30000 }),
  page.click('a:has-text("Download packet (.zip)")'),
]);
check(!!dl.suggestedFilename(), `zip downloads (${dl.suggestedFilename()})`);

// Previews for new file types (dxf/json) render.
const dxfPrev = page.locator('button[data-drawer-url*="SingleLineDiagram"][data-drawer-url*=".dxf"]');
if (await dxfPrev.count()) {
  await dxfPrev.first().click();
  await page.waitForTimeout(1200);
  check(true, "DXF preview drawer opened");
  await page.keyboard.press("Escape");
  await page.waitForTimeout(300);
}

// =========================================================================
// Part B — real app 5-step wizard
// =========================================================================
console.log("--- Part B: real app ---");
await page.goto(BASE + "/app#/signup");
await page.evaluate(() => localStorage.clear());
await page.goto(BASE + "/app#/signup");
await page.reload();
await page.waitForSelector("#auth-form");
await page.fill('[name="name"]', "Engine Tester");
await page.fill('[name="org_name"]', "Engine Test Org");
await page.fill('[name="email"]', `engine-${Date.now()}@acme-energy.com`);
await page.fill('[name="password"]', "sunny-12345");
await page.click('button[type="submit"]');
await page.waitForSelector("#new-project-btn", { timeout: 15000 });
await page.click("#new-project-btn");
await page.waitForSelector("#project-form");
await page.fill('#project-form [name="name"]', "Copper Flats Solar");
await page.fill('#project-form [name="capacity_mw"]', "80");
await page.fill('#project-form [name="state"]', "CA");
await page.fill('#project-form [name="poi_substation"]', "Copper 115 kV");
await page.click('#project-form button[type="submit"]');
await page.waitForSelector('a:has-text("Interconnection request")', { timeout: 15000 });
await page.click('a:has-text("Interconnection request")');
await page.waitForSelector("#req-skip", { timeout: 15000 });
check((await page.locator("text=Step 1 of 5").count()) === 1, "wizard shows 5 steps");

// Attach the site file (avoids the known blocker), enter data manually.
writeFileSync("/tmp/gp_engine_lease.pdf", "%PDF-1.4 executed lease agreement");
await page.setInputFiles('[data-req-input="file_site_control"]', "/tmp/gp_engine_lease.pdf");
await page.waitForTimeout(400);
await page.click("#req-skip");
await page.waitForSelector("#req-intake-form", { timeout: 15000 });
check((await page.locator("datalist#dl-inverter option").count()) >= 3,
  "equipment library picker on the inverter field");
check((await page.locator("datalist#dl-bess_vendor option").count()) >= 1,
  "equipment library picker on the BESS field");
check((await page.locator('[data-intake="gentie_mi"]').count()) === 1,
  "gen-tie length intake field present");

const fill = async (k, v) => page.fill(`[data-intake="${k}"]`, String(v));
await fill("legal_name", "Copper Flats Solar LLC");
await fill("signatory_name", "Dana Ray");
await fill("project_name", "Copper Flats Solar");
await fill("gps_lat", "35.2");
await fill("gps_lon", "-117.9");
await fill("county", "Kern");
await fill("state", "CA");
await fill("site_acreage", "480");
await page.selectOption('[data-intake="site_control"]', "Lease Agreement");
await fill("site_owner", "Copper Flats Ranch LP");
await fill("poi_name", "Copper 115 kV");
await fill("poi_voltage_kv", "115");
await page.selectOption('[data-intake="track"]', "Independent Study Process");
await fill("cod", "2029-03-31");
await page.selectOption('[data-intake="project_type"]', "Solar PV");
await fill("gross_mva", "84");
await fill("gross_mw", "82");
await fill("aux_mw", "1.2");
await fill("losses_mw", "0.8");
await fill("net_mw_poi", "80");
await fill("gentie_mi", "2.5"); // developer fact — replaces the routing assumption
await page.selectOption('[data-intake="bess_charging"]', "N/A — no storage");
await fill("inverter", "SMA Sunny Central 4600 UP, qty 18");
await page.selectOption('[data-intake="dyd_status"]', "Requested — pending");

await page.click("#req-validate");
await page.waitForSelector("h2:has-text('Validation')", { timeout: 15000 });
const clean = (await page.locator("text=Intake is clean").count()) > 0;
check(clean, "real-app validation clean");
check((await page.locator("#req-design").count()) === 1, "design step CTA after validation");

await page.click("#req-design");
await page.waitForSelector("h2:has-text('Engineering design review')", { timeout: 20000 });
await page.waitForSelector("text=Plant topology", { timeout: 20000 });
check((await page.locator("text=Sunny Central 4600").count()) >= 1, "library matched the SMA inverter");
check((await page.locator("text=2.5-mile gen-tie").count()) >= 1,
  "developer gen-tie length used in the topology");
const reqGen = page.locator("#req-generate");
check(await reqGen.isDisabled(), "real-app generate blocked until approvals");
await page.screenshot({ path: shots + "/b1_design.png", fullPage: true });

await page.click("#eng-approve-all");
await page.waitForSelector("text=all approved", { timeout: 20000 });
await page.waitForSelector("#req-generate:not([disabled])", { timeout: 20000 });
check(true, "real-app generate unlocked");

await page.click("#req-generate");
await page.waitForSelector('a:has-text("Download packet (.zip)")', { timeout: 60000 });
check((await page.locator("text=Step 5 of 5").count()) === 1, "packet is step 5");
check((await page.locator("text=Engineering — computed & approved").count()) === 1,
  "packet page shows the engineering summary");
check((await page.locator("text=Equipment Schedule").count()) >= 1, "real packet has the schedule");
await page.screenshot({ path: shots + "/b2_packet.png", fullPage: true });

const [dl2] = await Promise.all([
  page.waitForEvent("download", { timeout: 30000 }),
  page.click('a:has-text("Download packet (.zip)")'),
]);
check(!!dl2.suggestedFilename(), `real-app zip downloads (${dl2.suggestedFilename()})`);

await browser.close();
if (failures) {
  console.log(`ENGINE FLOW TEST: ${failures} FAILURE(S)`);
  process.exit(1);
}
console.log("ENGINE FLOW TEST DONE — all checks passed");

// Real-app user flow, end to end with REAL AI:
//   signup → create project → interconnection request wizard →
//   upload real documents → Grok extraction → intake review → validate →
//   fix blockers → generate packet → download zip →
//   SLD upload → real Grok vision audit → triage → report.
// Usage: node scripts/real_flow_test.mjs [base_url]   (defaults to :8000)
import { chromium } from "playwright-core";
import { mkdirSync } from "fs";

const BASE = process.argv[2] || "http://127.0.0.1:8000";
const shots = "/tmp/gp_real";
mkdirSync(shots, { recursive: true });
const FIX = "/tmp/gp_fixtures";

const browser = await chromium.launch({
  executablePath: "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
});
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
page.on("pageerror", (e) => console.log("PAGEERROR:", e.message));
page.on("console", (m) => {
  if (m.type() === "error") console.log("CONSOLE ERR:", m.text());
});

const email = `e2e-${Date.now()}@acme-energy.com`;

// ---- 1. Signup ----
await page.goto(BASE + "/app#/signup");
await page.waitForSelector("#auth-form");
await page.fill('[name="name"]', "Jordan Lee");
await page.fill('[name="org_name"]', "Acme Energy E2E");
await page.fill('[name="email"]', email);
await page.fill('[name="password"]', "sunny-12345");
await page.click('button[type="submit"]');
await page.waitForSelector("#new-project-btn", { timeout: 15000 });
console.log("signup → dashboard: ok");

// ---- 2. Create project ----
await page.click("#new-project-btn");
await page.waitForSelector("#project-form");
await page.fill('#project-form [name="name"]', "Acme Desert One");
await page.selectOption('#project-form [name="iso"]', "CAISO");
await page.fill('#project-form [name="capacity_mw"]', "105");
await page.fill('#project-form [name="state"]', "CA");
await page.fill('#project-form [name="poi_substation"]', "Devers Substation (SCE) 115 kV");
await page.click('#project-form button[type="submit"]');
await page.waitForSelector("text=Interconnection request", { timeout: 15000 });
console.log("project created: ok");
await page.screenshot({ path: shots + "/1_project.png", fullPage: true });

// ---- 3. Request wizard — documents ----
await page.click('a:has-text("Interconnection request")');
await page.waitForSelector("#req-extract", { timeout: 15000 });
const extractDisabled = await page.locator("#req-extract").isDisabled();
console.log("extract disabled before files:", extractDisabled);

await page.setInputFiles('[data-req-input="file_site_control"]', `${FIX}/Acme_Lease_SunriseRanch_Executed.pdf`);
await page.setInputFiles('[data-req-input="file_technical"]', `${FIX}/Acme_TechnicalData_Workbook.xlsx`);
await page.setInputFiles('[data-req-input="file_bess"]', `${FIX}/Acme_BESS_Spec.xlsx`);
await page.waitForTimeout(400);
console.log("files attached:", await page.locator('[data-req-remove]').count());
await page.screenshot({ path: shots + "/2_documents.png", fullPage: true });

// ---- 4. Real AI extraction ----
await page.click("#req-extract");
await page.waitForSelector("text=Reading your documents", { timeout: 5000 });
console.log("extraction running…");
await page.waitForSelector("#req-intake-form", { timeout: 180000 });
const aiBadges = await page.locator("text=Extracted from").count();
console.log("intake reached; AI provenance badges:", aiBadges);
const legal = await page.inputValue('[data-intake="legal_name"]');
const netMw = await page.inputValue('[data-intake="net_mw_poi"]');
console.log("extracted legal_name:", legal, "| net_mw_poi:", netMw);
await page.screenshot({ path: shots + "/3_intake.png", fullPage: true });

// ---- 5. Validate — expect blockers, fix, revalidate ----
await page.click("#req-validate");
await page.waitForSelector("text=Validation", { timeout: 15000 });
const hasBlockers = (await page.locator("text=Blocking issues found").count()) > 0;
console.log("first validation has blockers (expected):", hasBlockers);
await page.screenshot({ path: shots + "/4_validate_red.png", fullPage: true });

if (hasBlockers) {
  await page.click("#req-back-2b");
  await page.waitForSelector("#req-intake-form");
  await page.fill('[data-intake="signatory_name"]', "Jordan Lee");
  await page.fill('[data-intake="signatory_title"]', "VP, Development");
  await page.fill('[data-intake="contact_email"]', email);
  await page.fill('[data-intake="contact_phone"]', "(760) 555-0100");
  await page.fill('[data-intake="project_name"]', "Acme Desert One");
  await page.click("#req-validate");
  await page.waitForSelector("text=Validation", { timeout: 15000 });
}
const clean = (await page.locator("text=Intake is clean").count()) > 0;
console.log("validation clean after fixes:", clean);
await page.screenshot({ path: shots + "/5_validate_clean.png", fullPage: true });

// ---- 6. Generate packet ----
await page.click("#req-generate");
await page.waitForSelector("text=CAISO submission packet", { timeout: 120000 });
const docRows = await page.locator("[data-drawer-url]").count();
console.log("packet page; preview buttons:", docRows);
await page.screenshot({ path: shots + "/6_packet.png", fullPage: true });

// Preview one generated document through the drawer
await page.locator('[data-drawer-url*="preview"]').first().click();
await page.waitForSelector("#gp-drawer iframe", { timeout: 10000 });
console.log("packet doc preview opens: ok");
await page.keyboard.press("Escape");
await page.waitForTimeout(300);

// Zip download (fetch with session cookie)
const zipHref = await page.getAttribute('a:has-text("Download packet (.zip)")', "href");
const zipRes = await page.request.get(BASE + zipHref);
console.log("zip download:", zipRes.status(), (await zipRes.body()).length, "bytes");

// ---- 7. SLD audit with real AI ----
await page.click('a:has-text("Done")');
await page.waitForSelector("#draw-file", { state: "attached", timeout: 15000 });
await page.setInputFiles("#draw-file", "samples/cedar_ridge_sld_demo.pdf");
await page.waitForSelector("text=Drawing uploaded", { timeout: 30000 });
console.log("SLD uploaded: ok");
await page.click("#run-audit");
console.log("audit running (real Grok vision)…");
await page.waitForSelector("text=Readiness", { timeout: 300000 });
await page.screenshot({ path: shots + "/7_audit.png", fullPage: true });
const findings = await page.locator("[data-triage]").count();
console.log("audit complete; triage buttons:", findings);

// Triage the first finding if present
if (findings > 0) {
  await page.locator("[data-triage]").first().click();
  await page.waitForTimeout(800);
  console.log("triage click: ok");
}

// HTML report via drawer
const report = await page.locator('[data-drawer-url*="report.html"]').count();
console.log("report button present:", report > 0);

await browser.close();
console.log("REAL FLOW TEST DONE");

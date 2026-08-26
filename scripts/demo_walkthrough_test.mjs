// Demo walkthrough E2E — steps through the guided demo exactly like a user,
// verifies the CAISO 13-item checklist packet, and downloads the zip.
// Usage: node scripts/demo_walkthrough_test.mjs   (server on :8000)
import { chromium } from "playwright-core";
import { mkdirSync, writeFileSync } from "node:fs";

const BASE = process.argv[2] || "http://127.0.0.1:8000";
const shots = "/tmp/gp_walk";
mkdirSync(shots, { recursive: true });

let failures = 0;
const check = (ok, label) => {
  console.log(ok ? `ok: ${label}` : `FAIL: ${label}`);
  if (!ok) failures += 1;
};

const browser = await chromium.launch({
  executablePath: "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
});
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
page.on("pageerror", (e) => console.log("PAGEERROR:", e.message));

// ---- Demo entry → start ----
await page.goto(BASE + "/app#/demo");
await page.waitForSelector("#start-demo-btn", { timeout: 15000 });
await page.click("#start-demo-btn");
await page.waitForSelector("#wiz-next", { timeout: 15000 });
await page.screenshot({ path: shots + "/02_scenario.png", fullPage: true });

// ---- Step 2: documents — submit staged example files ----
await page.click("#wiz-next");
await page.waitForSelector("#wiz-extract", { timeout: 10000 });
while ((await page.locator("[data-file-submit]").count()) > 0) {
  await page.locator("[data-file-submit]").first().click();
  await page.waitForTimeout(250);
}
await page.screenshot({ path: shots + "/04_documents_submitted.png", fullPage: true });

// ---- Extract → step 3 intake ----
await page.click("#wiz-extract");
await page.waitForSelector("#intake-form", { timeout: 30000 });
await page.screenshot({ path: shots + "/05_intake.png", fullPage: true });

// ---- Step 4: validate — seeded defects go red, fix, revalidate ----
await page.click("#wiz-validate");
await page.waitForSelector("#wiz-back-2", { timeout: 15000 });
await page.screenshot({ path: shots + "/06_validate_red.png", fullPage: true });
await page.click("#wiz-back-2");
await page.waitForSelector("#intake-form", { timeout: 10000 });
await page.fill('[data-intake="net_mw_poi"]', "125");
await page.fill('[data-intake="bess_mwh"]', "200");
await page.click("#wiz-validate");
await page.waitForSelector("#wiz-next", { timeout: 15000 });
await page.screenshot({ path: shots + "/07_validate_clean.png", fullPage: true });

// ---- Step 5: design review + approvals ----
await page.click("#wiz-next");
await page.waitForSelector("h2:has-text('Engineering design review')", { timeout: 20000 });
await page.waitForSelector("[data-eng-approve], #wiz-generate:not([disabled])", { timeout: 20000 });
await page.screenshot({ path: shots + "/08_design_review.png", fullPage: true });
if (await page.locator("#eng-approve-all").count()) {
  await page.click("#eng-approve-all");
  await page.waitForSelector("text=all approved", { timeout: 20000 });
}
await page.waitForSelector("#wiz-generate:not([disabled])", { timeout: 20000 });

// ---- Step 6: generate → packet ----
await page.click("#wiz-generate");
await page.waitForSelector('a:has-text("Download packet (.zip)")', { timeout: 120000 });
await page.screenshot({ path: shots + "/09_packet.png", fullPage: true });

// Checklist items present on the packet page
for (const t of [
  "Appendix 1 — Interconnection Request",
  "Attachment A — Generator Technical Data",
  "Evidence of Site Exclusivity",
  "Load Flow Model (.epc)",
  "Dynamic Model (.dyd)",
  "Reactive Power Capability Document",
  "Site Drawing",
  "Single-Line Diagram",
  "Flat Run & Bump Test Plots",
  "Requested MW at POI Plot",
  "IBR Model Validation Results",
]) {
  check((await page.locator(`text=${t}`).count()) >= 1, `packet lists: ${t}`);
}
check((await page.locator("text=CAISO minimum requirements —").count()) >= 1,
  "13-item checklist band shown");

// Preview drawers open for the three most complex docs
for (const [frag, name] of [
  ["Appendix1", "appendix1"],
  ["AttachmentA", "attachment_a"],
  ["ReactivePowerCapability", "reactive"],
  ["SiteDrawing", "site_drawing"],
]) {
  await page.locator(`[data-drawer-url*="${frag}"]`).first().click();
  await page.waitForSelector("#gp-drawer iframe", { timeout: 15000 });
  await page.waitForTimeout(2000);
  await page.screenshot({ path: `${shots}/10_preview_${name}.png` });
  // Verify the preview endpoint actually serves content (not just that the
  // drawer opened) — this is what regenerates the packet on a cold instance.
  const prevSrc = await page.getAttribute("#gp-drawer iframe", "src");
  const prevRes = await page.request.get(prevSrc.startsWith("http") ? prevSrc : BASE + prevSrc);
  const prevBody = await prevRes.text();
  check(prevRes.status() === 200 && prevBody.length > 500,
    `preview renders content: ${name} (${prevRes.status()}, ${prevBody.length} bytes)`);
  await page.keyboard.press("Escape");
  await page.waitForTimeout(400);
}

// Download the zip
const zipHref = await page.getAttribute('a:has-text("Download packet (.zip)")', "href");
const zipRes = await page.request.get(BASE + zipHref);
const body = await zipRes.body();
writeFileSync(shots + "/packet.zip", body);
check(zipRes.status() === 200 && body.length > 100000, `zip downloads (${body.length} bytes)`);

console.log(failures ? `DEMO WALKTHROUGH: ${failures} FAILURE(S)` : "DEMO WALKTHROUGH DONE — all checks passed");
await browser.close();
process.exit(failures ? 1 : 0);

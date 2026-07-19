// Headless test for the 6-step wizard with staged uploads (choose → upload → preview → submit):
// Step 2 documents start uploaded-but-not-submitted; extraction requires submission.
// Validate step: red items → staged corrected upload → preview → submit & revalidate in-card.
// Usage: node scripts/extract_flow_test.mjs  (server must be running on :8000)
import { chromium } from "playwright-core";
import { mkdirSync, writeFileSync } from "fs";

const BASE = "http://127.0.0.1:8000";
const shots = "/tmp/gp_extract";
mkdirSync(shots, { recursive: true });
const fixedWb = "/tmp/Ravenwood_TechnicalData_Workbook_v2.xlsx";
writeFileSync(fixedWb, "corrected workbook placeholder");

const browser = await chromium.launch({
  executablePath: "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
});
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
page.on("pageerror", (e) => console.log("PAGEERROR:", e.message));
page.on("console", (m) => {
  if (m.type() === "error") console.log("CONSOLE ERR:", m.text());
});

await page.goto(BASE + "/app#/demo");
await page.waitForSelector("#start-demo-btn", { timeout: 10000 });
await page.click("#start-demo-btn");
await page.waitForSelector("#wiz-next", { timeout: 15000 });

// Step 2 — documents arrive staged (uploaded, not submitted)
await page.click("#wiz-next");
await page.waitForSelector("#wiz-extract", { timeout: 10000 });
const stagedChips = await page.getByText("Uploaded — not submitted").count();
const submitBtns = await page.locator("[data-file-submit]").count();
console.log("staged docs on arrival:", stagedChips, "| submit buttons:", submitBtns);
await page.screenshot({ path: shots + "/2_step2_staged.png", fullPage: true });

// Extraction is blocked until documents are submitted
await page.click("#wiz-extract");
await page.waitForTimeout(500);
console.log("extract blocked while staged:", (await page.locator("#intake-form").count()) === 0);

// Preview staged files — each carries its own seeded defect
await page.click('[data-file-preview="file_technical"]');
await page.waitForSelector("#gp-drawer iframe", { timeout: 8000 });
const wbSrc = await page.getAttribute("#gp-drawer iframe", "src");
const wbHtml = await (await page.request.get(BASE + wbSrc)).text();
console.log("staged workbook shows MW defect (128):", />128</.test(wbHtml));
await page.keyboard.press("Escape");
await page.waitForTimeout(400);
await page.click('[data-file-preview="file_bess"]');
await page.waitForSelector("#gp-drawer iframe", { timeout: 8000 });
const bessSrc = await page.getAttribute("#gp-drawer iframe", "src");
const bessHtml = await (await page.request.get(BASE + bessSrc)).text();
console.log("staged BESS sheet shows blank MWh:", bessHtml.includes("— blank —"));
await page.keyboard.press("Escape");
await page.waitForTimeout(400);
while ((await page.locator("[data-file-submit]").count()) > 0) {
  await page.locator("[data-file-submit]").first().click();
  await page.waitForTimeout(250);
}
console.log("submitted chips:", await page.getByText("Submitted", { exact: true }).count());
await page.screenshot({ path: shots + "/3_step2_submitted.png", fullPage: true });

// Extract → step 3
await page.click("#wiz-extract");
await page.waitForSelector("#intake-form", { timeout: 25000 });
console.log("AI provenance badges:", await page.getByText("Extracted from").count());

// Validate → red items in stable order
await page.click("#wiz-validate");
await page.waitForSelector("#wiz-back-2", { timeout: 10000 });
console.log("blocking shown:", (await page.textContent("body")).includes("Blocking issues found"));
const titlesBefore = await page.locator("article strong").allTextContents();
const mwIdxBefore = titlesBefore.findIndex((t) => t.includes("MW chain"));
await page.screenshot({ path: shots + "/5_step4_red.png", fullPage: true });

// Fix 1: corrected workbook → clears the MW chain finding only
await page.locator('[data-fix-example="file_technical"]').first().click();
await page.waitForTimeout(500);
console.log("in-card upload progress:", (await page.content()).includes("Uploading…"));
await page.waitForSelector('[data-fix-submit="file_technical"]', { timeout: 8000 });
await page.screenshot({ path: shots + "/8a_staged_in_card.png", fullPage: true });

// Preview the staged corrected workbook — corrected 125, no BESS rows here
const stagedPrevUrl = await page
  .locator('[data-drawer-url*="file_technical"][data-drawer-title*="review before submitting"]')
  .first()
  .getAttribute("data-drawer-url");
const stagedHtml = await (await page.request.get(BASE + stagedPrevUrl)).text();
console.log("staged workbook preview shows corrected 125:", />125</.test(stagedHtml));

await page.locator('[data-fix-submit="file_technical"]').first().click();
await page.waitForTimeout(700);
console.log("in-card revalidate progress:", (await page.content()).includes("Re-running validation checks"));
await page.waitForTimeout(3200);
const afterFix1 = await page.textContent("body");
console.log("MW chain fixed, BESS still red:",
  !afterFix1.includes("MW chain does not reconcile") && afterFix1.includes("BESS energy missing"));
const titlesAfter = await page.locator("article strong").allTextContents();
const mwIdxAfter = titlesAfter.findIndex((t) => t.includes("MW chain"));
console.log("MW chain position stable:", mwIdxBefore === mwIdxAfter, `(${mwIdxBefore} → ${mwIdxAfter})`);
await page.screenshot({ path: shots + "/8b_one_fixed_one_red.png", fullPage: true });

// Fix 2: corrected BESS spec sheet → clears the remaining finding
await page.locator('[data-fix-example="file_bess"]').first().click();
await page.waitForSelector('[data-fix-submit="file_bess"]', { timeout: 8000 });
const bessPrevUrl = await page
  .locator('[data-drawer-url*="file_bess"][data-drawer-title*="review before submitting"]')
  .first()
  .getAttribute("data-drawer-url");
const bessFixedHtml = await (await page.request.get(BASE + bessPrevUrl)).text();
console.log("staged BESS preview shows corrected 200:", />200</.test(bessFixedHtml));
await page.locator('[data-fix-submit="file_bess"]').first().click();
await page.waitForTimeout(3800);
const afterFix2 = await page.textContent("body");
console.log("revalidated clean:", afterFix2.includes("Intake is clean"));
await page.screenshot({ path: shots + "/8_step4_green.png", fullPage: true });

// Regression: native picker path also goes upload → staged → submit
await page.click("#wiz-back");
await page.waitForSelector("#intake-form", { timeout: 10000 });
await page.fill('[data-intake="net_mw_poi"]', "128");
await page.click("#wiz-validate");
await page.waitForSelector('[data-fix-input="file_technical"]', { state: "attached", timeout: 10000 });
await page.locator('[data-fix-input="file_technical"]').first().setInputFiles(fixedWb);
await page.waitForSelector("[data-fix-submit]", { timeout: 8000 });
await page.locator("[data-fix-submit]").first().click();
await page.waitForTimeout(3800);
console.log("picker path revalidated clean:", (await page.textContent("body")).includes("Intake is clean"));

// Generate → packet
await page.click("#wiz-generate");
await page.waitForSelector("#wiz-finish", { timeout: 30000 });
console.log("packet step reached:", (await page.textContent(".flex-1.p-7 p")).trim());

console.log("EXTRACT FLOW TEST DONE");
await browser.close();

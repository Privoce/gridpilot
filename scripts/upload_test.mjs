// Headless test for the Step 2 kickoff-document upload components (staged flow).
// Usage: node scripts/upload_test.mjs  (server must be running on :8000)
import { chromium } from "playwright-core";
import { mkdirSync, writeFileSync } from "fs";

const BASE = "http://127.0.0.1:8000";
const shots = "/tmp/gp_upload";
mkdirSync(shots, { recursive: true });
writeFileSync("/tmp/Ravenwood_Lease_Custom_2026.pdf", "%PDF-1.4 dummy");
writeFileSync("/tmp/SG4400UD_vendor_model.dyd", "# vendor dyd dummy");

const browser = await chromium.launch({
  executablePath: "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
});
const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
page.on("pageerror", (e) => console.log("PAGEERROR:", e.message));
page.on("console", (m) => {
  if (m.type() === "error") console.log("CONSOLE ERR:", m.text());
});

const submitAllStaged = async () => {
  while ((await page.locator("[data-file-submit]").count()) > 0) {
    await page.locator("[data-file-submit]").first().click();
    await page.waitForTimeout(250);
  }
};

await page.goto(BASE + "/app#/demo");
await page.waitForSelector("#start-demo-btn", { timeout: 10000 });
await page.click("#start-demo-btn");
await page.waitForSelector("#wiz-next", { timeout: 15000 });
await page.click("#wiz-next");
await page.waitForSelector("#wiz-extract", { timeout: 10000 }); // step 2: documents

// 1. Documents arrive staged with per-file controls
const stagedChips = await page.getByText("Uploaded — not submitted").count();
const removeBtns = await page.locator("[data-file-remove]").count();
console.log("staged docs:", stagedChips >= 4, "| remove buttons:", removeBtns >= 4);
await page.screenshot({ path: shots + "/1_step2_uploads.png", fullPage: true });

// 2. Remove the lease -> downstream validation must block
await page.click('[data-file-remove="file_site_control"]');
await page.waitForTimeout(300);
await submitAllStaged();
await page.click("#wiz-extract");
await page.waitForSelector("#intake-form", { timeout: 25000 });
await page.click("#wiz-validate");
await page.waitForSelector("#wiz-back-2", { timeout: 15000 });
const errText = await page.textContent("body");
console.log("blocking on missing lease:", errText.includes("Executed site agreement not attached"));
await page.screenshot({ path: shots + "/2_validate_blocked.png", fullPage: true });

// 3. Back to documents, attach a custom lease and a vendor .dyd
await page.click("#wiz-back-2"); // -> intake (step 3)
await page.waitForSelector("#intake-form", { timeout: 10000 });
await page.click("#wiz-back"); // -> documents (step 2)
await page.waitForSelector("#wiz-extract", { timeout: 10000 });
await page.setInputFiles('[data-file-input="file_site_control"]', "/tmp/Ravenwood_Lease_Custom_2026.pdf");
await page.waitForSelector('[data-file-submit="file_site_control"]', { timeout: 8000 });
const hasCustom = (await page.textContent("body")).includes("Ravenwood_Lease_Custom_2026.pdf");
console.log("custom lease attached:", hasCustom);
await page.setInputFiles('[data-file-input="file_dyd"]', "/tmp/SG4400UD_vendor_model.dyd");
await page.waitForSelector('[data-file-submit="file_dyd"]', { timeout: 8000 });
await page.screenshot({ path: shots + "/3_custom_files.png", fullPage: true });
await submitAllStaged();

// 4. Re-extract, correct the seeded defects, validate clean
await page.click("#wiz-extract");
await page.waitForSelector("#intake-form", { timeout: 25000 });
await page.fill('[data-intake="net_mw_poi"]', "125");
await page.fill('[data-intake="bess_mwh"]', "200");
await page.click("#wiz-validate");
await page.waitForSelector("#wiz-next", { timeout: 15000 });
const vText = await page.textContent("body");
console.log("validation shows custom lease:", vText.includes("Ravenwood_Lease_Custom_2026.pdf"),
  "| vendor dyd shown:", vText.includes("SG4400UD_vendor_model.dyd"));
await page.screenshot({ path: shots + "/4_validate_clean.png", fullPage: true });

// 5. Design review sign-off, generate, land on packet
await page.click("#wiz-next");
await page.waitForSelector("h2:has-text('Engineering design review')", { timeout: 20000 });
await page.waitForSelector("[data-eng-approve], #wiz-generate:not([disabled])", { timeout: 20000 });
if (await page.locator("#eng-approve-all").count()) {
  await page.click("#eng-approve-all");
  await page.waitForSelector("text=all approved", { timeout: 20000 });
}
await page.waitForSelector("#wiz-generate:not([disabled])", { timeout: 20000 });
await page.click("#wiz-generate");
await page.waitForSelector("#wiz-finish", { timeout: 30000 });
await page.screenshot({ path: shots + "/5_packet.png", fullPage: true });
console.log("UPLOAD TEST DONE");
await browser.close();

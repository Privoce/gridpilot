// Headless test for the Step 2 kickoff-document upload components.
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

await page.goto(BASE + "/app#/demo");
await page.waitForSelector("#start-demo-btn", { timeout: 10000 });
await page.click("#start-demo-btn");
await page.waitForSelector("#wiz-next", { timeout: 15000 });
await page.click("#wiz-next");
await page.waitForSelector("#intake-form", { timeout: 10000 });

// 1. Preloaded example files visible
const chips = await page.locator("[data-file-attach]").count();
const preloaded = await page.getByText("preloaded example").count();
console.log("file components:", chips >= 4, "| preloaded examples:", preloaded);
await page.locator('[data-file-field], fieldset:last-of-type').last().scrollIntoViewIfNeeded().catch(() => {});
await page.screenshot({ path: shots + "/1_step2_uploads.png", fullPage: true });

// 2. Remove the lease -> validation should block
await page.click('[data-file-remove="file_site_control"]');
await page.waitForTimeout(300);
await page.screenshot({ path: shots + "/2_lease_removed.png", fullPage: true });
await page.click("#wiz-validate");
await page.waitForSelector("#wiz-back-2", { timeout: 10000 });
const errText = await page.textContent("body");
console.log("blocking on missing lease:", errText.includes("Executed site agreement not attached"));
await page.screenshot({ path: shots + "/3_validate_blocked.png", fullPage: true });

// 3. Back, attach a custom lease file
await page.click("#wiz-back-2");
await page.waitForSelector("#intake-form", { timeout: 10000 });
await page.setInputFiles('[data-file-input="file_site_control"]', "/tmp/Ravenwood_Lease_Custom_2026.pdf");
await page.waitForTimeout(400);
const hasCustom = (await page.textContent("body")).includes("Ravenwood_Lease_Custom_2026.pdf");
console.log("custom lease attached:", hasCustom);

// 4. Attach the vendor .dyd too
await page.setInputFiles('[data-file-input="file_dyd"]', "/tmp/SG4400UD_vendor_model.dyd");
await page.waitForTimeout(400);
await page.screenshot({ path: shots + "/4_custom_files.png", fullPage: true });

// 5. Validate clean, generate, land on packet
await page.click("#wiz-validate");
await page.waitForSelector("#wiz-generate", { timeout: 10000 });
const vText = await page.textContent("body");
console.log("validation shows custom lease:", vText.includes("Ravenwood_Lease_Custom_2026.pdf"),
  "| vendor dyd pass:", vText.includes("SG4400UD_vendor_model.dyd"));
await page.screenshot({ path: shots + "/5_validate_clean.png", fullPage: true });
await page.click("#wiz-generate");
await page.waitForSelector("#wiz-finish", { timeout: 30000 });
await page.screenshot({ path: shots + "/6_packet.png", fullPage: true });
console.log("UPLOAD TEST DONE");
await browser.close();

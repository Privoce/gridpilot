// Headless smoke test for the CAISO guided demo wizard.
// Usage: node scripts/ui_smoke_test.mjs  (server must be running on :8000)
import { chromium } from "playwright-core";
import { mkdirSync } from "fs";

const BASE = "http://127.0.0.1:8000";
const shots = "/tmp/gp_ui";
mkdirSync(shots, { recursive: true });

const browser = await chromium.launch({
  executablePath: "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
});
const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
page.on("pageerror", (e) => console.log("PAGEERROR:", e.message));
page.on("console", (m) => {
  if (m.type() === "error") console.log("CONSOLE ERR:", m.text());
});

// Landing
await page.goto(BASE + "/");
await page.screenshot({ path: shots + "/0_landing.png" });

// Demo entry
await page.goto(BASE + "/app#/demo");
await page.waitForSelector("#start-demo-btn", { timeout: 10000 });
await page.screenshot({ path: shots + "/1_demo_entry.png" });

// Start demo → step 1
await page.click("#start-demo-btn");
await page.waitForSelector("#wiz-next", { timeout: 15000 });
await page.screenshot({ path: shots + "/2_step1_scenario.png" });

// Step 2 intake
await page.click("#wiz-next");
await page.waitForSelector("#intake-form", { timeout: 10000 });
await page.screenshot({ path: shots + "/3_step2_intake.png", fullPage: true });

// Step 3 validate (clean)
await page.click("#wiz-validate");
await page.waitForSelector("#wiz-generate, #wiz-back-2", { timeout: 10000 });
await page.screenshot({ path: shots + "/4_step3_validate.png", fullPage: true });

// Break the MW chain to test the error path
await page.click("#wiz-back");
await page.waitForSelector("#intake-form", { timeout: 10000 });
await page.fill('[data-intake="net_mw_poi"]', "200");
await page.click("#wiz-validate");
await page.waitForSelector("#wiz-back-2", { timeout: 10000 });
await page.screenshot({ path: shots + "/5_step3_errors.png", fullPage: true });

// Fix and continue
await page.click("#wiz-back-2");
await page.waitForSelector("#intake-form", { timeout: 10000 });
await page.fill('[data-intake="net_mw_poi"]', "125");
await page.click("#wiz-validate");
await page.waitForSelector("#wiz-generate", { timeout: 10000 });

// Generate → animation
await page.click("#wiz-generate");
await page.waitForTimeout(2500);
await page.screenshot({ path: shots + "/6_step4_generating.png" });

// Wait for the packet review screen
await page.waitForSelector("#wiz-finish", { timeout: 30000 });
await page.screenshot({ path: shots + "/7_step5_packet.png", fullPage: true });

// Finish → workspace dashboard
await page.click("#wiz-finish");
await page.waitForTimeout(1500);
await page.screenshot({ path: shots + "/8_dashboard.png" });

console.log("UI TEST DONE");
await browser.close();

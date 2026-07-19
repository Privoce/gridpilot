// Headless test: preview drawer for kickoff documents (Step 2) and packet docs (Step 5).
// Usage: node scripts/drawer_test.mjs  (server must be running on :8000)
import { chromium } from "playwright-core";
import { mkdirSync } from "fs";

const BASE = "http://127.0.0.1:8000";
const shots = "/tmp/gp_drawer";
mkdirSync(shots, { recursive: true });

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
await page.click("#wiz-next");
await page.waitForSelector("#intake-form", { timeout: 10000 });

// 1. Preview the preloaded lease -> drawer with server-rendered document
await page.click('[data-file-preview="file_site_control"]');
await page.waitForSelector("#gp-drawer iframe", { timeout: 8000 });
await page.waitForTimeout(1200);
console.log("lease drawer open:", await page.locator("#gp-drawer").count() === 1);
await page.screenshot({ path: shots + "/1_lease_drawer.png" });
await page.click('#gp-drawer [data-drawer-dismiss]:not(div)');
await page.waitForTimeout(400);
console.log("drawer closed:", await page.locator("#gp-drawer").count() === 0);

// 2. Preview the boundary KMZ example
await page.click('[data-file-preview="file_boundary"]');
await page.waitForSelector("#gp-drawer iframe", { timeout: 8000 });
await page.waitForTimeout(1200);
await page.screenshot({ path: shots + "/2_boundary_drawer.png" });
await page.keyboard.press("Escape");
await page.waitForTimeout(400);
console.log("esc closes:", await page.locator("#gp-drawer").count() === 0);

// 3. Signatory example
await page.click('[data-file-preview="file_signatory"]');
await page.waitForSelector("#gp-drawer iframe", { timeout: 8000 });
await page.waitForTimeout(1000);
await page.screenshot({ path: shots + "/3_signatory_drawer.png" });
await page.keyboard.press("Escape");
await page.waitForTimeout(400);

// 4. Attach a text .dyd this session and preview it (blob URL)
import { writeFileSync } from "fs";
writeFileSync("/tmp/vendor_model.dyd", "regc_a 90004 \"RAVEN-PV\" 0.60 \"1\" : #9 mva=131.3 ...vendor params...");
await page.setInputFiles('[data-file-input="file_dyd"]', "/tmp/vendor_model.dyd");
await page.waitForTimeout(500);
await page.click('[data-file-preview="file_dyd"]');
await page.waitForSelector("#gp-drawer iframe", { timeout: 8000 });
await page.waitForTimeout(600);
await page.screenshot({ path: shots + "/4_session_dyd_drawer.png" });
await page.keyboard.press("Escape");
await page.waitForTimeout(400);

// 5. Full run to Step 5 and open a packet doc preview in the drawer
await page.click("#wiz-validate");
await page.waitForSelector("#wiz-generate", { timeout: 10000 });
await page.click("#wiz-generate");
await page.waitForSelector("#wiz-finish", { timeout: 30000 });
await page.click('[data-drawer-url*="Appendix1"]');
await page.waitForSelector("#gp-drawer iframe", { timeout: 8000 });
await page.waitForTimeout(1500);
await page.screenshot({ path: shots + "/5_packet_doc_drawer.png" });
console.log("packet doc drawer:", await page.locator("#gp-drawer").count() === 1);

console.log("DRAWER TEST DONE");
await browser.close();

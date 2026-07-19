// Supplemental button sweep: landing links, demo completion screen (zip link),
// dashboard, projects, audits, billing (upgrade), sign out / sign in.
// Usage: node scripts/button_sweep_test.mjs [base_url]
import { chromium } from "playwright-core";
import { mkdirSync } from "fs";

const BASE = process.argv[2] || "http://127.0.0.1:8000";
mkdirSync("/tmp/gp_sweep", { recursive: true });

const browser = await chromium.launch({
  executablePath: "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
});
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
page.on("pageerror", (e) => console.log("PAGEERROR:", e.message));
page.on("console", (m) => {
  if (m.type() === "error") console.log("CONSOLE ERR:", m.text());
});

// ---- Landing page ----
await page.goto(BASE + "/");
const tryDemo = await page.locator('a:has-text("Try demo"), a:has-text("Try Demo")').count();
console.log("landing 'Try demo' links:", tryDemo);

// ---- Demo: fast-path to completion using localStorage from a real run ----
await page.goto(BASE + "/app#/demo");
await page.waitForSelector("#start-demo-btn");
await page.click("#start-demo-btn");
await page.waitForSelector("#wiz-next", { timeout: 15000 });

// Submit all documents, extract, validate is red → use corrected examples, generate.
await page.click("#wiz-next");
await page.waitForSelector("#wiz-extract");
while ((await page.locator("[data-file-submit]").count()) > 0) {
  await page.locator("[data-file-submit]").first().click();
  await page.waitForTimeout(250);
}
await page.click("#wiz-extract");
await page.waitForSelector("#intake-form", { timeout: 30000 });
await page.click("#wiz-validate");
await page.waitForSelector("[data-fix-example]", { timeout: 20000 });
for (const slot of ["file_technical", "file_bess"]) {
  await page.locator(`[data-fix-example="${slot}"]`).first().click();
  await page.waitForSelector(`[data-fix-submit="${slot}"]`, { timeout: 10000 });
  await page.locator(`[data-fix-submit="${slot}"]`).first().click();
  await page.waitForTimeout(3800);
}
await page.waitForSelector("#wiz-generate", { timeout: 30000 });
await page.click("#wiz-generate");
await page.waitForSelector('a:has-text("Download packet (.zip)")', { timeout: 60000 });
console.log("demo packet step reached");

// Zip from packet step
let zipHref = await page.getAttribute('a:has-text("Download packet (.zip)")', "href");
let res = await page.request.get(BASE + zipHref);
console.log("demo zip (packet step):", res.status(), (await res.body()).length, "bytes");
console.log("zip url carries ?d= :", zipHref.includes("?d="));

// Finish demo → lands on dashboard
await page.click("#wiz-finish");
await page.waitForSelector("#new-project-btn", { timeout: 15000 });
console.log("finish demo → dashboard: ok");

// Revisit the completed wizard — zip link must survive (packet re-fetched via ?d=)
await page.goto(BASE + "/app#/onboarding");
await page.waitForSelector('a:has-text("Open workspace")', { timeout: 15000 });
zipHref = await page.getAttribute('a:has-text("Download packet (.zip)")', "href");
res = await page.request.get(BASE + zipHref);
console.log("demo zip (completion revisit):", res.status(), (await res.body()).length, "bytes");

// ---- Workspace pages ----
await page.goto(BASE + "/app#/dashboard");
await page.waitForSelector("#new-project-btn", { timeout: 15000 });
console.log("dashboard renders: ok");

await page.goto(BASE + "/app#/projects");
await page.waitForSelector("#new-project-btn", { timeout: 15000 });
console.log("projects page: ok");

// Project modal open + cancel responsiveness
await page.click("#new-project-btn");
await page.waitForSelector("#project-form");
await page.click("#modal-cancel");
await page.waitForTimeout(400);
console.log("project modal cancel:", (await page.locator("#project-form").count()) === 0);

await page.goto(BASE + "/app#/audits");
await page.waitForSelector("text=Audits", { timeout: 15000 });
console.log("audits page: ok");

await page.goto(BASE + "/app#/billing");
await page.waitForSelector("text=Billing", { timeout: 15000 });
console.log("billing page: ok");

// ---- Sign out → sign in with demo creds ----
await page.click("#logout-link");
await page.waitForSelector("#auth-form", { timeout: 15000 });
await page.fill('[name="email"]', "demo@gridpilot.dev");
await page.fill('[name="password"]', "gridpilot");
await page.click('button[type="submit"]');
await page.waitForSelector("#wiz-next, #new-project-btn, #wiz-reset", { timeout: 15000 });
console.log("sign out / sign in: ok");

await browser.close();
console.log("BUTTON SWEEP DONE");

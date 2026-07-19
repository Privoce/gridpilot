// Regression test: Add-project modal Cancel and backdrop click must close the modal.
import { chromium } from "playwright-core";

const BASE = "http://127.0.0.1:8000";
const browser = await chromium.launch({
  executablePath: "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
});
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
page.on("pageerror", (e) => console.log("PAGEERROR:", e.message));

await page.goto(BASE + "/app#/demo");
await page.waitForSelector("#start-demo-btn", { timeout: 10000 });
await page.click("#start-demo-btn");
await page.waitForSelector("#wiz-next", { timeout: 15000 });

// Skip the wizard so app pages are reachable.
await page.evaluate(() => {
  localStorage.setItem("gp_demo_onboard_v4", JSON.stringify({ completed: true, wizardStep: 7 }));
});
await page.goto(BASE + "/app#/projects");
await page.waitForSelector("#new-project-btn", { timeout: 10000 });

// Cancel button closes.
await page.click("#new-project-btn");
await page.waitForSelector("#modal-cancel", { timeout: 5000 });
await page.click("#modal-cancel");
await page.waitForTimeout(400);
console.log("cancel closes modal:", (await page.locator("#modal").count()) === 0);

// Backdrop click closes.
await page.click("#new-project-btn");
await page.waitForSelector("#modal-cancel", { timeout: 5000 });
await page.mouse.click(20, 450);
await page.waitForTimeout(400);
console.log("backdrop closes modal:", (await page.locator("#modal").count()) === 0);

// Create still works.
await page.click("#new-project-btn");
await page.waitForSelector("#project-form", { timeout: 5000 });
await page.fill('input[name="name"]', "Cancel Test Project");
await page.click('button[type="submit"]');
await page.waitForTimeout(1200);
console.log("create navigates to project:", page.url().includes("#/project/"));

console.log("MODAL TEST DONE");
await browser.close();

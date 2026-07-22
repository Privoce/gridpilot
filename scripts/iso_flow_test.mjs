// Multi-ISO support test:
//   landing page ISO switcher → signup → MISO project → request wizard shows
//   MISO profile/tracks → manual intake → validate (MISO citations) →
//   generate → MISO-labeled packet + zip download.
// Usage: node scripts/iso_flow_test.mjs [base_url]   (defaults to :8000)
import { chromium } from "playwright-core";
import { mkdirSync } from "fs";

const BASE = process.argv[2] || "http://127.0.0.1:8000";
const shots = "/tmp/gp_iso";
mkdirSync(shots, { recursive: true });

const browser = await chromium.launch({
  executablePath: "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
});
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
page.on("pageerror", (e) => console.log("PAGEERROR:", e.message));
page.on("console", (m) => {
  if (m.type() === "error") console.log("CONSOLE ERR:", m.text());
});

// ---- 1. Landing switcher ----
await page.goto(BASE + "/");
await page.waitForSelector("#gp-iso-tabs button");
const tabCount = await page.locator("#gp-iso-tabs button").count();
console.log("ISO tabs:", tabCount);
const caisoFirst = await page.locator("#gp-iso-generates li").first().textContent();
console.log("CAISO first item:", caisoFirst);
await page.click('#gp-iso-tabs button[data-iso="MISO"]');
const misoFirst = await page.locator("#gp-iso-generates li").first().textContent();
const misoKeep = await page.locator("#gp-iso-keeps li").nth(1).textContent();
console.log("MISO first item:", misoFirst, "| keep:", misoKeep);
await page.click('#gp-iso-tabs button[data-iso="ERCOT"]');
const ercotHasPscad = (await page.locator('#gp-iso-generates li:has-text("PSCAD")').count()) > 0;
console.log("ERCOT lists PSCAD:", ercotHasPscad);
await page.screenshot({ path: shots + "/1_landing_switcher.png", fullPage: false });

// ---- 2. Signup + MISO project ----
const email = `iso-${Date.now()}@acme-energy.com`;
await page.goto(BASE + "/app#/signup");
await page.waitForSelector("#auth-form");
await page.fill('[name="name"]', "Iso Tester");
await page.fill('[name="org_name"]', "ISO Test Org");
await page.fill('[name="email"]', email);
await page.fill('[name="password"]', "sunny-12345");
await page.click('button[type="submit"]');
await page.waitForSelector("#new-project-btn", { timeout: 15000 });
await page.click("#new-project-btn");
await page.waitForSelector("#project-form");
const isoOptions = await page.locator('#project-form [name="iso"] option').allTextContents();
console.log("project ISO options:", isoOptions.join(", "));
await page.fill('#project-form [name="name"]', "Prairie Wind One");
await page.selectOption('#project-form [name="iso"]', "MISO");
await page.fill('#project-form [name="capacity_mw"]', "200");
await page.fill('#project-form [name="state"]', "IA");
await page.fill('#project-form [name="poi_substation"]', "Prairie 345 kV");
await page.click('#project-form button[type="submit"]');
await page.waitForSelector("text=Interconnection request", { timeout: 15000 });
console.log("MISO project created: ok");

// ---- 3. Request wizard — MISO profile ----
await page.click('a:has-text("Interconnection request")');
await page.waitForSelector("#req-extract", { timeout: 15000 });
const header = await page.locator("h1, h2").first().textContent();
const profileNote = (await page.locator("text=Midcontinent ISO").count()) > 0;
console.log("wizard header:", header?.trim(), "| MISO profile card:", profileNote);
await page.screenshot({ path: shots + "/2_wizard_docs.png", fullPage: true });

// Manual entry path
await page.click("#req-skip");
await page.waitForSelector("#req-intake-form", { timeout: 15000 });
const trackOptions = await page.locator('[data-intake="track"] option').allTextContents();
console.log("MISO track options:", trackOptions.join(", "));

// Fill a valid intake
const fill = async (k, v) => page.fill(`[data-intake="${k}"]`, String(v));
await fill("legal_name", "Prairie Wind One LLC");
await fill("signatory_name", "Ann Ames");
await fill("project_name", "Prairie Wind One");
await fill("gps_lat", "41.9");
await fill("gps_lon", "-93.5");
await fill("county", "Story");
await fill("state", "IA");
await fill("site_acreage", "900");
await page.selectOption('[data-intake="site_control"]', "Lease Agreement");
await fill("site_owner", "Story County Land LP");
await fill("poi_name", "Prairie 345 kV");
await fill("poi_voltage_kv", "345");
await page.selectOption('[data-intake="track"]', "DPP Cycle");
await fill("cod", "2029-06-30");
await page.selectOption('[data-intake="project_type"]', "Wind");
await fill("gross_mva", "210");
await fill("gross_mw", "204");
await fill("aux_mw", "3");
await fill("losses_mw", "1");
await fill("net_mw_poi", "200");
await page.selectOption('[data-intake="bess_charging"]', "N/A — no storage");
await fill("inverter", "Vestas V163, qty 30");
await page.selectOption('[data-intake="dyd_status"]', "Requested — pending");

// ---- 4. Validate ----
await page.click("#req-validate");
await page.waitForSelector("text=Validation", { timeout: 15000 });
const missingSite = (await page.locator("text=Executed site agreement not attached").count()) > 0;
const misoCitation = (await page.locator('[data-drawer-file*="MISO Tariff"]').count()) > 0;
const caisoLeak = (await page.locator("main >> text=CAISO").count());
console.log("site-file blocker (expected true):", missingSite, "| MISO citation:", misoCitation, "| stray CAISO mentions:", caisoLeak);
// Requirement drawer shows localized ground truth
await page.locator('[data-drawer-url*="/requirements/"]').first().click();
await page.waitForTimeout(1200);
const drawerFrame = page.frameLocator("#drawer-frame, iframe").first();
const drawerMiso = await drawerFrame.locator("body").textContent().catch(() => "");
console.log("requirement drawer mentions MISO:", /MISO/.test(drawerMiso || ""), "| mentions CAISO:", /CAISO/.test(drawerMiso || ""));
await page.keyboard.press("Escape");
await page.waitForTimeout(400);
await page.screenshot({ path: shots + "/3_validate.png", fullPage: true });

// Attach the site file to clear the blocker (go back to documents)
await page.click("#req-back-1");
await page.waitForSelector('[data-req-input="file_site_control"]', { state: "attached", timeout: 15000 });
const { writeFileSync } = await import("fs");
writeFileSync("/tmp/gp_iso_lease.pdf", "%PDF-1.4 test lease");
await page.setInputFiles('[data-req-input="file_site_control"]', "/tmp/gp_iso_lease.pdf");
await page.waitForTimeout(400);
await page.click("#req-skip");
await page.waitForSelector("#req-intake-form", { timeout: 15000 });
await page.click("#req-validate");
await page.waitForSelector("text=Validation", { timeout: 15000 });
const clean = (await page.locator("text=Intake is clean").count()) > 0;
console.log("validation clean after site file:", clean);

// ---- 5. Generate ----
await page.click("#req-generate");
await page.waitForSelector('a:has-text("Download packet (.zip)")', { timeout: 60000 });
const packetHeader = await page.locator("h2:has-text('submission packet')").first().textContent();
const hasRaw = (await page.locator("text=Load Flow Model (.raw)").count()) > 0;
const hasDpp = (await page.locator("text=DPP Application").count()) > 0;
console.log("packet header:", packetHeader?.trim(), "| .raw model:", hasRaw, "| DPP form:", hasDpp);
await page.screenshot({ path: shots + "/4_packet.png", fullPage: true });

// Zip download
const [dl] = await Promise.all([
  page.waitForEvent("download", { timeout: 30000 }),
  page.click('a:has-text("Download packet (.zip)")'),
]);
console.log("zip downloaded:", dl.suggestedFilename());

// Preview a MISO model file in the drawer
await page.click('button[data-drawer-url*="DynamicModel"]').catch(() => {});
await browser.close();
console.log("ISO FLOW TEST DONE");

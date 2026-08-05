// Datasheet ingestion e2e (demo): intake step -> "Add equipment from a
// datasheet" -> review drawer -> unverified entry -> design review shows the
// verification approval and the resized fleet.
// Usage: node scripts/datasheet_ingest_test.mjs [base_url]
import { chromium } from "playwright-core";
import { mkdirSync } from "fs";

const BASE = process.argv[2] || "http://127.0.0.1:8000";
const shots = "/tmp/gp_datasheet_e2e";
mkdirSync(shots, { recursive: true });

let failures = 0;
const check = (cond, msg) => {
  console.log(`${cond ? "ok" : "FAIL"}: ${msg}`);
  if (!cond) failures++;
};

const browser = await chromium.launch({
  executablePath: "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
});
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
page.on("pageerror", (e) => console.log("PAGEERROR:", e.message));

await page.goto(BASE + "/app");
await page.request.post(BASE + "/api/demo/start");

// Seed a clean intake at the intake step.
await page.evaluate(() => {
  const intake = {
    net_mw_poi: 125.0,
    bess_mwh: 200.0,
    file_site_control: { name: "Ravenwood_Lease_Executed_2026-03-14.pdf", size: 2871342, example: true },
    file_technical: { name: "Ravenwood_TechnicalData_Workbook_v2.xlsx", size: 87450, example: true },
    file_bess: { name: "Ravenwood_BESS_Spec_v2.xlsx", size: 54120, example: true },
    file_signatory: { name: "Ravenwood_OfficerCertificate.pdf", size: 184230, example: true },
    file_dyd: { name: "Sungrow_SG4400UD_PSLF_Models.dyd", size: 18240, example: true },
    file_boundary: { name: "Ravenwood_ParcelBoundary.kmz", size: 46210, example: true },
  };
  localStorage.setItem("gp_caiso_intake_v1", JSON.stringify(intake));
  localStorage.setItem("gp_demo_onboard_v4", JSON.stringify({ started: true, wizardStep: 3 }));
});
await page.goto(BASE + "/app#/onboarding");
await page.reload();
await page.waitForSelector('[data-intake="inverter"]', { timeout: 20000 });

check((await page.locator("datalist#dl-inverter option").count()) >= 3,
  "library datalist on the inverter field");
check((await page.locator('[data-ingest="inverter"]').count()) === 1,
  "add-from-datasheet affordance present");

// Upload a (fake) datasheet through the file chooser.
const [chooser] = await Promise.all([
  page.waitForEvent("filechooser"),
  page.click('[data-ingest="inverter"]'),
]);
await chooser.setFiles({
  name: "GE_LV5plus_3.6MVA_Datasheet.pdf",
  mimeType: "application/pdf",
  buffer: Buffer.from("%PDF-1.4 dummy datasheet"),
});

await page.waitForSelector("#ingest-confirm", { timeout: 15000 });
check(true, "review drawer opened");
check((await page.inputValue('[data-ingest-field="vendor"]')) === "GE", "vendor prefilled from extraction");
check(Number(await page.inputValue('[data-ingest-field="mva"]')) === 3.6, "MVA prefilled from extraction");
check((await page.locator("text=unverified").count()) >= 1, "drawer states the entry stays unverified");
await page.screenshot({ path: shots + "/1_review_drawer.png", fullPage: true });

await page.click("#ingest-confirm");
await page.waitForSelector("#ingest-confirm", { state: "detached", timeout: 10000 });
await page.waitForSelector('[data-intake="inverter"]', { timeout: 10000 });
const invVal = await page.inputValue('[data-intake="inverter"]');
check(invVal.startsWith("GE LV5plus"), `inverter field set to the new entry (${invVal})`);
check((await page.locator('datalist#dl-inverter option[label*="unverified"]').count()) === 1,
  "datalist gained the unverified entry");
const stored = await page.evaluate(() =>
  JSON.parse(localStorage.getItem("gp_caiso_intake_v1") || "{}"));
check(Array.isArray(stored.custom_equipment) && stored.custom_equipment[0]?.vendor === "GE",
  "custom_equipment record persisted in the intake");
await page.screenshot({ path: shots + "/2_entry_added.png", fullPage: true });

// Design review: the entry drives the design and queues the verification.
await page.evaluate(() => {
  localStorage.setItem("gp_demo_onboard_v4", JSON.stringify({ started: true, wizardStep: 5 }));
});
await page.reload();
await page.waitForSelector("text=Plant topology", { timeout: 30000 });
check((await page.locator("text=GE LV5plus").count()) >= 1, "design uses the datasheet entry");
check((await page.locator("text=Datasheet inverter entry verification").count()) >= 1,
  "engineer verification queued in the approval list");
check((await page.locator("[data-eng-approve]").count()) === 3,
  "three pending approvals (routing, SC duty, datasheet entry)");
check((await page.locator("text=22 x GE LV5plus").count()) >= 1
  || (await page.locator("text=22 inverters").count()) >= 1, "fleet resized to 22 units");
await page.screenshot({ path: shots + "/3_design_review.png", fullPage: true });

await page.click("#eng-approve-all");
await page.waitForSelector("text=all approved", { timeout: 20000 });
await page.waitForSelector("#wiz-generate:not([disabled])", { timeout: 20000 });
check(true, "generate unlocked after signing off the datasheet entry");

await browser.close();
console.log(failures ? `DATASHEET INGEST TEST: ${failures} FAILURES` : "DATASHEET INGEST TEST DONE — all checks passed");
process.exit(failures ? 1 : 0);

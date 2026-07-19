// Screenshot every packet-file preview type.
// Usage: node scripts/preview_screenshots.mjs  (server must be running on :8000)
import { chromium } from "playwright-core";
import { mkdirSync } from "fs";

const BASE = "http://127.0.0.1:8000";
const shots = "/tmp/gp_preview_ui";
mkdirSync(shots, { recursive: true });

const browser = await chromium.launch({
  executablePath: "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
});
const page = await browser.newPage({ viewport: { width: 1200, height: 900 } });
page.on("pageerror", (e) => console.log("PAGEERROR:", e.message));
page.on("console", (m) => {
  if (m.type() === "error") console.log("CONSOLE ERR:", m.text());
});

// Demo login (sets session cookie in this context), then generate a packet via API.
const start = await page.request.post(BASE + "/api/demo/start");
if (!start.ok()) throw new Error("demo start failed");
const intakeRes = await page.request.get(BASE + "/api/caiso/intake");
const { defaults } = await intakeRes.json();
const genRes = await page.request.post(BASE + "/api/caiso/generate", { data: defaults });
const gen = await genRes.json();
if (!gen.ok) throw new Error("generate failed");
const pid = gen.packet.id;
console.log("packet:", pid);

const targets = [
  ["02_AttachmentA_Ravenwood.xlsx", "xlsx"],
  ["08_ProjectBoundary_Ravenwood.kmz", "kmz"],
  ["10_LoadFlowModel_Ravenwood.epc", "epc"],
  ["11_DynamicModel_Ravenwood.dyd", "dyd"],
  ["00_SubmissionChecklist_Ravenwood.md", "md"],
  ["01_Appendix1_Ravenwood.pdf", "pdf"],
];
for (const [file, tag] of targets) {
  await page.goto(`${BASE}/api/caiso/packets/${pid}/preview/${file}`);
  await page.waitForTimeout(tag === "pdf" ? 1800 : 500);
  await page.screenshot({ path: `${shots}/${tag}.png`, fullPage: tag !== "pdf" });
  console.log("shot:", tag);
}

console.log("PREVIEW SHOTS DONE");
await browser.close();

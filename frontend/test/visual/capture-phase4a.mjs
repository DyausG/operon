// Phase 4A visual-gate captures (08 §11.2) from the REAL running application:
//  • backend: `OPERON_AI_PROVIDER=none OPERON_REASONING_BACKEND=none uv run python run.py --no-browser`
//  • frontend: `npm run dev` (the design specimen is a development-only route)
// The script signs in through the UI, starts the Guided Demo from System → Simulation & Demo (the real
// lifecycle with simulated inputs), captures each state as the engine reaches it, then stops the
// backend (STOP_BACKEND_CMD) to capture the real disconnected state. No data is injected.
//
// Usage: STOP_BACKEND_CMD="kill <pid>" node test/visual/capture-phase4a.mjs [outDir]
import { execSync } from "node:child_process";
import { mkdirSync } from "node:fs";
import { resolve } from "node:path";
import { chromium } from "@playwright/test";

const BASE = process.env.BASE_URL || "http://127.0.0.1:5173";
const API = process.env.API_URL || "http://127.0.0.1:8000";
const OUT = resolve(process.argv[2] || "../design/v2/review/phase4a");
mkdirSync(OUT, { recursive: true });
const log = (...a) => console.log(new Date().toISOString().slice(11, 19), ...a);

async function engine() { return (await fetch(`${API}/api/state`)).json(); }
async function waitFor(pred, label, timeoutMs = 120000) {
  const end = Date.now() + timeoutMs;
  while (Date.now() < end) {
    const s = await engine();
    const hit = pred(s);
    if (hit) return hit;
    await new Promise((r) => setTimeout(r, 150));
  }
  throw new Error(`timed out waiting for ${label}`);
}
const demoAlert = (s) => (s.alerts || []).find((a) => a.incident_id && a.incident_id === s.demo_scenario?.incident_id);

const browser = await chromium.launch();
const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, colorScheme: "light" });
const page = await ctx.newPage();
page.on("pageerror", (e) => log("PAGEERROR", e.message));

async function shot(name, { width, height, theme, path, scroll, clip } = {}) {
  if (width) await page.setViewportSize({ width, height: height || 900 });
  if (path) {
    await page.goto(`${BASE}${path}${path.includes("?") ? "&" : "?"}theme=${theme || "light"}`);
    await page.waitForSelector(".wb-root");
    await page.waitForTimeout(900);
  }
  if (scroll) {
    await page.evaluate((sel) => document.querySelector(sel)?.scrollIntoView({ block: "start" }), scroll);
    await page.waitForTimeout(350);
  }
  const file = `${OUT}/${name}.png`;
  if (clip) await page.locator(clip).screenshot({ path: file });
  else await page.screenshot({ path: file });
  log("captured", name);
}

// ---- sign in through the UI (browser-local demo session; declared identity) ----
await page.goto(`${BASE}/login`);
await page.fill("input[type=email]", "reviewer@example.com");
await page.fill("input[type=password]", "reviewer-pass");
await page.keyboard.press("Enter");
await page.waitForURL("**/app/**");

// ---- start the Guided Demo from System → Simulation & Demo ----
await page.goto(`${BASE}/app/system/simulation?theme=light`);
await page.getByRole("button", { name: "Start guided demo" }).click();
log("guided demo started");

// ---- Case: investigation (Awaiting inspection loop; the engine holds it ~5 s) ----
const opened = await waitFor((s) => demoAlert(s), "a guided case");
await page.goto(`${BASE}/app/cases/${opened.incident_id}?theme=light`);
await page.getByText("Awaiting inspection · 2 of 8").waitFor({ timeout: 60000 });
await page.waitForTimeout(400);
await shot("06-case-investigation-light-1440", {});
await shot("06b-case-investigation-section-light-1440", { scroll: "#sec-investigation" });
await page.evaluate(() => document.querySelector(".wb-sheet")?.scrollTo(0, 0));
await shot("07-case-investigation-light-1024", { width: 1024, height: 768 });
const phaseAfter = demoAlert(await engine())?.lifecycle?.phase;
log("phase after investigation captures:", phaseAfter, phaseAfter === "AWAITING_EVIDENCE" ? "(captured inside the window)" : "(window may have passed; check images)");

// ---- Awaiting approval ----
const pending = await waitFor((s) => { const a = demoAlert(s); return a?.lifecycle?.phase === "AWAITING_APPROVAL" ? a : null; }, "AWAITING_APPROVAL");
const id = pending.incident_id;
log("awaiting approval:", id);

await shot("01-overview-active-light-1440", { width: 1440, height: 900, path: "/app/overview" });
await shot("01b-overview-active-dark-1440", { width: 1440, height: 900, theme: "dark", path: "/app/overview" });

for (const [n, w, h] of [["03-my-actions-docked-light-1440", 1440, 900], ["04-my-actions-docked-light-1280", 1280, 800]]) {
  await page.setViewportSize({ width: w, height: h });
  await page.goto(`${BASE}/app/actions?theme=light`);
  await page.locator(`[data-row="${id}"]`).click();
  await page.getByRole("complementary", { name: "Case preview" }).waitFor();
  await page.waitForTimeout(400);
  await shot(n);
}
await page.setViewportSize({ width: 1024, height: 768 });
await page.goto(`${BASE}/app/actions?theme=light`);
await page.locator(`[data-row="${id}"]`).click();
await page.getByRole("dialog", { name: "Case preview" }).waitFor();
await page.waitForTimeout(500);
await shot("05-my-actions-modal-drawer-light-1024");
await page.keyboard.press("Escape");
await shot("05b-my-actions-dark-1440-docked", { width: 1440, height: 900, theme: "dark", path: `/app/actions?preview=${id}` });

await shot("08-case-awaiting-approval-light-1440", { width: 1440, height: 900, path: `/app/cases/${id}` });
await shot("08b-case-decision-surface-light-1440", { scroll: "#decision-surface" });
await shot("08c-case-decision-surface-full-light-1440", { width: 1440, height: 2000, clip: "#decision-surface" });
await shot("09-case-awaiting-approval-light-1024", { width: 1024, height: 768, path: `/app/cases/${id}` });
await shot("09b-case-decision-surface-light-1024", { scroll: "#decision-surface" });
await shot("10-case-awaiting-approval-dark-1440", { width: 1440, height: 900, theme: "dark", path: `/app/cases/${id}` });
await shot("10b-case-decision-surface-dark-1440", { scroll: "#decision-surface" });
await shot("10c-case-decision-surface-full-dark-1440", { width: 1440, height: 2000, clip: "#decision-surface" });
await shot("11-case-awaiting-approval-dark-1024", { width: 1024, height: 768, theme: "dark", path: `/app/cases/${id}` });
await shot("11b-case-decision-surface-dark-1024", { scroll: "#decision-surface" });

await shot("12-specimen-light", { width: 1440, height: 900, path: "/app/dev/specimen" });
await page.setViewportSize({ width: 1440, height: 4200 });
await shot("12b-specimen-light-full", {});
await shot("13-specimen-dark", { width: 1440, height: 900, theme: "dark", path: "/app/dev/specimen" });
await page.setViewportSize({ width: 1440, height: 4200 });
await shot("13b-specimen-dark-full", {});

// ---- Disconnected: stop the real backend while two views are open ----
if (process.env.STOP_BACKEND_CMD) {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto(`${BASE}/app/overview?theme=light`);
  await page.waitForTimeout(2500);
  const second = await ctx.newPage();
  await second.setViewportSize({ width: 1440, height: 900 });
  await second.goto(`${BASE}/app/cases/${id}?theme=light#decision`);
  await second.waitForTimeout(2500);
  execSync(process.env.STOP_BACKEND_CMD);
  log("backend stopped");
  await page.getByText("Live connection lost.", { exact: true }).waitFor({ timeout: 20000 });
  await page.waitForTimeout(800);
  await shot("02-overview-disconnected-light-1440");
  await second.getByText("Live connection lost.", { exact: true }).waitFor({ timeout: 20000 });
  await second.evaluate(() => document.querySelector(".wb-decision-controls")?.scrollIntoView({ block: "center" }));
  await second.waitForTimeout(500);
  await second.screenshot({ path: `${OUT}/02b-case-decision-disconnected-light-1440.png` });
  log("captured", "02b-case-decision-disconnected-light-1440");
} else {
  log("STOP_BACKEND_CMD not set: skipped the disconnected captures");
}
await browser.close();

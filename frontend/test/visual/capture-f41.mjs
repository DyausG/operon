// F4.1 review captures from real engine fixture frames (test/make_fixtures.py): no backend, no
// simulator. The stream socket is answered with one fixture frame, the clock is pinned to the
// fixture era (test/fixture-era.js), and a declared demo session is seeded, as in test/e2e.
//
//   BASE_URL=http://127.0.0.1:5174 OUT=../design/v2/review/f4-1 node test/visual/capture-f41.mjs
//   (optional) CHANNEL=chrome to use the installed Chrome instead of Playwright's Chromium.
import { readFileSync, mkdirSync } from "node:fs";
import { chromium } from "@playwright/test";
import { fixtureNow } from "../fixture-era.js";

const BASE = process.env.BASE_URL || "http://127.0.0.1:5174";
const OUT = process.env.OUT || "../design/v2/review/f4-1";
const load = (name) => JSON.parse(readFileSync(new URL(`../fixtures/${name}`, import.meta.url), "utf8"));
const FRAMES = load("demo-frames.json");
const NOW = fixtureNow(FRAMES);
const SESSION = { email: "reviewer@example.com", name: "Reviewer", role: "maintenance_approver", remember: true, signedInAt: "2026-10-08T21:00:00Z", mode: "demo" };
const byPhase = (frames, phase) => frames.find((f) => f.alerts?.[0]?.lifecycle?.phase === phase);
const idOf = (frame) => frame.alerts[0].incident_id;

const [, REJECTED] = load("demo-frames-reject.json");
const [ESCALATED, , CANCELLED] = load("demo-frames-recovery.json");
const [FAILED, READY] = load("demo-frames-dispatch.json");
const APPROVAL = byPhase(FRAMES, "AWAITING_APPROVAL");

// Opens a recovery confirmation with a reason typed (nothing is sent: /api is answered with 404).
const confirmResume = async (page) => {
  await page.getByRole("button", { name: "Resume investigation…" }).click();
  await page.getByLabel("Reason").fill("Rejection reviewed with the planner; investigate the seal option.");
};

// name, frame, path, viewport, theme, optional interaction before the capture
const SHOTS = [
  ["01-case-decision-now-light-1440", APPROVAL, (f) => `/app/cases/${idOf(f)}`, [1440, 900], "light"],
  ["02-case-decision-now-dark-1440", APPROVAL, (f) => `/app/cases/${idOf(f)}`, [1440, 900], "dark"],
  ["03-case-decision-now-light-1024", APPROVAL, (f) => `/app/cases/${idOf(f)}`, [1024, 768], "light"],
  ["04-case-blocking-inspection-light-1440", load("demo-frames-blocking.json")[0], (f) => `/app/cases/${idOf(f)}`, [1440, 900], "light"],
  ["05-case-suspended-analysis-light-1440", load("demo-frames-suspended.json")[0], (f) => `/app/cases/${idOf(f)}`, [1440, 900], "light"],
  ["06-case-expired-approval-light-1440", load("demo-frames-expired.json")[0], (f) => `/app/cases/${idOf(f)}`, [1440, 900], "light"],
  ["07-case-escalated-light-1440", ESCALATED, (f) => `/app/cases/${idOf(f)}`, [1440, 900], "light"],
  ["08-case-escalated-resume-confirm-light-1440", ESCALATED, (f) => `/app/cases/${idOf(f)}`, [1440, 900], "light", confirmResume],
  ["09-case-dispatch-failed-light-1440", FAILED, (f) => `/app/cases/${idOf(f)}`, [1440, 900], "light"],
  ["10-case-ready-for-dispatch-dark-1440", READY, (f) => `/app/cases/${idOf(f)}`, [1440, 900], "dark"],
  ["11-case-planning-after-reject-light-1440", REJECTED, (f) => `/app/cases/${idOf(f)}`, [1440, 900], "light"],
  ["12-case-cancelled-light-1440", CANCELLED, (f) => `/app/cases/${idOf(f)}`, [1440, 900], "light"],
  ["13-case-inspector-asset-docked-light-1440", APPROVAL, (f) => `/app/cases/${idOf(f)}?inspect=asset#evidence`, [1440, 900], "light"],
  ["14-case-inspector-record-drawer-light-1024", APPROVAL, (f) => `/app/cases/${idOf(f)}?inspect=record`, [1024, 768], "light"],
  ["15-cases-list-light-1440", APPROVAL, () => "/app/cases?status=all", [1440, 900], "light"],
  ["16-cases-list-preview-light-1440", APPROVAL, (f) => `/app/cases?status=all&preview=${idOf(f)}`, [1440, 900], "light"],
  ["17-case-phone-390", APPROVAL, (f) => `/app/cases/${idOf(f)}`, [390, 844], "light"],
];

const only = process.env.ONLY ? new RegExp(process.env.ONLY) : null;
mkdirSync(OUT, { recursive: true });
const browser = await chromium.launch(process.env.CHANNEL ? { channel: process.env.CHANNEL } : {});
try {
  for (const [name, frame, path, [width, height], theme, act] of SHOTS) {
    if (only && !only.test(name)) continue;
    const context = await browser.newContext({ viewport: { width, height }, deviceScaleFactor: 1 });
    const page = await context.newPage();
    await page.clock.install({ time: NOW });
    await page.addInitScript(([session, t]) => {
      localStorage.setItem("operon.session", JSON.stringify(session));
      localStorage.setItem("operon.v2.theme", JSON.stringify(t));
    }, [SESSION, theme]);
    await page.routeWebSocket(/\/ws$/, (ws) => ws.send(JSON.stringify(frame)));
    await page.route("**/api/**", (route) => route.fulfill({ status: 404, json: { ok: false, error: "not in the capture harness" } }));
    await page.goto(`${BASE}${path(frame)}`);
    await page.waitForSelector(".wb-root");
    await page.waitForSelector(".wb-case, .wb-cl-table, .wb-cl-empty"); // the frame has arrived
    if (act) await act(page);
    await page.waitForTimeout(400);
    await page.screenshot({ path: `${OUT}/${name}.png` });
    await context.close();
    console.log("captured", name);
  }
} finally {
  await browser.close();
}

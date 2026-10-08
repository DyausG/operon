// Warm the server once before the suite. On a freshly installed node_modules, Vite's first
// dependency pre-bundle took ~30 s on Windows (observed: the pre-bundle finished exactly when the
// first test's navigation hit its 30 s timeout; later runs, even with an emptied cache, pre-bundle
// in ~2 s). Vite also reloads an open page when the pre-bundle completes. Two full page loads here,
// outside any test's timeout, absorb both; against a production preview this is a quick no-op.
import { chromium } from "@playwright/test";

export default async function globalSetup(config) {
  const use = config.projects[0]?.use || {};
  const browser = await chromium.launch(use.channel ? { channel: use.channel } : {});
  try {
    const page = await browser.newPage();
    // No engine in the suite: answer the app's stream socket so the dev proxy never dials :8000.
    await page.routeWebSocket(/\/ws$/, (ws) => ws.close());
    for (let i = 0; i < 2; i += 1) {
      await page.goto(`${use.baseURL}/login`, { waitUntil: "load", timeout: 180_000 });
      await page.waitForLoadState("networkidle", { timeout: 30_000 }).catch(() => {});
    }
  } finally {
    await browser.close();
  }
}

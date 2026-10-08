// Phase 4A interaction tests. The app runs on the Vite dev server; the engine WebSocket and REST calls
// are answered by the test from the real engine fixture frames (test/make_fixtures.py), so nothing
// here depends on a running backend and nothing is added to the application.
import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: ".",
  globalSetup: "./global-setup.js",
  timeout: 30000,
  fullyParallel: false,
  workers: 1,
  reporter: [["list"]],
  use: { baseURL: "http://127.0.0.1:5174", trace: "off" },
  webServer: {
    command: "npx vite --port 5174 --strictPort --host 127.0.0.1",
    cwd: "../..",
    url: "http://127.0.0.1:5174",
    reuseExistingServer: true,
    timeout: 60000,
  },
});

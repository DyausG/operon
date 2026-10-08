// V2 / legacy isolation in a real browser: the workbench owns /app, the legacy portal owns /legacy,
// navigation never silently crosses between them, and old /app/<legacy page> URLs keep working.
import { expect, test } from "@playwright/test";
import { INCIDENT, boot } from "./harness.js";

const v2 = async (page) => { await expect(page.locator(".wb-root")).toBeVisible(); await expect(page.locator(".app")).toHaveCount(0); };
const legacy = async (page) => { await expect(page.locator(".app")).toBeVisible(); await expect(page.locator(".wb-root")).toHaveCount(0); };
const at = (page, path) => expect(page).toHaveURL((u) => `${u.pathname}${u.search}${u.hash}` === path);

async function start(page, opts) {
  await page.setViewportSize({ width: 1440, height: 900 });
  const h = await boot(page, opts);
  // No backend in this harness: REST calls answer with a JSON 404 instead of a proxy error.
  await page.route("**/api/**", (route) => route.fulfill({ status: 404, json: { ok: false, error: "not in harness" } }));
  return h;
}

async function signIn(page) {
  await expect(page).toHaveURL(/\/login$/);
  await page.locator('input[name="email"]').fill("reviewer@example.com");
  await page.locator('input[name="password"]').fill("harness-pass");
  await page.getByRole("button", { name: "Sign in" }).click();
}

test.describe("V2 navigation stays in the workbench", () => {
  test("every rail item opens a /app page inside the V2 shell", async ({ page }) => {
    await start(page);
    await page.goto("/app/overview");
    const rail = page.getByRole("navigation", { name: "Primary" });
    for (const [name, path] of [["Cases", "/app/cases"], ["Assets", "/app/assets"], ["Work orders", "/app/work-orders"], ["Reliability", "/app/reliability"],
      ["Audit log", "/app/audit"], ["System", "/app/system/simulation"], [/^My actions/, "/app/actions"], ["Overview", "/app/overview"]]) {
      await rail.getByRole("link", { name }).click();
      await at(page, path);
      await v2(page);
    }
  });

  test("unfinished destinations say so; the legacy page is only an explicit, labelled link", async ({ page }) => {
    await start(page);
    await page.goto("/app/cases");
    await v2(page);
    await expect(page.locator("h1")).toHaveText("Cases");
    await expect(page.getByText("Cases isn’t available in this version of the workbench yet.")).toBeVisible();
    await expect(page.getByRole("navigation", { name: "Primary" }).getByRole("link", { name: "Cases" })).toHaveClass(/is-active/);
    await page.getByRole("link", { name: "open Incidents in the legacy portal" }).click();
    await at(page, "/legacy/incidents");
    await legacy(page);
    await page.goBack();
    await at(page, "/app/cases");
    await v2(page);
  });

  test("Updates, Preferences and the case breadcrumb stay in V2", async ({ page }) => {
    await start(page);
    await page.goto(`/app/cases/${INCIDENT}`);
    await page.getByRole("navigation", { name: "Breadcrumb" }).getByRole("link", { name: "Cases" }).click();
    await at(page, "/app/cases");
    await v2(page);
    await page.getByRole("link", { name: /^Updates/ }).click();
    await at(page, "/app/updates");
    await v2(page);
    await page.getByRole("button", { name: /Reviewer/ }).click();
    await page.getByRole("menuitem", { name: "Preferences" }).click();
    await at(page, "/app/preferences");
    await v2(page);
  });

  test("Back and Forward move between V2 pages without leaving the shell", async ({ page }) => {
    await start(page);
    await page.goto("/app/overview");
    const rail = page.getByRole("navigation", { name: "Primary" });
    await rail.getByRole("link", { name: /^My actions/ }).click();
    await rail.getByRole("link", { name: "Cases" }).click();
    await rail.getByRole("link", { name: "Assets" }).click();
    for (const path of ["/app/cases", "/app/actions", "/app/overview"]) { await page.goBack(); await at(page, path); await v2(page); }
    await page.goForward();
    await at(page, "/app/actions");
    await v2(page);
  });

  test("direct links and refreshes keep the path, query and hash", async ({ page }) => {
    await start(page);
    await page.goto(`/app/cases/${INCIDENT}#decision`);
    await page.reload();
    await at(page, `/app/cases/${INCIDENT}#decision`);
    await v2(page);
    await expect(page.getByRole("heading", { name: "Decision required" })).toBeVisible();
    await page.goto(`/app/actions?preview=${INCIDENT}`);
    await page.reload();
    await at(page, `/app/actions?preview=${INCIDENT}`);
    await expect(page.getByRole("complementary", { name: "Case preview" })).toBeVisible();
  });

  test("root, unknown paths and unknown /app paths never land on a legacy page", async ({ page }) => {
    await start(page);
    for (const path of ["/", "/no-such-page"]) { await page.goto(path); await at(page, "/app/overview"); await v2(page); }
    await page.goto("/app/no-such-page?x=1");
    await at(page, "/app/no-such-page?x=1");
    await v2(page);
    await expect(page.locator("h1")).toHaveText("Page not found");
  });
});

test.describe("legacy portal under /legacy", () => {
  test("old /app/<legacy page> URLs redirect to /legacy with query and hash", async ({ page }) => {
    await start(page);
    for (const [from, to] of [["/app", "/app/overview"], ["/app/dashboard?x=1#top", "/legacy/dashboard?x=1#top"], [`/app/incidents/${INCIDENT}`, `/legacy/incidents/${INCIDENT}`],
      [`/app/agent?incident=${INCIDENT}`, `/legacy/agent?incident=${INCIDENT}`], ["/app/settings#plant", "/legacy/settings#plant"]]) {
      await page.goto(from);
      await at(page, to);
      if (to.startsWith("/legacy")) await legacy(page); else await v2(page);
    }
    await page.goBack(); // the redirect replaced the old entry: Back does not bounce through it
    await at(page, `/legacy/agent?incident=${INCIDENT}`);
  });

  test("legacy navigation stays in the legacy shell", async ({ page }) => {
    await start(page);
    await page.goto("/legacy");
    await at(page, "/legacy/dashboard");
    await legacy(page);
    const sidebar = page.getByRole("complementary", { name: "Primary" });
    await sidebar.getByRole("link", { name: /^Machines/ }).click();
    await at(page, "/legacy/machines");
    await page.locator("table tbody tr").first().click();
    await expect(page).toHaveURL(/\/legacy\/machines\/[^/]+$/);
    await legacy(page);
    await sidebar.getByRole("link", { name: /^Incidents/ }).click();
    await at(page, "/legacy/incidents");
    await page.locator("table tbody tr").first().click();
    await expect(page).toHaveURL(/\/legacy\/incidents\/[^/]+$/);
    await legacy(page);
    await page.reload();
    await legacy(page);
    await page.goBack();
    await at(page, "/legacy/incidents");
    await legacy(page);
  });
});

test.describe("authentication redirects", () => {
  test("signed out, a legacy deep link returns to itself after sign-in, query and hash intact", async ({ page }) => {
    await start(page, { signedIn: false });
    await page.goto("/legacy/machines?q=comp#list");
    await signIn(page);
    await at(page, "/legacy/machines?q=comp#list");
    await legacy(page);
  });

  test("signed out, a V2 deep link returns to itself after sign-in", async ({ page }) => {
    await start(page, { signedIn: false });
    await page.goto(`/app/actions?preview=${INCIDENT}`);
    await signIn(page);
    await at(page, `/app/actions?preview=${INCIDENT}`);
    await v2(page);
  });

  test("signed out, an old /app/<legacy page> URL ends on the legacy page after sign-in", async ({ page }) => {
    await start(page, { signedIn: false });
    await page.goto("/app/machines");
    await signIn(page);
    await at(page, "/legacy/machines");
    await legacy(page);
  });

  test("sign-out and sign-in keep each experience in its own shell", async ({ page }) => {
    await start(page, { signedIn: false });
    await page.goto("/legacy/dashboard");
    await signIn(page);
    await at(page, "/legacy/dashboard");
    await page.getByRole("button", { name: "Account menu" }).click();
    await page.getByRole("menuitem", { name: "Sign out" }).click();
    await signIn(page);
    await at(page, "/legacy/dashboard");
    await legacy(page);

    await page.goto("/app/cases");
    await page.getByRole("button", { name: /Reviewer/ }).click();
    await page.getByRole("menuitem", { name: "Sign out" }).click();
    await signIn(page);
    await at(page, "/app/cases");
    await v2(page);
  });
});

// F4.1 case inspector in a real browser: docked beside the case at ≥ 1280 (non-modal, the case stays
// usable), a modal drawer below (scrim, focus moves in, Esc closes), Back closes, focus returns to
// the control that opened it, and record detail comes from GET /api/demo/artifacts/{id}.
import { expect, test } from "@playwright/test";
import { APPROVAL, ARTIFACTS, INCIDENT, boot, serveArtifacts } from "./harness.js";

const caseUrl = `/app/cases/${INCIDENT}`;
const evidence = APPROVAL.alerts[0].lifecycle.read_model.evidence;

test.describe("case inspector", () => {
  for (const width of [1440, 1280]) {
    test(`${width}: docked beside the case, non-modal; Back closes and focus returns`, async ({ page }) => {
      await page.setViewportSize({ width, height: 900 });
      await boot(page);
      await page.goto(caseUrl);
      const opener = page.getByRole("link", { name: "asset", exact: true });
      await opener.click();
      await expect(page).toHaveURL(/\?inspect=asset$/);
      const pane = page.getByRole("complementary", { name: /^Asset · / });
      await expect(pane).toBeVisible();
      await expect(page.getByRole("dialog")).toHaveCount(0);
      // The case is not occluded: the content column ends where the pane begins.
      const content = await page.locator(".wb-case-scroll").boundingBox();
      const box = await pane.boundingBox();
      expect(content.x + content.width).toBeLessThanOrEqual(box.x + 1);
      expect(box.width).toBeGreaterThanOrEqual(370);
      // Still interactive: the navigator works with the pane open.
      await page.getByRole("navigation", { name: "Case sections" }).getByRole("link", { name: /Evidence/ }).click();
      await expect(page).toHaveURL(/\?inspect=asset#evidence$/);
      await expect(pane).toBeVisible();
      await page.goBack();
      await page.goBack();
      await expect(pane).toHaveCount(0);
      await expect(opener).toBeFocused();
    });
  }

  test("1024: a modal drawer; Esc closes and focus returns to the opener", async ({ page }) => {
    await page.setViewportSize({ width: 1024, height: 768 });
    await boot(page);
    await page.goto(caseUrl);
    const opener = page.getByRole("link", { name: "identifiers", exact: true });
    await opener.click();
    const dialog = page.getByRole("dialog", { name: "Identifiers" });
    await expect(dialog).toBeVisible();
    await expect(page.locator(".wb-scrim")).toBeVisible();
    await expect(dialog.getByRole("heading", { name: "Identifiers" })).toBeFocused();
    expect(await page.locator("[data-wb-inert]").evaluate((el) => el.inert)).toBe(true);
    await page.keyboard.press("Escape");
    await expect(dialog).toHaveCount(0);
    await expect(page).toHaveURL(new RegExp(`${caseUrl}$`));
    await expect(opener).toBeFocused();
  });

  test("record detail comes from the artifact endpoint, without confidence values; Back closes it", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await boot(page);
    await serveArtifacts(page);
    const ev = evidence.find((e) => ARTIFACTS[e.id]);
    test.skip(!ev, "no captured artifact for this frame's evidence");
    await page.goto(`${caseUrl}#evidence`);
    await page.getByRole("link", { name: ev.summary }).first().click();
    const pane = page.getByRole("complementary", { name: "Record detail" });
    await expect(pane.getByText("Recorded content")).toBeVisible();
    await expect(pane).toContainText(ARTIFACTS[ev.id].id.slice(0, 8));
    await expect(pane).not.toContainText(/confidence/i);
    await page.goBack();
    await expect(pane).toHaveCount(0);
  });

  test("an id the server doesn't know falls back to the case's own row", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await boot(page);
    await page.route(/\/api\/demo\/artifacts\//, (route) => route.fulfill({ status: 404, json: { ok: false, error: "unknown demo artifact" } }));
    await page.goto(`${caseUrl}?inspect=artifact:${encodeURIComponent(evidence[0].id)}`);
    const pane = page.getByRole("complementary", { name: "Record detail" });
    await expect(pane).toContainText("The server has no detail for this record (HTTP 404). Showing the case’s own copy.");
    await expect(pane.getByText("Recorded content")).toBeVisible();
  });

  test("a direct link opens the inspector; closing it replaces the URL instead of leaving the page", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await boot(page);
    await page.goto(`${caseUrl}?inspect=record#record`);
    const pane = page.getByRole("complementary", { name: "Full record" });
    await expect(pane).toBeVisible();
    await pane.getByRole("radio", { name: "All events" }).click();
    await pane.getByRole("searchbox", { name: "Filter the record" }).fill("approval");
    await expect(pane).toContainText(/\d+ of \d+ events/);
    await pane.getByRole("button", { name: "Close inspector" }).click();
    await expect(pane).toHaveCount(0);
    await expect(page).toHaveURL(new RegExp(`${caseUrl}#record$`));
  });
});

// F4.1 Cases list in a real browser: filters live in the URL (reload and Back restore them), a row
// opens the CH-2 preview (docked ≥ 1280, modal drawer below, the case itself on a phone), keyboard
// moves between rows, and Back from a case returns to the same filtered list.
import { expect, test } from "@playwright/test";
import { APPROVAL, INCIDENT, RECOVERY_FRAMES, boot } from "./harness.js";

const [ESCALATED] = RECOVERY_FRAMES;
const ESC_ID = ESCALATED.alerts[0].incident_id;
const row = (page, id) => page.locator(`[data-row="${id}"]`);

test.describe("Cases list", () => {
  test("filters are in the URL; reload and Back restore them", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await boot(page, { frame: ESCALATED });
    await page.goto("/app/cases");
    await expect(page.getByText("Limited history: the live stream carries only the latest case for each asset (G5).")).toBeVisible();
    await page.getByRole("radio", { name: /^Exceptions · 1$/ }).click();
    await expect(page).toHaveURL(/\?status=exceptions$/);
    await page.getByLabel("Waiting on").selectOption("reliability_engineer");
    await expect(page).toHaveURL(/status=exceptions&waiting=reliability_engineer$/);
    await expect(row(page, ESC_ID)).toBeVisible();
    await page.reload();
    await expect(page.getByLabel("Waiting on")).toHaveValue("reliability_engineer");
    await expect(row(page, ESC_ID)).toBeVisible();

    await page.getByRole("searchbox", { name: "Asset" }).fill("zzz");
    await expect(page.getByText("No cases match these filters.")).toBeVisible();
    await page.getByRole("button", { name: "Clear filters" }).click();
    await expect(page).toHaveURL(/\?status=exceptions$/);

    await page.getByRole("link", { name: /^Open case/ }).click();
    await expect(page).toHaveURL(new RegExp(`/app/cases/${ESC_ID}$`));
    await page.goBack();
    await expect(page).toHaveURL(/\?status=exceptions$/);
    await expect(page.getByRole("radio", { name: /^Exceptions/ })).toHaveAttribute("aria-checked", "true");
  });

  test("1440: a row opens the docked preview; Esc closes it and focus returns to the row", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await boot(page, { frame: APPROVAL });
    await page.goto("/app/cases");
    await row(page, INCIDENT).click();
    const pane = page.getByRole("complementary", { name: "Case preview" });
    await expect(pane).toBeVisible();
    await expect(pane.getByRole("link", { name: "Go to decision" })).toBeVisible();
    await expect(page.getByRole("dialog")).toHaveCount(0);
    await row(page, INCIDENT).press("Escape");
    await expect(pane).toHaveCount(0);
    await expect(row(page, INCIDENT)).toBeFocused();
    // Shift+Enter opens the case workspace.
    await row(page, INCIDENT).press("Shift+Enter");
    await expect(page).toHaveURL(new RegExp(`/app/cases/${INCIDENT}$`));
  });

  test("1024: a row opens a modal drawer; Back closes it", async ({ page }) => {
    await page.setViewportSize({ width: 1024, height: 768 });
    await boot(page, { frame: APPROVAL });
    await page.goto("/app/cases?status=all");
    await row(page, INCIDENT).click();
    await expect(page.getByRole("dialog", { name: "Case preview" })).toBeVisible();
    await page.goBack();
    await expect(page.getByRole("dialog")).toHaveCount(0);
    await expect(page).toHaveURL(/\?status=all$/);
    await expect(row(page, INCIDENT)).toBeFocused();
  });

  test("390: a row opens the case itself", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await boot(page, { frame: APPROVAL });
    await page.goto("/app/cases");
    await row(page, INCIDENT).click();
    await expect(page).toHaveURL(new RegExp(`/app/cases/${INCIDENT}$`));
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    expect(overflow).toBeLessThanOrEqual(0);
  });
});

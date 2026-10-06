import { expect, test } from "@playwright/test";
import { APPROVAL, INCIDENT, boot } from "./harness.js";

const row = (page) => page.locator(`[data-row="${INCIDENT}"]`);

test.describe("CH-2 preview behaviour", () => {
  for (const width of [1440, 1280]) {
    test(`${width}: docked, non-modal, queue stays interactive and unoccluded`, async ({ page }) => {
      await page.setViewportSize({ width, height: 900 });
      await boot(page);
      await page.goto("/app/actions");
      await row(page).click();
      const pane = page.getByRole("complementary", { name: "Case preview" });
      await expect(pane).toBeVisible();
      await expect(page.locator(".wb-scrim")).toHaveCount(0);
      await expect(page.getByRole("dialog")).toHaveCount(0);
      const box = await pane.boundingBox();
      expect(Math.round(box.width)).toBe(380);
      const r = await row(page).boundingBox();
      expect(r.x + r.width).toBeLessThanOrEqual(box.x + 1); // selected row never covered
      await expect(page).toHaveURL(new RegExp(`preview=${INCIDENT}`));
      // Queue remains operable while the preview is open.
      await page.getByRole("radio", { name: "All roles" }).click();
      await expect(pane).toBeVisible();
      // Esc closes and returns focus to the originating row.
      await pane.getByRole("button", { name: "Close preview" }).focus();
      await page.keyboard.press("Escape");
      await expect(pane).toHaveCount(0);
      await expect(row(page)).toBeFocused();
    });
  }

  test("1024: modal drawer with scrim, inert background, trapped focus, Esc and Back", async ({ page }) => {
    await page.setViewportSize({ width: 1024, height: 768 });
    await boot(page);
    await page.goto("/app/actions");
    await row(page).focus();
    await page.keyboard.press("Enter");
    const dialog = page.getByRole("dialog", { name: "Case preview" });
    await expect(dialog).toBeVisible();
    await expect(dialog).toHaveAttribute("aria-modal", "true");
    await expect(page.locator(".wb-scrim")).toBeVisible();
    await expect(page.getByRole("heading", { name: "Case preview" })).toBeFocused();
    expect(await page.locator("[data-wb-inert]").evaluate((el) => el.inert)).toBe(true);
    for (let i = 0; i < 8; i += 1) {
      await page.keyboard.press("Tab");
      expect(await page.evaluate(() => !!document.activeElement?.closest('[role="dialog"]'))).toBe(true);
    }
    await page.keyboard.press("Escape");
    await expect(dialog).toHaveCount(0);
    await expect(row(page)).toBeFocused();
    expect(await page.locator("[data-wb-inert]").evaluate((el) => el.inert)).toBe(false);
    // Back closes the preview before leaving the page.
    await row(page).click();
    await expect(dialog).toBeVisible();
    await page.goBack();
    await expect(dialog).toHaveCount(0);
    await expect(page).toHaveURL(/\/app\/actions$/);
  });

  test("docked ↑/↓ and J/K move between rows; Shift+Enter opens the workspace", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await boot(page);
    await page.goto("/app/actions");
    await row(page).focus();
    await page.keyboard.press("Shift+Enter");
    await expect(page).toHaveURL(new RegExp(`/app/cases/${INCIDENT}`));
  });
});

test.describe("decision surface (screen 8)", () => {
  test("Approve sends the exact bound identifiers and a declared actor", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await boot(page);
    let body = null;
    await page.route(`**/api/incidents/${INCIDENT}/approval`, async (route) => {
      body = route.request().postDataJSON();
      await route.fulfill({ json: { ok: true } });
    });
    await page.goto(`/app/cases/${INCIDENT}#decision`);
    await page.getByRole("button", { name: "Approve and dispatch" }).click();
    await expect(page.getByText(/^Approved by Reviewer at/)).toBeVisible();
    const lc = APPROVAL.alerts[0].lifecycle;
    expect(body).toMatchObject({
      requirement_id: lc.requirement_id, intervention_id: lc.intervention_id, intervention_hash: lc.intervention_hash,
      context_revision: lc.context_revision, decision: "APPROVE", actor_id: "reviewer@example.com", actor_role: "maintenance_approver",
    });
  });

  test("Reject requires a reason; a short reason warns; refusals are shown verbatim", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await boot(page);
    const sent = [];
    await page.route(`**/api/incidents/${INCIDENT}/approval`, async (route) => {
      sent.push(route.request().postDataJSON());
      await route.fulfill({ status: 409, json: { ok: false, error: "requirement is already EXPIRED" } });
    });
    await page.goto(`/app/cases/${INCIDENT}#decision`);
    await page.getByRole("button", { name: "Reject and escalate…" }).click();
    await page.getByRole("button", { name: "Confirm rejection" }).click();
    await expect(page.getByText("A reason is required to reject.")).toBeVisible();
    await expect(page.getByLabel("Rationale")).toBeFocused();
    expect(sent).toHaveLength(0);
    await page.getByLabel("Rationale").fill("too soon");
    await page.getByLabel("Rationale").blur();
    await expect(page.getByText("This reason is short. It will be recorded as written.")).toBeVisible();
    await page.getByRole("button", { name: "Confirm rejection" }).click();
    await expect(page.getByText("requirement is already EXPIRED")).toBeVisible();
    expect(sent[0]).toMatchObject({ decision: "REJECT", rationale: "too soon" });
  });

  test("disconnected: Approve is inactive (focusable, aria-disabled) and moves focus to the banner", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    const { disconnect } = await boot(page);
    let calls = 0;
    await page.route(`**/api/incidents/${INCIDENT}/approval`, (route) => { calls += 1; return route.fulfill({ json: { ok: true } }); });
    await page.goto(`/app/cases/${INCIDENT}#decision`);
    await expect(page.getByRole("button", { name: "Approve and dispatch" })).not.toHaveAttribute("aria-disabled", "true");
    await disconnect();
    const approve = page.getByRole("button", { name: "Approve and dispatch" });
    await expect(approve).toHaveAttribute("aria-disabled", "true");
    expect(await approve.evaluate((el) => el.disabled)).toBe(false); // inactive, not disabled (R-3)
    await approve.focus();
    await expect(approve).toBeFocused();
    await page.keyboard.press("Enter");
    await expect(page.locator("#wb-connection-banner")).toBeFocused();
    expect(calls).toBe(0);
  });

  test("Approve has no keyboard shortcut", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await boot(page);
    let calls = 0;
    await page.route("**/api/incidents/**", (route) => { calls += 1; return route.fulfill({ json: { ok: true } }); });
    await page.goto(`/app/cases/${INCIDENT}`);
    for (const key of ["a", "A", "Enter", "y"]) await page.keyboard.press(key);
    expect(calls).toBe(0);
  });
});

test.describe("shell, theme and structure", () => {
  test("theme follows the OS and the account-menu override persists", async ({ page }) => {
    await page.emulateMedia({ colorScheme: "dark" });
    await boot(page, { theme: "system" });
    await page.goto("/app/overview");
    await expect(page.locator(".wb-root")).toHaveAttribute("data-theme", "dark");
    await page.getByRole("button", { name: /Reviewer/ }).click();
    await page.getByRole("radio", { name: "Light" }).click();
    await expect(page.locator(".wb-root")).toHaveAttribute("data-theme", "light");
    await page.reload();
    await expect(page.locator(".wb-root")).toHaveAttribute("data-theme", "light");
  });

  test("landmarks, one h1, stage track semantics, no engine controls in the header", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await boot(page);
    await page.goto(`/app/cases/${INCIDENT}`);
    await expect(page.getByRole("banner")).toHaveCount(1);
    await expect(page.getByRole("navigation", { name: "Primary" })).toBeVisible();
    await expect(page.getByRole("main")).toHaveCount(1);
    await expect(page.locator("h1")).toHaveCount(1);
    const track = page.getByRole("group", { name: "Case lifecycle position" });
    await expect(track.locator('[aria-current="step"]')).toContainText("Awaiting decision");
    await expect(track.locator("a, button")).toHaveCount(0); // a position display, never a stepper
    const header = page.getByRole("banner");
    await expect(header.getByText(/Start guided demo|Pause simulation|Reset engine/)).toHaveCount(0);
    await page.getByRole("link", { name: "System" }).click();
    await expect(page.getByRole("button", { name: "Start guided demo" })).toBeVisible();
  });

  test("390 px smoke: shell does not break", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await boot(page);
    await page.goto("/app/overview");
    await expect(page.locator("h1")).toHaveText("Overview");
    const overflow = await page.evaluate(() => document.querySelector(".wb-sheet").scrollWidth - document.querySelector(".wb-sheet").clientWidth);
    expect(overflow).toBeLessThanOrEqual(1);
  });
});

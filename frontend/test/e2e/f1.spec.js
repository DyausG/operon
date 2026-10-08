// F1.1 behaviour in a real browser, over frames the real engine produced (test/make_fixtures.py):
// a rejection returns the case to planning, MATERIAL uncertainty is a condition on the decision,
// and BLOCKING uncertainty leaves the case parked with no decision offered.
import { expect, test } from "@playwright/test";
import { BLOCKING_FRAME, MATERIAL_FRAME, REJECT_FRAMES, boot, incidentOf } from "./harness.js";

const [AWAITING, REJECTED] = REJECT_FRAMES;
const track = (page) => page.getByRole("group", { name: "Case lifecycle position" });

test.describe("F1.1 decisions and uncertainty", () => {
  test("reject, then the backend's planning frame: the case moves to Planning and no decision remains", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    const { push } = await boot(page, { frame: AWAITING });
    const id = incidentOf(AWAITING);
    let body = null;
    await page.route(`**/api/incidents/${id}/approval`, async (route) => {
      body = route.request().postDataJSON();
      await route.fulfill({ json: { ok: true } });
    });
    await page.goto(`/app/cases/${id}#decision`);
    await expect(track(page).locator('[aria-current="step"]')).toContainText("Awaiting decision");
    await page.getByRole("button", { name: "Reject and return to planning…" }).click();
    await page.getByLabel("Rationale").fill("maintenance window clashes with a planned shutdown");
    await page.getByRole("button", { name: "Confirm rejection" }).click();
    await expect(page.getByText(/^Rejected; returned to planning by Reviewer at/)).toBeVisible();
    const lc = AWAITING.alerts[0].lifecycle;
    expect(body).toMatchObject({ decision: "REJECT", requirement_id: lc.requirement_id, intervention_id: lc.intervention_id,
      intervention_hash: lc.intervention_hash, context_revision: lc.context_revision });

    push(REJECTED); // what the engine broadcasts once the rejection is recorded
    await expect(track(page).locator('[aria-current="step"]')).toContainText("Planning");
    await expect(page.getByRole("button", { name: "Approve and dispatch" })).toHaveCount(0);
    await expect(page.getByText("Decision required")).toHaveCount(0);
    await expect(page.getByText("Rejected by dashboard-operator")).toBeVisible();
  });

  test("MATERIAL uncertainty is listed under Conditions and approval stays available", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await boot(page, { frame: MATERIAL_FRAME });
    await page.goto(`/app/cases/${incidentOf(MATERIAL_FRAME)}#decision`);
    const decision = page.locator("#decision-surface");
    await expect(decision.getByText("MATERIAL uncertainty (diagnostic): Fixture: maintenance history before the last service is incomplete")).toBeVisible();
    await expect(decision.getByRole("button", { name: "Approve and dispatch" })).not.toHaveAttribute("aria-disabled", "true");
  });

  test("BLOCKING uncertainty: the case waits for inspection, no decision is offered, the record says why", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await boot(page, { frame: BLOCKING_FRAME });
    await page.goto(`/app/cases/${incidentOf(BLOCKING_FRAME)}`);
    await expect(page.getByText("Awaiting inspection · 2/8").first()).toBeVisible();
    await expect(page.locator("#decision-surface")).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Approve and dispatch" })).toHaveCount(0);
    await expect(page.getByText(/blocking uncertainty remains: Fixture: shaft condition has not been inspected/).first()).toBeVisible();
  });
});

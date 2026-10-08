// F1.1 recovery commands in a real browser, over real engine exception frames. The command endpoints
// are answered by the test (route), so these check what the interface sends, when it refuses to
// send, and how it shows the backend's answer; the backend's own validation is tested in tests/.
import { expect, test } from "@playwright/test";
import { DISPATCH_FRAMES, EXPIRED_FRAME, RECOVERY_FRAMES, SESSION, boot, incidentOf, lifecycleOf } from "./harness.js";

const [ESCALATED, RESUMED] = RECOVERY_FRAMES;
const [, READY] = DISPATCH_FRAMES;
const actions = (page) => page.getByRole("region", { name: /actions on this case/i });
const confirmPanel = (page, label) => page.getByRole("group", { name: `Confirm: ${label}` });

/** Record every POST to the case's command endpoints; answer with `reply` (default: accepted). */
async function capture(page, id, reply = () => ({ status: 200, json: { ok: true } })) {
  const sent = [];
  await page.route(new RegExp(`/api/incidents/${id}/(commands/[a-z_]+|execute)$`), async (route) => {
    const req = route.request();
    sent.push({ path: new URL(req.url()).pathname, body: req.postDataJSON() });
    const r = reply(req);
    await route.fulfill({ status: r.status, json: r.json });
  });
  return sent;
}

test.describe("F1.1 recovery commands", () => {
  test.beforeEach(async ({ page }) => { await page.setViewportSize({ width: 1440, height: 900 }); });

  test("resume an escalated case: consequence first, a reason required, the reviewed revision sent", async ({ page }) => {
    const { push } = await boot(page, { frame: ESCALATED });
    const id = incidentOf(ESCALATED);
    const sent = await capture(page, id);
    await page.goto(`/app/cases/${id}`);
    await expect(actions(page).getByRole("button")).toHaveText(["Resume investigation…", "Cancel case…"]);

    await actions(page).getByRole("button", { name: "Resume investigation…" }).click();
    const panel = confirmPanel(page, "Resume investigation");
    await expect(panel).toContainText("Returns the case to Investigating.");
    await expect(panel).toContainText("recorded with a declared identity (not verified: G8)");
    await panel.getByRole("button", { name: "Resume investigation", exact: true }).click();
    await expect(panel.getByText("A reason is required.")).toBeVisible();
    expect(sent).toHaveLength(0);

    await panel.getByLabel("Reason").fill("rejection reviewed with the planner; investigate the seal option");
    await panel.getByRole("button", { name: "Resume investigation", exact: true }).click();
    await expect(page.getByRole("status").filter({ hasText: "“Resume investigation” accepted by the backend" })).toBeVisible();
    expect(sent).toEqual([{ path: `/api/incidents/${id}/commands/resume`, body: {
      actor_id: SESSION.email, actor_role: "maintenance_approver", expected_revision: lifecycleOf(ESCALATED).revision,
      rationale: "rejection reviewed with the planner; investigate the seal option" } }]);

    push(RESUMED); // what the engine broadcasts once the command is applied
    await expect(page.getByRole("group", { name: "Case lifecycle position" }).locator('[aria-current="step"]')).toContainText("Investigating");
    await expect(actions(page).getByRole("button")).toHaveText(["Escalate…", "Cancel case…"]);
  });

  test("a refusal keeps its lead, a cleaned server reason and the HTTP status; markup in the body stays text", async ({ page }) => {
    await boot(page, { frame: EXPIRED_FRAME });
    const id = incidentOf(EXPIRED_FRAME);
    const sent = await capture(page, id, () => ({ status: 409, json: { ok: false, error: "only an expired approval requirement can be renewed <img src=x onerror=alert(1)>\u0007" } }));
    await page.goto(`/app/cases/${id}`);
    await expect(page.getByRole("heading", { name: "Approval request expired" })).toBeVisible();
    await actions(page).getByRole("button", { name: "Renew approval…" }).click();
    const panel = confirmPanel(page, "Renew approval");
    await panel.getByLabel("Reason").fill("window confirmed again with operations");
    await panel.getByRole("button", { name: "Renew approval", exact: true }).click();
    const alert = page.getByRole("alert").filter({ hasText: "The backend refused “Renew approval”" });
    await expect(alert).toContainText("Refused: not valid in the case’s current state, or the case changed.");
    await expect(alert).toContainText("Server reason: “only an expired approval requirement can be renewed <img src=x onerror=alert(1)>”");
    await expect(alert).toContainText("(HTTP 409)");
    await expect(alert.locator("img")).toHaveCount(0);
    expect(sent[0].path).toBe(`/api/incidents/${id}/commands/renew_approval`);
    // The confirmation stays open so the person can change course.
    await expect(panel).toBeVisible();
  });

  test("production refusal (403) is shown as not permitted", async ({ page }) => {
    await boot(page, { frame: ESCALATED });
    const id = incidentOf(ESCALATED);
    await capture(page, id, () => ({ status: 403, json: { ok: false, error: "authenticated identity is required in production and is not available before F3" } }));
    await page.goto(`/app/cases/${id}`);
    await actions(page).getByRole("button", { name: "Cancel case…" }).click();
    const panel = confirmPanel(page, "Cancel case");
    await panel.getByLabel("Reason").fill("duplicate of the planned overhaul");
    await panel.getByRole("button", { name: "Cancel case", exact: true }).click();
    const alert = page.getByRole("alert").filter({ hasText: "The backend refused “Cancel case”" });
    await expect(alert).toContainText("Not permitted here. The server refused this action.");
    await expect(alert).toContainText("(HTTP 403)");
  });

  test("the case changes while a confirmation is open: review first, then the new revision is sent", async ({ page }) => {
    const { push } = await boot(page, { frame: ESCALATED });
    const id = incidentOf(ESCALATED);
    const sent = await capture(page, id);
    await page.goto(`/app/cases/${id}`);
    await actions(page).getByRole("button", { name: "Cancel case…" }).click();
    const panel = confirmPanel(page, "Cancel case");
    await panel.getByLabel("Reason").fill("superseded by the scheduled overhaul");

    push(RESUMED); // revision moves on; cancel is still valid on the resumed case
    await expect(panel.getByText("Changed since you opened this", { exact: true })).toBeVisible();
    const confirm = panel.getByRole("button", { name: "Cancel case", exact: true });
    await expect(confirm).toHaveAttribute("aria-disabled", "true");
    await confirm.focus(); // inactive, not disabled (R-3): activating it moves focus to the change
    await page.keyboard.press("Enter");
    await expect(panel.getByRole("alert")).toBeFocused();
    expect(sent).toHaveLength(0);

    await panel.getByRole("button", { name: "I have reviewed the change" }).click();
    await confirm.click();
    await expect.poll(() => sent.length).toBe(1);
    expect(sent[0].body.expected_revision).toBe(lifecycleOf(RESUMED).revision);
  });

  test("a command that stops being valid closes its confirmation", async ({ page }) => {
    const { push } = await boot(page, { frame: ESCALATED });
    await page.goto(`/app/cases/${incidentOf(ESCALATED)}`);
    await actions(page).getByRole("button", { name: "Resume investigation…" }).click();
    await expect(confirmPanel(page, "Resume investigation")).toBeVisible();
    push(RESUMED); // resume is no longer valid on an investigating case
    await expect(confirmPanel(page, "Resume investigation")).toHaveCount(0);
    await expect(page.getByText("That action is no longer valid: the case changed.")).toBeVisible();
  });

  test("READY: dispatch is explicit, takes no reason and sends only the exact intent", async ({ page }) => {
    await boot(page, { frame: READY });
    const id = incidentOf(READY);
    const sent = await capture(page, id);
    await page.goto(`/app/cases/${id}`);
    await actions(page).getByRole("button", { name: "Dispatch approved work package…" }).click();
    const panel = confirmPanel(page, "Dispatch approved work package");
    await expect(panel).toContainText("This call records no actor in this build.");
    await expect(panel).toContainText("It doesn’t mean the work was done or that the asset recovered.");
    await expect(panel.getByLabel("Reason")).toHaveCount(0);
    await panel.getByRole("button", { name: "Dispatch approved work package", exact: true }).click();
    await expect(page.getByRole("status").filter({ hasText: "The backend accepted the dispatch" })).toBeVisible();
    const lc = lifecycleOf(READY);
    expect(sent).toEqual([{ path: `/api/incidents/${id}/execute`, body: { intervention_id: lc.intervention_id, intervention_hash: lc.intervention_hash } }]);
  });

  test("an observer sees what is valid, with no controls", async ({ page }) => {
    await boot(page, { frame: ESCALATED, session: { ...SESSION, role: "observer" } });
    await page.goto(`/app/cases/${incidentOf(ESCALATED)}`);
    await expect(actions(page)).toContainText("Observer is a read-only role in this interface.");
    await expect(actions(page).getByRole("button")).toHaveCount(0);
  });

  test("disconnected: the commands stay visible but inactive, with the reason", async ({ page }) => {
    const { disconnect } = await boot(page, { frame: ESCALATED });
    await page.goto(`/app/cases/${incidentOf(ESCALATED)}`);
    await expect(actions(page).getByRole("button", { name: "Resume investigation…" })).toBeVisible();
    await disconnect();
    await expect(actions(page).getByText("Reconnect to act on this case.")).toBeVisible();
    await expect(actions(page).getByRole("button", { name: "Resume investigation…" })).toHaveAttribute("aria-disabled", "true");
  });
});

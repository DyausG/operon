// F4.1 layout D in a real browser: the case navigator (hash sections, keyboard, Back / Forward),
// the existing deep links, where the decision surface lands, page structure for assistive
// technology, and the phone width.
import { expect, test } from "@playwright/test";
import { APPROVAL, INCIDENT, REJECT_FRAMES, boot, incidentOf } from "./harness.js";

const [, PLANNING] = REJECT_FRAMES;
const caseUrl = `/app/cases/${INCIDENT}`;
const nav = (page) => page.getByRole("navigation", { name: "Case sections" });
const sectionTitle = (page) => page.locator("#wb-case-section");

test.describe("case workspace, layout D", () => {
  test("the navigator: one section at a time, focus on its heading, Back and Forward", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await boot(page);
    await page.goto(caseUrl);
    await expect(nav(page).locator('[aria-current="page"]')).toContainText("Now");
    await expect(sectionTitle(page)).toHaveText("Now");

    await nav(page).getByRole("link", { name: /Evidence/ }).click();
    await expect(page).toHaveURL(new RegExp(`${caseUrl}#evidence$`));
    await expect(sectionTitle(page)).toHaveText("Evidence");
    await expect(sectionTitle(page)).toBeFocused();
    await expect(page.locator("#decision-surface")).toHaveCount(0);

    // Keyboard: Tab to a navigator link and activate it with Enter.
    await nav(page).getByRole("link", { name: /Investigation/ }).focus();
    await page.keyboard.press("Enter");
    await expect(page).toHaveURL(/#investigation$/);
    await expect(sectionTitle(page)).toHaveText("Investigation");

    await page.goBack();
    await expect(sectionTitle(page)).toHaveText("Evidence");
    await page.goForward();
    await expect(sectionTitle(page)).toHaveText("Investigation");
    // "Go to decision" from another section while a decision is pending.
    await page.getByRole("link", { name: "Go to decision" }).click();
    await expect(sectionTitle(page)).toHaveText("Now");
    await expect(page.locator("#decision-surface")).toBeVisible();
  });

  test("existing deep links still land: #decision, #summary and #work", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await boot(page);
    for (const [hash, title] of [["#decision", "Now"], ["#decision-surface", "Now"], ["#summary", "Now"], ["#work", "Work & verification"], ["#nonsense", "Now"]]) {
      await page.goto(`${caseUrl}${hash}`);
      await expect(sectionTitle(page)).toHaveText(title);
    }
    await expect(page.locator("#decision-surface")).toBeVisible();
  });

  test("#decision opens Plan & decision when no decision is pending", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await boot(page, { frame: PLANNING });
    await page.goto(`/app/cases/${incidentOf(PLANNING)}#decision`);
    await expect(sectionTitle(page)).toHaveText("Plan & decision");
    await expect(page.getByText("Decisions recorded")).toBeVisible();
  });

  for (const [width, height] of [[1440, 900], [1280, 800]]) {
    test(`${width}×${height}: the decision surface starts in the first viewport`, async ({ page }) => {
      await page.setViewportSize({ width, height });
      await boot(page);
      await page.goto(caseUrl);
      const box = await page.locator("#decision-surface").boundingBox();
      expect(box.y).toBeLessThan(height * 0.6);
      await expect(page.locator("#decision-surface").getByRole("heading", { name: "Decision required" })).toBeInViewport();
    });
  }

  test("structure: one h1, landmarks, a labelled lifecycle position with one current step, unique ids", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await boot(page);
    await page.goto(caseUrl);
    await expect(page.locator("h1")).toHaveCount(1);
    await expect(page.getByRole("main")).toHaveCount(1);
    await expect(page.getByRole("navigation", { name: "Breadcrumb" })).toBeVisible();
    await expect(nav(page)).toBeVisible();
    const position = page.getByRole("group", { name: "Case lifecycle position" });
    await expect(position.locator('[aria-current="step"]')).toHaveCount(1);
    await expect(page.getByRole("region", { name: "Now" })).toBeVisible();
    const dupes = await page.evaluate(() => {
      const seen = new Map();
      for (const el of document.querySelectorAll("[id]")) seen.set(el.id, (seen.get(el.id) || 0) + 1);
      return [...seen].filter(([, n]) => n > 1).map(([id]) => id);
    });
    expect(dupes).toEqual([]);
    // Every navigator link has a name that includes its section.
    for (const label of ["Now", "Evidence", "Investigation", "Plan & decision", "Work & verification", "Record"]) {
      await expect(nav(page).getByRole("link", { name: new RegExp(label.replace("&", "\\&")) })).toHaveCount(1);
    }
  });

  test("390: no horizontal scroll; the navigator becomes a strip; the decision is reachable", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await boot(page);
    await page.goto(caseUrl);
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    expect(overflow).toBeLessThanOrEqual(0);
    await expect(nav(page)).toBeVisible();
    // The strip scrolls on its own; its items never overlap each other.
    const boxes = await nav(page).locator("li").evaluateAll((els) => els.map((el) => { const r = el.getBoundingClientRect(); return [r.left, r.right]; }));
    for (let i = 1; i < boxes.length; i += 1) expect(boxes[i][0]).toBeGreaterThanOrEqual(boxes[i - 1][1] - 0.5);
    const labels = await nav(page).locator(".wb-casenav-label").evaluateAll((els) => els.map((el) => el.scrollWidth <= el.clientWidth + 1));
    expect(labels.every(Boolean)).toBe(true);
    const approve = page.getByRole("button", { name: "Approve and dispatch" });
    await approve.scrollIntoViewIfNeeded();
    await expect(approve).toBeInViewport();
    const box = await approve.boundingBox();
    expect(box.x).toBeGreaterThanOrEqual(0);
    expect(box.x + box.width).toBeLessThanOrEqual(390);
  });

  test("dark theme renders the same structure", async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 800 });
    await boot(page, { theme: "dark" });
    await page.goto(caseUrl);
    await expect(page.locator(".wb-root")).toHaveAttribute("data-theme", "dark");
    await expect(page.locator("#decision-surface")).toBeVisible();
    await expect(page.getByRole("group", { name: "Case lifecycle position" })).toBeVisible();
  });
});

test("APPROVAL fixture sanity: the harness frame is a pending decision", () => {
  expect(APPROVAL.alerts[0].lifecycle.phase).toBe("AWAITING_APPROVAL");
});

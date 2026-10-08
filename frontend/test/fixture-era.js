// Tests pin the clock to the era the fixtures were generated in (test/make_fixtures.py), so
// requirement deadlines are pending exactly as they were at capture: a few minutes after the
// first approval was requested. Derived from the fixtures, so regeneration keeps it correct.
export function fixtureNow(frames, minutesAfterRequest = 5) {
  for (const frame of frames) {
    const lc = frame.alerts?.[0]?.lifecycle;
    const requirement = (lc?.read_model?.requirements || []).find((r) => r.id === lc?.requirement_id);
    if (lc?.phase === "AWAITING_APPROVAL" && requirement?.created_at) {
      return new Date(Date.parse(requirement.created_at) + minutesAfterRequest * 60_000);
    }
  }
  throw new Error("the fixtures contain no approval request to pin the clock to");
}

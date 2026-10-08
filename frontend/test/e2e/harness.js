// Test-only harness: answers /ws with one real engine fixture frame and pins the browser clock to
// the fixture era so requirement deadlines are as they were when the frames were captured.
import { readFileSync } from "node:fs";
import { fixtureNow } from "../fixture-era.js";

const load = (name) => JSON.parse(readFileSync(new URL(`../fixtures/${name}`, import.meta.url), "utf8"));
export const FRAMES = load("demo-frames.json");
export const APPROVAL = FRAMES.find((f) => f.alerts?.[0]?.lifecycle?.phase === "AWAITING_APPROVAL");
export const INCIDENT = APPROVAL.alerts[0].incident_id;
// F1 frames: [approval, after the recorded rejection]; one MATERIAL approval; one BLOCKING park.
export const REJECT_FRAMES = load("demo-frames-reject.json");
export const MATERIAL_FRAME = load("demo-frames-material.json")[0];
export const BLOCKING_FRAME = load("demo-frames-blocking.json")[0];
// F4.1 exception frames (each driven through a labelled test seam in make_fixtures.py):
// [escalated after a rejection, resumed, cancelled]; suspended analysis; expired approval;
// [definitive dispatch failure, READY after retry_execution].
export const RECOVERY_FRAMES = load("demo-frames-recovery.json");
export const SUSPENDED_FRAME = load("demo-frames-suspended.json")[0];
export const EXPIRED_FRAME = load("demo-frames-expired.json")[0];
export const DISPATCH_FRAMES = load("demo-frames-dispatch.json");
export const ARTIFACTS = load("demo-artifacts.json"); // GET /api/demo/artifacts/{id} for the demo incident
export const incidentOf = (frame) => frame.alerts[0].incident_id;

/** Answers the artifact detail endpoint from the captured artifacts; unknown ids get the server's 404. */
export async function serveArtifacts(page) {
  await page.route(/\/api\/demo\/artifacts\/[^/?#]+$/, (route) => {
    const id = decodeURIComponent(new URL(route.request().url()).pathname.split("/").pop());
    const hit = ARTIFACTS[id];
    return hit ? route.fulfill({ json: hit }) : route.fulfill({ status: 404, json: { ok: false, error: "unknown demo artifact" } });
  });
}
export const lifecycleOf = (frame) => frame.alerts[0].lifecycle;
const NOW = fixtureNow(FRAMES);

export const SESSION = { email: "reviewer@example.com", name: "Reviewer", role: "maintenance_approver", remember: true, signedInAt: "2026-09-15T18:40:00Z", mode: "demo" };

export async function boot(page, { frame = APPROVAL, theme = "light", signedIn = true, session = SESSION } = {}) {
  await page.clock.install({ time: NOW });
  await page.addInitScript(([s, t]) => {
    if (s) localStorage.setItem("operon.session", JSON.stringify(s));
    if (!localStorage.getItem("operon.v2.theme")) localStorage.setItem("operon.v2.theme", JSON.stringify(t));
  }, [signedIn ? session : null, theme]);
  const sockets = [];
  let refuse = false;
  await page.routeWebSocket(/\/ws$/, (ws) => {
    sockets.push(ws);
    if (refuse) { ws.close(); return; }
    ws.send(JSON.stringify(frame));
  });
  // Simulates the engine going away: the open socket closes and reconnect attempts are refused.
  const disconnect = async () => { refuse = true; for (const ws of sockets) await ws.close().catch(() => {}); };
  // Delivers the engine's next real frame on every open socket (as the backend would broadcast it).
  const push = (next) => { for (const ws of sockets) ws.send(JSON.stringify(next)); };
  return { sockets, disconnect, push };
}

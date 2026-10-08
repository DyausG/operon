// Test-only harness: answers /ws with one real engine fixture frame and pins the browser clock to
// the fixture era so requirement deadlines are as they were when the frames were captured.
import { readFileSync } from "node:fs";

const load = (name) => JSON.parse(readFileSync(new URL(`../fixtures/${name}`, import.meta.url), "utf8"));
export const FRAMES = load("demo-frames.json");
export const APPROVAL = FRAMES.find((f) => f.alerts?.[0]?.lifecycle?.phase === "AWAITING_APPROVAL");
export const INCIDENT = APPROVAL.alerts[0].incident_id;

const SESSION = { email: "reviewer@example.com", name: "Reviewer", role: "maintenance_approver", remember: true, signedInAt: "2026-09-15T18:40:00Z", mode: "demo" };

export async function boot(page, { frame = APPROVAL, theme = "light", signedIn = true } = {}) {
  await page.clock.install({ time: new Date("2026-09-15T18:45:00Z") });
  await page.addInitScript(([session, t]) => {
    if (session) localStorage.setItem("operon.session", JSON.stringify(session));
    if (!localStorage.getItem("operon.v2.theme")) localStorage.setItem("operon.v2.theme", JSON.stringify(t));
  }, [signedIn ? SESSION : null, theme]);
  const sockets = [];
  let refuse = false;
  await page.routeWebSocket(/\/ws$/, (ws) => {
    sockets.push(ws);
    if (refuse) { ws.close(); return; }
    ws.send(JSON.stringify(frame));
  });
  // Simulates the engine going away: the open socket closes and reconnect attempts are refused.
  const disconnect = async () => { refuse = true; for (const ws of sockets) await ws.close().catch(() => {}); };
  return { sockets, disconnect };
}

# Operon frontend

React + Vite operations portal for Operon. It consumes the engine WebSocket (`/ws`), the
human-in-the-loop endpoints (`/api/approve`, `/api/reject`, `/api/reset`, `/api/start`,
`/api/stop`, `/api/demo/scenario`) and the demo artifact endpoint
(`GET /api/demo/artifacts/{id}`). It never changes backend semantics.

```
npm install          # once
npm run dev          # hot reload on :5173, proxies /api and /ws to the backend on :8000
npm run build        # regenerates the committed dist/ bundle served by FastAPI
npm run fixtures     # dumps every scripted-demo snapshot + artifact index into test/fixtures
npm run test:smoke   # server-renders every route for every fixture frame, both themes, every artifact type
```

## Routes

`/login` is the only public route. Everything else lives under `/app` inside the shell
(`src/app/AppShell.jsx`): `dashboard`, `machines`, `machines/:id`, `incidents`, `incidents/:id`,
`agent`, `maintenance`, `analytics`, `activity`, `notifications`, `profile`, `settings`.
FastAPI serves `index.html` for these paths so a hard refresh works (`server/main.py`).

Sign-in is a **demo session**: the host has no authentication layer, so the session lives in
the browser only and the UI says so. Approvals still carry the exact requirement /
intervention / hash / revision the lifecycle service demands.

## Layout (`src/`)

- `app/` — routes table (`routes.js`) and the application shell (sidebar, top bar, global
  search, engine controls, notification and user menus, inspector host).
- `pages/` — one file per route. The dashboard hosts `features/OperationsBoard.jsx`, the
  original command view (KPI deck, fleet strip, process line, signal / operation / record).
- `state/` — pure reducer (`engineState.js`, including the client-side stream event log),
  WebSocket hook, selectors, portal derivations (`portal.js`: machines, incidents, maintenance,
  activity, analytics), the agent runtime contract (`agentRuntime.js`), and providers for the
  engine, theme, session, settings, notifications and the artifact inspector.
- `components/` — shared composites: page header, breadcrumbs, sections, metric cards,
  sortable table, filters, tabs, toggles, fields, menus, modal, empty/loading/error states,
  and the SVG charts (`charts.jsx`).
- `primitives/` — status vocabulary (Dot, Tag, Stamp, ProvenanceTag, OwnerChip), identifiers
  and readouts, buttons, slots, key-value cells, `Inspectable`, `ArtifactChip`, icons.
- `features/` — domain views reused across pages: the operations board, process line, signal
  column, record ledger, `Operation/` phase objects, specialist chain, `Inspector/`.
- `styles/` — `tokens.css` (dark default + designed light palette, chart tokens), base,
  primitives, shell (board pieces), app-shell, components, pages, login, charts.

## Design rules

Grey is normal; colour means warning, critical, verified, advisory, or a human action.
Dashed = advisory AI output, solid = authoritative application record, hatch = SIMULATED
provenance or a reserved slot. The APPROVE segment of the process line is a hold point.
Both themes are built from the same semantic tokens; the resolved theme is stamped as
`data-theme` on `<html>` and persisted (`operon.theme`). Deep link `#artifact=<id>` opens the
inspector on load.

## What is browser-local

Session, theme, sidebar state, preferences (`operon.settings`) and notification read marks.
Notifications and the Activity "stream" lane derive from events the engine actually sent to
this browser; the durable record is the incident ledger.

## Reserved for the interruptible-agent runtime

`state/agentRuntime.js` declares the run-state vocabulary (fast/slow path, interruption,
cancellation, supersession, recovery, re-planning) and which capabilities the backend supports
today. The agent workspace renders only what the engine reports and marks the rest as reserved.

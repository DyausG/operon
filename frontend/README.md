# Operon frontend

React + Vite command surface for Operon. It consumes the engine WebSocket (`/ws`), the
human-in-the-loop endpoints (`/api/approve`, `/api/reject`, `/api/reset`, `/api/start`,
`/api/stop`, `/api/demo/scenario`) and the demo artifact endpoint
(`GET /api/demo/artifacts/{id}`). It never changes backend semantics.

```
npm install          # once
npm run dev          # hot reload on :5173, proxies /api and /ws to the backend on :8000
npm run build        # regenerates the committed dist/ bundle served by FastAPI
npm run fixtures     # dumps every scripted-demo snapshot + artifact index into test/fixtures
npm run test:smoke   # server-renders the whole shell for every fixture frame and every artifact type
```

Layout (`src/`):

- `state/` — pure reducer (`engineState.js`), WebSocket hook, selectors (process line,
  owner, ledger, telemetry series) and the artifact/inspector provider (`artifacts.jsx`).
- `primitives/` — status vocabulary (Dot, Tag, Stamp, ProvenanceTag, OwnerChip), identifiers
  and readouts, panel header, buttons, slots, key-value cells, `Inspectable`, `ArtifactChip`, icons.
- `motion/` — duration bands, easing, `Reveal`, `Swap`, `useAnimatedNumber`, `usePulse`.
- `features/` — CommandHeader, FleetStrip, ProcessLine, SignalColumn, Record, ProvenanceFooter,
  `Operation/` (one stage object per lifecycle phase), SpecialistChain, `Inspector/` (tray + typed renderers).
- `styles/` — tokens, base, primitives, shell, signal, stage, record, inspector.

Design rules: grey is normal; colour means warning, critical, verified, advisory, or a human
action. Dashed = advisory AI output, solid = authoritative application record, hatch = SIMULATED
provenance. The APPROVE segment of the process line is a hold point: nothing passes it without
explicit human approval. Deep link: `#artifact=<id>` opens the inspector on load.

"""
FastAPI application — serves the dashboard, streams live fleet telemetry + agent
activity over a WebSocket, and exposes the human-in-the-loop control endpoints
(approve / reject / reset) for the concurrent-alert queue.
"""
from __future__ import annotations
import json

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from core import config
from core.db import reset_transactional
from core.seed_data import seed
from core.engine import DemoEngine

app = FastAPI(title=f"{config.APP_NAME} — {config.APP_TAGLINE}")
engine: DemoEngine | None = None


@app.on_event("startup")
async def _startup():
    global engine
    seed()
    reset_transactional()
    engine = DemoEngine()
    await engine.start()


# ---- REST ----------------------------------------------------------------
@app.get("/api/health")
async def health():
    return {"ok": True, "agent_mode": config.agent_mode(),
            "running": engine.running if engine else False}


@app.get("/api/state")
async def state():
    return JSONResponse(engine.snapshot())


@app.post("/api/start")
async def start():
    await engine.start()
    return {"ok": True, "running": engine.running}


@app.post("/api/stop")
async def stop():
    await engine.stop()
    return {"ok": True, "running": engine.running}


@app.post("/api/approve/{equipment_id}")
async def approve(equipment_id: str):
    return await engine.approve(equipment_id)


@app.post("/api/reject/{equipment_id}")
async def reject(equipment_id: str):
    return await engine.reject(equipment_id)


@app.post("/api/reset")
async def reset():
    await engine.reset()
    return {"ok": True}


# ---- WebSocket -----------------------------------------------------------
@app.websocket("/ws")
async def ws(websocket: WebSocket):
    await websocket.accept()
    engine.clients.add(websocket)
    await websocket.send_text(json.dumps(engine.snapshot(), default=str))
    # NB: don't auto-start here — the loop is started at app startup, and a
    # reconnect must not override a deliberate Stop. Resume is explicit (/api/start).
    try:
        while True:
            await websocket.receive_text()  # keepalive; inbound ignored
    except WebSocketDisconnect:
        engine.clients.discard(websocket)
    except Exception:
        engine.clients.discard(websocket)


# ---- Static frontend (mounted LAST so /api and /ws win) ------------------
_PLACEHOLDER = f"""<!doctype html><html><head><meta charset=utf-8>
<title>{config.APP_NAME}</title><style>body{{font-family:system-ui;background:#0b0f17;color:#e6edf3;
display:grid;place-items:center;height:100vh;margin:0}}code{{color:#7ee787}}</style></head>
<body><div><h1>{config.APP_NAME} · {config.APP_TAGLINE}</h1>
<p>Backend is running. The React dashboard build was not found.</p>
<p>Build it with <code>cd frontend &amp;&amp; npm install &amp;&amp; npm run build</code>,
then reload — or use the API at <code>/api/state</code>.</p></div></body></html>"""


@app.get("/")
async def index():
    if config.FRONTEND_BUILD.exists() and (config.FRONTEND_BUILD / "index.html").exists():
        return FileResponse(str(config.FRONTEND_BUILD / "index.html"))
    return HTMLResponse(_PLACEHOLDER)


if (config.FRONTEND_BUILD / "assets").exists():
    # Serve built assets (JS/CSS) under the SPA. HTML index handled above.
    app.mount("/assets", StaticFiles(directory=str(config.FRONTEND_BUILD / "assets")), name="assets")

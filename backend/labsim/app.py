"""Lab field simulator: virtual PLC (Modbus TCP) + MQTT transmitters + presenter panel.

Stands in for the customer's physical equipment during demos. The presenter
panel triggers physical-world events (E-stop button, jam, cable pulled) that the
platform must detect on its own through its protocol connections.

Run:  python -m labsim.app        (env: LAB_PANEL_HOST/PORT, LAB_MODBUS_HOST/PORT, LAB_MQTT_HOST/PORT)
"""

import asyncio
import hashlib
import hmac
import json
import logging
import os
import time
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse

from labsim.plc import Line3Plc
from labsim.sensors import Transmitters

log = logging.getLogger("labsim")
plc = Line3Plc()
tx = Transmitters(plc, os.environ.get("LAB_MQTT_HOST", "127.0.0.1"), int(os.environ.get("LAB_MQTT_PORT", "1883")))


@asynccontextmanager
async def lifespan(_: FastAPI):
    host, port = os.environ.get("LAB_MODBUS_HOST", "127.0.0.1"), int(os.environ.get("LAB_MODBUS_PORT", "5020"))
    tasks = [asyncio.create_task(plc.run(host, port)), asyncio.create_task(tx.run())]
    log.info("Virtual PLC on %s:%d, MQTT transmitters → %s:%d", host, port, tx.host, tx.port)
    plc.log("Lab field simulator started")
    yield
    for t in tasks:
        t.cancel()
    await plc.stop()


app = FastAPI(title="Lab field simulator", lifespan=lifespan, docs_url=None, redoc_url=None)

ACTIONS = {
    "estop": plc.press_estop, "estop_reset": plc.reset_estop, "jam": plc.jam_conveyor,
    "clear_faults": plc.clear_faults, "pump_trip": plc.pump_trip, "overheat": tx.overheat,
    "disconnect_tt201": lambda: tx.toggle_disconnect("tt-201"), "disconnect_em002": lambda: tx.toggle_disconnect("em-002"),
}


# --- external "maintenance system" inbox: receives the platform's webhook notifications ---
WEBHOOK_SECRET = os.environ.get("LAB_WEBHOOK_SECRET", "lab-demo-secret")
INBOX: list[dict] = []


@app.post("/hooks/inbox")
async def inbox(request: Request):
    body = await request.body()
    sig = request.headers.get("X-Twin-Signature", "")
    expected = "sha256=" + hmac.new(WEBHOOK_SECRET.encode(), body, hashlib.sha256).hexdigest()
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        raise HTTPException(400, "invalid JSON") from None
    INBOX.insert(0, {"received": time.strftime("%H:%M:%S"), "verified": hmac.compare_digest(sig, expected),
                     "event": data.get("event"), "severity": data.get("severity"), "subject": data.get("subject")})
    del INBOX[50:]
    return {"ok": True}


@app.get("/api/inbox")
def inbox_list():
    return INBOX


@app.get("/api/status")
def status():
    return {**plc.status(), "mqtt_connected": tx.connected, "disconnected": sorted(tx.faults.disconnected),
            "transmitters": tx.last}


@app.post("/api/action/{name}")
def action(name: str):
    fn = ACTIONS.get(name)
    if fn is None:
        raise HTTPException(404, "unknown action")
    fn()
    return status()


PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Lab field simulator</title><style>
:root{--bg:#0d1016;--p:#151a22;--b:#263040;--t:#e6e9ef;--m:#93a0b4;--ok:#22c55e;--bad:#ef4444;--warn:#f59e0b;--a:#38bdf8}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--t);font:14px/1.45 system-ui,Segoe UI,Roboto,sans-serif}
header{padding:14px 20px;border-bottom:1px solid var(--b);display:flex;gap:12px;align-items:center;flex-wrap:wrap}
.tag{background:#3b2a07;color:var(--warn);border:1px solid #6b4c10;border-radius:999px;padding:2px 10px;font-size:12px;font-weight:600}
main{padding:18px 20px;display:grid;gap:14px;grid-template-columns:repeat(auto-fit,minmax(300px,1fr))}
section{background:var(--p);border:1px solid var(--b);border-radius:10px;padding:14px}
h1{font-size:17px;margin:0}h2{font-size:13px;margin:0 0 10px;color:var(--m);text-transform:uppercase;letter-spacing:.05em}
button{font:inherit;font-weight:600;border-radius:8px;padding:10px 14px;border:1px solid var(--b);background:#1c2330;color:var(--t);cursor:pointer;margin:0 8px 8px 0}
button:hover{border-color:var(--a)}.estop{background:#7f1d1d;border-color:#b91c1c;color:#fff;border-radius:50%;width:110px;height:110px}
.kv{display:grid;grid-template-columns:150px 1fr;gap:4px 10px}.kv dt{color:var(--m)}.kv dd{margin:0;font-variant-numeric:tabular-nums}
.s-running{color:var(--ok)}.s-stopped{color:var(--m)}.s-fault,.s-emergency_stop{color:var(--bad);font-weight:700}
pre{margin:0;font:12px/1.5 ui-monospace,monospace;color:var(--m);white-space:pre-wrap}
</style></head><body>
<header><h1>Lab field simulator</h1><span class="tag">STANDS IN FOR PHYSICAL EQUIPMENT · NOT PART OF THE PLATFORM</span>
<span id="conn" style="color:var(--m)"></span></header>
<main>
<section><h2>Emergency stop (physical button)</h2>
<button class="estop" onclick="act('estop')">E-STOP</button>
<button onclick="act('estop_reset')">Reset E-stop</button>
<p style="color:var(--m);margin:6px 0 0">The PLC drops all run outputs on its own. The platform can only observe this; it can't override it.</p></section>
<section><h2>Faults</h2>
<button onclick="act('jam')">Jam conveyor CV-301</button><button onclick="act('pump_trip')">Trip pump PMP-401</button>
<button onclick="act('clear_faults')">Clear faults (local reset)</button><br>
<button onclick="act('overheat')">Overheat TT-101 (90 s)</button>
<button onclick="act('disconnect_tt201')" id="d1">Pull TT-201 cable</button>
<button onclick="act('disconnect_em002')" id="d2">Pull EM-002 cable</button></section>
<section><h2>Virtual PLC (Modbus TCP)</h2><dl class="kv" id="plc"></dl></section>
<section><h2>Event log</h2><pre id="log"></pre></section>
<section style="grid-column:1/-1"><h2>Maintenance system inbox (webhooks from the platform)</h2><div id="inbox" style="color:var(--m)">No notifications yet.</div></section>
</main>
<script>
function esc(t){return String(t??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))}
async function act(n){await fetch('api/action/'+n,{method:'POST'});load()}
function row(k,v,c){return `<dt>${k}</dt><dd class="${c||''}">${v}</dd>`}
async function load(){try{const s=await (await fetch('api/status')).json();
document.getElementById('plc').innerHTML=row('E-stop',s.estop?'TRIPPED':'healthy',s.estop?'s-fault':'s-running')
+row('Conveyor CV-301',s.conveyor_state,'s-'+s.conveyor_state)+row('Run request',s.line_run_request?'ON':'off')
+row('Speed',s.speed_mps+' m/s (sp '+s.speed_setpoint_mps+')')+row('Motor',s.motor_rpm+' rpm')
+row('Pump PMP-401',s.pump_state,'s-'+s.pump_state)+row('Pump flow',s.pump_flow+' m³/h')+row('Items',s.items);
document.getElementById('log').textContent=s.events.join('\\n');
document.getElementById('conn').textContent='MQTT '+(s.mqtt_connected?'connected':'DISCONNECTED')+(s.disconnected.length?' · unplugged: '+s.disconnected.join(', '):'');
document.getElementById('d1').textContent=(s.disconnected.includes('tt-201')?'Reconnect':'Pull')+' TT-201 cable';
document.getElementById('d2').textContent=(s.disconnected.includes('em-002')?'Reconnect':'Pull')+' EM-002 cable';
const ib=await (await fetch('api/inbox')).json();
document.getElementById('inbox').innerHTML=ib.length?ib.map(n=>`<div style="padding:5px 0;border-bottom:1px solid var(--b)"><span style="color:var(--m)">${esc(n.received)}</span> <b class="${n.severity==='alarm'?'s-fault':''}">${esc(n.event)}</b> ${esc(n.subject)} <span style="color:${n.verified?'var(--ok)':'var(--bad)'}">${n.verified?'✓ signature verified':'✕ bad signature'}</span></div>`).join(''):'No notifications yet.';
}catch(e){document.getElementById('conn').textContent='simulator unreachable'}}
load();setInterval(load,1000);
</script></body></html>"""


@app.get("/", response_class=HTMLResponse)
def page():
    return PAGE


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("pymodbus").setLevel(logging.WARNING)
    uvicorn.run(app, host=os.environ.get("LAB_PANEL_HOST", "127.0.0.1"), port=int(os.environ.get("LAB_PANEL_PORT", "8090")),
                log_level="warning")

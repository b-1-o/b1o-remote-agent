from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel

import asyncio
import json
from pathlib import Path

from commands_store import COMMANDS_DIR, install_pack, load_commands
from config_store import load_settings, save_settings
from runner import execute_command_sync
from schedule_store import delete_schedule, load_schedules, upsert_schedule
from agent.actions import get_status, lock_pc, shutdown_pc
from agent.input_actions import unlock_configured

app = FastAPI(title="b1o Remote Admin")

class SettingsPayload(BaseModel):
    school_enabled: bool
    school_days: list[int]
    school_time: str
    zoom_time: str
    zoom_url: str
    schoology_url: str
    schoology_user: str
    schoology_password: str = ""
    browser: str
    browser_profile: str
    pc_unlock_password: str = ""

class CommandPayload(BaseModel):
    content: str

class SchedulePayload(BaseModel):
    id: str
    title: str
    time: str
    days: list[int]
    command_id: str
    enabled: bool = True

HTML = '''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>b1o Remote Admin</title>
<style>
:root{color-scheme:dark;font-family:Inter,ui-sans-serif,system-ui,-apple-system,sans-serif;background:#090a0f;color:#f4f5f7}
*{box-sizing:border-box}body{margin:0;min-height:100vh;background:radial-gradient(900px 500px at 18% -10%,#243148 0,transparent 52%),radial-gradient(760px 460px at 92% 4%,#351722 0,transparent 46%),radial-gradient(900px 600px at 50% 100%,#11161f 0,transparent 60%),#090a0f}
.shell{display:grid;grid-template-columns:230px 1fr;min-height:100vh}.side{padding:24px 16px;border-right:1px solid #252b35;background:#0d1017b8;backdrop-filter:blur(18px);position:sticky;top:0;height:100vh}
.brand{font-weight:800;font-size:20px;padding:8px 10px 22px}.brand span{color:#c7cbd4}.nav{display:grid;gap:8px}.nav button{width:100%;text-align:left}
.nav button.active{background:linear-gradient(135deg,#f1f3f6,#d7dbe2);color:#0d1015;box-shadow:0 10px 30px #0005}.content{padding:30px;max-width:1250px;width:100%}.top{display:flex;justify-content:space-between;align-items:end;margin-bottom:22px}
h1{font-size:32px;margin:0 0 5px}.muted{color:#8d98a8}.grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px}.page{display:none}.page.active{display:block}
.card{background:linear-gradient(180deg,#151a22c9,#0f1319c2);border:1px solid #2a313c;backdrop-filter:blur(20px);border-radius:20px;padding:20px;box-shadow:0 18px 60px #0006;margin-bottom:16px}.card h2{margin:0 0 6px;font-size:18px}
.label{font-size:12px;color:#9eabb9;margin:14px 0 6px}.field{display:grid;gap:5px}.field input,.field textarea,.field select{width:100%;background:#0b0f14;border:1px solid #2b3540;color:#f2f5f8;border-radius:11px;padding:11px 12px;outline:none}
.field input:focus,.field textarea:focus,.field select:focus{border-color:#6f82b5;box-shadow:0 0 0 3px #6f82b520}.field textarea{min-height:120px;resize:vertical}
.row{display:flex;gap:9px;flex-wrap:wrap;align-items:center}.spaced{margin-top:14px}.btn{border:1px solid #303b47;background:#171e27;color:#f2f5f8;border-radius:10px;padding:10px 13px;cursor:pointer}.btn:hover{filter:brightness(1.08)}.btn.primary{background:linear-gradient(135deg,#f3f4f6,#dfe3e8);color:#0d1015;border-color:#fff4}.btn.danger{background:linear-gradient(135deg,#391820,#2a1218);border-color:#6a2f3a}
.pill{padding:6px 10px;border-radius:999px;font-size:12px;background:#151c24;border:1px solid #2a3540}.ok{color:#8de3a5}.warn{color:#f1ca75}
.list{display:grid;gap:8px;margin-top:14px}.item{display:flex;justify-content:space-between;gap:12px;align-items:center;padding:12px;border:1px solid #222b35;border-radius:12px;background:#0c1117}.item-title{font-weight:700}.item-sub{font-size:12px;color:#8490a0;margin-top:3px}.empty{padding:18px;border:1px dashed #2a3540;border-radius:12px;color:#7f8b9a;text-align:center}
.action-row{display:grid;grid-template-columns:160px 1fr auto;gap:8px;align-items:center;margin-top:8px}.action-row input,.action-row select{background:#0b0f14;border:1px solid #2b3540;color:#f2f5f8;border-radius:10px;padding:10px}
.toast{position:fixed;right:22px;bottom:22px;padding:12px 15px;border:1px solid #303b47;border-radius:12px;background:#121820ee;backdrop-filter:blur(12px);display:none}.toast.show{display:block}
@media(max-width:900px){.shell{grid-template-columns:1fr}.side{position:static;height:auto;border-right:0;border-bottom:1px solid #202731}.nav{grid-template-columns:repeat(5,1fr)}.nav button{text-align:center;padding:10px 5px}.content{padding:18px}.grid{grid-template-columns:1fr}}
</style></head><body>
<div class="shell">
<aside class="side"><div class="brand"><span>b1o</span> Remote</div>
<div class="nav">
<button class="btn active" data-page="overview">Overview</button>
<button class="btn" data-page="school">School</button>
<button class="btn" data-page="browser">Browser</button>
<button class="btn" data-page="commands">Buttons</button>
<button class="btn" data-page="schedules">Schedules</button>
<button class="btn" data-page="system">System</button>
</div></aside>
<main class="content">
<div class="top"><div><h1 id="pageTitle">Overview</h1><div class="muted">Configure the PC here. Telegram is runtime-only.</div></div><div id="status" class="pill">Loading…</div></div>
<section id="overview" class="page active">
<div class="grid">
<div class="card"><h2>🎓 School Mode</h2><div id="overviewSchool" class="muted">—</div><div class="row spaced"><button class="btn primary" onclick="go('school')">Configure school</button><button class="btn" onclick="runNamed('open_zoom')">Open Zoom</button><button class="btn" onclick="runNamed('open_schoology')">Open LAUSD</button></div></div>
<div class="card"><h2>🖥 PC</h2><div id="overviewPc" class="muted">—</div><div class="row spaced"><button class="btn" onclick="runAgent('/lock')">Lock</button><button class="btn" onclick="runAgent('/unlock')">Unlock</button><button class="btn danger" onclick="runAgent('/shutdown')">Shutdown</button></div></div>
<div class="card"><h2>🔗 Lesson</h2><div class="field"><div class="label">Zoom URL</div><div id="overviewZoom" class="muted">—</div></div><div class="field"><div class="label">LAUSD URL</div><div id="overviewSchoology" class="muted">—</div></div></div>
<div class="card"><h2>📦 Runtime</h2><div id="overviewStats" class="muted">—</div></div>
</div></section>
<section id="school" class="page">
<div class="card"><h2>🎓 School Mode</h2><div class="muted">This controls the automatic school routine.</div>
<div class="grid">
<div class="field"><div class="label">Mode</div><select id="school_enabled"><option value="true">ON</option><option value="false">OFF</option></select></div>
<div class="field"><div class="label">School start</div><input id="school_time" placeholder="08:20"></div>
<div class="field"><div class="label">Zoom time</div><input id="zoom_time" placeholder="08:30"></div>
<div class="field"><div class="label">Days</div><input id="school_days" placeholder="0,1,2,3,4"></div>
<div class="field"><div class="label">Zoom lesson URL</div><input id="zoom_url"></div>
<div class="field"><div class="label">LAUSD Schoology URL</div><input id="schoology_url"></div>
<div class="field"><div class="label">Schoology email</div><input id="schoology_user"></div>
<div class="field"><div class="label">Schoology password</div><input id="schoology_password" type="password" placeholder="Leave blank to keep current"></div>
</div><div class="row spaced"><button class="btn primary" onclick="saveSettings()">Save School Mode</button></div></div>
<div class="card"><h2>🔓 PC Unlock</h2><div class="muted">Password is stored locally on this PC and never displayed in Telegram.</div><div class="field"><div class="label">PC password</div><input id="pc_unlock_password" type="password" placeholder="Leave blank to keep current"></div><div class="row spaced"><button class="btn primary" onclick="saveSettings()">Save unlock password</button></div></div>
</section>
<section id="browser" class="page">
<div class="card"><h2>🌐 Brave</h2><div class="grid"><div class="field"><div class="label">Executable</div><input id="browser"></div><div class="field"><div class="label">Automation profile</div><input id="browser_profile"></div></div><div class="row spaced"><button class="btn primary" onclick="saveSettings()">Save browser</button></div></div>
</section>
<section id="commands" class="page">
<div class="card"><h2>🧩 Telegram Buttons</h2><div class="muted">Create the buttons that should be available in Telegram. No shell commands are allowed.</div>
<div class="grid">
<div class="field"><div class="label">Button ID</div><input id="cmd_id" placeholder="assignment"></div>
<div class="field"><div class="label">Button title</div><input id="cmd_title" placeholder="📝 Assignment"></div>
</div>
<div class="label">Actions</div><div id="actionBuilder"></div>
<div class="row spaced"><button class="btn" onclick="addAction()">+ Add action</button><button class="btn primary" onclick="saveCommand()">Save button</button><button class="btn" onclick="clearCommand()">Clear</button><label class="btn">Upload JSON<input id="command_file" type="file" accept=".json" hidden></label></div>
<div id="commandsList" class="list"></div></div>
</section>
<section id="schedules" class="page">
<div class="card"><h2>⏰ Schedules</h2><div class="grid"><div class="field"><div class="label">Schedule ID</div><input id="sch_id" placeholder="morning_zoom"></div><div class="field"><div class="label">Title</div><input id="sch_title" placeholder="Morning Zoom"></div><div class="field"><div class="label">Time</div><input id="sch_time" placeholder="08:30"></div><div class="field"><div class="label">Days</div><input id="sch_days" placeholder="0,1,2,3,4"></div><div class="field"><div class="label">Command</div><select id="sch_command"></select></div><div class="field"><div class="label">Enabled</div><select id="sch_enabled"><option value="true">ON</option><option value="false">OFF</option></select></div></div><div class="row spaced"><button class="btn primary" onclick="saveSchedule()">Save schedule</button><button class="btn" onclick="clearSchedule()">Clear</button></div><div id="scheduleList" class="list"></div></div>
</section>
<section id="system" class="page">
<div class="card"><h2>⚙️ System</h2><div id="systemInfo" class="muted">—</div><div class="row spaced"><button class="btn" onclick="reloadAll()">Reload</button></div></div>
</section>
</main></div><div id="toast" class="toast"></div>
<script src="/app.js?v=3"></script></body></html>'''

@app.get('/', response_class=HTMLResponse)
def home():
    return HTMLResponse(HTML, headers={"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"})

@app.get('/app.js')
def app_js():
    return Response(
        content=__import__("pathlib").Path(__file__).with_name("app.js").read_text(encoding="utf-8"),
        media_type="application/javascript",
        headers={"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"},
    )

@app.get('/favicon.ico')
def favicon():
    return Response(status_code=204)

@app.get('/api/state')
def state():
    settings = load_settings()
    safe = dict(settings)
    safe['schoology_password'] = bool(settings.get('schoology_password'))
    safe['pc_unlock_password'] = bool(settings.get('pc_unlock_password'))
    return {'settings': safe, 'commands': load_commands(), 'schedules': load_schedules()}

@app.post('/api/settings')
def update_settings(payload: SettingsPayload):
    settings = load_settings()
    data = payload.model_dump()
    for key in ('school_enabled','school_days','school_time','zoom_time','zoom_url','schoology_url','schoology_user','browser','browser_profile'): settings[key]=data[key]
    if data['schoology_password']: settings['schoology_password']=data['schoology_password']
    if data['pc_unlock_password']: settings['pc_unlock_password']=data['pc_unlock_password']
    save_settings(settings)
    return {'ok': True}

@app.post('/api/commands')
def add_command(payload: CommandPayload):
    try: installed = install_pack(payload.content.encode('utf-8'), 'admin.json')
    except Exception as exc: raise HTTPException(400, str(exc)) from exc
    return {'ok': True, 'commands': installed}

@app.delete('/api/commands/{command_id}')
def delete_command(command_id: str):
    path = COMMANDS_DIR / f'{command_id}.json'
    if not path.exists(): raise HTTPException(404, 'Command not found')
    path.unlink(); return {'ok': True}

@app.post('/api/commands/{command_id}/run')
def run_command(command_id: str):
    command = next((x for x in load_commands() if x['id']==command_id), None)
    if not command: raise HTTPException(404, 'Command not found')
    execute_command_sync(command); return {'ok': True}

@app.post('/api/schedules')
def add_schedule(payload: SchedulePayload):
    try: item = upsert_schedule(payload.model_dump())
    except Exception as exc: raise HTTPException(400, str(exc)) from exc
    return item

@app.post('/api/action/{action}')
def action(action: str):
    if action == "status":
        return get_status()
    if action == "lock":
        return lock_pc()
    if action == "unlock":
        return unlock_configured()
    if action == "shutdown":
        return shutdown_pc()
    raise HTTPException(404, "Unknown action")


@app.delete('/api/schedules/{schedule_id}')
def remove_schedule(schedule_id: str):
    if not delete_schedule(schedule_id):
        raise HTTPException(404, 'Schedule not found')
    return {'ok': True}


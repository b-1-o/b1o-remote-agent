from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

import asyncio
import json
from pathlib import Path

from commands_store import COMMANDS_DIR, install_pack, load_commands
from config_store import load_settings, save_settings
from runner import execute_command_sync
from schedule_store import delete_schedule, load_schedules, upsert_schedule

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
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>b1o Remote Admin</title>
<style>
:root{color-scheme:dark;font-family:Inter,system-ui,sans-serif;background:#090b0f;color:#eef2f7}
*{box-sizing:border-box}body{margin:0;background:radial-gradient(circle at top,#17202b,#090b0f 45%);min-height:100vh}
main{max-width:1200px;margin:auto;padding:28px}.head{display:flex;justify-content:space-between;align-items:end;margin-bottom:22px}
h1{margin:0;font-size:32px}.muted{color:#8792a2}.grid{display:grid;grid-template-columns:1fr 1fr;gap:16px}
.card{background:#11161dcc;border:1px solid #27303a;border-radius:18px;padding:20px;box-shadow:0 18px 50px #0006}
h2{font-size:17px;margin:0 0 14px}label{font-size:12px;color:#9aa6b5;display:block;margin:10px 0 5px}
input,textarea,select{width:100%;padding:10px;border-radius:10px;border:1px solid #2c3743;background:#0c1015;color:#eef2f7}
textarea{min-height:130px;font-family:ui-monospace,monospace}.row{display:flex;gap:8px;flex-wrap:wrap;margin-top:10px}
button{padding:10px 13px;border-radius:10px;border:1px solid #33404d;background:#18202a;color:#eef2f7;cursor:pointer}
.primary{background:#eef2f7;color:#0c1015}.danger{background:#35181c;border-color:#5b272d}.item{padding:10px 0;border-bottom:1px solid #222b34;display:flex;justify-content:space-between;gap:10px;align-items:center}
.tag{font-size:12px;color:#8290a0}@media(max-width:850px){.grid{grid-template-columns:1fr}main{padding:16px}}
</style></head><body><main>
<div class="head"><div><h1>b1o Remote</h1><div class="muted">PC administration • Telegram is a control panel only</div></div><div id="status">…</div></div>
<div class="grid">
<section class="card"><h2>🎓 School Mode</h2>
<label>Enabled</label><select id="school_enabled"><option value="true">ON</option><option value="false">OFF</option></select>
<label>School start</label><input id="school_time" placeholder="08:20">
<label>Zoom time</label><input id="zoom_time" placeholder="08:30">
<label>Days (0 Mon … 6 Sun)</label><input id="school_days" placeholder="0,1,2,3,4">
<div class="row"><button class="primary" onclick="save()">Save</button></div></section>
<section class="card"><h2>🔗 School & Zoom</h2>
<label>Zoom lesson URL</label><input id="zoom_url">
<label>LAUSD Schoology URL</label><input id="schoology_url">
<label>Schoology email</label><input id="schoology_user">
<label>Schoology password</label><input id="schoology_password" type="password" placeholder="leave blank = keep current">
<div class="row"><button class="primary" onclick="save()">Save</button></div></section>
<section class="card"><h2>🔓 PC Unlock</h2>
<label>PC password</label><input id="pc_unlock_password" type="password" placeholder="leave blank = keep current">
<div class="muted">Stored only on this PC; never shown to Telegram.</div><div class="row"><button class="primary" onclick="save()">Save</button></div></section>
<section class="card"><h2>🌐 Brave</h2>
<label>Executable</label><input id="browser">
<label>Automation profile</label><input id="browser_profile">
<div class="row"><button class="primary" onclick="save()">Save</button></div></section>
<section class="card"><h2>🧩 Telegram buttons</h2>
<div class="muted">Add a JSON command or upload a JSON pack. It appears in Telegram immediately after refresh.</div>
<label>Command JSON</label><textarea id="command_json" placeholder='{"id":"assignment","title":"📝 Assignment","actions":[{"type":"open_url","url":"https://example.com"}]}'></textarea>
<div class="row"><button class="primary" onclick="addCommand()">Add / update</button><input id="command_file" type="file" accept=".json"></div>
<div id="commands"></div></section>
<section class="card"><h2>⏰ Schedules</h2>
<div class="muted">Schedules trigger buttons automatically.</div>
<label>Schedule JSON</label><textarea id="schedule_json" placeholder='{"id":"morning","title":"Morning Zoom","time":"08:30","days":[0,1,2,3,4],"command_id":"open_zoom","enabled":true}'></textarea>
<div class="row"><button class="primary" onclick="addSchedule()">Add / update</button></div>
<div id="schedules"></div></section>
</div></main>
<script>
async function api(path,opt){const r=await fetch(path,opt||{});if(!r.ok)throw new Error(await r.text());return r.json()}
const $=id=>document.getElementById(id);
const esc=s=>String(s).replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[m]));
async function load(){const x=await api('/api/state');
$('school_enabled').value=String(x.settings.school_enabled);$('school_time').value=x.settings.school_time;$('zoom_time').value=x.settings.zoom_time;$('school_days').value=x.settings.school_days.join(',');
$('zoom_url').value=x.settings.zoom_url;$('schoology_url').value=x.settings.schoology_url;$('schoology_user').value=x.settings.schoology_user;$('browser').value=x.settings.browser;$('browser_profile').value=x.settings.browser_profile;$('status').textContent='Ready';
$('commands').innerHTML=x.commands.map(c=>'<div class="item"><div><b>'+esc(c.title)+'</b><div class="tag">'+esc(c.id)+'</div></div><div class="row"><button onclick="runCmd(\''+esc(c.id)+'\')">Run</button><button class="danger" onclick="delCmd(\''+esc(c.id)+'\')">Delete</button></div></div>').join('');
$('schedules').innerHTML=x.schedules.map(s=>'<div class="item"><div><b>'+esc(s.title)+'</b><div class="tag">'+esc(s.time)+' • '+esc(s.days.join(','))+' • '+esc(s.command_id)+'</div></div><button class="danger" onclick="delSch(\''+esc(s.id)+'\')">Delete</button></div>').join('')}
async function save(){const x=await api('/api/state');const body={...x.settings,school_enabled:$('school_enabled').value==='true',school_time:$('school_time').value,zoom_time:$('zoom_time').value,school_days:$('school_days').value.split(',').map(v=>Number(v.trim())).filter(Number.isInteger),zoom_url:$('zoom_url').value,schoology_url:$('schoology_url').value,schoology_user:$('schoology_user').value,browser:$('browser').value,browser_profile:$('browser_profile').value,schoology_password:$('schoology_password').value,pc_unlock_password:$('pc_unlock_password').value};await api('/api/settings',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});$('schoology_password').value='';$('pc_unlock_password').value='';await load();}
async function addCommand(){await api('/api/commands',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({content:$('command_json').value})});$('command_json').value='';await load()}
$('command_file').addEventListener('change',async e=>{const f=e.target.files[0];if(!f)return;await api('/api/commands',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({content:await f.text()})});e.target.value='';await load()});
async function delCmd(id){await api('/api/commands/'+encodeURIComponent(id),{method:'DELETE'});await load()}async function runCmd(id){await api('/api/commands/'+encodeURIComponent(id)+'/run',{method:'POST'});}
async function addSchedule(){await api('/api/schedules',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(JSON.parse($('schedule_json').value))});$('schedule_json').value='';await load()}async function delSch(id){await api('/api/schedules/'+encodeURIComponent(id),{method:'DELETE'});await load()}
load().catch(e=>$('status').textContent=e.message);
</script></body></html>'''

@app.get('/', response_class=HTMLResponse)
def home(): return HTML

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

@app.delete('/api/schedules/{schedule_id}')
def remove_schedule(schedule_id: str):
    if not delete_schedule(schedule_id): raise HTTPException(404, 'Schedule not found')
    return {'ok': True}
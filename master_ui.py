import httpx
import asyncio
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from typing import List, Dict
import json
from pathlib import Path
from datetime import datetime, timedelta
import secrets

# ================= PIN ԿԱՐԳԱՎՈՐՈՒՄ =================
MASTER_PIN = "1973"
# ====================================================

# ================= ՍԵՍԻԱՆԵՐԻ ԿԱՌԱՎԱՐՈՒՄ =================
sessions = {}

def create_session() -> str:
    token = secrets.token_urlsafe(32)
    sessions[token] = datetime.now() + timedelta(hours=24)
    return token

def verify_session(token: str) -> bool:
    if token not in sessions:
        return False
    if sessions[token] < datetime.now():
        del sessions[token]
        return False
    return True

# ================= ՍԵՐՎԵՐՆԵՐԻ ԿԱՐԳԱՎՈՐՈՒՄ =================
CONFIG_FILE = Path("bot_servers.json")
ACCOUNTS_FILE = Path("saved_accounts.json")

def load_servers():
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE, "r") as f:
            return json.load(f).get("servers", [])
    return []

def save_servers(servers):
    with open(CONFIG_FILE, "w") as f:
        json.dump({"servers": servers}, f)

def load_saved_accounts(server: str):
    if ACCOUNTS_FILE.exists():
        with open(ACCOUNTS_FILE, "r") as f:
            data = json.load(f)
            return data.get(server, "")
    return ""

def save_accounts(server: str, accounts: str):
    data = {}
    if ACCOUNTS_FILE.exists():
        with open(ACCOUNTS_FILE, "r") as f:
            data = json.load(f)
    data[server] = accounts
    with open(ACCOUNTS_FILE, "w") as f:
        json.dump(data, f)

BOT_SERVERS = load_servers()
# ====================================================

app = FastAPI(title="Master UI - Multi Bot Aggregator")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

async def fetch_all_results() -> List[Dict]:
    all_accounts = []
    async with httpx.AsyncClient(timeout=10) as client:
        for server in BOT_SERVERS:
            try:
                res = await client.get(f"{server}/results")
                if res.status_code == 200:
                    data = res.json()
                    all_accounts.extend(data)
                    print(f"✅ Fetched {len(data)} accounts from {server}")
            except Exception as e:
                print(f"❌ Error fetching from {server}: {e}")
    return all_accounts

@app.get("/results")
async def get_merged_results():
    return await fetch_all_results()

@app.get("/health")
async def health():
    statuses = []
    async with httpx.AsyncClient(timeout=5) as client:
        for server in BOT_SERVERS:
            try:
                res = await client.get(f"{server}/health")
                if res.status_code == 200:
                    data = res.json()
                    is_running = data.get("current_index", 0) > 0 and data.get("total", 0) > 0 and data.get("current_index", 0) < data.get("total", 0)
                    statuses.append({
                        "server": server, 
                        "status": "online",
                        "running": is_running,
                        "current_index": data.get("current_index", 0),
                        "total": data.get("total", 0)
                    })
                else:
                    statuses.append({"server": server, "status": "unhealthy", "running": False})
            except:
                statuses.append({"server": server, "status": "offline", "running": False})
    return {"bots": statuses}

@app.post("/retry/{username}")
async def retry_account(username: str):
    for server in BOT_SERVERS:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                await client.post(f"{server}/retry/{username}")
        except:
            pass
    return {"status": "retry_sent"}

@app.post("/api/control/{server_id}/start")
async def control_start(server_id: int, request: Request):
    if server_id >= len(BOT_SERVERS):
        return {"success": False, "error": "Server not found"}
    
    server = BOT_SERVERS[server_id]
    data = await request.json()
    accounts_text = data.get("accounts", "")
    
    if accounts_text:
        save_accounts(server, accounts_text)
    else:
        accounts_text = load_saved_accounts(server)
        if not accounts_text:
            return {"success": False, "error": "No accounts provided and no saved accounts"}
    
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            res = await client.post(f"{server}/start", content=accounts_text)
            if res.status_code == 200:
                return {"success": True, "message": f"Start command sent to {server}"}
            return {"success": False, "error": f"Server returned {res.status_code}"}
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.post("/api/control/{server_id}/restart")
async def control_restart(server_id: int):
    if server_id >= len(BOT_SERVERS):
        return {"success": False, "error": "Server not found"}
    
    server = BOT_SERVERS[server_id]
    saved_accounts = load_saved_accounts(server)
    
    if not saved_accounts:
        return {"success": False, "error": "No saved accounts for this server. Please use Start first."}
    
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            await client.post(f"{server}/stop")
            await asyncio.sleep(0.5)
            await client.post(f"{server}/reset")
            await asyncio.sleep(0.5)
            res = await client.post(f"{server}/start", content=saved_accounts)
            if res.status_code == 200:
                return {"success": True, "message": f"Restart command sent to {server}"}
            return {"success": False, "error": f"Server returned {res.status_code}"}
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.post("/api/control/{server_id}/stop")
async def control_stop(server_id: int):
    if server_id >= len(BOT_SERVERS):
        return {"success": False, "error": "Server not found"}
    
    server = BOT_SERVERS[server_id]
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            res = await client.post(f"{server}/stop")
            if res.status_code == 200:
                return {"success": True, "message": f"Stop command sent to {server}"}
            return {"success": False, "error": f"Server returned {res.status_code}"}
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.get("/api/servers")
async def get_servers():
    return {"servers": BOT_SERVERS}

@app.post("/api/servers")
async def update_servers(request: Request):
    global BOT_SERVERS
    data = await request.json()
    servers = data.get("servers", [])
    if servers:
        BOT_SERVERS = servers
        save_servers(servers)
    return {"success": True, "servers": BOT_SERVERS}

@app.post("/api/verify")
async def verify_pin(request: Request):
    data = await request.json()
    pin = data.get("pin", "")
    if pin == MASTER_PIN:
        token = create_session()
        return {"success": True, "token": token}
    return {"success": False}

@app.get("/api/check")
async def check_session(token: str = None):
    if token and verify_session(token):
        return {"authenticated": True}
    return {"authenticated": False}

# ================= HTML UI =================
HTML_UI = '''<!DOCTYPE html>
<html lang="hy">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>MASTER UI | All Bots Results</title>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap" rel="stylesheet">
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <style>
        * { margin:0; padding:0; box-sizing:border-box; }
        body { background: linear-gradient(135deg, #0a0c10 0%, #0d1117 100%); color: #e6edf3; font-family: 'Inter', sans-serif; padding: 20px; min-height: 100vh; }
        .container { max-width: 1600px; margin: 0 auto; }
        
        .pin-overlay { position: fixed; top:0; left:0; width:100%; height:100%; background: rgba(0,0,0,0.95); backdrop-filter: blur(12px); display: flex; align-items: center; justify-content: center; z-index: 1000; }
        .pin-box { background: #161b22; border: 1px solid #30363d; border-radius: 24px; padding: 40px; width: 320px; text-align: center; }
        .pin-box h2 { margin-bottom: 24px; background: linear-gradient(135deg, #58a6ff, #3fb950); -webkit-background-clip: text; background-clip: text; color: transparent; }
        .pin-box input { width: 100%; padding: 12px; margin: 8px 0; background: #0d1117; border: 1px solid #30363d; border-radius: 12px; color: white; font-size: 18px; text-align: center; letter-spacing: 6px; }
        .pin-box button { width: 100%; padding: 12px; background: linear-gradient(135deg, #238636, #2ea043); border: none; border-radius: 12px; color: white; font-weight: bold; cursor: pointer; margin-top: 16px; }
        .pin-error { color: #f85149; font-size: 12px; margin-top: 12px; }
        
        .main-content { display: none; }
        .header { background: linear-gradient(135deg, rgba(22,27,34,0.95), rgba(13,17,23,0.95)); border-radius: 20px; padding: 14px 24px; margin-bottom: 20px; border: 1px solid rgba(48,54,61,0.5); text-align: center; }
        .header h1 { font-size: 24px; font-weight: 700; background: linear-gradient(135deg, #58a6ff, #3fb950, #f0883e); -webkit-background-clip: text; background-clip: text; color: transparent; }
        .header-sub { font-size: 12px; color: #8b949e; margin-top: 4px; }
        .stats-top { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin-bottom: 20px; }
        .stat-card { background: #161b22; border-radius: 14px; padding: 10px 12px; text-align: center; cursor: pointer; border: 1px solid #30363d; transition: all 0.2s; }
        .stat-card:hover { border-color: #58a6ff; background: #1a1f2e; transform: translateY(-2px); }
        .stat-number { font-size: 22px; font-weight: 700; color: #58a6ff; }
        .stat-label { font-size: 10px; color: #8b949e; margin-top: 3px; }
        .results-section { background: #161b22; border-radius: 20px; border: 1px solid #30363d; overflow: hidden; margin-bottom: 20px; }
        .section-header { padding: 14px 20px; background: #0d1117; border-bottom: 1px solid #30363d; font-weight: 600; font-size: 15px; }
        .filter-bar { display: flex; gap: 10px; padding: 12px 20px; background: #0d1117; border-bottom: 1px solid #21262d; flex-wrap: wrap; align-items: center; }
        .search-input { padding: 6px 14px; background: #010409; border: 1px solid #30363d; border-radius: 30px; color: white; width: 220px; font-size: 12px; }
        .filter-btn { padding: 5px 14px; background: #21262d; border: none; border-radius: 30px; color: #8b949e; cursor: pointer; font-size: 11px; transition: all 0.2s; }
        .filter-btn.active { background: #58a6ff; color: white; }
        .balance-filter { display: flex; gap: 6px; margin-left: auto; }
        .balance-filter-btn { padding: 4px 10px; background: #21262d; border: none; border-radius: 30px; color: #8b949e; cursor: pointer; font-size: 10px; }
        .balance-filter-btn.active { background: #3fb950; color: white; }
        .refresh-btn { padding: 5px 14px; background: #1f6feb; border: none; border-radius: 30px; color: white; cursor: pointer; font-size: 11px; }
        .table-container { max-height: 520px; overflow-y: auto; }
        table { width: 100%; border-collapse: collapse; }
        th { background: #0d1117; padding: 12px 14px; text-align: left; font-size: 12px; font-weight: 600; color: #8b949e; cursor: pointer; position: sticky; top: 0; border-bottom: 1px solid #30363d; }
        th:hover { color: #58a6ff; }
        td { padding: 10px 14px; font-size: 12px; border-bottom: 1px solid #21262d; }
        .balance-positive { color: #3fb950; font-weight: 600; }
        .balance-medium { color: #d29922; font-weight: 600; }
        .balance-zero { color: #f85149; }
        .copy-btn, .retry-btn { background: transparent; border: none; cursor: pointer; font-size: 11px; padding: 3px 8px; border-radius: 6px; transition: all 0.2s; }
        .copy-btn { color: #58a6ff; }
        .copy-btn:hover { background: #30363d; color: #3fb950; }
        .retry-btn { color: #d29922; }
        .retry-btn:hover { background: #30363d; color: #f0883e; }
        .username-cell, .password-cell { display: flex; align-items: center; justify-content: space-between; gap: 6px; flex-wrap: wrap; }
        .error-cell { display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 6px; }
        .bottom-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }
        .card { background: #161b22; border-radius: 20px; border: 1px solid #30363d; overflow: hidden; }
        .card-header { padding: 12px 18px; background: #0d1117; border-bottom: 1px solid #30363d; font-weight: 600; font-size: 13px; }
        .card-header i { color: #58a6ff; margin-right: 6px; }
        
        .terminal-header { display: flex; justify-content: space-between; align-items: center; padding: 12px 18px; background: #0d1117; border-bottom: 1px solid #30363d; }
        .toggle-terminal-btn { background: #21262d; border: none; border-radius: 20px; color: #8b949e; cursor: pointer; padding: 4px 12px; font-size: 10px; transition: all 0.2s; }
        .toggle-terminal-btn:hover { background: #30363d; color: #58a6ff; }
        .terminal { background: #010409; height: 280px; overflow-y: auto; padding: 10px; font-family: monospace; font-size: 10px; transition: all 0.3s; }
        .terminal.hidden { display: none; }
        .terminal-line { padding: 4px 0; color: #b1bac4; border-bottom: 1px solid #1a1f2e; }
        .terminal-line .time { color: #58a6ff; margin-right: 10px; }
        
        .servers-list { padding: 14px; background: #0d1117; margin: 10px; border-radius: 10px; }
        .server-item { display: flex; gap: 8px; margin-bottom: 10px; align-items: center; flex-wrap: wrap; background: #010409; padding: 8px 10px; border-radius: 10px; }
        .server-item input { flex: 2; min-width: 180px; padding: 8px 10px; background: #0d1117; border: 1px solid #30363d; border-radius: 8px; color: white; font-size: 12px; }
        .server-item input:focus { outline: none; border-color: #58a6ff; }
        
        .server-status { display: inline-flex; align-items: center; gap: 8px; margin-left: 5px; }
        .status-led { width: 10px; height: 10px; border-radius: 50%; display: inline-block; }
        .status-led.online { background: #3fb950; box-shadow: 0 0 5px #3fb950; }
        .status-led.running { background: #58a6ff; box-shadow: 0 0 5px #58a6ff; animation: pulse 1s infinite; }
        .status-led.offline { background: #f85149; box-shadow: 0 0 5px #f85149; }
        .status-led.checking { background: #d29922; box-shadow: 0 0 5px #d29922; animation: pulse 1s infinite; }
        @keyframes pulse { 0% { opacity: 0.5; } 50% { opacity: 1; } 100% { opacity: 0.5; } }
        .server-status-text { font-size: 10px; color: #8b949e; }
        .server-progress { font-size: 9px; color: #58a6ff; margin-left: 5px; }
        
        .server-controls { display: flex; gap: 6px; margin-left: auto; }
        .control-btn { padding: 5px 12px; border: none; border-radius: 6px; cursor: pointer; font-size: 10px; font-weight: 500; transition: all 0.2s; }
        .control-start { background: #238636; color: white; }
        .control-start:hover { background: #2ea043; transform: scale(1.02); }
        .control-restart { background: #d29922; color: #0a0c10; }
        .control-restart:hover { background: #f0883e; transform: scale(1.02); }
        .control-stop { background: #da3633; color: white; }
        .control-stop:hover { background: #f85149; transform: scale(1.02); }
        .control-btn:disabled { opacity: 0.5; cursor: not-allowed; transform: none; }
        
        .remove-server-btn { background: #da3633; border: none; border-radius: 6px; color: white; cursor: pointer; padding: 5px 8px; font-size: 10px; transition: all 0.2s; }
        .remove-server-btn:hover { background: #f85149; }
        
        .add-server-btn { background: #238636; border: none; border-radius: 8px; color: white; cursor: pointer; padding: 6px 12px; font-size: 11px; margin-top: 8px; transition: all 0.2s; }
        .add-server-btn:hover { background: #2ea043; }
        .button-group { padding: 14px; display: flex; gap: 8px; flex-wrap: wrap; border-top: 1px solid #21262d; }
        .btn { padding: 6px 16px; border: none; border-radius: 8px; font-weight: 600; cursor: pointer; transition: all 0.2s; font-size: 12px; }
        .btn-primary { background: linear-gradient(135deg, #238636, #2ea043); color: white; }
        .btn-primary:hover { transform: translateY(-1px); }
        .btn-secondary { background: #6e7681; color: white; }
        .btn-secondary:hover { background: #8b949e; transform: translateY(-1px); }
        
        .auto-refresh { position: fixed; bottom: 20px; right: 20px; background: #161b22; padding: 6px 12px; border-radius: 20px; font-size: 10px; border: 1px solid #30363d; }
        ::-webkit-scrollbar { width: 6px; }
        ::-webkit-scrollbar-track { background: #161b22; border-radius: 3px; }
        ::-webkit-scrollbar-thumb { background: #30363d; border-radius: 3px; }
        ::-webkit-scrollbar-thumb:hover { background: #58a6ff; }
        
        @media (max-width: 900px) {
            body { padding: 12px; }
            .bottom-grid { grid-template-columns: 1fr; }
            .stats-top { grid-template-columns: repeat(2, 1fr); }
            .balance-filter { margin-left: 0; margin-top: 8px; }
            .filter-bar { flex-direction: column; align-items: stretch; }
            .search-input { width: 100%; }
            .server-item { flex-direction: column; align-items: stretch; }
            .server-controls { margin-left: 0; margin-top: 8px; justify-content: flex-end; }
        }
    </style>
</head>
<body>
<div id="pinOverlay" class="pin-overlay">
    <div class="pin-box">
        <h2><i class="fas fa-lock"></i> Master UI Access</h2>
        <input type="password" id="pinInput" placeholder="PIN" maxlength="6" autofocus>
        <button onclick="verifyPin()"><i class="fas fa-unlock-alt"></i> Access</button>
        <div id="pinError" class="pin-error"></div>
    </div>
</div>

<div id="mainContent" class="main-content">
<div class="container">
    <div class="header">
        <h1><i class="fas fa-network-wired"></i> MASTER UI | Multi Bot Aggregator</h1>
        <div class="header-sub">📡 Հավաքում է բոլոր bot-երի արդյունքները մեկ տեղում</div>
    </div>

    <div class="stats-top">
        <div class="stat-card" onclick="setFilter('all')"><div class="stat-number" id="totalCount">0</div><div class="stat-label">TOTAL</div></div>
        <div class="stat-card" onclick="setFilter('success')"><div class="stat-number" id="successCount">0</div><div class="stat-label">✅ SUCCESS</div></div>
        <div class="stat-card" onclick="setFilter('failed')"><div class="stat-number" id="failedCount">0</div><div class="stat-label">❌ FAILED</div></div>
        <div class="stat-card" onclick="setFilter('timeout')"><div class="stat-number" id="timeoutCount">0</div><div class="stat-label">⏰ TIMEOUT</div></div>
    </div>

    <div class="results-section">
        <div class="section-header"><i class="fas fa-chart-line"></i> Results Dashboard</div>
        <div class="filter-bar">
            <input type="text" id="searchInput" class="search-input" placeholder="🔍 Search username...">
            <button class="filter-btn active" data-filter="all" onclick="setFilter('all')">All</button>
            <button class="filter-btn" data-filter="success" onclick="setFilter('success')">✅ Success</button>
            <button class="filter-btn" data-filter="failed" onclick="setFilter('failed')">❌ Failed</button>
            <button class="filter-btn" data-filter="timeout" onclick="setFilter('timeout')">⏰ Timeout</button>
            <button class="refresh-btn" onclick="manualRefresh()"><i class="fas fa-sync-alt"></i> Refresh</button>
            <div class="balance-filter">
                <span>💰</span>
                <button class="balance-filter-btn active" data-balance="all" onclick="setBalanceFilter('all')">All</button>
                <button class="balance-filter-btn" data-balance="low" onclick="setBalanceFilter('low')">&lt;10</button>
                <button class="balance-filter-btn" data-balance="mid" onclick="setBalanceFilter('mid')">10-100</button>
                <button class="balance-filter-btn" data-balance="high" onclick="setBalanceFilter('high')">100+</button>
            </div>
        </div>
        <div class="table-container">
            <table id="resultsTable">
                <thead><tr><th onclick="sortBy('status')"><i class="fas fa-flag"></i> Status</th><th onclick="sortBy('username')"><i class="fas fa-user"></i> Username</th><th onclick="sortBy('password')"><i class="fas fa-key"></i> Password</th><th onclick="sortBy('balance')"><i class="fas fa-coins"></i> Balance</th><th><i class="fas fa-cogs"></i> Action</th></tr></thead>
                <tbody id="resultsBody"><tr><td colspan="5" style="text-align:center; padding:40px;"><i class="fas fa-spinner fa-pulse"></i> Loading...</td></tr></tbody>
            </table>
        </div>
    </div>

    <div class="bottom-grid">
        <div class="card">
            <div class="card-header"><i class="fas fa-server"></i> Bot Servers</div>
            <div class="servers-list">
                <div id="serversContainer"></div>
                <div style="display: flex; gap: 8px; margin-top: 10px;">
                    <input type="text" id="newServerInput" class="search-input" placeholder="http://..." style="flex:1;">
                    <button class="add-server-btn" onclick="addServer()"><i class="fas fa-plus"></i> Add</button>
                </div>
                <button class="btn btn-primary" onclick="saveServers()" style="margin-top: 10px; width:100%;"><i class="fas fa-save"></i> Save & Apply</button>
            </div>
            <div class="button-group">
                <button class="btn btn-secondary" onclick="manualRefresh()"><i class="fas fa-sync-alt"></i> Refresh All</button>
                <button class="btn btn-secondary" onclick="clearTerminal()"><i class="fas fa-trash"></i> Clear Terminal</button>
            </div>
        </div>
        <div class="card">
            <div class="terminal-header">
                <h3><i class="fas fa-terminal"></i> Live Console</h3>
                <button class="toggle-terminal-btn" onclick="toggleTerminal()"><i class="fas fa-eye-slash"></i> Hide</button>
            </div>
            <div class="terminal" id="terminal">
                <div class="terminal-line"><span class="time">●</span> 🚀 MASTER UI v2.0</div>
                <div class="terminal-line"><span class="time">●</span> 📡 Auto-refresh every 5 seconds</div>
                <div class="terminal-line"><span class="time">●</span> 💡 Start = Save accounts & Run</div>
                <div class="terminal-line"><span class="time">●</span> 💡 Restart = Stop + Reset + Start (same accounts)</div>
            </div>
        </div>
    </div>
</div>
</div>
<div class="auto-refresh"><i class="fas fa-clock"></i> Auto-refresh: 5s</div>

<script>
let allResults = [], currentFilter = 'all', currentBalanceFilter = 'all', currentSort = { field: 'balance', dir: 'desc' };
let refreshInterval = null, currentServers = [], authToken = null, serverStatuses = {}, accountsText = '';

function toggleTerminal() {
    const terminal = document.getElementById('terminal');
    const btn = document.querySelector('.toggle-terminal-btn');
    if (terminal.classList.contains('hidden')) {
        terminal.classList.remove('hidden');
        btn.innerHTML = '<i class="fas fa-eye-slash"></i> Hide';
    } else {
        terminal.classList.add('hidden');
        btn.innerHTML = '<i class="fas fa-eye"></i> Show';
    }
}

async function verifyPin() {
    const pin = document.getElementById('pinInput').value;
    const errorDiv = document.getElementById('pinError');
    if(!pin) { errorDiv.innerText = 'Enter PIN'; return; }
    try {
        const res = await fetch('/api/verify', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ pin: pin })
        });
        const data = await res.json();
        if(data.success) {
            authToken = data.token;
            localStorage.setItem('master_token', authToken);
            document.getElementById('pinOverlay').style.display = 'none';
            document.getElementById('mainContent').style.display = 'block';
            initializeApp();
        } else {
            errorDiv.innerText = 'Invalid PIN';
            document.getElementById('pinInput').value = '';
        }
    } catch(e) { errorDiv.innerText = 'Connection error'; }
}

async function checkExistingSession() {
    const savedToken = localStorage.getItem('master_token');
    if(savedToken) {
        try {
            const res = await fetch(`/api/check?token=${savedToken}`);
            const data = await res.json();
            if(data.authenticated) {
                authToken = savedToken;
                document.getElementById('pinOverlay').style.display = 'none';
                document.getElementById('mainContent').style.display = 'block';
                initializeApp();
                return true;
            }
        } catch(e) {}
    }
    return false;
}

async function initializeApp() {
    await loadServers();
    await loadResults();
    await updateServerStatuses();
    refreshInterval = setInterval(() => { loadResults(); updateServerStatuses(); }, 5000);
}

async function updateServerStatuses() {
    try {
        const res = await fetch('/health');
        if (res.ok) {
            const data = await res.json();
            for (const bot of data.bots) {
                serverStatuses[bot.server] = {
                    status: bot.status,
                    running: bot.running || false,
                    current_index: bot.current_index || 0,
                    total: bot.total || 0
                };
            }
            renderServersList();
        }
    } catch(e) { console.error(e); }
}

async function loadServers() {
    try {
        const res = await fetch('/api/servers');
        if (res.ok) {
            const data = await res.json();
            currentServers = data.servers;
            renderServersList();
        }
    } catch(e) { addLog(`❌ Error loading servers: ${e.message}`); }
}

function renderServersList() {
    const container = document.getElementById('serversContainer');
    if (!container) return;
    if (currentServers.length === 0) {
        container.innerHTML = '<div style="color:#8b949e; text-align:center; padding:20px;"><i class="fas fa-info-circle"></i> No servers added. Add a server above.</div>';
        return;
    }
    
    container.innerHTML = currentServers.map((server, index) => {
        const info = serverStatuses[server] || { status: 'checking', running: false, current_index: 0, total: 0 };
        let ledClass = '', statusText = '';
        
        if (info.status === 'offline') {
            ledClass = 'offline';
            statusText = 'Offline';
        } else if (info.status === 'online' && info.running) {
            ledClass = 'running';
            statusText = `Running`;
        } else if (info.status === 'online' && !info.running) {
            ledClass = 'online';
            statusText = 'Online';
        } else {
            ledClass = 'checking';
            statusText = 'Checking...';
        }
        
        const progressInfo = (info.running && info.status === 'online') ? `<span class="server-progress">📊 ${info.current_index}/${info.total}</span>` : '';
        
        return `
            <div class="server-item">
                <input type="text" id="server_${index}" value="${escapeHtml(server)}" placeholder="https://...">
                <div class="server-status">
                    <span class="status-led ${ledClass}"></span>
                    <span class="server-status-text">${statusText}</span>
                    ${progressInfo}
                </div>
                <div class="server-controls">
                    <button class="control-btn control-start" onclick="startServer(${index})" ${info.status !== 'online' ? 'disabled' : ''}><i class="fas fa-play"></i> Start</button>
                    <button class="control-btn control-restart" onclick="restartServer(${index})" ${info.status !== 'online' ? 'disabled' : ''}><i class="fas fa-sync-alt"></i> Restart</button>
                    <button class="control-btn control-stop" onclick="stopServer(${index})" ${info.status !== 'online' ? 'disabled' : ''}><i class="fas fa-stop"></i> Stop</button>
                    <button class="remove-server-btn" onclick="removeServer(${index})"><i class="fas fa-trash"></i></button>
                </div>
            </div>
        `;
    }).join('');
}

async function startServer(index) {
    const server = currentServers[index];
    if (!server) return;
    
    const accounts = prompt(`📝 Enter accounts for ${server}\\n\\nFormat: username:password (one per line):`, accountsText);
    if (!accounts) return;
    
    accountsText = accounts;
    addLog(`🚀 Starting bot on ${server}...`);
    
    const btn = document.querySelector(`#serversContainer .server-item:nth-child(${index+1}) .control-start`);
    if (btn) { btn.disabled = true; btn.innerHTML = '<i class="fas fa-spinner fa-pulse"></i>'; }
    
    try {
        const res = await fetch(`/api/control/${index}/start`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ accounts: accounts })
        });
        const data = await res.json();
        if (data.success) {
            addLog(`✅ Start command sent to ${server}`);
            setTimeout(() => updateServerStatuses(), 1000);
        } else {
            addLog(`❌ Failed to start ${server}: ${data.error}`);
        }
    } catch(e) { addLog(`❌ Error starting ${server}: ${e.message}`); }
    
    setTimeout(() => {
        if (btn) { btn.disabled = false; btn.innerHTML = '<i class="fas fa-play"></i> Start'; }
    }, 3000);
}

async function restartServer(index) {
    const server = currentServers[index];
    if (!server) return;
    
    addLog(`🔄 Restarting bot on ${server}...`);
    
    const btn = document.querySelector(`#serversContainer .server-item:nth-child(${index+1}) .control-restart`);
    if (btn) { btn.disabled = true; btn.innerHTML = '<i class="fas fa-spinner fa-pulse"></i>'; }
    
    try {
        const res = await fetch(`/api/control/${index}/restart`, { method: 'POST' });
        const data = await res.json();
        if (data.success) {
            addLog(`✅ Restart command sent to ${server}`);
            setTimeout(() => { updateServerStatuses(); loadResults(); }, 2000);
        } else {
            addLog(`❌ Failed to restart ${server}: ${data.error}`);
        }
    } catch(e) { addLog(`❌ Error restarting ${server}: ${e.message}`); }
    
    setTimeout(() => {
        if (btn) { btn.disabled = false; btn.innerHTML = '<i class="fas fa-sync-alt"></i> Restart'; }
    }, 3000);
}

async function stopServer(index) {
    const server = currentServers[index];
    if (!server) return;
    
    addLog(`🛑 Stopping bot on ${server}...`);
    
    const btn = document.querySelector(`#serversContainer .server-item:nth-child(${index+1}) .control-stop`);
    if (btn) { btn.disabled = true; btn.innerHTML = '<i class="fas fa-spinner fa-pulse"></i>'; }
    
    try {
        const res = await fetch(`/api/control/${index}/stop`, { method: 'POST' });
        const data = await res.json();
        if (data.success) {
            addLog(`✅ Stop command sent to ${server}`);
            setTimeout(() => updateServerStatuses(), 1000);
        } else {
            addLog(`❌ Failed to stop ${server}: ${data.error}`);
        }
    } catch(e) { addLog(`❌ Error stopping ${server}: ${e.message}`); }
    
    setTimeout(() => {
        if (btn) { btn.disabled = false; btn.innerHTML = '<i class="fas fa-stop"></i> Stop'; }
    }, 3000);
}

function addServer() {
    const input = document.getElementById('newServerInput');
    const newServer = input.value.trim();
    if (newServer) {
        if (!newServer.startsWith('http://') && !newServer.startsWith('https://')) {
            addLog(`⚠️ Server should start with http:// or https://`);
            return;
        }
        currentServers.push(newServer);
        input.value = '';
        renderServersList();
        addLog(`➕ Added server: ${newServer}`);
    }
}

function removeServer(index) {
    const removed = currentServers[index];
    if (confirm(`Remove server ${removed}?`)) {
        currentServers.splice(index, 1);
        renderServersList();
        addLog(`❌ Removed server: ${removed}`);
    }
}

async function saveServers() {
    const inputs = document.querySelectorAll('#serversContainer input');
    const updatedServers = Array.from(inputs).map(input => input.value.trim()).filter(s => s);
    if (updatedServers.length === 0) { addLog('⚠️ No servers specified'); return; }
    try {
        const res = await fetch('/api/servers', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ servers: updatedServers })
        });
        if (res.ok) {
            currentServers = updatedServers;
            addLog(`✅ Servers saved: ${updatedServers.length} server(s)`);
            await updateServerStatuses();
        } else addLog('❌ Failed to save servers');
    } catch(e) { addLog(`❌ Error saving servers: ${e.message}`); }
}

async function loadResults() {
    try {
        const res = await fetch('/results');
        if (res.ok) {
            allResults = await res.json();
            renderResults();
            updateStats();
        }
    } catch(e) { addLog(`❌ Error fetching results: ${e.message}`); }
}

function renderResults() {
    let filtered = allResults.filter(r => {
        if(currentFilter !== 'all') {
            if(currentFilter === 'success' && r.status !== '✅') return false;
            if(currentFilter === 'failed' && r.status !== '❌') return false;
            if(currentFilter === 'timeout' && r.status !== '⏰') return false;
        }
        if(currentBalanceFilter !== 'all') {
            let num = parseFloat(r.balance_value) || 0;
            if(currentBalanceFilter === 'low' && num >= 10) return false;
            if(currentBalanceFilter === 'mid' && (num < 10 || num > 100)) return false;
            if(currentBalanceFilter === 'high' && num <= 100) return false;
        }
        return true;
    });
    let search = document.getElementById('searchInput')?.value.toLowerCase() || '';
    if(search) filtered = filtered.filter(r => r.username.toLowerCase().includes(search));
    filtered.sort((a,b) => {
        let av = currentSort.field === 'balance' ? (a.balance_value || 0) : (a[currentSort.field] || '').toString().toLowerCase();
        let bv = currentSort.field === 'balance' ? (b.balance_value || 0) : (b[currentSort.field] || '').toString().toLowerCase();
        if(typeof av === 'number') return currentSort.dir === 'asc' ? av - bv : bv - av;
        return currentSort.dir === 'asc' ? (av > bv ? 1 : -1) : (av < bv ? 1 : -1);
    });
    let balanceClass = (v) => { let n = parseFloat(v)||0; return n>100?'balance-positive':n>10?'balance-medium':'balance-zero'; };
    document.getElementById('resultsBody').innerHTML = filtered.map(r => `
        <tr>
            <td style="font-size:18px">${r.status}</td>
            <td><div class="username-cell"><strong style="color:#58a6ff">${escapeHtml(r.username)}</strong><button class="copy-btn" onclick="copyToClipboard('${escapeHtml(r.username)}', this)"><i class="fas fa-copy"></i></button></div></td>
            <td><div class="password-cell">${escapeHtml(r.password)}<button class="copy-btn" onclick="copyToClipboard('${escapeHtml(r.password)}', this)"><i class="fas fa-key"></i></button></div></td>
            <td class="${balanceClass(r.balance_value)}">${r.balance||'0 ֏'}</td>
            <td class="error-cell">${escapeHtml(r.error||'-')}<button class="retry-btn" onclick="retryAccount('${escapeHtml(r.username)}', this)"><i class="fas fa-sync-alt"></i> Retry</button></td>
        </tr>`).join('');
    if (filtered.length === 0 && allResults.length > 0) document.getElementById('resultsBody').innerHTML = '<td><td colspan="5" style="text-align:center; padding:40px;">No matching results</td></tr>';
}

function updateStats() {
    document.getElementById('totalCount').innerText = allResults.length;
    document.getElementById('successCount').innerText = allResults.filter(r => r.status === '✅').length;
    document.getElementById('failedCount').innerText = allResults.filter(r => r.status === '❌').length;
    document.getElementById('timeoutCount').innerText = allResults.filter(r => r.status === '⏰').length;
}

function sortBy(field) {
    if(currentSort.field === field) currentSort.dir = currentSort.dir === 'asc' ? 'desc' : 'asc';
    else { currentSort.field = field; currentSort.dir = field === 'balance' ? 'desc' : 'asc'; }
    renderResults();
}
function setFilter(f) { currentFilter = f; document.querySelectorAll('.filter-btn').forEach(btn => btn.classList.toggle('active', btn.dataset.filter === f)); renderResults(); }
function setBalanceFilter(f) { currentBalanceFilter = f; document.querySelectorAll('.balance-filter-btn').forEach(btn => btn.classList.toggle('active', btn.dataset.balance === f)); renderResults(); }
function manualRefresh() { loadResults(); updateServerStatuses(); addLog('🔄 Manual refresh'); }
function escapeHtml(s) { if(!s) return ''; return s.replace(/[&<>]/g, m => ({'&':'&amp;','<':'&lt;','>':'&gt;'})[m]); }
function addLog(msg) { let term = document.getElementById('terminal'); let div = document.createElement('div'); div.className = 'terminal-line'; div.innerHTML = `<span class="time">[${new Date().toLocaleTimeString()}]</span> ${msg}`; term.appendChild(div); if(term.children.length > 100) term.removeChild(term.firstChild); }
function clearTerminal() { document.getElementById('terminal').innerHTML = ''; addLog('Terminal cleared'); }
async function copyToClipboard(text, btn) { await navigator.clipboard.writeText(text); let orig = btn.innerHTML; btn.innerHTML = '✓'; setTimeout(() => btn.innerHTML = orig, 1000); }
async function retryAccount(username, btn) {
    let orig = btn.innerHTML;
    btn.innerHTML = '<i class="fas fa-spinner fa-pulse"></i>';
    btn.disabled = true;
    addLog(`⟳ Retrying ${username}...`);
    try {
        await fetch(`/retry/${encodeURIComponent(username)}`, { method: 'POST' });
        addLog(`✅ Retry request sent for ${username}`);
        setTimeout(() => loadResults(), 2000);
    } catch(e) { addLog(`❌ Retry failed for ${username}`); }
    setTimeout(() => { btn.innerHTML = orig; btn.disabled = false; }, 3000);
}

document.getElementById('searchInput').addEventListener('input', () => renderResults());
document.getElementById('pinInput').addEventListener('keypress', (e) => { if(e.key === 'Enter') verifyPin(); });
checkExistingSession();
</script>
</body>
</html>'''

@app.get("/")
async def root():
    return HTMLResponse(HTML_UI)

if __name__ == "__main__":
    import uvicorn
    print("\n" + "=" * 60)
    print("🖥️  MASTER UI - Multi Bot Aggregator v2.0")
    print("=" * 60)
    print(f"📍 Master UI: http://localhost:9000")
    print(f"🔐 Master PIN: {MASTER_PIN}")
    print("=" * 60)
    print("📌 Instructions:")
    print("   1. Add your bot servers (e.g., http://localhost:8000)")
    print("   2. Click Start and enter accounts (username:password)")
    print("   3. Use Restart to run same accounts again")
    print("   4. Stop to pause the bot")
    print("=" * 60 + "\n")
    uvicorn.run(app, host="0.0.0.0", port=9000, log_level="info")

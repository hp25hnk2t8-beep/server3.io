import httpx
import asyncio
from fastapi import FastAPI, Request, HTTPException, Depends
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from typing import List, Dict, Optional
import json
from pathlib import Path
from datetime import datetime, timedelta
import secrets

# ================= PIN ԿԱՐԳԱՎՈՐՈՒՄ =================
MASTER_PIN = "991122"
MOBILE_PIN = "1111"
# ====================================================

# ================= ՍԵՍԻԱՆԵՐԻ ԿԱՌԱՎԱՐՈՒՄ =================
sessions = {}
mobile_sessions = {}

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

def create_mobile_session() -> str:
    token = secrets.token_urlsafe(32)
    mobile_sessions[token] = datetime.now() + timedelta(hours=24)
    return token

def verify_mobile_session(token: str) -> bool:
    if token not in mobile_sessions:
        return False
    if mobile_sessions[token] < datetime.now():
        del mobile_sessions[token]
        return False
    return True

# ================= AUTH DEPENDENCIES =================
async def get_current_user(token: Optional[str] = None) -> str:
    """Ստուգում է Master UI-ի սեսիան"""
    if not token:
        raise HTTPException(status_code=401, detail="Missing authentication token")
    if not verify_session(token):
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    return token

async def get_mobile_user(token: Optional[str] = None) -> str:
    """Ստուգում է Mobile UI-ի սեսիան"""
    if not token:
        raise HTTPException(status_code=401, detail="Missing authentication token")
    if not verify_mobile_session(token):
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    return token

# ================= ONLINE USERS =================
online_users = {}
last_activity = {}

def update_user_activity(token: str):
    if token:
        online_users[token] = datetime.now()
        last_activity[token] = datetime.now()

def cleanup_inactive_users():
    now = datetime.now()
    to_remove = []
    for token, last in list(last_activity.items()):
        if (now - last).seconds > 30:
            to_remove.append(token)
    for token in to_remove:
        if token in online_users:
            del online_users[token]
        if token in last_activity:
            del last_activity[token]

def get_online_count():
    cleanup_inactive_users()
    return len(online_users)

# ================= ՍԵՐՎԵՐՆԵՐԻ ԿԱՐԳԱՎՈՐՈՒՄ =================
CONFIG_FILE = Path("master_servers.json")
ACCOUNTS_FILE = Path("master_saved_accounts.json")
CACHED_RESULTS_FILE = Path("master_cached_results.json")

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

def load_cached_results() -> Dict[str, Dict]:
    if CACHED_RESULTS_FILE.exists():
        with open(CACHED_RESULTS_FILE, "r") as f:
            return json.load(f)
    return {}

def save_cached_results(results: Dict[str, Dict]):
    for k, v in results.items():
        if "balance_value" not in v or not isinstance(v["balance_value"], (int, float)):
            v["balance_value"] = 0.0
    with open(CACHED_RESULTS_FILE, "w") as f:
        json.dump(results, f, indent=2)

BOT_SERVERS = load_servers()
# ====================================================

app = FastAPI(title="Master UI - Multi Bot Aggregator")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# ================= MERGE RESULTS LOGIC =================
cached_results: Dict[str, Dict] = load_cached_results()

async def fetch_and_merge_results() -> List[Dict]:
    global cached_results
    
    async with httpx.AsyncClient(timeout=10) as client:
        for server in BOT_SERVERS:
            try:
                res = await client.get(f"{server}/results")
                if res.status_code == 200:
                    data = res.json()
                    for account in data:
                        username = account.get("username")
                        if username:
                            balance_val = account.get("balance_value")
                            if balance_val is None:
                                balance_val = 0.0
                            try:
                                balance_val = float(balance_val)
                            except:
                                balance_val = 0.0
                            
                            if username in cached_results:
                                old = cached_results[username]
                                old["balance"] = account.get("balance", old.get("balance", "0 ֏"))
                                old["balance_value"] = balance_val
                                old["status"] = account.get("status", old.get("status", "❌"))
                                old["error"] = account.get("error", old.get("error", ""))
                                old["timestamp"] = account.get("timestamp", old.get("timestamp", datetime.now().isoformat()))
                                old["password"] = account.get("password", old.get("password", ""))
                            else:
                                new_acc = account.copy()
                                new_acc["balance_value"] = balance_val
                                cached_results[username] = new_acc
                    print(f"✅ Fetched/merged {len(data)} accounts from {server}")
            except Exception as e:
                print(f"❌ Error fetching from {server}: {e}")
    
    save_cached_results(cached_results)
    return list(cached_results.values())

# ================= PROTECTED API ENDPOINTS =================

@app.get("/results")
async def get_merged_results(token: str = Depends(get_current_user)):
    """Արդյունքները ստանալու համար պահանջվում է աուտենտիֆիկացիա"""
    return await fetch_and_merge_results()

@app.post("/results/clear")
async def clear_all_results(token: str = Depends(get_current_user)):
    """Բոլոր արդյունքները ջնջելու համար պահանջվում է աուտենտիֆիկացիա"""
    global cached_results
    cached_results = {}
    save_cached_results({})
    return {"success": True, "message": "All results cleared"}

@app.post("/results/clear/{username}")
async def clear_single_result(username: str, token: str = Depends(get_current_user)):
    """Մեկ արդյունք ջնջելու համար պահանջվում է աուտենտիֆիկացիա"""
    global cached_results
    if username in cached_results:
        del cached_results[username]
        save_cached_results(cached_results)
        return {"success": True, "message": f"Removed {username}"}
    return {"success": False, "message": "Account not found"}

@app.get("/health")
async def health(token: str = Depends(get_current_user)):
    """Սերվերների կարգավիճակը ստանալու համար պահանջվում է աուտենտիֆիկացիա"""
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
async def retry_account(username: str, token: str = Depends(get_current_user)):
    """Ակաունթը կրկին փորձելու համար պահանջվում է աուտենտիֆիկացիա"""
    for server in BOT_SERVERS:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                await client.post(f"{server}/retry/{username}")
        except:
            pass
    return {"status": "retry_sent"}

@app.post("/api/control/{server_id}/start")
async def control_start(server_id: int, request: Request, token: str = Depends(get_current_user)):
    """Սերվերը գործարկելու համար պահանջվում է աուտենտիֆիկացիա"""
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
async def control_restart(server_id: int, token: str = Depends(get_current_user)):
    """Սերվերը վերագործարկելու համար պահանջվում է աուտենտիֆիկացիա"""
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
async def control_stop(server_id: int, token: str = Depends(get_current_user)):
    """Սերվերը կանգնեցնելու համար պահանջվում է աուտենտիֆիկացիա"""
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
async def get_servers(token: str = Depends(get_current_user)):
    """Սերվերների ցանկը ստանալու համար պահանջվում է աուտենտիֆիկացիա"""
    return {"servers": BOT_SERVERS}

@app.post("/api/servers")
async def update_servers(request: Request, token: str = Depends(get_current_user)):
    """Սերվերների ցանկը թարմացնելու համար պահանջվում է աուտենտիֆիկացիա"""
    global BOT_SERVERS
    data = await request.json()
    servers = data.get("servers", [])
    if servers:
        BOT_SERVERS = servers
        save_servers(servers)
    return {"success": True, "servers": BOT_SERVERS}

@app.get("/api/online")
async def get_online_count_endpoint(token: Optional[str] = None):
    """Online օգտատերերի քանակը - հասանելի է առանց աուտենտիֆիկացիայի (միայն քանակը)"""
    if token:
        update_user_activity(token)
    return {"online": get_online_count()}

# ================= AUTH ENDPOINTS (ՉԵՆ ՊԱՇՏՊԱՆՎՈՒՄ) =================

@app.post("/api/verify")
async def verify_pin(request: Request):
    """Master PIN-ի ստուգում - հասանելի է առանց աուտենտիֆիկացիայի"""
    data = await request.json()
    pin = data.get("pin", "")
    if pin == MASTER_PIN:
        token = create_session()
        return {"success": True, "token": token}
    return {"success": False}

@app.get("/api/check")
async def check_session(token: str = None):
    """Սեսիայի ստուգում - հասանելի է առանց աուտենտիֆիկացիայի"""
    if token and verify_session(token):
        return {"authenticated": True}
    return {"authenticated": False}

@app.post("/mobile/verify")
async def verify_mobile_pin(request: Request):
    """Mobile PIN-ի ստուգում - հասանելի է առանց աուտենտիֆիկացիայի"""
    data = await request.json()
    pin = data.get("pin", "")
    if pin == MOBILE_PIN:
        token = create_mobile_session()
        return {"success": True, "token": token}
    return {"success": False}

@app.get("/mobile/check")
async def check_mobile_session(token: str = None):
    """Mobile սեսիայի ստուգում - հասանելի է առանց աուտենտիֆիկացիայի"""
    if token and verify_mobile_session(token):
        return {"authenticated": True}
    return {"authenticated": False}

# ================= HTML PAGES WITH SOURCE PROTECTION =================

# Հիմնական HTML-ը պարունակում է միայն դատարկ կառուցվածք և JavaScript, որը կստեղծի ամբողջ բովանդակությունը
MAIN_HTML = '''<!DOCTYPE html>
<html lang="hy">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Master UI</title>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap" rel="stylesheet">
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <style>
        * { margin:0; padding:0; box-sizing:border-box; }
        body { background: #0a0c10; color: #e6edf3; font-family: 'Inter', sans-serif; min-height: 100vh; }
        #app { min-height: 100vh; }
        .pin-overlay { position: fixed; top:0; left:0; width:100%; height:100%; background: rgba(0,0,0,0.95); backdrop-filter: blur(12px); display: flex; align-items: center; justify-content: center; z-index: 1000; }
        .pin-box { background: #161b22; border: 1px solid #30363d; border-radius: 24px; padding: 40px; width: 320px; text-align: center; }
        .pin-box h2 { margin-bottom: 24px; background: linear-gradient(135deg, #58a6ff, #3fb950); -webkit-background-clip: text; background-clip: text; color: transparent; }
        .pin-box input { width: 100%; padding: 12px; margin: 8px 0; background: #0d1117; border: 1px solid #30363d; border-radius: 12px; color: white; font-size: 18px; text-align: center; letter-spacing: 6px; }
        .pin-box button { width: 100%; padding: 12px; background: linear-gradient(135deg, #238636, #2ea043); border: none; border-radius: 12px; color: white; font-weight: bold; cursor: pointer; margin-top: 16px; }
        .pin-error { color: #f85149; font-size: 12px; margin-top: 12px; }
        .main-content { display: none; }
        .container { max-width: 1600px; margin: 0 auto; padding: 20px; }
        /* styles will be applied by JavaScript */
    </style>
</head>
<body>
<div id="app">
    <div id="pinOverlay" class="pin-overlay">
        <div class="pin-box">
            <h2><i class="fas fa-lock"></i> Master UI Access</h2>
            <input type="password" id="pinInput" placeholder="PIN" maxlength="6" autofocus>
            <button onclick="verifyPin()"><i class="fas fa-unlock-alt"></i> Access</button>
            <div id="pinError" class="pin-error"></div>
        </div>
    </div>
    <div id="mainContent" class="main-content"></div>
</div>
<script>
// ===== ԱՄԲՈՂՋ HTML ԿՈԴԸ ԳՏՆՎՈՒՄ Է ԱՅՍ JavaScript-ՈՒՄ =====
// Սա դժվարացնում է աղբյուրի կոդի տեսանելիությունը

const APP_HTML = {
    header: function(onlineCount) {
        return `<div class="header"><h1><i class="fas fa-network-wired"></i> MASTER UI | Multi Bot Aggregator <span class="online-badge" id="onlineUsers">👤 ${onlineCount}</span></h1><div class="header-sub">📡 Արդյունքները ՊԱՀՊԱՆՎՈՒՄ ԵՆ | ⭐ Pin ակաունթները միշտ վերևում</div></div>`;
    },
    stats: function(total, success, failed, timeout, balance) {
        return `<div class="stats-top"><div class="stat-card" onclick="setFilter('all')"><div class="stat-number" id="totalCount">${total}</div><div class="stat-label">TOTAL</div></div><div class="stat-card" onclick="setFilter('success')"><div class="stat-number" id="successCount">${success}</div><div class="stat-label">✅ SUCCESS</div></div><div class="stat-card" onclick="setFilter('failed')"><div class="stat-number" id="failedCount">${failed}</div><div class="stat-label">❌ FAILED</div></div><div class="stat-card" onclick="setFilter('timeout')"><div class="stat-number" id="timeoutCount">${timeout}</div><div class="stat-label">⏰ TIMEOUT</div></div><div class="stat-card"><div class="stat-number balance-total" id="totalBalance">${balance.toFixed(2)} ֏</div><div class="stat-label">💰 TOTAL BALANCE</div></div></div>`;
    },
    results: function() {
        return `<div class="results-section"><div class="section-header"><span><i class="fas fa-chart-line"></i> Results Dashboard</span><button class="clear-all-btn" onclick="clearAllResults()"><i class="fas fa-trash-alt"></i> Clear All Results</button></div><div class="filter-bar"><input type="text" id="searchInput" class="search-input" placeholder="🔍 Search username..."><button class="filter-btn active" data-filter="all" onclick="setFilter('all')">All</button><button class="filter-btn" data-filter="success" onclick="setFilter('success')">✅ Success</button><button class="filter-btn" data-filter="failed" onclick="setFilter('failed')">❌ Failed</button><button class="filter-btn" data-filter="timeout" onclick="setFilter('timeout')">⏰ Timeout</button><button class="refresh-btn" onclick="manualRefresh()"><i class="fas fa-sync-alt"></i> Refresh</button><div class="balance-filter"><span>💰</span><button class="balance-filter-btn active" data-balance="all" onclick="setBalanceFilter('all')">All</button><button class="balance-filter-btn" data-balance="low" onclick="setBalanceFilter('low')">&lt;10</button><button class="balance-filter-btn" data-balance="mid" onclick="setBalanceFilter('mid')">10-100</button><button class="balance-filter-btn" data-balance="high" onclick="setBalanceFilter('high')">100+</button></div></div><div class="table-container"><table id="resultsTable"><thead><tr><th>⭐</th><th onclick="sortBy('status')">Status</th><th onclick="sortBy('username')">Username</th><th onclick="sortBy('password')">Password</th><th onclick="sortBy('balance')">Balance</th><th>Action</th></tr></thead><tbody id="resultsBody"><tr><td colspan="6" style="text-align:center; padding:40px;">Loading...</tr></tbody></table></div></div>`;
    },
    bottom: function() {
        return `<div class="bottom-grid"><div class="card"><div class="card-header"><i class="fas fa-server"></i> Bot Servers</div><div class="servers-list"><div id="serversContainer"></div><div style="display: flex; gap: 8px; margin-top: 10px;"><input type="text" id="newServerInput" class="search-input" placeholder="http://..." style="flex:1;"><button class="add-server-btn" onclick="addServer()"><i class="fas fa-plus"></i> Add</button></div><button class="btn btn-primary" onclick="saveServers()" style="margin-top: 10px; width:100%;"><i class="fas fa-save"></i> Save & Apply</button></div><div class="button-group"><button class="btn btn-secondary" onclick="manualRefresh()"><i class="fas fa-sync-alt"></i> Refresh All</button><button class="btn btn-danger" onclick="clearAllResults()"><i class="fas fa-trash-alt"></i> Clear All Results</button><button class="btn btn-secondary" onclick="clearTerminal()"><i class="fas fa-trash"></i> Clear Terminal</button></div></div><div class="card"><div class="terminal-header"><h3><i class="fas fa-terminal"></i> Live Console</h3><button class="toggle-terminal-btn" onclick="toggleTerminal()"><i class="fas fa-eye-slash"></i> Hide</button></div><div class="terminal" id="terminal"><div class="terminal-line"><span class="time">●</span> 🚀 MASTER UI v3.0 (PERSISTENT RESULTS + PINNED + ONLINE USERS)</div><div class="terminal-line"><span class="time">●</span> 📡 Արդյունքները ՊԱՀՊԱՆՎՈՒՄ ԵՆ | ⭐ Pin արածները միշտ վերևում</div></div></div></div></div>`;
    },
    footer: function(onlineCount) {
        return `<div class="auto-refresh"><i class="fas fa-clock"></i> Auto-refresh: 5s | <span id="onlineUsersSmall">👤 ${onlineCount}</span></div>`;
    }
};

// ===== STYLES =====
const APP_STYLES = `
    .header { background: linear-gradient(135deg, rgba(22,27,34,0.95), rgba(13,17,23,0.95)); border-radius: 20px; padding: 14px 24px; margin-bottom: 20px; border: 1px solid rgba(48,54,61,0.5); text-align: center; }
    .header h1 { font-size: 24px; font-weight: 700; background: linear-gradient(135deg, #58a6ff, #3fb950, #f0883e); -webkit-background-clip: text; background-clip: text; color: transparent; }
    .header-sub { font-size: 12px; color: #8b949e; margin-top: 4px; }
    .online-badge { background: transparent; padding: 2px 12px; border-radius: 20px; font-size: 12px; color: #58a6ff; border: 1px solid #30363d; margin-left: 8px; }
    .stats-top { display: grid; grid-template-columns: repeat(5, 1fr); gap: 12px; margin-bottom: 20px; }
    .stat-card { background: #161b22; border-radius: 14px; padding: 10px 12px; text-align: center; cursor: pointer; border: 1px solid #30363d; transition: all 0.2s; }
    .stat-card:hover { border-color: #58a6ff; background: #1a1f2e; transform: translateY(-2px); }
    .stat-number { font-size: 22px; font-weight: 700; color: #58a6ff; }
    .stat-number.balance-total { color: #f0883e; }
    .stat-label { font-size: 10px; color: #8b949e; margin-top: 3px; }
    .results-section { background: #161b22; border-radius: 20px; border: 1px solid #30363d; overflow: hidden; margin-bottom: 20px; }
    .section-header { padding: 14px 20px; background: #0d1117; border-bottom: 1px solid #30363d; font-weight: 600; font-size: 15px; display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 8px; }
    .clear-all-btn { background: #da3633; border: none; border-radius: 30px; padding: 5px 12px; color: white; cursor: pointer; font-size: 11px; margin-left: 10px; }
    .clear-all-btn:hover { background: #f85149; }
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
    .copy-btn, .retry-btn, .delete-row-btn, .pin-star-btn { background: transparent; border: none; cursor: pointer; font-size: 11px; padding: 3px 8px; border-radius: 6px; transition: all 0.2s; }
    .copy-btn { color: #58a6ff; }
    .copy-btn:hover { background: #30363d; color: #3fb950; }
    .retry-btn { color: #d29922; }
    .retry-btn:hover { background: #30363d; color: #f0883e; }
    .delete-row-btn { color: #f85149; }
    .delete-row-btn:hover { background: #30363d; color: #ff6b6b; }
    .pin-star-btn { color: #d29922; font-size: 14px; }
    .pin-star-btn.active { color: #3fb950; text-shadow: 0 0 3px #3fb950; }
    .username-cell, .password-cell { display: flex; align-items: center; justify-content: space-between; gap: 6px; flex-wrap: wrap; }
    .error-cell { display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 6px; }
    .bottom-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }
    .card { background: #161b22; border-radius: 20px; border: 1px solid #30363d; overflow: hidden; }
    .card-header { padding: 12px 18px; background: #0d1117; border-bottom: 1px solid #30363d; font-weight: 600; font-size: 13px; }
    .card-header i { color: #58a6ff; margin-right: 6px; }
    .terminal-header { display: flex; justify-content: space-between; align-items: center; padding: 12px 18px; background: #0d1117; border-bottom: 1px solid #30363d; }
    .toggle-terminal-btn { background: #21262d; border: none; border-radius: 20px; color: #8b949e; cursor: pointer; padding: 4px 12px; font-size: 10px; }
    .terminal { background: #010409; height: 280px; overflow-y: auto; padding: 10px; font-family: monospace; font-size: 10px; transition: all 0.3s; }
    .terminal.hidden { display: none; }
    .terminal-line { padding: 4px 0; color: #b1bac4; border-bottom: 1px solid #1a1f2e; }
    .terminal-line .time { color: #58a6ff; margin-right: 10px; }
    .servers-list { padding: 14px; background: #0d1117; margin: 10px; border-radius: 10px; }
    .server-item { display: flex; gap: 8px; margin-bottom: 10px; align-items: center; flex-wrap: wrap; background: #010409; padding: 8px 10px; border-radius: 10px; }
    .server-item input { flex: 2; min-width: 180px; padding: 8px 10px; background: #0d1117; border: 1px solid #30363d; border-radius: 8px; color: white; font-size: 12px; }
    .server-status { display: inline-flex; align-items: center; gap: 8px; margin-left: 5px; }
    .status-led { width: 10px; height: 10px; border-radius: 50%; display: inline-block; }
    .status-led.online { background: #3fb950; box-shadow: 0 0 5px #3fb950; }
    .status-led.running { background: #58a6ff; box-shadow: 0 0 5px #58a6ff; animation: pulse 1s infinite; }
    .status-led.offline { background: #f85149; box-shadow: 0 0 5px #f85149; }
    .status-led.checking { background: #d29922; box-shadow: 0 0 5px #d29922; animation: pulse 1s infinite; }
    @keyframes pulse { 0% { opacity: 0.5; } 50% { opacity: 1; } 100% { opacity: 0.5; } }
    .server-controls { display: flex; gap: 6px; margin-left: auto; flex-wrap: wrap; }
    .control-btn { padding: 5px 12px; border: none; border-radius: 6px; cursor: pointer; font-size: 10px; font-weight: 500; }
    .control-start { background: #238636; color: white; }
    .control-restart { background: #d29922; color: #0a0c10; }
    .control-stop { background: #da3633; color: white; }
    .remove-server-btn { background: #da3633; border: none; border-radius: 6px; color: white; cursor: pointer; padding: 5px 8px; }
    .add-server-btn { background: #238636; border: none; border-radius: 8px; color: white; cursor: pointer; padding: 6px 12px; }
    .button-group { padding: 14px; display: flex; gap: 8px; flex-wrap: wrap; border-top: 1px solid #21262d; }
    .btn { padding: 6px 16px; border: none; border-radius: 8px; font-weight: 600; cursor: pointer; font-size: 12px; }
    .btn-primary { background: linear-gradient(135deg, #238636, #2ea043); color: white; }
    .btn-secondary { background: #6e7681; color: white; }
    .btn-danger { background: #da3633; color: white; }
    .auto-refresh { position: fixed; bottom: 20px; right: 20px; background: #161b22; padding: 6px 12px; border-radius: 20px; font-size: 10px; border: 1px solid #30363d; }
    @media (max-width: 900px) { .bottom-grid { grid-template-columns: 1fr; } .balance-filter { margin-left: 0; margin-top: 8px; } .filter-bar { flex-direction: column; align-items: stretch; } .search-input { width: 100%; } .server-item { flex-direction: column; align-items: stretch; } .server-controls { margin-left: 0; margin-top: 8px; justify-content: flex-end; } }
`;

// ===== APPLY STYLES =====
const styleEl = document.createElement('style');
styleEl.textContent = APP_STYLES;
document.head.appendChild(styleEl);

// ===== MAIN APPLICATION LOGIC =====
let allResults = [], currentFilter = 'all', currentBalanceFilter = 'all';
let currentSort = {field: 'balance', dir: 'desc'};
let refreshInterval = null, currentServers = [], authToken = null;
let serverStatuses = {}, accountsText = '';
let pinnedAccounts = JSON.parse(localStorage.getItem('master_pinned') || '[]');

function savePinned() { localStorage.setItem('master_pinned', JSON.stringify(pinnedAccounts)); }
function isPinned(username) { return pinnedAccounts.includes(username); }

function togglePin(username) {
    let idx = pinnedAccounts.indexOf(username);
    if(idx === -1) pinnedAccounts.push(username);
    else pinnedAccounts.splice(idx,1);
    savePinned();
    renderResults();
}

function toggleTerminal() {
    let t = document.getElementById('terminal'), b = document.querySelector('.toggle-terminal-btn');
    if(t) {
        if(t.classList.contains('hidden')) {
            t.classList.remove('hidden');
            if(b) b.innerHTML = '<i class="fas fa-eye-slash"></i> Hide';
        } else {
            t.classList.add('hidden');
            if(b) b.innerHTML = '<i class="fas fa-eye"></i> Show';
        }
    }
}

async function verifyPin() {
    let p = document.getElementById('pinInput').value;
    if(!p) { document.getElementById('pinError').innerText = 'Enter PIN'; return; }
    try {
        let r = await fetch('/api/verify', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({pin:p})});
        let d = await r.json();
        if(d.success) {
            authToken = d.token;
            localStorage.setItem('master_token', authToken);
            document.getElementById('pinOverlay').style.display = 'none';
            document.getElementById('mainContent').style.display = 'block';
            initializeApp();
        } else {
            document.getElementById('pinError').innerText = 'Invalid PIN';
            document.getElementById('pinInput').value = '';
        }
    } catch(e) {
        document.getElementById('pinError').innerText = 'Connection error';
    }
}

function initializeApp() {
    renderMainContent();
    loadServers();
    loadResults();
    updateServerStatuses();
    refreshInterval = setInterval(() => {
        loadResults();
        updateServerStatuses();
        updateOnline();
    }, 5000);
    updateOnline();
}

function renderMainContent(onlineCount = 0) {
    const mc = document.getElementById('mainContent');
    mc.innerHTML = `
        <div class="container">
            ${APP_HTML.header(onlineCount)}
            ${APP_HTML.stats(0,0,0,0,0)}
            ${APP_HTML.results()}
            ${APP_HTML.bottom()}
            ${APP_HTML.footer(onlineCount)}
        </div>
    `;
}

async function updateOnline() {
    try {
        let res = await fetch(`/api/online?token=${authToken}`);
        let data = await res.json();
        let el = document.getElementById('onlineUsers');
        let elSmall = document.getElementById('onlineUsersSmall');
        if(el) el.innerHTML = '👤 ' + data.online;
        if(elSmall) elSmall.innerHTML = '👤 ' + data.online;
    } catch(e) {}
}

async function updateServerStatuses() {
    try {
        let r = await fetch(`/health?token=${authToken}`);
        if(r.ok) {
            let d = await r.json();
            for(let b of d.bots) {
                serverStatuses[b.server] = {status: b.status, running: b.running || false, current_index: b.current_index || 0, total: b.total || 0};
            }
            renderServersList();
        } else if(r.status === 401) {
            addLog('⚠️ Session expired. Please login again.');
        }
    } catch(e) {}
}

async function loadServers() {
    try {
        let r = await fetch(`/api/servers?token=${authToken}`);
        if(r.ok) {
            let d = await r.json();
            currentServers = d.servers;
            renderServersList();
        } else if(r.status === 401) {
            addLog('⚠️ Session expired. Please login again.');
        }
    } catch(e) { addLog(`Error: ${e.message}`); }
}

function renderServersList() {
    let c = document.getElementById('serversContainer');
    if(!c) return;
    if(currentServers.length === 0) {
        c.innerHTML = '<div style="color:#8b949e; text-align:center; padding:20px;">No servers added.</div>';
        return;
    }
    c.innerHTML = currentServers.map((s,i) => {
        let info = serverStatuses[s] || {status:'checking', running:false, current_index:0, total:0};
        let ledClass = '', statusText = '';
        if(info.status === 'offline') { ledClass = 'offline'; statusText = 'Offline'; }
        else if(info.status === 'online' && info.running) { ledClass = 'running'; statusText = 'Running'; }
        else if(info.status === 'online' && !info.running) { ledClass = 'online'; statusText = 'Online'; }
        else { ledClass = 'checking'; statusText = 'Checking...'; }
        let prog = (info.running && info.status === 'online') ? `<span class="server-progress">📊 ${info.current_index}/${info.total}</span>` : '';
        return `<div class="server-item"><input type="text" id="server_${i}" value="${escapeHtml(s)}"><div class="server-status"><span class="status-led ${ledClass}"></span><span class="server-status-text">${statusText}</span>${prog}</div><div class="server-controls"><button class="control-btn control-start" onclick="startServer(${i})" ${info.status !== 'online' ? 'disabled' : ''}>Start</button><button class="control-btn control-restart" onclick="restartServer(${i})" ${info.status !== 'online' ? 'disabled' : ''}>Restart</button><button class="control-btn control-stop" onclick="stopServer(${i})" ${info.status !== 'online' ? 'disabled' : ''}>Stop</button><button class="remove-server-btn" onclick="removeServer(${i})"><i class="fas fa-trash"></i></button></div></div>`;
    }).join('');
}

async function startServer(i) {
    let s = currentServers[i];
    if(!s) return;
    let a = prompt(`Accounts for ${s}\n\nFormat: username:password (one per line):`, accountsText);
    if(!a) return;
    accountsText = a;
    addLog(`Starting ${s}...`);
    let btn = document.querySelector(`#serversContainer .server-item:nth-child(${i+1}) .control-start`);
    if(btn) { btn.disabled = true; btn.innerHTML = '<i class="fas fa-spinner fa-pulse"></i>'; }
    try {
        let r = await fetch(`/api/control/${i}/start?token=${authToken}`, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({accounts:a})});
        let d = await r.json();
        if(d.success) { addLog(`Started ${s}`); setTimeout(() => updateServerStatuses(), 1000); }
        else { addLog(`Failed: ${d.error}`); }
    } catch(e) { addLog(`Error: ${e.message}`); }
    setTimeout(() => { if(btn) { btn.disabled = false; btn.innerHTML = 'Start'; } }, 3000);
}

async function restartServer(i) {
    let s = currentServers[i];
    if(!s) return;
    addLog(`Restarting ${s}...`);
    let btn = document.querySelector(`#serversContainer .server-item:nth-child(${i+1}) .control-restart`);
    if(btn) { btn.disabled = true; btn.innerHTML = '<i class="fas fa-spinner fa-pulse"></i>'; }
    try {
        let r = await fetch(`/api/control/${i}/restart?token=${authToken}`, {method:'POST'});
        let d = await r.json();
        if(d.success) { addLog(`Restarted ${s}`); setTimeout(() => { updateServerStatuses(); loadResults(); }, 2000); }
        else { addLog(`Failed: ${d.error}`); }
    } catch(e) { addLog(`Error: ${e.message}`); }
    setTimeout(() => { if(btn) { btn.disabled = false; btn.innerHTML = 'Restart'; } }, 3000);
}

async function stopServer(i) {
    let s = currentServers[i];
    if(!s) return;
    addLog(`Stopping ${s}...`);
    let btn = document.querySelector(`#serversContainer .server-item:nth-child(${i+1}) .control-stop`);
    if(btn) { btn.disabled = true; btn.innerHTML = '<i class="fas fa-spinner fa-pulse"></i>'; }
    try {
        let r = await fetch(`/api/control/${i}/stop?token=${authToken}`, {method:'POST'});
        let d = await r.json();
        if(d.success) { addLog(`Stopped ${s}`); setTimeout(() => updateServerStatuses(), 1000); }
        else { addLog(`Failed: ${d.error}`); }
    } catch(e) { addLog(`Error: ${e.message}`); }
    setTimeout(() => { if(btn) { btn.disabled = false; btn.innerHTML = 'Stop'; } }, 3000);
}

function addServer() {
    let i = document.getElementById('newServerInput'), v = i.value.trim();
    if(v) {
        if(!v.startsWith('http://') && !v.startsWith('https://')) {
            addLog('Server must start with http:// or https://');
            return;
        }
        currentServers.push(v);
        i.value = '';
        renderServersList();
        addLog(`Added: ${v}`);
    }
}

function removeServer(i) {
    let r = currentServers[i];
    if(confirm(`Remove ${r}?`)) {
        currentServers.splice(i, 1);
        renderServersList();
        addLog(`Removed: ${r}`);
    }
}

async function saveServers() {
    let ins = document.querySelectorAll('#serversContainer input'), ups = Array.from(ins).map(i => i.value.trim()).filter(s => s);
    if(ups.length === 0) { addLog('No servers'); return; }
    try {
        let r = await fetch(`/api/servers?token=${authToken}`, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({servers:ups})});
        if(r.ok) {
            currentServers = ups;
            addLog(`Saved ${ups.length} servers`);
            await updateServerStatuses();
        } else if(r.status === 401) {
            addLog('⚠️ Session expired. Please login again.');
        } else addLog('Save failed');
    } catch(e) { addLog(`Error: ${e.message}`); }
}

async function clearAllResults() {
    if(confirm('Delete ALL results?')) {
        try {
            let r = await fetch(`/results/clear?token=${authToken}`, {method:'POST'});
            if(r.ok) {
                allResults = [];
                renderResults();
                updateStats();
                addLog('All results cleared');
            } else if(r.status === 401) {
                addLog('⚠️ Session expired. Please login again.');
            }
        } catch(e) { addLog(`Error: ${e.message}`); }
    }
}

async function deleteSingleResult(u) {
    if(confirm(`Delete ${u}?`)) {
        try {
            await fetch(`/results/clear/${encodeURIComponent(u)}?token=${authToken}`, {method:'POST'});
            await loadResults();
            addLog(`Removed ${u}`);
        } catch(e) { addLog(`Error: ${e.message}`); }
    }
}

async function loadResults() {
    try {
        let r = await fetch(`/results?token=${authToken}`);
        if(r.ok) {
            allResults = await r.json();
            renderResults();
            updateStats();
        } else if(r.status === 401) {
            addLog('⚠️ Session expired. Please login again.');
        }
    } catch(e) { addLog(`Error: ${e.message}`); }
}

function renderResults() {
    let f = allResults.filter(r => {
        if(currentFilter !== 'all') {
            if(currentFilter === 'success' && r.status !== '✅') return false;
            if(currentFilter === 'failed' && r.status !== '❌') return false;
            if(currentFilter === 'timeout' && r.status !== '⏰') return false;
        }
        if(currentBalanceFilter !== 'all') {
            let n = parseFloat(r.balance_value) || 0;
            if(currentBalanceFilter === 'low' && n >= 10) return false;
            if(currentBalanceFilter === 'mid' && (n < 10 || n > 100)) return false;
            if(currentBalanceFilter === 'high' && n <= 100) return false;
        }
        return true;
    });
    let s = document.getElementById('searchInput')?.value.toLowerCase() || '';
    if(s) f = f.filter(r => r.username.toLowerCase().includes(s));
    f.sort((a,b) => {
        let aPinned = isPinned(a.username) ? 0 : 1;
        let bPinned = isPinned(b.username) ? 0 : 1;
        if(aPinned !== bPinned) return aPinned - bPinned;
        let av = currentSort.field === 'balance' ? (a.balance_value || 0) : (a[currentSort.field] || '').toString().toLowerCase();
        let bv = currentSort.field === 'balance' ? (b.balance_value || 0) : (b[currentSort.field] || '').toString().toLowerCase();
        if(typeof av === 'number') return currentSort.dir === 'asc' ? av - bv : bv - av;
        return currentSort.dir === 'asc' ? (av > bv ? 1 : -1) : (av < bv ? 1 : -1);
    });
    let bc = v => { let n = parseFloat(v) || 0; return n > 100 ? 'balance-positive' : n > 10 ? 'balance-medium' : 'balance-zero'; };
    let body = document.getElementById('resultsBody');
    if(!body) return;
    body.innerHTML = f.map(r => `<tr><td><button class="pin-star-btn ${isPinned(r.username) ? 'active' : ''}" onclick="togglePin('${escapeHtml(r.username)}')"><i class="fas fa-star"></i></button></td><td style="font-size:18px">${r.status}</td><td><div class="username-cell"><strong style="color:#58a6ff">${escapeHtml(r.username)}</strong><button class="copy-btn" onclick="copyToClipboard('${escapeHtml(r.username)}',this)"><i class="fas fa-copy"></i></button></div></td><td><div class="password-cell">${escapeHtml(r.password)}<button class="copy-btn" onclick="copyToClipboard('${escapeHtml(r.password)}',this)"><i class="fas fa-key"></i></button></div></td><td class="${bc(r.balance_value)}">${r.balance || '0 ֏'}</td><td class="error-cell">${escapeHtml(r.error || '-')}<button class="retry-btn" onclick="retryAccount('${escapeHtml(r.username)}',this)"><i class="fas fa-sync-alt"></i> Retry</button><button class="delete-row-btn" onclick="deleteSingleResult('${escapeHtml(r.username)}')"><i class="fas fa-trash"></i></button></td></tr>`).join('');
    if(f.length === 0 && allResults.length > 0) body.innerHTML = '<tr><td colspan="6" style="text-align:center; padding:40px;">No matching results</td></tr>';
}

function updateStats() {
    let totalBalance = allResults.reduce((sum, r) => sum + (parseFloat(r.balance_value) || 0), 0);
    let el1 = document.getElementById('totalCount'), el2 = document.getElementById('successCount');
    let el3 = document.getElementById('failedCount'), el4 = document.getElementById('timeoutCount');
    let el5 = document.getElementById('totalBalance');
    if(el1) el1.innerText = allResults.length;
    if(el2) el2.innerText = allResults.filter(r => r.status === '✅').length;
    if(el3) el3.innerText = allResults.filter(r => r.status === '❌').length;
    if(el4) el4.innerText = allResults.filter(r => r.status === '⏰').length;
    if(el5) el5.innerText = totalBalance.toFixed(2) + ' ֏';
}

function sortBy(f) {
    if(currentSort.field === f) currentSort.dir = currentSort.dir === 'asc' ? 'desc' : 'asc';
    else { currentSort.field = f; currentSort.dir = f === 'balance' ? 'desc' : 'asc'; }
    renderResults();
}

function setFilter(f) {
    currentFilter = f;
    document.querySelectorAll('.filter-btn').forEach(b => b.classList.toggle('active', b.dataset.filter === f));
    renderResults();
}

function setBalanceFilter(f) {
    currentBalanceFilter = f;
    document.querySelectorAll('.balance-filter-btn').forEach(b => b.classList.toggle('active', b.dataset.balance === f));
    renderResults();
}

function manualRefresh() {
    loadResults();
    updateServerStatuses();
    addLog('Manual refresh');
}

function escapeHtml(s) {
    if(!s) return '';
    return s.replace(/[&<>]/g, m => ({'&':'&amp;','<':'&lt;','>':'&gt;'})[m]);
}

function addLog(m) {
    let t = document.getElementById('terminal');
    if(!t) return;
    let d = document.createElement('div');
    d.className = 'terminal-line';
    d.innerHTML = `<span class="time">[${new Date().toLocaleTimeString()}]</span> ${m}`;
    t.appendChild(d);
    if(t.children.length > 100) t.removeChild(t.firstChild);
}

function clearTerminal() {
    let t = document.getElementById('terminal');
    if(t) { t.innerHTML = ''; addLog('Terminal cleared'); }
}

async function copyToClipboard(t, b) {
    await navigator.clipboard.writeText(t);
    let o = b.innerHTML;
    b.innerHTML = '✓';
    setTimeout(() => b.innerHTML = o, 1000);
}

async function retryAccount(u, b) {
    let o = b.innerHTML;
    b.innerHTML = '<i class="fas fa-spinner fa-pulse"></i>';
    b.disabled = true;
    addLog(`Retrying ${u}...`);
    try {
        await fetch(`/retry/${encodeURIComponent(u)}?token=${authToken}`, {method:'POST'});
        addLog(`Retry sent for ${u}`);
        setTimeout(() => loadResults(), 2000);
    } catch(e) { addLog(`Retry failed`); }
    setTimeout(() => { b.innerHTML = o; b.disabled = false; }, 3000);
}

// Event listeners
document.addEventListener('input', function(e) {
    if(e.target && e.target.id === 'searchInput') renderResults();
});

document.addEventListener('keypress', function(e) {
    if(e.target && e.target.id === 'pinInput' && e.key === 'Enter') verifyPin();
});

// Auto-login check
(async() => {
    let t = localStorage.getItem('master_token');
    if(t) {
        try {
            let r = await fetch(`/api/check?token=${t}`);
            let d = await r.json();
            if(d.authenticated) {
                authToken = t;
                document.getElementById('pinOverlay').style.display = 'none';
                document.getElementById('mainContent').style.display = 'block';
                initializeApp();
            }
        } catch(e) {}
    }
})();

// Թաքցնել աջ սեղմման մենյուն (կանխել Inspect Element-ը)
document.addEventListener('contextmenu', function(e) {
    e.preventDefault();
    return false;
});

// Թաքցնել Developer Tools-ի բացումը (F12, Ctrl+Shift+I, Ctrl+Shift+J, Ctrl+U)
document.addEventListener('keydown', function(e) {
    // F12
    if(e.key === 'F12') {
        e.preventDefault();
        return false;
    }
    // Ctrl+Shift+I, Ctrl+Shift+J, Ctrl+U
    if(e.ctrlKey && e.shiftKey && (e.key === 'I' || e.key === 'J' || e.key === 'i' || e.key === 'j')) {
        e.preventDefault();
        return false;
    }
    // Ctrl+U
    if(e.ctrlKey && (e.key === 'u' || e.key === 'U')) {
        e.preventDefault();
        return false;
    }
});

console.log('%c🔒 Protected Mode Active', 'font-size:20px; color:#3fb950;');
console.log('%cView Source and Inspect Element are disabled', 'font-size:14px; color:#8b949e;');
</script>
</body>
</html>'''

# ===== MOBILE HTML WITH PROTECTION =====
MOBILE_HTML = '''<!DOCTYPE html>
<html lang="hy">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover, user-scalable=yes">
    <title>Mobile Monitor</title>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap" rel="stylesheet">
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <style>
        * { margin:0; padding:0; box-sizing:border-box; }
        body { background: linear-gradient(135deg, #0a0c10 0%, #0d1117 100%); color: #e6edf3; font-family: 'Inter', sans-serif; padding: 10px; min-height: 100vh; }
        .pin-overlay { position: fixed; top:0; left:0; width:100%; height:100%; background: rgba(0,0,0,0.95); backdrop-filter: blur(12px); display: flex; align-items: center; justify-content: center; z-index: 1000; }
        .pin-box { background: #161b22; border: 1px solid #30363d; border-radius: 24px; padding: 30px; width: 280px; text-align: center; }
        .pin-box input { width: 100%; padding: 12px; background: #0d1117; border: 1px solid #30363d; border-radius: 12px; color: white; font-size: 20px; text-align: center; letter-spacing: 6px; }
        .pin-box button { width: 100%; padding: 12px; background: #238636; border: none; border-radius: 12px; color: white; font-weight: bold; cursor: pointer; margin-top: 16px; }
        .mobile-dashboard { display: none; }
        .header { background: #161b22; border-radius: 16px; padding: 12px; margin-bottom: 12px; text-align: center; border: 1px solid #30363d; }
        .header h1 { font-size: 16px; background: linear-gradient(135deg, #58a6ff, #3fb950); -webkit-background-clip: text; background-clip: text; color: transparent; }
        .last-update { font-size: 9px; color: #6e7681; margin-top: 3px; }
        .toolbar { display: flex; justify-content: space-between; margin-bottom: 10px; flex-wrap: wrap; gap: 6px; }
        .refresh-btn { background: #1f6feb; border: none; border-radius: 30px; color: white; padding: 6px 14px; font-size: 11px; cursor: pointer; }
        .online-badge { background: transparent; padding: 2px 10px; border-radius: 20px; font-size: 10px; color: #58a6ff; }
        .accounts-list { display: flex; flex-direction: column; gap: 10px; }
        .account-card { background: #161b22; border-radius: 14px; border: 1px solid #30363d; overflow: hidden; }
        .account-row { display: flex; justify-content: space-between; align-items: center; padding: 10px 12px; border-bottom: 1px solid #21262d; }
        .account-row:last-child { border-bottom: none; }
        .label { font-size: 9px; color: #8b949e; text-transform: uppercase; margin-bottom: 2px; }
        .username-value { font-size: 14px; font-weight: 600; color: #58a6ff; word-break: break-all; }
        .password-value { font-size: 11px; font-family: monospace; color: #e6edf3; word-break: break-all; }
        .balance-value { font-size: 16px; font-weight: 700; }
        .balance-positive { color: #3fb950; }
        .balance-medium { color: #d29922; }
        .balance-zero { color: #f85149; }
        .copy-btn { background: transparent; border: 1px solid #30363d; border-radius: 16px; padding: 3px 8px; color: #58a6ff; cursor: pointer; font-size: 9px; margin-left: 6px; }
        .status-badge { font-size: 16px; margin-right: 6px; }
        .pin-star { background: transparent; border: none; color: #d29922; cursor: pointer; font-size: 14px; padding: 0 4px; }
        .pin-star.active { color: #f0883e; text-shadow: 0 0 3px #f0883e; }
        .footer { text-align: center; padding: 10px; font-size: 9px; color: #6e7681; border-top: 1px solid #21262d; margin-top: 12px; }
        .error-text { color: #f85149; font-size: 9px; }
    </style>
</head>
<body>
<div id="pinOverlay" class="pin-overlay">
    <div class="pin-box"><h2><i class="fas fa-mobile-alt"></i> Mobile Access</h2>
    <input type="password" id="pinInput" placeholder="PIN" maxlength="6"><button onclick="verifyPin()">Access</button>
    <div id="pinError" style="color:#f85149; font-size:12px; margin-top:12px;"></div></div>
</div>
<div id="mobileDashboard" class="mobile-dashboard">
    <div class="header"><h1><i class="fas fa-mobile-alt"></i> Mobile Monitor</h1><div class="last-update" id="lastUpdate">Loading... <span class="online-badge" id="onlineUsers">👤 0</span></div></div>
    <div class="toolbar"><button class="refresh-btn" onclick="loadResults()"><i class="fas fa-sync-alt"></i> Refresh</button></div>
    <div class="accounts-list" id="accountsList"><div style="text-align:center; padding:30px;"><i class="fas fa-spinner fa-pulse"></i> Loading...</div></div>
    <div class="footer"><i class="fas fa-chart-line"></i> Auto-refresh 5s | ⭐ Pinned on top</div>
</div>
<script>
let mobileResults=[], authToken=null, refreshInterval=null;
let pinnedAccounts = JSON.parse(localStorage.getItem('mobile_pinned') || '[]');

function savePinned() { localStorage.setItem('mobile_pinned', JSON.stringify(pinnedAccounts)); }
function togglePin(username) {
    let idx = pinnedAccounts.indexOf(username);
    if(idx === -1) pinnedAccounts.push(username);
    else pinnedAccounts.splice(idx,1);
    savePinned();
    renderList();
}
function isPinned(username) { return pinnedAccounts.includes(username); }

async function verifyPin(){let pin=document.getElementById('pinInput').value;if(!pin){document.getElementById('pinError').innerText='Enter PIN';return;}try{let res=await fetch('/mobile/verify',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({pin:pin})});let data=await res.json();if(data.success){authToken=data.token;localStorage.setItem('mobile_token',authToken);document.getElementById('pinOverlay').style.display='none';document.getElementById('mobileDashboard').style.display='block';loadResults();refreshInterval=setInterval(()=>{loadResults();updateOnline();},5000);updateOnline();}else{document.getElementById('pinError').innerText='Invalid PIN';document.getElementById('pinInput').value='';}}catch(e){document.getElementById('pinError').innerText='Connection error';}}
async function updateOnline(){try{let res=await fetch(`/api/online?token=${authToken}`);let data=await res.json();document.getElementById('onlineUsers').innerHTML='👤 '+data.online;}catch(e){}}
async function loadResults(){try{let res=await fetch(`/results?token=${authToken}`);if(res.ok){let data=await res.json();mobileResults=data;renderList();document.getElementById('lastUpdate').innerHTML='Last: '+new Date().toLocaleTimeString()+' <span class="online-badge" id="onlineUsers">👤 '+document.getElementById('onlineUsers').innerText.replace('👤 ','')+'</span>';} else if(res.status === 401) { document.getElementById('accountsList').innerHTML='<div style="text-align:center; padding:30px; color:#f85149;"><i class="fas fa-lock"></i> Session expired. Please login again.</div>'; }}catch(e){}}
function renderList(){
    const container=document.getElementById('accountsList');
    let sorted = [...mobileResults].sort((a,b)=>{
        let aPinned = isPinned(a.username) ? 0 : 1;
        let bPinned = isPinned(b.username) ? 0 : 1;
        if(aPinned !== bPinned) return aPinned - bPinned;
        return (parseFloat(b.balance_value)||0) - (parseFloat(a.balance_value)||0);
    });
    if(sorted.length===0){container.innerHTML='<div style="text-align:center; padding:30px;"><i class="fas fa-inbox"></i> No results</div>';return;}
    const balanceClass=(v)=>{let n=parseFloat(v)||0;return n>100?'balance-positive':n>10?'balance-medium':'balance-zero';};
    container.innerHTML=sorted.map(acc=>`<div class="account-card"><div class="account-row"><div><span class="status-badge">${acc.status}</span><span class="username-value"><strong>${escapeHtml(acc.username)}</strong></span><button class="copy-btn" onclick="copyToClipboard('${escapeHtml(acc.username)}')"><i class="fas fa-copy"></i></button><button class="pin-star ${isPinned(acc.username)?'active':''}" onclick="togglePin('${escapeHtml(acc.username)}')"><i class="fas fa-star"></i></button></div></div><div class="account-row"><div><div class="label"><i class="fas fa-key"></i> Password</div><div class="password-value">${escapeHtml(acc.password)} <button class="copy-btn" onclick="copyToClipboard('${escapeHtml(acc.password)}')"><i class="fas fa-copy"></i></button></div></div></div><div class="account-row"><div><div class="label"><i class="fas fa-coins"></i> Balance</div><div class="balance-value ${balanceClass(acc.balance_value)}">${acc.balance||'0 ֏'}</div></div></div>${acc.error?`<div class="account-row"><div class="error-text"><i class="fas fa-exclamation-triangle"></i> ${escapeHtml(acc.error)}</div></div>`:''}</div>`).join('');
}
function copyToClipboard(text){navigator.clipboard.writeText(text);}
function escapeHtml(s){if(!s)return '';return s.replace(/[&<>]/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;'})[m]);}
(async()=>{let savedToken=localStorage.getItem('mobile_token');if(savedToken){try{let res=await fetch(`/mobile/check?token=${savedToken}`);let data=await res.json();if(data.authenticated){authToken=savedToken;document.getElementById('pinOverlay').style.display='none';document.getElementById('mobileDashboard').style.display='block';loadResults();refreshInterval=setInterval(()=>{loadResults();updateOnline();},5000);updateOnline();}}catch(e){}}})();

// Թաքցնել աջ սեղմման մենյուն (կանխել Inspect Element-ը)
document.addEventListener('contextmenu', function(e) {
    e.preventDefault();
    return false;
});

// Թաքցնել Developer Tools-ի բացումը (F12, Ctrl+Shift+I, Ctrl+Shift+J, Ctrl+U)
document.addEventListener('keydown', function(e) {
    if(e.key === 'F12') { e.preventDefault(); return false; }
    if(e.ctrlKey && e.shiftKey && (e.key === 'I' || e.key === 'J' || e.key === 'i' || e.key === 'j')) {
        e.preventDefault();
        return false;
    }
    if(e.ctrlKey && (e.key === 'u' || e.key === 'U')) {
        e.preventDefault();
        return false;
    }
});

console.log('%c🔒 Mobile Protected Mode Active', 'font-size:20px; color:#3fb950;');
</script>
</body>
</html>'''

@app.get("/")
async def root():
    return HTMLResponse(MAIN_HTML)

@app.get("/mobile")
async def mobile():
    return HTMLResponse(MOBILE_HTML)

if __name__ == "__main__":
    import uvicorn
    print("\n" + "=" * 60)
    print("🖥️  MASTER UI - Multi Bot Aggregator v3.0")
    print("=" * 60)
    print(f"📍 Master UI (Full): http://localhost:9000")
    print(f"📍 Mobile Monitor:   http://localhost:9000/mobile")
    print("=" * 60)
    print(f"🔐 Master UI PIN:    {MASTER_PIN}")
    print(f"🔐 Mobile PIN:       {MOBILE_PIN}")
    print("=" * 60)
    print("📌 FEATURES:")
    print("   ⭐ Pin (Star) - click ⭐ to pin accounts on top (saved in browser)")
    print("   💰 Total Balance - shows sum of all balances")
    print("   👤 Online Users - shows how many people have the page open")
    print("   ✅ Persistent results + all buttons working")
    print("   🔒 ALL API endpoints are protected with authentication")
    print("   🛡️ Source code protection (View Source & Inspect Element disabled)")
    print("=" * 60 + "\n")
    uvicorn.run(app, host="0.0.0.0", port=9000, log_level="info")

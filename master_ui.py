# ================= MASTER UI V3.5 - FIXED PROGRESS =================
import os
import httpx
import asyncio
from fastapi import FastAPI, Request, HTTPException, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from typing import List, Dict, Optional
import json
from pathlib import Path
from datetime import datetime, timedelta
import secrets
import base64
from cryptography.fernet import Fernet
from dotenv import load_dotenv
load_dotenv()

# ================= ENCRYPTION SETUP =================
ENCRYPTION_KEY = os.getenv("ENCRYPTION_KEY")
if not ENCRYPTION_KEY:
    ENCRYPTION_KEY = base64.urlsafe_b64encode(os.urandom(32)).decode()
    print(f"⚠️ Generated ENCRYPTION_KEY: {ENCRYPTION_KEY}")

cipher_suite = Fernet(ENCRYPTION_KEY.encode())

def decrypt_data(encrypted: str) -> any:
    try:
        decrypted = cipher_suite.decrypt(encrypted.encode()).decode()
        try:
            return json.loads(decrypted)
        except:
            return decrypted
    except Exception:
        return None

# ================= BOT AUTH =================
BOT_AUTH_USERNAME = os.getenv("BOT_AUTH_USERNAME", "Pentagon999")
BOT_AUTH_PASSWORD = os.getenv("BOT_AUTH_PASSWORD", "King2002")

# ================= PINS =================
MASTER_PIN = os.getenv("MASTER_PIN", "285925")
MOBILE_PIN = os.getenv("MOBILE_PIN", "185659")
LIVE_ADMIN_PIN = os.getenv("LIVE_ADMIN_PIN", "123456")

# ================= SESSIONS =================
sessions = {}
mobile_sessions = {}
live_admin_sessions = {}

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

def create_live_admin_session() -> str:
    token = secrets.token_urlsafe(32)
    live_admin_sessions[token] = datetime.now() + timedelta(hours=24)
    return token

def verify_live_admin_session(token: str) -> bool:
    if token not in live_admin_sessions:
        return False
    if live_admin_sessions[token] < datetime.now():
        del live_admin_sessions[token]
        return False
    return True

# ================= ONLINE USERS (MAX 2) =================
online_users = {}
last_activity = {}
MAX_ONLINE_USERS = 2

def update_user_activity(token: str):
    if token:
        online_users[token] = datetime.now()
        last_activity[token] = datetime.now()
    if len(online_users) > MAX_ONLINE_USERS:
        sorted_users = sorted(online_users.items(), key=lambda x: x[1])
        for token, _ in sorted_users[:len(online_users) - MAX_ONLINE_USERS]:
            if token in online_users:
                del online_users[token]
            if token in last_activity:
                del last_activity[token]

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
    return min(len(online_users), MAX_ONLINE_USERS)

# ================= AUTH DEPENDENCIES =================
async def get_current_user(token: Optional[str] = None) -> str:
    if not token:
        raise HTTPException(status_code=401, detail="Missing authentication token")
    if not verify_session(token):
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    update_user_activity(token)
    return token

async def get_mobile_user(token: Optional[str] = None) -> str:
    if not token:
        raise HTTPException(status_code=401, detail="Missing authentication token")
    if not verify_mobile_session(token):
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    update_user_activity(token)
    return token

async def get_any_user(token: Optional[str] = None) -> str:
    if not token:
        raise HTTPException(status_code=401, detail="Missing authentication token")
    if verify_session(token) or verify_mobile_session(token):
        update_user_activity(token)
        return token
    raise HTTPException(status_code=401, detail="Invalid or expired token")

async def get_live_admin_user(token: Optional[str] = None) -> str:
    if not token:
        raise HTTPException(status_code=401, detail="Missing authentication token")
    if not verify_live_admin_session(token):
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    update_user_activity(token)
    return token

# ================= SERVERS =================
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
        try:
            with open(CACHED_RESULTS_FILE, "r") as f:
                return json.load(f)
        except:
            return {}
    return {}

def save_cached_results(results: Dict[str, Dict]):
    for k, v in results.items():
        if "balance_value" not in v or not isinstance(v["balance_value"], (int, float)):
            v["balance_value"] = 0.0
    try:
        with open(CACHED_RESULTS_FILE, "w") as f:
            json.dump(results, f, indent=2)
    except:
        pass

BOT_SERVERS = load_servers()

app = FastAPI(title="Master UI - Fixed Progress")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# ================= CACHE =================
cached_results: Dict[str, Dict] = load_cached_results()
last_fetch_time = 0
fetch_lock = asyncio.Lock()
CACHE_TTL = 3

async def fetch_and_merge_results(use_encrypted: bool = True) -> List[Dict]:
    global cached_results, last_fetch_time
    
    async with fetch_lock:
        now = time.time()
        if now - last_fetch_time < CACHE_TTL and cached_results:
            return list(cached_results.values())
        
        limits = httpx.Limits(max_keepalive_connections=10, max_connections=20)
        async with httpx.AsyncClient(timeout=10, limits=limits) as client:
            tasks = []
            for server in BOT_SERVERS:
                tasks.append(fetch_from_server(client, server, use_encrypted))
            
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            for result in results:
                if result and isinstance(result, list):
                    for account in result:
                        username = account.get("username")
                        if username:
                            balance_val = account.get("balance_value", 0.0)
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
        
        last_fetch_time = time.time()
        save_cached_results(cached_results)
        return list(cached_results.values())

async def fetch_from_server(client, server: str, use_encrypted: bool) -> Optional[List[Dict]]:
    try:
        if use_encrypted:
            try:
                auth = httpx.BasicAuth(BOT_AUTH_USERNAME, BOT_AUTH_PASSWORD)
                res = await client.get(
                    f"{server}/results/encrypted",
                    auth=auth,
                    timeout=8
                )
                if res.status_code == 200:
                    data = res.json()
                    encrypted_data = data.get("data")
                    if encrypted_data:
                        decrypted_data = decrypt_data(encrypted_data)
                        if decrypted_data and isinstance(decrypted_data, list):
                            return decrypted_data
            except:
                pass
        
        res = await client.get(f"{server}/results", timeout=8)
        if res.status_code == 200:
            return res.json()
    except:
        pass
    return None

# ================= PROTECTED API ENDPOINTS =================

@app.get("/results")
async def get_merged_results(token: str = Depends(get_any_user)):
    return await fetch_and_merge_results(use_encrypted=True)

@app.get("/results/public")
async def get_public_results():
    results = await fetch_and_merge_results(use_encrypted=True)
    filtered = []
    for account in results:
        filtered.append({
            "username": account.get("username", ""),
            "balance": account.get("balance", "0 ֏"),
            "balance_value": account.get("balance_value", 0.0),
            "status": account.get("status", "❌")
        })
    return filtered

@app.post("/results/clear")
async def clear_all_results(token: str = Depends(get_current_user)):
    global cached_results
    cached_results = {}
    save_cached_results({})
    return {"success": True}

@app.post("/results/clear/{username}")
async def clear_single_result(username: str, token: str = Depends(get_current_user)):
    global cached_results
    if username in cached_results:
        del cached_results[username]
        save_cached_results(cached_results)
        return {"success": True}
    return {"success": False}

@app.get("/health")
async def health(token: str = Depends(get_any_user)):
    statuses = []
    async with httpx.AsyncClient(timeout=5) as client:
        for server in BOT_SERVERS:
            try:
                res = await client.get(f"{server}/health", timeout=3)
                if res.status_code == 200:
                    data = res.json()
                    is_running = data.get("processed", 0) > 0 and data.get("total", 0) > 0
                    statuses.append({
                        "server": server, 
                        "status": "online",
                        "running": is_running,
                        "processed": data.get("processed", 0),  # current_index -> processed
                        "total": data.get("total", 0),
                        "encryption": data.get("encryption", "enabled")
                    })
                else:
                    statuses.append({"server": server, "status": "unhealthy", "running": False})
            except:
                statuses.append({"server": server, "status": "offline", "running": False})
    return {"bots": statuses}

@app.post("/retry/{username}")
async def retry_account(username: str, token: str = Depends(get_any_user)):
    for server in BOT_SERVERS:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                auth = httpx.BasicAuth(BOT_AUTH_USERNAME, BOT_AUTH_PASSWORD)
                await client.post(f"{server}/retry/{username}", auth=auth)
        except:
            pass
    return {"status": "retry_sent"}

@app.post("/api/control/{server_id}/start")
async def control_start(server_id: int, request: Request, token: str = Depends(get_current_user)):
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
            return {"success": False, "error": "No accounts provided"}
    
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            res = await client.post(f"{server}/start", content=accounts_text)
            if res.status_code == 200:
                return {"success": True, "message": f"Started {server}"}
            return {"success": False, "error": f"Status {res.status_code}"}
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.post("/api/control/{server_id}/restart")
async def control_restart(server_id: int, token: str = Depends(get_current_user)):
    if server_id >= len(BOT_SERVERS):
        return {"success": False, "error": "Server not found"}
    
    server = BOT_SERVERS[server_id]
    saved_accounts = load_saved_accounts(server)
    
    if not saved_accounts:
        return {"success": False, "error": "No saved accounts"}
    
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            await client.post(f"{server}/stop")
            await asyncio.sleep(0.5)
            await client.post(f"{server}/reset")
            await asyncio.sleep(0.5)
            res = await client.post(f"{server}/start", content=saved_accounts)
            if res.status_code == 200:
                return {"success": True, "message": f"Restarted {server}"}
            return {"success": False, "error": f"Status {res.status_code}"}
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.post("/api/control/{server_id}/stop")
async def control_stop(server_id: int, token: str = Depends(get_current_user)):
    if server_id >= len(BOT_SERVERS):
        return {"success": False, "error": "Server not found"}
    
    server = BOT_SERVERS[server_id]
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            res = await client.post(f"{server}/stop")
            if res.status_code == 200:
                return {"success": True, "message": f"Stopped {server}"}
            return {"success": False, "error": f"Status {res.status_code}"}
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.get("/api/servers")
async def get_servers(token: str = Depends(get_current_user)):
    return {"servers": BOT_SERVERS}

@app.post("/api/servers")
async def update_servers(request: Request, token: str = Depends(get_current_user)):
    global BOT_SERVERS
    data = await request.json()
    servers = data.get("servers", [])
    if servers:
        BOT_SERVERS = servers
        save_servers(servers)
    return {"success": True, "servers": BOT_SERVERS}

@app.get("/api/online")
async def get_online_count_endpoint(token: Optional[str] = None):
    if token:
        update_user_activity(token)
    return {"online": get_online_count()}

# ================= AUTH ENDPOINTS =================

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

@app.post("/mobile/verify")
async def verify_mobile_pin(request: Request):
    data = await request.json()
    pin = data.get("pin", "")
    if pin == MOBILE_PIN:
        token = create_mobile_session()
        return {"success": True, "token": token}
    return {"success": False}

@app.get("/mobile/check")
async def check_mobile_session(token: str = None):
    if token and verify_mobile_session(token):
        return {"authenticated": True}
    return {"authenticated": False}

@app.post("/live/verify")
async def verify_live_admin_pin(request: Request):
    data = await request.json()
    pin = data.get("pin", "")
    if pin == LIVE_ADMIN_PIN:
        token = create_live_admin_session()
        return {"success": True, "token": token}
    return {"success": False}

@app.get("/live/check")
async def check_live_admin_session(token: str = None):
    if token and verify_live_admin_session(token):
        return {"authenticated": True}
    return {"authenticated": False}

# ================= HTML PAGES =================

# ===== MAIN HTML (with fixed JavaScript) =====
MAIN_HTML = '''<!DOCTYPE html>
<html lang="hy">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Master UI v3.5</title>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap" rel="stylesheet">
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <style>
        *{margin:0;padding:0;box-sizing:border-box}
        body{background:#0a0c10;color:#e6edf3;font-family:'Inter',sans-serif;min-height:100vh}
        .pin-overlay{position:fixed;inset:0;background:rgba(0,0,0,0.95);backdrop-filter:blur(12px);display:flex;align-items:center;justify-content:center;z-index:1000}
        .pin-box{background:#161b22;border:1px solid #30363d;border-radius:24px;padding:40px;width:320px;text-align:center}
        .pin-box h2{margin-bottom:24px;background:linear-gradient(135deg,#58a6ff,#3fb950);-webkit-background-clip:text;background-clip:text;color:transparent}
        .pin-box input{width:100%;padding:12px;background:#0d1117;border:1px solid #30363d;border-radius:12px;color:#fff;font-size:18px;text-align:center;letter-spacing:6px}
        .pin-box button{width:100%;padding:12px;background:linear-gradient(135deg,#238636,#2ea043);border:none;border-radius:12px;color:#fff;font-weight:bold;cursor:pointer;margin-top:16px}
        .pin-error{color:#f85149;font-size:12px;margin-top:12px}
        .main-content{display:none}
        .container{max-width:1600px;margin:0 auto;padding:20px}
        .header{background:linear-gradient(135deg,rgba(22,27,34,0.95),rgba(13,17,23,0.95));border-radius:20px;padding:14px 24px;margin-bottom:20px;border:1px solid rgba(48,54,61,0.5);text-align:center}
        .header h1{font-size:24px;font-weight:700;background:linear-gradient(135deg,#58a6ff,#3fb950,#f0883e);-webkit-background-clip:text;background-clip:text;color:transparent}
        .header-sub{font-size:12px;color:#8b949e;margin-top:4px}
        .online-badge{background:transparent;padding:2px 12px;border-radius:20px;font-size:12px;color:#58a6ff;border:1px solid #30363d}
        .live-admin-link{background:transparent;border:1px solid #30363d;border-radius:20px;padding:3px 12px;color:#58a6ff;cursor:pointer;font-size:11px;margin-left:8px;text-decoration:none;display:inline-block}
        .live-admin-link:hover{background:#30363d;border-color:#58a6ff}
        .stats-top{display:grid;grid-template-columns:repeat(5,1fr);gap:12px;margin-bottom:20px}
        .stat-card{background:#161b22;border-radius:14px;padding:10px 12px;text-align:center;cursor:pointer;border:1px solid #30363d;transition:all 0.2s}
        .stat-card:hover{border-color:#58a6ff;background:#1a1f2e;transform:translateY(-2px)}
        .stat-number{font-size:22px;font-weight:700;color:#58a6ff}
        .stat-number.balance-total{color:#f0883e}
        .stat-label{font-size:10px;color:#8b949e;margin-top:3px}
        .results-section{background:#161b22;border-radius:20px;border:1px solid #30363d;overflow:hidden;margin-bottom:20px}
        .section-header{padding:14px 20px;background:#0d1117;border-bottom:1px solid #30363d;font-weight:600;font-size:15px;display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px}
        .clear-all-btn{background:#da3633;border:none;border-radius:30px;padding:5px 12px;color:#fff;cursor:pointer;font-size:11px}
        .clear-all-btn:hover{background:#f85149}
        .filter-bar{display:flex;gap:10px;padding:12px 20px;background:#0d1117;border-bottom:1px solid #21262d;flex-wrap:wrap;align-items:center}
        .search-input{padding:6px 14px;background:#010409;border:1px solid #30363d;border-radius:30px;color:#fff;width:220px;font-size:12px}
        .filter-btn{padding:5px 14px;background:#21262d;border:none;border-radius:30px;color:#8b949e;cursor:pointer;font-size:11px;transition:all 0.2s}
        .filter-btn.active{background:#58a6ff;color:#fff}
        .balance-filter{display:flex;gap:6px;margin-left:auto}
        .balance-filter-btn{padding:4px 10px;background:#21262d;border:none;border-radius:30px;color:#8b949e;cursor:pointer;font-size:10px}
        .balance-filter-btn.active{background:#3fb950;color:#fff}
        .refresh-btn{padding:5px 14px;background:#1f6feb;border:none;border-radius:30px;color:#fff;cursor:pointer;font-size:11px}
        .refresh-btn:hover{background:#388bfd}
        .table-container{max-height:520px;overflow-y:auto}
        .table-container::-webkit-scrollbar{width:6px}
        .table-container::-webkit-scrollbar-track{background:#161b22}
        .table-container::-webkit-scrollbar-thumb{background:#30363d;border-radius:3px}
        .table-container::-webkit-scrollbar-thumb:hover{background:#58a6ff}
        table{width:100%;border-collapse:collapse}
        th{background:#0d1117;padding:12px 14px;text-align:left;font-size:12px;font-weight:600;color:#8b949e;cursor:pointer;position:sticky;top:0;border-bottom:1px solid #30363d}
        th:hover{color:#58a6ff}
        td{padding:10px 14px;font-size:12px;border-bottom:1px solid #21262d}
        tr:hover{background:#1a1f2e}
        .balance-positive{color:#3fb950;font-weight:600}
        .balance-medium{color:#d29922;font-weight:600}
        .balance-zero{color:#f85149}
        .copy-btn,.retry-btn,.delete-row-btn,.pin-star-btn{background:transparent;border:none;cursor:pointer;font-size:11px;padding:3px 8px;border-radius:6px;transition:all 0.2s}
        .copy-btn{color:#58a6ff}
        .copy-btn:hover{background:#30363d;color:#3fb950}
        .retry-btn{color:#d29922}
        .retry-btn:hover{background:#30363d;color:#f0883e}
        .delete-row-btn{color:#f85149}
        .delete-row-btn:hover{background:#30363d;color:#ff6b6b}
        .pin-star-btn{color:#d29922;font-size:14px}
        .pin-star-btn.active{color:#3fb950;text-shadow:0 0 3px #3fb950}
        .username-cell,.password-cell{display:flex;align-items:center;justify-content:space-between;gap:6px;flex-wrap:wrap}
        .error-cell{display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:6px}
        .bottom-grid{display:grid;grid-template-columns:1fr 1fr;gap:20px}
        .card{background:#161b22;border-radius:20px;border:1px solid #30363d;overflow:hidden}
        .card-header{padding:12px 18px;background:#0d1117;border-bottom:1px solid #30363d;font-weight:600;font-size:13px}
        .card-header i{color:#58a6ff;margin-right:6px}
        .terminal-header{display:flex;justify-content:space-between;align-items:center;padding:12px 18px;background:#0d1117;border-bottom:1px solid #30363d}
        .toggle-terminal-btn{background:#21262d;border:none;border-radius:20px;color:#8b949e;cursor:pointer;padding:4px 12px;font-size:10px}
        .terminal{background:#010409;height:280px;overflow-y:auto;padding:10px;font-family:monospace;font-size:10px;transition:all 0.3s}
        .terminal.hidden{display:none}
        .terminal-line{padding:4px 0;color:#b1bac4;border-bottom:1px solid #1a1f2e}
        .terminal-line .time{color:#58a6ff;margin-right:10px}
        .servers-list{padding:14px;background:#0d1117;margin:10px;border-radius:10px}
        .server-item{display:flex;gap:8px;margin-bottom:10px;align-items:center;flex-wrap:wrap;background:#010409;padding:8px 10px;border-radius:10px}
        .server-item input{flex:2;min-width:180px;padding:8px 10px;background:#0d1117;border:1px solid #30363d;border-radius:8px;color:#fff;font-size:12px}
        .server-status{display:inline-flex;align-items:center;gap:8px;margin-left:5px}
        .status-led{width:10px;height:10px;border-radius:50%;display:inline-block}
        .status-led.online{background:#3fb950;box-shadow:0 0 5px #3fb950}
        .status-led.running{background:#58a6ff;box-shadow:0 0 5px #58a6ff;animation:pulse 1s infinite}
        .status-led.offline{background:#f85149;box-shadow:0 0 5px #f85149}
        .status-led.checking{background:#d29922;box-shadow:0 0 5px #d29922;animation:pulse 1s infinite}
        @keyframes pulse{0%{opacity:0.5}50%{opacity:1}100%{opacity:0.5}}
        .server-controls{display:flex;gap:6px;margin-left:auto;flex-wrap:wrap}
        .control-btn{padding:5px 12px;border:none;border-radius:6px;cursor:pointer;font-size:10px;font-weight:500}
        .control-start{background:#238636;color:#fff}
        .control-restart{background:#d29922;color:#0a0c10}
        .control-stop{background:#da3633;color:#fff}
        .remove-server-btn{background:#da3633;border:none;border-radius:6px;color:#fff;cursor:pointer;padding:5px 8px}
        .add-server-btn{background:#238636;border:none;border-radius:8px;color:#fff;cursor:pointer;padding:6px 12px}
        .button-group{padding:14px;display:flex;gap:8px;flex-wrap:wrap;border-top:1px solid #21262d}
        .btn{padding:6px 16px;border:none;border-radius:8px;font-weight:600;cursor:pointer;font-size:12px}
        .btn-primary{background:linear-gradient(135deg,#238636,#2ea043);color:#fff}
        .btn-secondary{background:#6e7681;color:#fff}
        .btn-danger{background:#da3633;color:#fff}
        .auto-refresh{position:fixed;bottom:20px;right:20px;background:#161b22;padding:6px 12px;border-radius:20px;font-size:10px;border:1px solid #30363d;z-index:100}
        @media(max-width:900px){.bottom-grid{grid-template-columns:1fr}.balance-filter{margin-left:0;margin-top:8px}.filter-bar{flex-direction:column;align-items:stretch}.search-input{width:100%}.server-item{flex-direction:column;align-items:stretch}.server-controls{margin-left:0;margin-top:8px;justify-content:flex-end}}
    </style>
</head>
<body>
<div id="pinOverlay" class="pin-overlay"><div class="pin-box"><h2><i class="fas fa-lock"></i> Master Access</h2>
<input type="password" id="pinInput" placeholder="PIN" maxlength="6" autofocus>
<button onclick="verifyPin()"><i class="fas fa-unlock-alt"></i> Access</button>
<div id="pinError" class="pin-error"></div></div></div>
<div id="mainContent" class="main-content"><div class="container">
<div class="header"><h1><i class="fas fa-network-wired"></i> MASTER UI v3.5 <span class="online-badge" id="onlineUsers">👤 0</span></h1>
<div class="header-sub">🔐 Encrypted | ⭐ Pinned on top <a href="/live_administrator" target="_blank" class="live-admin-link"><i class="fas fa-eye"></i> Live Admin</a></div></div>
<div class="stats-top"><div class="stat-card" onclick="setFilter('all')"><div class="stat-number" id="totalCount">0</div><div class="stat-label">TOTAL</div></div>
<div class="stat-card" onclick="setFilter('success')"><div class="stat-number" id="successCount">0</div><div class="stat-label">✅ SUCCESS</div></div>
<div class="stat-card" onclick="setFilter('failed')"><div class="stat-number" id="failedCount">0</div><div class="stat-label">❌ FAILED</div></div>
<div class="stat-card" onclick="setFilter('timeout')"><div class="stat-number" id="timeoutCount">0</div><div class="stat-label">⏰ TIMEOUT</div></div>
<div class="stat-card"><div class="stat-number balance-total" id="totalBalance">0</div><div class="stat-label">💰 TOTAL BALANCE</div></div></div>
<div class="results-section"><div class="section-header"><span><i class="fas fa-chart-line"></i> Results <span style="font-size:10px;color:#3fb950;">🔐 Encrypted</span></span><button class="clear-all-btn" onclick="clearAllResults()"><i class="fas fa-trash-alt"></i> Clear All</button></div>
<div class="filter-bar"><input type="text" id="searchInput" class="search-input" placeholder="🔍 Search..."><button class="filter-btn active" data-filter="all" onclick="setFilter('all')">All</button><button class="filter-btn" data-filter="success" onclick="setFilter('success')">✅</button><button class="filter-btn" data-filter="failed" onclick="setFilter('failed')">❌</button><button class="filter-btn" data-filter="timeout" onclick="setFilter('timeout')">⏰</button><button class="refresh-btn" onclick="manualRefresh()"><i class="fas fa-sync-alt"></i> Refresh</button><div class="balance-filter"><span>💰</span><button class="balance-filter-btn active" data-balance="all" onclick="setBalanceFilter('all')">All</button><button class="balance-filter-btn" data-balance="low" onclick="setBalanceFilter('low')">&lt;10</button><button class="balance-filter-btn" data-balance="mid" onclick="setBalanceFilter('mid')">10-100</button><button class="balance-filter-btn" data-balance="high" onclick="setBalanceFilter('high')">100+</button></div></div>
<div class="table-container"><table><thead><tr><th>⭐</th><th onclick="sortBy('status')">Status</th><th onclick="sortBy('username')">Username</th><th onclick="sortBy('password')">Password</th><th onclick="sortBy('balance')">Balance</th><th>Action</th></tr></thead><tbody id="resultsBody"><tr><td colspan="6" style="text-align:center;padding:40px;"><i class="fas fa-spinner fa-pulse"></i> Loading...</td></tr></tbody></table></div></div>
<div class="bottom-grid"><div class="card"><div class="card-header"><i class="fas fa-server"></i> Bot Servers</div><div class="servers-list"><div id="serversContainer"></div><div style="display:flex;gap:8px;margin-top:10px;"><input type="text" id="newServerInput" class="search-input" placeholder="http://..." style="flex:1;"><button class="add-server-btn" onclick="addServer()"><i class="fas fa-plus"></i> Add</button></div><button class="btn btn-primary" onclick="saveServers()" style="margin-top:10px;width:100%;"><i class="fas fa-save"></i> Save & Apply</button></div><div class="button-group"><button class="btn btn-secondary" onclick="manualRefresh()"><i class="fas fa-sync-alt"></i> Refresh</button><button class="btn btn-danger" onclick="clearAllResults()"><i class="fas fa-trash-alt"></i> Clear</button><button class="btn btn-secondary" onclick="clearTerminal()"><i class="fas fa-trash"></i> Clear Terminal</button></div></div>
<div class="card"><div class="terminal-header"><h3 style="font-size:13px;"><i class="fas fa-terminal"></i> Console</h3><button class="toggle-terminal-btn" onclick="toggleTerminal()"><i class="fas fa-eye-slash"></i> Hide</button></div><div class="terminal" id="terminal"><div class="terminal-line"><span class="time">●</span> 🚀 Master UI v3.5 Fixed</div><div class="terminal-line"><span class="time">●</span> 📊 Progress: processed/total</div></div></div></div></div>
<div class="auto-refresh"><i class="fas fa-clock"></i> Auto: 3s | 👤 <span id="onlineUsersSmall">0</span></div></div>
<script>
let allResults=[], currentFilter='all', currentBalanceFilter='all', currentSort={field:'balance',dir:'desc'};
let refreshInterval=null, currentServers=[], authToken=null, serverStatuses={};
let pinnedAccounts=JSON.parse(localStorage.getItem('master_pinned')||'[]');

function savePinned(){localStorage.setItem('master_pinned',JSON.stringify(pinnedAccounts));}
function isPinned(u){return pinnedAccounts.includes(u);}
function togglePin(u){let i=pinnedAccounts.indexOf(u);i===-1?pinnedAccounts.push(u):pinnedAccounts.splice(i,1);savePinned();renderResults();}
function toggleTerminal(){let t=document.getElementById('terminal'),b=document.querySelector('.toggle-terminal-btn');if(t){t.classList.toggle('hidden');b.innerHTML=t.classList.contains('hidden')?'<i class="fas fa-eye"></i> Show':'<i class="fas fa-eye-slash"></i> Hide';}}

async function verifyPin(){let p=document.getElementById('pinInput').value;if(!p){document.getElementById('pinError').innerText='Enter PIN';return;}try{let r=await fetch('/api/verify',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({pin:p})});let d=await r.json();if(d.success){authToken=d.token;localStorage.setItem('master_token',authToken);document.getElementById('pinOverlay').style.display='none';document.getElementById('mainContent').style.display='block';initializeApp();}else{document.getElementById('pinError').innerText='Invalid PIN';document.getElementById('pinInput').value='';}}catch(e){document.getElementById('pinError').innerText='Connection error';}}

function initializeApp(){loadServers();loadResults();updateServerStatuses();updateOnline();refreshInterval=setInterval(()=>{loadResults();updateServerStatuses();updateOnline();},3000);}

async function updateOnline(){try{let r=await fetch(`/api/online?token=${authToken}`);let d=await r.json();let c=Math.min(d.online,2);document.getElementById('onlineUsers').innerHTML='👤 '+c;document.getElementById('onlineUsersSmall').innerHTML=c;}catch(e){}}

async function updateServerStatuses(){
    try{
        let r=await fetch(`/health?token=${authToken}`);
        if(r.ok){
            let d=await r.json();
            for(let b of d.bots){
                serverStatuses[b.server] = {
                    status: b.status,
                    running: b.running || false,
                    processed: b.processed || 0,
                    total: b.total || 0
                };
            }
            renderServersList();
        }
    } catch(e) {}
}

async function loadServers(){try{let r=await fetch(`/api/servers?token=${authToken}`);if(r.ok){let d=await r.json();currentServers=d.servers;renderServersList();}}catch(e){}}

function renderServersList(){
    let c=document.getElementById('serversContainer');
    if(!c)return;
    if(!currentServers.length){
        c.innerHTML='<div style="color:#8b949e;text-align:center;padding:20px;">No servers.</div>';
        return;
    }
    c.innerHTML=currentServers.map((s,i)=>{
        let info=serverStatuses[s]||{status:'checking',running:false,processed:0,total:0};
        let ledClass='',statusText='';
        if(info.status==='offline'){ledClass='offline';statusText='Offline';}
        else if(info.status==='online'&&info.running){ledClass='running';statusText='Running';}
        else if(info.status==='online'&&!info.running){ledClass='online';statusText='Online';}
        else{ledClass='checking';statusText='Checking...';}
        
        let progressText='';
        if(info.status==='online'&&info.total>0){
            progressText=`<span style="font-size:10px;color:#58a6ff;margin-left:6px;">📊 ${info.processed}/${info.total}</span>`;
        }
        return`<div class="server-item">
            <input type="text" id="server_${i}" value="${esc(s)}">
            <div class="server-status">
                <span class="status-led ${ledClass}"></span>
                <span style="font-size:10px;">${statusText}</span>
                ${progressText}
            </div>
            <div class="server-controls">
                <button class="control-btn control-start" onclick="startServer(${i})" ${info.status!=='online'?'disabled':''}>Start</button>
                <button class="control-btn control-restart" onclick="restartServer(${i})" ${info.status!=='online'?'disabled':''}>Restart</button>
                <button class="control-btn control-stop" onclick="stopServer(${i})" ${info.status!=='online'?'disabled':''}>Stop</button>
                <button class="remove-server-btn" onclick="removeServer(${i})"><i class="fas fa-trash"></i></button>
            </div>
        </div>`;
    }).join('');
}

async function startServer(i){let s=currentServers[i];if(!s)return;let a=prompt(`Accounts for ${s}\n\nFormat: username:password (one per line):`,'');if(!a)return;addLog(`Starting ${s}...`);try{let r=await fetch(`/api/control/${i}/start?token=${authToken}`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({accounts:a})});let d=await r.json();addLog(d.success?`Started ${s}`:`Failed: ${d.error}`);if(d.success)setTimeout(()=>updateServerStatuses(),1000);}catch(e){addLog(`Error: ${e.message}`);}}

async function restartServer(i){let s=currentServers[i];if(!s)return;addLog(`Restarting ${s}...`);try{let r=await fetch(`/api/control/${i}/restart?token=${authToken}`,{method:'POST'});let d=await r.json();addLog(d.success?`Restarted ${s}`:`Failed: ${d.error}`);if(d.success){setTimeout(()=>{updateServerStatuses();loadResults();},2000);}}catch(e){addLog(`Error: ${e.message}`);}}

async function stopServer(i){let s=currentServers[i];if(!s)return;addLog(`Stopping ${s}...`);try{let r=await fetch(`/api/control/${i}/stop?token=${authToken}`,{method:'POST'});let d=await r.json();addLog(d.success?`Stopped ${s}`:`Failed: ${d.error}`);if(d.success)setTimeout(()=>updateServerStatuses(),1000);}catch(e){addLog(`Error: ${e.message}`);}}

function addServer(){let i=document.getElementById('newServerInput'),v=i.value.trim();if(v){if(!v.startsWith('http://')&&!v.startsWith('https://')){addLog('Must start with http:// or https://');return;}currentServers.push(v);i.value='';renderServersList();addLog(`Added: ${v}`);}}

function removeServer(i){if(confirm(`Remove ${currentServers[i]}?`)){addLog(`Removed: ${currentServers[i]}`);currentServers.splice(i,1);renderServersList();}}

async function saveServers(){let ins=document.querySelectorAll('#serversContainer input'),ups=Array.from(ins).map(i=>i.value.trim()).filter(s=>s);if(!ups.length){addLog('No servers');return;}try{let r=await fetch(`/api/servers?token=${authToken}`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({servers:ups})});if(r.ok){currentServers=ups;addLog(`Saved ${ups.length} servers`);await updateServerStatuses();}else addLog('Save failed');}catch(e){addLog(`Error: ${e.message}`);}}

async function clearAllResults(){if(confirm('Delete ALL results?')){try{let r=await fetch(`/results/clear?token=${authToken}`,{method:'POST'});if(r.ok){allResults=[];renderResults();updateStats();addLog('All results cleared');}}catch(e){addLog(`Error: ${e.message}`);}}}

async function deleteSingleResult(u){if(confirm(`Delete ${u}?`)){try{await fetch(`/results/clear/${encodeURIComponent(u)}?token=${authToken}`,{method:'POST'});await loadResults();addLog(`Removed ${u}`);}catch(e){addLog(`Error: ${e.message}`);}}}

async function loadResults(){try{let r=await fetch(`/results?token=${authToken}`);if(r.ok){allResults=await r.json();renderResults();updateStats();}else if(r.status===401){addLog('⚠️ Session expired');}}catch(e){}}

function renderResults(){let f=allResults.filter(r=>{if(currentFilter!=='all'){if(currentFilter==='success'&&r.status!=='✅')return false;if(currentFilter==='failed'&&r.status!=='❌')return false;if(currentFilter==='timeout'&&r.status!=='⏰')return false;}if(currentBalanceFilter!=='all'){let n=parseFloat(r.balance_value)||0;if(currentBalanceFilter==='low'&&n>=10)return false;if(currentBalanceFilter==='mid'&&(n<10||n>100))return false;if(currentBalanceFilter==='high'&&n<=100)return false;}return true;});let s=document.getElementById('searchInput')?.value.toLowerCase()||'';if(s)f=f.filter(r=>r.username.toLowerCase().includes(s));f.sort((a,b)=>{let aP=isPinned(a.username)?0:1,bP=isPinned(b.username)?0:1;if(aP!==bP)return aP-bP;let av=currentSort.field==='balance'?(a.balance_value||0):(a[currentSort.field]||'').toString().toLowerCase();let bv=currentSort.field==='balance'?(b.balance_value||0):(b[currentSort.field]||'').toString().toLowerCase();if(typeof av==='number')return currentSort.dir==='asc'?av-bv:bv-av;return currentSort.dir==='asc'?(av>bv?1:-1):(av<bv?1:-1);});let bc=v=>{let n=parseFloat(v)||0;return n>100?'balance-positive':n>10?'balance-medium':'balance-zero';};let body=document.getElementById('resultsBody');if(!body)return;body.innerHTML=f.map(r=>`<tr><td><button class="pin-star-btn ${isPinned(r.username)?'active':''}" onclick="togglePin('${esc(r.username)}')"><i class="fas fa-star"></i></button></td><td style="font-size:18px">${r.status}</td><td><div class="username-cell"><strong style="color:#58a6ff">${esc(r.username)}</strong><button class="copy-btn" onclick="copyToClipboard('${esc(r.username)}',this)"><i class="fas fa-copy"></i></button></div></td><td><div class="password-cell">${esc(r.password)}<button class="copy-btn" onclick="copyToClipboard('${esc(r.password)}',this)"><i class="fas fa-key"></i></button></div></td><td class="${bc(r.balance_value)}">${r.balance||'0 ֏'}</td><td class="error-cell">${esc(r.error||'-')}<button class="retry-btn" onclick="retryAccount('${esc(r.username)}',this)"><i class="fas fa-sync-alt"></i> Retry</button><button class="delete-row-btn" onclick="deleteSingleResult('${esc(r.username)}')"><i class="fas fa-trash"></i></button></td></tr>`).join('');if(!f.length&&allResults.length)body.innerHTML='<tr><td colspan="6" style="text-align:center;padding:40px;">No matching results</td></tr>';}

function updateStats(){let tb=allResults.reduce((sum,r)=>sum+(parseFloat(r.balance_value)||0),0);document.getElementById('totalCount').innerText=allResults.length;document.getElementById('successCount').innerText=allResults.filter(r=>r.status==='✅').length;document.getElementById('failedCount').innerText=allResults.filter(r=>r.status==='❌').length;document.getElementById('timeoutCount').innerText=allResults.filter(r=>r.status==='⏰').length;document.getElementById('totalBalance').innerText=tb.toFixed(2)+' ֏';}

function sortBy(f){if(currentSort.field===f)currentSort.dir=currentSort.dir==='asc'?'desc':'asc';else{currentSort.field=f;currentSort.dir=f==='balance'?'desc':'asc';}renderResults();}
function setFilter(f){currentFilter=f;document.querySelectorAll('.filter-btn').forEach(b=>b.classList.toggle('active',b.dataset.filter===f));renderResults();}
function setBalanceFilter(f){currentBalanceFilter=f;document.querySelectorAll('.balance-filter-btn').forEach(b=>b.classList.toggle('active',b.dataset.balance===f));renderResults();}
function manualRefresh(){loadResults();updateServerStatuses();addLog('🔄 Refreshed');}
function esc(s){if(!s)return'';return s.replace(/[&<>]/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;'})[m]);}
function addLog(m){let t=document.getElementById('terminal');if(!t)return;let d=document.createElement('div');d.className='terminal-line';d.innerHTML=`<span class="time">[${new Date().toLocaleTimeString()}]</span> ${m}`;t.appendChild(d);if(t.children.length>100)t.removeChild(t.firstChild);}
function clearTerminal(){let t=document.getElementById('terminal');if(t){t.innerHTML='';addLog('Terminal cleared');}}
async function copyToClipboard(t,b){await navigator.clipboard.writeText(t);let o=b.innerHTML;b.innerHTML='✓';setTimeout(()=>b.innerHTML=o,1000);}
async function retryAccount(u,b){let o=b.innerHTML;b.innerHTML='<i class="fas fa-spinner fa-pulse"></i>';b.disabled=true;addLog(`Retrying ${u}...`);try{await fetch(`/retry/${encodeURIComponent(u)}?token=${authToken}`,{method:'POST'});addLog(`Retry sent for ${u}`);setTimeout(()=>loadResults(),2000);}catch(e){addLog('Retry failed');}setTimeout(()=>{b.innerHTML=o;b.disabled=false;},3000);}
document.addEventListener('input',function(e){if(e.target&&e.target.id==='searchInput')renderResults();});
document.addEventListener('keypress',function(e){if(e.target&&e.target.id==='pinInput'&&e.key==='Enter')verifyPin();});
(async()=>{let t=localStorage.getItem('master_token');if(t){try{let r=await fetch(`/api/check?token=${t}`);let d=await r.json();if(d.authenticated){authToken=t;document.getElementById('pinOverlay').style.display='none';document.getElementById('mainContent').style.display='block';initializeApp();}}catch(e){}}})();
document.addEventListener('contextmenu',e=>e.preventDefault());
document.addEventListener('keydown',e=>{if(e.key==='F12'||(e.ctrlKey&&e.shiftKey&&['i','I','j','J'].includes(e.key))||(e.ctrlKey&&['u','U'].includes(e.key))){e.preventDefault();}});
console.log('%c⚡ Master UI v3.5 - Progress Fixed','font-size:18px;color:#3fb950;');
</script>
</body>
</html>'''

# ===== LIVE ADMIN HTML =====
LIVE_ADMIN_HTML = '''<!DOCTYPE html>
<html lang="hy">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover">
    <title>Live Admin</title>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap" rel="stylesheet">
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <style>
        *{margin:0;padding:0;box-sizing:border-box}
        body{background:#0a0c10;color:#e6edf3;font-family:'Inter',sans-serif;min-height:100vh}
        .pin-overlay{position:fixed;inset:0;background:rgba(0,0,0,0.95);backdrop-filter:blur(12px);display:flex;align-items:center;justify-content:center;z-index:1000}
        .pin-box{background:#161b22;border:1px solid #30363d;border-radius:24px;padding:40px;width:320px;text-align:center}
        .pin-box h2{margin-bottom:24px;background:linear-gradient(135deg,#58a6ff,#3fb950);-webkit-background-clip:text;background-clip:text;color:transparent}
        .pin-box input{width:100%;padding:12px;background:#0d1117;border:1px solid #30363d;border-radius:12px;color:#fff;font-size:18px;text-align:center;letter-spacing:6px}
        .pin-box button{width:100%;padding:12px;background:linear-gradient(135deg,#238636,#2ea043);border:none;border-radius:12px;color:#fff;font-weight:bold;cursor:pointer;margin-top:16px}
        .pin-error{color:#f85149;font-size:12px;margin-top:12px}
        .main-content{display:none}
        .container{max-width:1600px;margin:0 auto;padding:20px}
        .header{background:linear-gradient(135deg,rgba(22,27,34,0.95),rgba(13,17,23,0.95));border-radius:20px;padding:14px 24px;margin-bottom:20px;border:1px solid rgba(48,54,61,0.5);text-align:center}
        .header h1{font-size:24px;font-weight:700;background:linear-gradient(135deg,#58a6ff,#3fb950,#f0883e);-webkit-background-clip:text;background-clip:text;color:transparent}
        .header-sub{font-size:12px;color:#8b949e;margin-top:4px}
        .online-badge{background:transparent;padding:2px 12px;border-radius:20px;font-size:12px;color:#58a6ff;border:1px solid #30363d}
        .stats-top{display:grid;grid-template-columns:repeat(5,1fr);gap:12px;margin-bottom:20px}
        .stat-card{background:#161b22;border-radius:14px;padding:10px 12px;text-align:center;border:1px solid #30363d;transition:all 0.2s}
        .stat-card:hover{border-color:#58a6ff;background:#1a1f2e}
        .stat-number{font-size:22px;font-weight:700;color:#58a6ff}
        .stat-number.balance-total{color:#f0883e}
        .stat-label{font-size:10px;color:#8b949e;margin-top:3px}
        .results-section{background:#161b22;border-radius:20px;border:1px solid #30363d;overflow:hidden;margin-bottom:20px}
        .section-header{padding:14px 20px;background:#0d1117;border-bottom:1px solid #30363d;font-weight:600;font-size:15px;display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px}
        .filter-bar{padding:12px 20px;background:#0d1117;border-bottom:1px solid #21262d;display:flex;flex-wrap:wrap;gap:10px;align-items:center}
        .search-input{padding:6px 14px;background:#010409;border:1px solid #30363d;border-radius:30px;color:#fff;width:220px;font-size:12px}
        .refresh-btn{padding:5px 14px;background:#1f6feb;border:none;border-radius:30px;color:#fff;cursor:pointer;font-size:11px}
        .refresh-btn:hover{background:#388bfd}
        .accounts-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:12px}
        .account-card{background:#161b22;border-radius:16px;border:1px solid #30363d;overflow:hidden;transition:all 0.2s}
        .account-card:hover{border-color:#58a6ff;transform:translateY(-2px)}
        .account-card .card-header{padding:12px 16px;background:#0d1117;border-bottom:1px solid #21262d;display:flex;justify-content:space-between;align-items:center}
        .account-card .username{font-size:15px;font-weight:600;color:#58a6ff;word-break:break-all}
        .account-card .status-badge{font-size:18px}
        .account-card .card-body{padding:12px 16px}
        .account-card .balance{font-size:28px;font-weight:700}
        .balance-positive{color:#3fb950}
        .balance-medium{color:#d29922}
        .balance-zero{color:#f85149}
        .balance-label{font-size:10px;color:#8b949e;margin-bottom:2px}
        .copy-btn{background:transparent;border:1px solid #30363d;border-radius:16px;padding:2px 8px;color:#58a6ff;cursor:pointer;font-size:10px}
        .copy-btn:hover{background:#30363d}
        .footer{text-align:center;padding:16px;font-size:10px;color:#6e7681;border-top:1px solid #21262d;margin-top:20px}
        .no-results{text-align:center;padding:60px 20px;color:#6e7681;grid-column:1/-1}
        .no-results i{font-size:40px;margin-bottom:16px;color:#30363d}
        .autorefresh-info{font-size:11px;color:#6e7681}
        @media(max-width:900px){.stats-top{grid-template-columns:repeat(3,1fr)}.accounts-grid{grid-template-columns:1fr}.filter-bar{flex-direction:column;align-items:stretch}.search-input{width:100%}}
    </style>
</head>
<body>
<div id="pinOverlay" class="pin-overlay">
    <div class="pin-box"><h2><i class="fas fa-eye"></i> Live Admin</h2>
    <input type="password" id="pinInput" placeholder="PIN" maxlength="6" autofocus>
    <button onclick="verifyPin()"><i class="fas fa-unlock-alt"></i> Access</button>
    <div id="pinError" class="pin-error"></div></div>
</div>
<div id="mainContent" class="main-content"><div class="container">
    <div class="header"><h1><i class="fas fa-eye"></i> Live Administrator <span class="online-badge" id="onlineUsers">👤 0</span></h1>
    <div class="header-sub"><i class="fas fa-lock"></i> Encrypted | <span id="lastUpdate">Loading...</span> | <i class="fas fa-user-secret"></i> Passwords hidden</div></div>
    <div class="stats-top"><div class="stat-card"><div class="stat-number" id="totalAccounts">0</div><div class="stat-label">📊 Total</div></div>
    <div class="stat-card"><div class="stat-number" id="successAccounts">0</div><div class="stat-label">✅ Success</div></div>
    <div class="stat-card"><div class="stat-number" id="failedAccounts">0</div><div class="stat-label">❌ Failed</div></div>
    <div class="stat-card"><div class="stat-number" id="timeoutAccounts">0</div><div class="stat-label">⏰ Timeout</div></div>
    <div class="stat-card"><div class="stat-number balance-total" id="totalBalance">0</div><div class="stat-label">💰 Total Balance</div></div></div>
    <div class="results-section"><div class="section-header"><span><i class="fas fa-chart-line"></i> Live Results <span style="font-size:10px;color:#3fb950;">🔐 Encrypted</span></span>
    <button class="refresh-btn" onclick="manualRefresh()"><i class="fas fa-sync-alt"></i> Refresh</button></div>
    <div class="filter-bar"><input type="text" id="searchInput" class="search-input" placeholder="🔍 Search..." oninput="filterResults()">
    <button class="refresh-btn" onclick="loadResults()"><i class="fas fa-sync-alt"></i> Refresh</button>
    <span class="autorefresh-info"><i class="fas fa-clock"></i> Auto: 3s</span></div>
    <div class="accounts-grid" id="accountsGrid"><div class="no-results"><i class="fas fa-spinner fa-pulse"></i><div>Loading...</div></div></div></div>
    <div class="footer"><i class="fas fa-chart-line"></i> <span id="footerCount">0</span> accounts | <i class="fas fa-lock"></i> Passwords hidden</div>
</div></div>
<script>
let liveResults=[], authToken=null, refreshInterval=null;
async function verifyPin(){let p=document.getElementById('pinInput').value;if(!p){document.getElementById('pinError').innerText='Enter PIN';return;}try{let r=await fetch('/live/verify',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({pin:p})});let d=await r.json();if(d.success){authToken=d.token;localStorage.setItem('live_admin_token',authToken);document.getElementById('pinOverlay').style.display='none';document.getElementById('mainContent').style.display='block';loadResults();updateOnline();refreshInterval=setInterval(()=>{loadResults();updateOnline();},3000);}else{document.getElementById('pinError').innerText='Invalid PIN';document.getElementById('pinInput').value='';}}catch(e){document.getElementById('pinError').innerText='Connection error';}}
async function loadResults(){try{let r=await fetch('/results/public');if(r.ok){liveResults=await r.json();renderResults();updateStats();document.getElementById('lastUpdate').innerHTML='🕐 '+new Date().toLocaleTimeString();}else{document.getElementById('accountsGrid').innerHTML='<div class="no-results"><i class="fas fa-exclamation-triangle" style="color:#f85149;"></i><div style="color:#f85149;">Error loading</div></div>';}}catch(e){}}
async function updateOnline(){try{let r=await fetch('/api/online');let d=await r.json();document.getElementById('onlineUsers').innerHTML='👤 '+d.online;}catch(e){}}
function renderResults(){let g=document.getElementById('accountsGrid'), s=document.getElementById('searchInput').value.toLowerCase();let f=liveResults;if(s)f=f.filter(r=>r.username.toLowerCase().includes(s));f.sort((a,b)=>(parseFloat(b.balance_value)||0)-(parseFloat(a.balance_value)||0));if(!f.length){g.innerHTML='<div class="no-results"><i class="fas fa-inbox"></i><div>No results</div></div>';return;}let bc=v=>{let n=parseFloat(v)||0;return n>100?'balance-positive':n>10?'balance-medium':'balance-zero';};g.innerHTML=f.map(a=>`<div class="account-card"><div class="card-header"><span class="username"><i class="fas fa-user-circle" style="margin-right:6px;color:#58a6ff;"></i>${esc(a.username)}</span><span class="status-badge">${a.status}</span></div><div class="card-body"><div class="balance-label"><i class="fas fa-coins"></i> Balance</div><div class="balance ${bc(a.balance_value)}">${a.balance||'0 ֏'}</div><div style="margin-top:8px;"><button class="copy-btn" onclick="copyToClipboard('${esc(a.username)}')"><i class="fas fa-copy"></i> Copy</button></div></div></div>`).join('');}
function updateStats(){let t=liveResults.length,s=liveResults.filter(r=>r.status==='✅').length,f=liveResults.filter(r=>r.status==='❌').length,to=liveResults.filter(r=>r.status==='⏰').length,tb=liveResults.reduce((sum,r)=>sum+(parseFloat(r.balance_value)||0),0);document.getElementById('totalAccounts').textContent=t;document.getElementById('successAccounts').textContent=s;document.getElementById('failedAccounts').textContent=f;document.getElementById('timeoutAccounts').textContent=to;document.getElementById('totalBalance').textContent=tb.toFixed(2)+' ֏';document.getElementById('footerCount').textContent=t;}
function filterResults(){renderResults();}
function manualRefresh(){loadResults();updateOnline();}
function copyToClipboard(t){navigator.clipboard.writeText(t);}
function esc(s){if(!s)return'';return String(s).replace(/[&<>]/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;'})[m]);}
(async()=>{let t=localStorage.getItem('live_admin_token');if(t){try{let r=await fetch(`/live/check?token=${t}`);let d=await r.json();if(d.authenticated){authToken=t;document.getElementById('pinOverlay').style.display='none';document.getElementById('mainContent').style.display='block';loadResults();updateOnline();refreshInterval=setInterval(()=>{loadResults();updateOnline();},3000);}}catch(e){}}})();
document.addEventListener('contextmenu',e=>e.preventDefault());
document.addEventListener('keydown',e=>{if(e.key==='F12'||(e.ctrlKey&&e.shiftKey&&['i','I','j','J'].includes(e.key))||(e.ctrlKey&&['u','U'].includes(e.key))){e.preventDefault();}});
console.log('%c🔒 Live Admin - Protected','font-size:18px;color:#3fb950;');
</script>
</body>
</html>'''

# ===== MOBILE HTML =====
MOBILE_HTML = '''<!DOCTYPE html>
<html lang="hy">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover, user-scalable=yes">
    <title>Mobile Monitor</title>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap" rel="stylesheet">
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <style>
        *{margin:0;padding:0;box-sizing:border-box}
        body{background:linear-gradient(135deg,#0a0c10,#0d1117);color:#e6edf3;font-family:'Inter',sans-serif;padding:10px;min-height:100vh}
        .pin-overlay{position:fixed;inset:0;background:rgba(0,0,0,0.95);backdrop-filter:blur(12px);display:flex;align-items:center;justify-content:center;z-index:1000}
        .pin-box{background:#161b22;border:1px solid #30363d;border-radius:24px;padding:30px;width:280px;text-align:center}
        .pin-box input{width:100%;padding:12px;background:#0d1117;border:1px solid #30363d;border-radius:12px;color:#fff;font-size:20px;text-align:center;letter-spacing:6px}
        .pin-box button{width:100%;padding:12px;background:#238636;border:none;border-radius:12px;color:#fff;font-weight:bold;cursor:pointer;margin-top:16px}
        .mobile-dashboard{display:none}
        .header{background:#161b22;border-radius:16px;padding:12px;margin-bottom:12px;text-align:center;border:1px solid #30363d}
        .header h1{font-size:16px;background:linear-gradient(135deg,#58a6ff,#3fb950);-webkit-background-clip:text;background-clip:text;color:transparent}
        .last-update{font-size:9px;color:#6e7681;margin-top:3px}
        .toolbar{display:flex;justify-content:space-between;margin-bottom:10px;flex-wrap:wrap;gap:6px}
        .refresh-btn{background:#1f6feb;border:none;border-radius:30px;color:#fff;padding:6px 14px;font-size:11px;cursor:pointer}
        .online-badge{background:transparent;padding:2px 10px;border-radius:20px;font-size:10px;color:#58a6ff}
        .accounts-list{display:flex;flex-direction:column;gap:10px}
        .account-card{background:#161b22;border-radius:14px;border:1px solid #30363d;overflow:hidden}
        .account-row{display:flex;justify-content:space-between;align-items:center;padding:10px 12px;border-bottom:1px solid #21262d}
        .account-row:last-child{border-bottom:none}
        .label{font-size:9px;color:#8b949e;text-transform:uppercase;margin-bottom:2px}
        .username-value{font-size:14px;font-weight:600;color:#58a6ff;word-break:break-all}
        .password-value{font-size:11px;font-family:monospace;color:#e6edf3;word-break:break-all}
        .balance-value{font-size:16px;font-weight:700}
        .balance-positive{color:#3fb950}
        .balance-medium{color:#d29922}
        .balance-zero{color:#f85149}
        .copy-btn{background:transparent;border:1px solid #30363d;border-radius:16px;padding:3px 8px;color:#58a6ff;cursor:pointer;font-size:9px;margin-left:6px}
        .status-badge{font-size:16px;margin-right:6px}
        .pin-star{background:transparent;border:none;color:#d29922;cursor:pointer;font-size:14px;padding:0 4px}
        .pin-star.active{color:#f0883e;text-shadow:0 0 3px #f0883e}
        .footer{text-align:center;padding:10px;font-size:9px;color:#6e7681;border-top:1px solid #21262d;margin-top:12px}
        .error-text{color:#f85149;font-size:9px}
    </style>
</head>
<body>
<div id="pinOverlay" class="pin-overlay"><div class="pin-box"><h2><i class="fas fa-mobile-alt"></i> Mobile Access</h2>
<input type="password" id="pinInput" placeholder="PIN" maxlength="6"><button onclick="verifyPin()">Access</button>
<div id="pinError" style="color:#f85149;font-size:12px;margin-top:12px;"></div></div></div>
<div id="mobileDashboard" class="mobile-dashboard"><div class="header"><h1><i class="fas fa-mobile-alt"></i> Mobile Monitor</h1><div class="last-update" id="lastUpdate">Loading... <span class="online-badge" id="onlineUsers">👤 0</span></div></div>
<div class="toolbar"><button class="refresh-btn" onclick="loadResults()"><i class="fas fa-sync-alt"></i> Refresh</button></div>
<div class="accounts-list" id="accountsList"><div style="text-align:center;padding:30px;"><i class="fas fa-spinner fa-pulse"></i> Loading...</div></div>
<div class="footer"><i class="fas fa-chart-line"></i> Auto 3s | ⭐ Pinned on top | 🔐 Encrypted</div></div>
<script>
let mobileResults=[], authToken=null, refreshInterval=null;
let pinnedAccounts=JSON.parse(localStorage.getItem('mobile_pinned')||'[]');
function savePinned(){localStorage.setItem('mobile_pinned',JSON.stringify(pinnedAccounts));}
function togglePin(u){let i=pinnedAccounts.indexOf(u);i===-1?pinnedAccounts.push(u):pinnedAccounts.splice(i,1);savePinned();renderList();}
function isPinned(u){return pinnedAccounts.includes(u);}
async function verifyPin(){let p=document.getElementById('pinInput').value;if(!p){document.getElementById('pinError').innerText='Enter PIN';return;}try{let r=await fetch('/mobile/verify',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({pin:p})});let d=await r.json();if(d.success){authToken=d.token;localStorage.setItem('mobile_token',authToken);document.getElementById('pinOverlay').style.display='none';document.getElementById('mobileDashboard').style.display='block';loadResults();updateOnline();refreshInterval=setInterval(()=>{loadResults();updateOnline();},3000);}else{document.getElementById('pinError').innerText='Invalid PIN';document.getElementById('pinInput').value='';}}catch(e){document.getElementById('pinError').innerText='Connection error';}}
async function updateOnline(){try{let r=await fetch(`/api/online?token=${authToken}`);let d=await r.json();let c=Math.min(d.online,2);document.getElementById('onlineUsers').innerHTML='👤 '+c;}catch(e){}}
async function loadResults(){try{let r=await fetch(`/results?token=${authToken}`);if(r.ok){let d=await r.json();mobileResults=d;renderList();document.getElementById('lastUpdate').innerHTML='Last: '+new Date().toLocaleTimeString();}else if(r.status===401){document.getElementById('accountsList').innerHTML='<div style="text-align:center;padding:30px;color:#f85149;"><i class="fas fa-lock"></i> Session expired</div>';}}catch(e){}}
function renderList(){let c=document.getElementById('accountsList');let s=[...mobileResults].sort((a,b)=>{let aP=isPinned(a.username)?0:1,bP=isPinned(b.username)?0:1;if(aP!==bP)return aP-bP;return(parseFloat(b.balance_value)||0)-(parseFloat(a.balance_value)||0);});if(!s.length){c.innerHTML='<div style="text-align:center;padding:30px;"><i class="fas fa-inbox"></i> No results</div>';return;}let bc=v=>{let n=parseFloat(v)||0;return n>100?'balance-positive':n>10?'balance-medium':'balance-zero';};c.innerHTML=s.map(a=>`<div class="account-card"><div class="account-row"><div><span class="status-badge">${a.status}</span><span class="username-value">${esc(a.username)}</span><button class="copy-btn" onclick="copyToClipboard('${esc(a.username)}')"><i class="fas fa-copy"></i></button><button class="pin-star ${isPinned(a.username)?'active':''}" onclick="togglePin('${esc(a.username)}')"><i class="fas fa-star"></i></button></div></div><div class="account-row"><div><div class="label"><i class="fas fa-key"></i> Password</div><div class="password-value">${esc(a.password)}<button class="copy-btn" onclick="copyToClipboard('${esc(a.password)}')"><i class="fas fa-copy"></i></button></div></div></div><div class="account-row"><div><div class="label"><i class="fas fa-coins"></i> Balance</div><div class="balance-value ${bc(a.balance_value)}">${a.balance||'0 ֏'}</div></div></div>${a.error?`<div class="account-row"><div class="error-text"><i class="fas fa-exclamation-triangle"></i> ${esc(a.error)}</div></div>`:''}</div>`).join('');}
function copyToClipboard(t){navigator.clipboard.writeText(t);}
function esc(s){if(!s)return'';return s.replace(/[&<>]/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;'})[m]);}
(async()=>{let t=localStorage.getItem('mobile_token');if(t){try{let r=await fetch(`/mobile/check?token=${t}`);let d=await r.json();if(d.authenticated){authToken=t;document.getElementById('pinOverlay').style.display='none';document.getElementById('mobileDashboard').style.display='block';loadResults();updateOnline();refreshInterval=setInterval(()=>{loadResults();updateOnline();},3000);}}catch(e){}}})();
document.addEventListener('contextmenu',e=>e.preventDefault());
document.addEventListener('keydown',e=>{if(e.key==='F12'||(e.ctrlKey&&e.shiftKey&&['i','I','j','J'].includes(e.key))||(e.ctrlKey&&['u','U'].includes(e.key))){e.preventDefault();}});
console.log('%c📱 Mobile Monitor v3.5','font-size:18px;color:#3fb950;');
</script>
</body>
</html>'''

# ================= MAIN ROUTES =================

@app.get("/")
async def root():
    return RedirectResponse(url="/homepages.admin.dashboard")

@app.get("/homepages.admin.dashboard")
async def master_dashboard():
    return HTMLResponse(MAIN_HTML)

@app.get("/mobile.dashboard.administration")
async def mobile_dashboard():
    return HTMLResponse(MOBILE_HTML)

@app.get("/live_administrator")
async def live_administrator():
    return HTMLResponse(LIVE_ADMIN_HTML)

if __name__ == "__main__":
    import uvicorn
    import time
    
    print("\n" + "=" * 60)
    print("⚡ MASTER UI v3.5 - PROGRESS FIXED")
    print("=" * 60)
    print(f"📍 Master UI:     http://localhost:9000/homepages.admin.dashboard")
    print(f"📍 Mobile:        http://localhost:9000/mobile.dashboard.administration")
    print(f"📍 Live Admin:    http://localhost:9000/live_administrator")
    print("=" * 60)
    print(f"🔐 Master PIN:    {MASTER_PIN}")
    print(f"🔐 Mobile PIN:    {MOBILE_PIN}")
    print(f"🔐 Live PIN:      {LIVE_ADMIN_PIN}")
    print(f"👤 Online Users:  MAX 2")
    print(f"⚡ Cache TTL:     3 seconds")
    print(f"📊 Progress:      processed/total")
    print("=" * 60 + "\n")
    
    uvicorn.run(app, host="0.0.0.0", port=9000, log_level="info")

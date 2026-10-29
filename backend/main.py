import os
import json
from datetime import datetime, date
from typing import List, Optional

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect, File, UploadFile, Form
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import asyncio

app = FastAPI(title="WeldGuard Backend API")

# --- CORS Middleware ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Path Configurations ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SNAPSHOTS_DIR = os.path.join(BASE_DIR, "snapshots")
DATA_FILE = os.path.join(BASE_DIR, "data.json")

os.makedirs(SNAPSHOTS_DIR, exist_ok=True)

# --- Mount Static Files ---
app.mount("/snapshots", StaticFiles(directory=SNAPSHOTS_DIR), name="snapshots")

# --- WebSocket Manager ---
class ConnectionManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: str):
        for connection in self.active_connections:
            try:
                await connection.send_text(message)
            except Exception:
                pass

manager = ConnectionManager()

# --- Pydantic Models ---
class RelayCommand(BaseModel):
    command: str  # "on" or "off"

class WorkerCreate(BaseModel):
    uid: str
    name: str
    dept: str = "Las Struktural"
    cert: str = "2027-01-01"
    status: str = "active"

# --- In-Memory Database ---
def load_data():
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r") as f:
                return json.load(f)
        except:
            pass
    return {
        "stations": {
            "LAS-01": {
                "name": "Stasiun Las 1",
                "worker": "Menunggu RFID...",
                "uid": "-",
                "status": "idle",
                "machine": "OFF",
                "last_update": "",
                "apd_status": {
                    "welding_helmet": False,
                    "gloves": False
                }
            }
        },
        "incidents": [],
        "workers": [
            {
                "uid": "-",
                "name": "Fadli",
                "dept": "Las Struktural",
                "cert": "2027-01-01",
                "status": "active",
                "avatar": "FA",
                "color": "#f97316"
            }
        ]
    }

def save_data(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=4)

db = load_data()

# Ensure workers key exists (migration from old data.json)
if "workers" not in db:
    db["workers"] = [
        {
            "uid": "-",
            "name": "Fadli",
            "dept": "Las Struktural",
            "cert": "2027-01-01",
            "status": "active",
            "avatar": "FA",
            "color": "#f97316"
        }
    ]
    save_data(db)

# --- State untuk Video Streaming ---
latest_frames = {}
frame_events = {}

# --- Pending Relay Commands (from Website) ---
pending_relay_commands = {}

# --- Helper: Find worker by UID ---
def find_worker_by_uid(uid: str):
    """Cari worker berdasarkan RFID UID"""
    for w in db.get("workers", []):
        if w["uid"].upper() == uid.upper():
            return w
    return None

# --- Helper: Calculate KPIs ---
def calc_kpis():
    stations = db["stations"]
    incidents = db["incidents"]
    today_str = date.today().isoformat()
    
    total_stations = len(stations)
    active_stations = sum(1 for s in stations.values() if s.get("machine") == "ON")
    safe_stations = sum(1 for s in stations.values() if s.get("status") == "safe")
    danger_stations = sum(1 for s in stations.values() if s.get("status") == "danger")
    idle_stations = sum(1 for s in stations.values() if s.get("status") == "idle")
    
    today_incidents = [i for i in incidents if i.get("time", "").startswith(today_str)]
    high_incidents = [i for i in incidents if i.get("severity") == "high"]
    
    # Safety score: percentage of safe scans (if any scans happened)
    total_scans = len(incidents) + safe_stations  # rough estimate
    safety_score = round(safe_stations / total_stations * 100) if total_stations > 0 else 100
    
    # Unique workers active today
    active_workers = len(set(
        s.get("worker", "") for s in stations.values() 
        if s.get("machine") == "ON" and s.get("worker") not in ["", "Menunggu RFID..."]
    ))
    
    return {
        "total_stations": total_stations,
        "active_stations": active_stations,
        "safe_stations": safe_stations,
        "danger_stations": danger_stations,
        "idle_stations": idle_stations,
        "total_incidents": len(incidents),
        "today_incidents": len(today_incidents),
        "high_incidents": len(high_incidents),
        "safety_score": safety_score,
        "active_workers": active_workers,
        "total_workers": len(db.get("workers", [])),
        "snapshots": len([f for f in os.listdir(SNAPSHOTS_DIR) if f.endswith('.jpg')])
    }

# --- WebSocket Endpoint ---
@app.websocket("/ws/updates")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    # Kirim state awal termasuk KPIs dan workers
    await websocket.send_text(json.dumps({
        "type": "init",
        "stations": db["stations"],
        "incidents": db["incidents"],
        "workers": db.get("workers", []),
        "kpis": calc_kpis()
    }))
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)

# --- API Endpoints ---
@app.get("/api/status")
def get_status():
    return {"status": "success", "data": db["stations"]}

@app.get("/api/incidents")
def get_incidents():
    incidents = sorted(db["incidents"], key=lambda x: x.get("time", ""), reverse=True)
    return {"status": "success", "data": incidents}

# === SCAN ENDPOINT ===
@app.post("/api/scan")
async def process_scan(
    station_id: str = Form(...),
    rfid_uid: str = Form(...),
    status_apd: str = Form(...), # "ALLOWED" or "DENIED"
    missing_apd: str = Form(""), # Comma separated
    image: UploadFile = File(...)
):
    """Menerima hasil scan RFID dan deteksi AI dari Laptop (Edge Node)"""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"scan_{station_id}_{ts}.jpg"
    filepath = os.path.join(SNAPSHOTS_DIR, filename)
    
    with open(filepath, "wb") as f:
        f.write(await image.read())
        
    is_violation = (status_apd == "DENIED")
    
    if station_id not in db["stations"]:
        db["stations"][station_id] = {
            "name": f"Stasiun {station_id}",
            "worker": "Unknown",
            "uid": "-",
        }
    
    # Cari worker di database
    worker = find_worker_by_uid(rfid_uid)
    if worker:
        worker_name = worker["name"]
        # Update UID di worker jika belum di-set
        if worker.get("uid") == "-":
            worker["uid"] = rfid_uid
    else:
        if rfid_uid == "AUTO-AI":
            # Jika ini auto-update tanpa tap RFID, pertahankan pekerja yang sedang aktif di stasiun (jika ada)
            worker_name = db["stations"].get(station_id, {}).get("worker", "Unknown")
        else:
            # Bind UID otomatis ke pekerja pertama yang belum punya kartu (uid = "-")
            unassigned_worker = next((w for w in db.get("workers", []) if w.get("uid") == "-"), None)
            if unassigned_worker:
                unassigned_worker["uid"] = rfid_uid
                worker_name = unassigned_worker["name"]
            else:
                worker_name = "Pekerja " + rfid_uid
    
    # Parse missing APD for APD status
    missing_list = [m.strip() for m in missing_apd.split(",") if m.strip()] if missing_apd else []
    
    station = db["stations"][station_id]
    station["worker"] = worker_name
    station["uid"] = rfid_uid
    station["status"] = "danger" if is_violation else "safe"
    station["machine"] = "OFF" if is_violation else "ON"
    station["last_update"] = datetime.now().isoformat()
    station["apd_status"] = {
        "welding_helmet": "welding_helmet" not in missing_list and "kacamata_las" not in missing_list and "safety_glasses" not in missing_list,
        "kacamata_las": "welding_helmet" not in missing_list and "kacamata_las" not in missing_list and "safety_glasses" not in missing_list
    }
    
    if is_violation:
        incident_id = f"INC-{len(db['incidents']) + 1:03d}"
        # Determine severity based on number of missing APD
        severity = "high" if len(missing_list) >= 2 else "medium" if len(missing_list) == 1 else "low"
        new_incident = {
            "id": incident_id,
            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "station": station_id,
            "worker": worker_name,
            "uid": rfid_uid,
            "type": missing_apd if missing_apd else "APD Tidak Lengkap",
            "severity": severity,
            "snapshot": f"/snapshots/{filename}"
        }
        db["incidents"].append(new_incident)
        
    save_data(db)
    
    await manager.broadcast(json.dumps({
        "type": "update",
        "stations": db["stations"],
        "incidents": db["incidents"],
        "workers": db.get("workers", []),
        "kpis": calc_kpis()
    }))
    
    return {"status": "success", "message": "Scan processed"}

# === RELAY CONTROL ENDPOINTS ===
@app.post("/api/relay/{station_id}")
async def set_relay(station_id: str, cmd: RelayCommand):
    """Website mengirim perintah relay ON/OFF"""
    command = cmd.command.lower()
    if command not in ("on", "off"):
        raise HTTPException(status_code=400, detail="Command must be 'on' or 'off'")
    
    # Simpan pending command untuk inference engine
    pending_relay_commands[station_id] = {
        "command": command,
        "source": "web",
        "timestamp": datetime.now().isoformat()
    }
    
    # Update station machine state
    if station_id in db["stations"]:
        db["stations"][station_id]["machine"] = command.upper()
        if command == "off":
            db["stations"][station_id]["status"] = "idle"
        save_data(db)
    
    # Broadcast update ke semua client
    await manager.broadcast(json.dumps({
        "type": "update",
        "stations": db["stations"],
        "incidents": db["incidents"],
        "workers": db.get("workers", []),
        "kpis": calc_kpis()
    }))
    
    print(f"[RELAY] Website command: {station_id} -> {command.upper()}")
    return {"status": "success", "message": f"Relay {station_id} set to {command.upper()}"}

@app.get("/api/relay/pending/{station_id}")
def get_pending_relay(station_id: str):
    """Inference engine polls untuk pending relay command"""
    cmd = pending_relay_commands.pop(station_id, None)
    if cmd:
        return {"command": cmd["command"], "source": cmd["source"]}
    return {"command": None}

# === WORKER MANAGEMENT ENDPOINTS ===
@app.get("/api/workers")
def get_workers():
    return {"status": "success", "data": db.get("workers", [])}

@app.post("/api/workers")
async def add_worker(worker: WorkerCreate):
    """Tambah worker baru"""
    # Check duplicate UID (unless UID is "-")
    if worker.uid != "-":
        existing = find_worker_by_uid(worker.uid)
        if existing:
            raise HTTPException(status_code=400, detail=f"UID {worker.uid} sudah terdaftar untuk {existing['name']}")
    
    initials = "".join([w[0].upper() for w in worker.name.split()[:2]])
    colors = ["#f97316", "#3b82f6", "#22c55e", "#ef4444", "#a855f7", "#06b6d4", "#eab308"]
    color = colors[len(db.get("workers", [])) % len(colors)]
    
    new_worker = {
        "uid": worker.uid,
        "name": worker.name,
        "dept": worker.dept,
        "cert": worker.cert,
        "status": worker.status,
        "avatar": initials,
        "color": color
    }
    
    if "workers" not in db:
        db["workers"] = []
    db["workers"].append(new_worker)
    save_data(db)
    
    await manager.broadcast(json.dumps({
        "type": "update",
        "stations": db["stations"],
        "incidents": db["incidents"],
        "workers": db["workers"],
        "kpis": calc_kpis()
    }))
    
    return {"status": "success", "message": f"Worker {worker.name} ditambahkan", "data": new_worker}

@app.put("/api/workers/{uid}")
async def update_worker(uid: str, worker: WorkerCreate):
    """Update worker status"""
    for i, w in enumerate(db.get("workers", [])):
        if w["uid"].upper() == uid.upper() or (w["name"].lower() == worker.name.lower() and w["uid"] == "-"):
            db["workers"][i]["name"] = worker.name
            db["workers"][i]["dept"] = worker.dept
            db["workers"][i]["cert"] = worker.cert
            db["workers"][i]["status"] = worker.status
            if worker.uid != "-":
                db["workers"][i]["uid"] = worker.uid
            save_data(db)
            
            await manager.broadcast(json.dumps({
                "type": "update",
                "stations": db["stations"],
                "incidents": db["incidents"],
                "workers": db["workers"],
                "kpis": calc_kpis()
            }))
            
            return {"status": "success", "message": f"Worker {worker.name} diupdate"}
    
    raise HTTPException(status_code=404, detail=f"Worker dengan UID {uid} tidak ditemukan")

# === FRAME STREAMING ===
@app.post("/api/frame/{station_id}")
async def upload_frame(station_id: str, request: Request):
    """Menerima live frame JPEG dari Laptop"""
    body = await request.body()
    latest_frames[station_id] = body
    if station_id in frame_events:
        frame_events[station_id].set()
    return {"status": "success"}

async def frame_generator(station_id: str):
    last_frame = None
    timeout_counter = 0
    while True:
        frame = latest_frames.get(station_id)
        if frame and frame != last_frame:
            last_frame = frame
            timeout_counter = 0
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')
        else:
            timeout_counter += 1
            if timeout_counter > 200: 
                break
        await asyncio.sleep(0.05)

@app.get("/api/video_feed/{station_id}")
async def video_feed(station_id: str):
    return StreamingResponse(
        frame_generator(station_id), 
        media_type="multipart/x-mixed-replace; boundary=frame"
    )

if __name__ == "__main__":
    import uvicorn
    print("=" * 60)
    print("Starting WeldGuard Backend API...")
    print("Mendengarkan di port 8000")
    print("=" * 60)
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)

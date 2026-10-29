"""
WeldGuard — AI Inference Engine
================================
Core loop: Kamera → YOLOv8 → Violation Logic → Backend API + ESP32 Relay

Cara menjalankan:
    cd proyek/
    python inference_engine/inference.py

Pastikan sudah:
    1. pip install -r inference_engine/requirements.txt
       2. Letakkan best.pt di inference_engine/best.pt
    3. Jalankan backend: python backend/main.py (terminal terpisah)
    4. ESP32 sudah terhubung ke WiFi & IP-nya sudah diisi di config.py
"""

import cv2
import sys
import os
import time
import datetime
import threading
import requests
import json

# Tambahkan root proyek ke sys.path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from inference_engine import config as cfg

try:
    from ultralytics import YOLO
except ImportError:
    print("[ERROR] ultralytics belum terinstall!")
    print("        Jalankan: pip install ultralytics")
    sys.exit(1)


# ──────────────────────────────────────────────────────────────────
# HELPER: Hitung IoU dua bounding box [x1,y1,x2,y2]
# ──────────────────────────────────────────────────────────────────
def iou(boxA, boxB):
    xA = max(boxA[0], boxB[0])
    yA = max(boxA[1], boxB[1])
    xB = min(boxA[2], boxB[2])
    yB = min(boxA[3], boxB[3])
    inter = max(0, xB - xA) * max(0, yB - yA)
    if inter == 0:
        return 0.0
    areaA = (boxA[2]-boxA[0]) * (boxA[3]-boxA[1])
    areaB = (boxB[2]-boxB[0]) * (boxB[3]-boxB[1])
    return inter / float(areaA + areaB - inter)


# ──────────────────────────────────────────────────────────────────
# HELPER: Cek apakah APD box berada di dekat / overlap welder box
# ──────────────────────────────────────────────────────────────────
def is_apd_near_welder(welder_box, apd_box, ratio=cfg.APD_PROXIMITY_RATIO):
    """
    Expand welder_box sebesar `ratio` ke setiap sisi,
    lalu cek apakah apd_box ada di dalam expanded area itu.
    """
    wx1, wy1, wx2, wy2 = welder_box
    w = wx2 - wx1
    h = wy2 - wy1
    expand_x = w * ratio
    expand_y = h * ratio
    expanded = [wx1 - expand_x, wy1 - expand_y, wx2 + expand_x, wy2 + expand_y]

    ax1, ay1, ax2, ay2 = apd_box
    # Center point APD harus berada di dalam expanded welder area
    cx = (ax1 + ax2) / 2
    cy = (ay1 + ay2) / 2
    return (expanded[0] < cx < expanded[2]) and (expanded[1] < cy < expanded[3])


# ──────────────────────────────────────────────────────────────────
# HELPER: Kirim perintah relay ke ESP32 (async, tidak block inference)
# ──────────────────────────────────────────────────────────────────
def send_relay_command(url: str):
    if not cfg.ESP32_ENABLED:
        return
    def _send():
        try:
            r = requests.get(url, timeout=cfg.ESP32_TIMEOUT)
            state = "ON (arus diputus)" if "on" in url else "OFF (arus tersambung)"
            print(f"[ESP32] Relay {state} — HTTP {r.status_code}")
        except requests.exceptions.ConnectionError:
            print(f"[ESP32] ⚠ Tidak bisa konek ke ESP32 ({cfg.ESP32_IP})")
        except Exception as e:
            print(f"[ESP32] Error: {e}")
    threading.Thread(target=_send, daemon=True).start()


# ──────────────────────────────────────────────────────────────────
# HELPER: Kirim laporan insiden ke FastAPI backend (async)
# ──────────────────────────────────────────────────────────────────
def post_incident(missing_apd: list, snapshot_filename: str):
    now = datetime.datetime.now()
    payload = {
        "station"      : cfg.STATION_ID,
        "timestamp"    : now.isoformat(),
        "missing_apd"  : missing_apd,
        "snapshot_file": snapshot_filename,
        "severity"     : "high" if "welding_helmet" in missing_apd else "medium",
        "type"         : " + ".join(
            cfg.APD_DISPLAY_NAME.get(a, a) for a in missing_apd
        ) + " Tidak Terdeteksi",
    }
    def _post():
        try:
            r = requests.post(cfg.API_INCIDENT_ENDPOINT, json=payload, timeout=3)
            print(f"[BACKEND] Insiden dikirim → HTTP {r.status_code}")
        except Exception as e:
            print(f"[BACKEND] ⚠ Gagal kirim insiden: {e}")
    threading.Thread(target=_post, daemon=True).start()


# ──────────────────────────────────────────────────────────────────
# HELPER: Update status stasiun ke backend (setiap N detik)
# ──────────────────────────────────────────────────────────────────
def post_status(apd_status: dict, is_violation: bool):
    payload = {
        "station"     : cfg.STATION_ID,
        "timestamp"   : datetime.datetime.now().isoformat(),
        "is_violation": is_violation,
        "apd_status"  : apd_status,
        "machine"     : "ON",
    }
    def _post():
        try:
            requests.post(cfg.API_STATUS_ENDPOINT, json=payload, timeout=2)
        except Exception:
            pass  # Silent fail untuk status update
    threading.Thread(target=_post, daemon=True).start()


# ──────────────────────────────────────────────────────────────────
# HELPER: Simpan snapshot frame saat pelanggaran terkonfirmasi
# ──────────────────────────────────────────────────────────────────
def save_snapshot(frame) -> str:
    os.makedirs(cfg.SNAPSHOT_DIR, exist_ok=True)
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"incident_{cfg.STATION_ID}_{ts}.jpg"
    filepath = os.path.join(cfg.SNAPSHOT_DIR, filename)
    cv2.imwrite(filepath, frame, [cv2.IMWRITE_JPEG_QUALITY, cfg.SNAPSHOT_QUALITY])
    print(f"[SNAPSHOT] Tersimpan: {filepath}")
    return filename


# ──────────────────────────────────────────────────────────────────
# HELPER: Draw bounding box dengan label
# ──────────────────────────────────────────────────────────────────
def draw_box(frame, box, label, color, conf=None):
    x1, y1, x2, y2 = map(int, box)
    cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
    text = label if conf is None else f"{label} {conf:.0%}"
    (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.55, 1)
    cv2.rectangle(frame, (x1, y1 - th - 8), (x1 + tw + 6, y1), color, -1)
    cv2.putText(frame, text, (x1 + 3, y1 - 5),
                cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1, cv2.LINE_AA)


# ──────────────────────────────────────────────────────────────────
# HELPER: Overlay status panel di pojok kiri atas
# ──────────────────────────────────────────────────────────────────
def draw_status_panel(frame, apd_status: dict, violation_count: int, is_alarming: bool):
    h, w = frame.shape[:2]
    panel_x, panel_y = 10, 10
    line_h = 28
    panel_w = 260
    n_lines = len(cfg.REQUIRED_APD) + 3
    panel_h = n_lines * line_h + 16

    # Background semi-transparan
    overlay = frame.copy()
    cv2.rectangle(overlay, (panel_x, panel_y),
                  (panel_x + panel_w, panel_y + panel_h), (10, 10, 30), -1)
    cv2.addWeighted(overlay, 0.70, frame, 0.30, 0, frame)

    # Header
    header_color = (0, 50, 220) if is_alarming else (0, 180, 80)
    header_text  = "⚠ PELANGGARAN!" if is_alarming else "✓ APD LENGKAP"
    cv2.putText(frame, "WeldGuard K3", (panel_x + 8, panel_y + 20),
                cv2.FONT_HERSHEY_SIMPLEX, 0.55, (200, 200, 255), 1, cv2.LINE_AA)
    cv2.putText(frame, header_text, (panel_x + 8, panel_y + 44),
                cv2.FONT_HERSHEY_SIMPLEX, 0.60, header_color, 2, cv2.LINE_AA)

    # APD status rows
    for i, apd_cls in enumerate(cfg.REQUIRED_APD):
        ok    = apd_status.get(apd_cls, False)
        name  = cfg.APD_DISPLAY_NAME.get(apd_cls, apd_cls)
        icon  = "OK" if ok else "!!"
        color = (0, 200, 80) if ok else (0, 50, 220)
        y     = panel_y + 64 + i * line_h
        cv2.putText(frame, f"[{icon}] {name}", (panel_x + 12, y),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.50, color, 1, cv2.LINE_AA)

    # Frame counter / alarm progress
    prog_y = panel_y + 64 + len(cfg.REQUIRED_APD) * line_h + 8
    ratio  = min(violation_count / cfg.VIOLATION_FRAME_THRESHOLD, 1.0)
    bar_w  = int((panel_w - 24) * ratio)
    cv2.rectangle(frame, (panel_x + 12, prog_y),
                  (panel_x + panel_w - 12, prog_y + 10), (40, 40, 60), -1)
    if bar_w > 0:
        bar_color = (0, 50, 220) if ratio >= 1.0 else (0, 140, 220)
        cv2.rectangle(frame, (panel_x + 12, prog_y),
                      (panel_x + 12 + bar_w, prog_y + 10), bar_color, -1)
    pct_text = f"Frame: {violation_count}/{cfg.VIOLATION_FRAME_THRESHOLD}"
    cv2.putText(frame, pct_text, (panel_x + 12, prog_y + 24),
                cv2.FONT_HERSHEY_SIMPLEX, 0.42, (160, 160, 200), 1, cv2.LINE_AA)

    # Timestamp
    ts = datetime.datetime.now().strftime("%H:%M:%S")
    cv2.putText(frame, ts, (panel_x + 12, prog_y + 42),
                cv2.FONT_HERSHEY_SIMPLEX, 0.42, (120, 120, 160), 1, cv2.LINE_AA)


# ──────────────────────────────────────────────────────────────────
# HELPER: Dedicated Thread untuk Membaca Kamera (Anti-Lag / Buffer overflow)
# ──────────────────────────────────────────────────────────────────
class CameraStream:
    def __init__(self, mode, index, video_path):
        self.mode = mode
        if mode == "webcam":
            self.stream = cv2.VideoCapture(index)
            self.stream.set(cv2.CAP_PROP_FRAME_WIDTH, cfg.FRAME_WIDTH)
            self.stream.set(cv2.CAP_PROP_FRAME_HEIGHT, cfg.FRAME_HEIGHT)
            self.stream.set(cv2.CAP_PROP_FPS, cfg.TARGET_FPS)
        else:
            self.stream = cv2.VideoCapture(video_path)
        
        self.ret = False
        self.frame = None
        self.stopped = False
        self.lock = threading.Lock()

    def start(self):
        if not self.stream.isOpened():
            return self
        self.ret, self.frame = self.stream.read()
        threading.Thread(target=self.update, daemon=True).start()
        return self

    def update(self):
        while True:
            if self.stopped:
                self.stream.release()
                return
            ret, frame = self.stream.read()
            if not ret and self.mode == "video":
                self.stream.set(cv2.CAP_PROP_POS_FRAMES, 0)
                continue
            with self.lock:
                self.ret = ret
                self.frame = frame

    def read(self):
        with self.lock:
            return self.ret, self.frame.copy() if self.frame is not None else None

    def stop(self):
        self.stopped = True

# ──────────────────────────────────────────────────────────────────
# HELPER: Kirim Frame Live ke Backend (untuk Video Streaming di UI)
# ──────────────────────────────────────────────────────────────────
last_frame_bytes = None
frame_lock = threading.Lock()

def frame_sender_worker():
    while True:
        frame_to_send = None
        with frame_lock:
            frame_to_send = last_frame_bytes
        
        if frame_to_send:
            try:
                requests.post(f"{cfg.API_FRAME_ENDPOINT}/{cfg.STATION_ID}", 
                              data=frame_to_send, 
                              headers={'Content-Type': 'application/octet-stream'}, 
                              timeout=1.0)
            except Exception:
                pass
        time.sleep(0.04)  # Maksimal ~25 FPS

threading.Thread(target=frame_sender_worker, daemon=True).start()


# ──────────────────────────────────────────────────────────────────
# MAIN LOOP
# ──────────────────────────────────────────────────────────────────
def main():
    global last_frame_bytes
    
    print("=" * 60)
    print("  WeldGuard — AI Inference Engine")
    print("=" * 60)

    # --- Load Model ---
    model_path = os.path.abspath(cfg.MODEL_PATH)
    if not os.path.exists(model_path):
        print(f"[ERROR] Model tidak ditemukan: {model_path}")
        print("        Jalankan training di Google Colab dulu,")
        print("        lalu letakkan best.pt di inference_engine/best.pt")
        sys.exit(1)

    print(f"[INFO] Memuat model: {model_path}")
    model = YOLO(model_path)
    print(f"[INFO] Model dimuat. Kelas: {model.names}")

    # --- Buka Sumber Kamera (Background Thread) ---
    print(f"[INFO] Membuka kamera dengan multi-threading (Anti-Lag)...")
    cap = CameraStream(cfg.CAMERA_MODE, cfg.WEBCAM_INDEX, cfg.VIDEO_PATH).start()

    if not cap.stream.isOpened():
        source = f"webcam {cfg.WEBCAM_INDEX}" if cfg.CAMERA_MODE == "webcam" else cfg.VIDEO_PATH
        print(f"[ERROR] Tidak bisa membuka sumber kamera: {source}")
        sys.exit(1)

    actual_fps = cap.stream.get(cv2.CAP_PROP_FPS) or cfg.TARGET_FPS
    print(f"[INFO] FPS stream: {actual_fps:.1f}")
    print(f"[INFO] Stasiun: {cfg.STATION_ID}")
    print(f"[INFO] APD wajib: {cfg.REQUIRED_APD}")
    print(f"[INFO] Alarm threshold: {cfg.VIOLATION_FRAME_THRESHOLD} frame")
    print(f"[INFO] Backend: {cfg.BACKEND_URL}")
    print(f"[INFO] ESP32: {'AKTIF (' + cfg.ESP32_IP + ')' if cfg.ESP32_ENABLED else 'NONAKTIF'}")
    print("\n  Tekan 'q' untuk keluar, 's' untuk snapshot manual\n")

    # --- State Variables ---
    violation_frame_count = 0     # Counter frame pelanggaran berturut-turut
    clear_frame_count     = 0     # Counter frame bersih berturut-turut
    is_alarming           = False # Apakah alarm sedang aktif
    last_status_time      = 0.0   # Waktu terakhir kirim status ke backend
    last_missing_apd      = []    # APD yang terakhir missing
    snapshot_taken        = False # Cegah snapshot ganda untuk 1 insiden

    frame_count = 0

    while True:
        ret, frame = cap.read()
        if not ret or frame is None:
            time.sleep(0.01)
            continue

        frame_count += 1
        display_frame = frame.copy()

        # ── Jalankan YOLOv8 Inference ──
        results = model(
            frame,
            conf=cfg.CONFIDENCE_THRESHOLD,
            iou=cfg.IOU_THRESHOLD,
            verbose=False,
        )[0]

        # ── Parse deteksi ──
        welder_boxes = []  # Semua bbox welder di frame ini
        apd_boxes    = {}  # {class_name: [bbox, ...]}

        for det in results.boxes:
            cls_id  = int(det.cls[0])
            cls_name = cfg.CLASS_NAMES[cls_id] if cls_id < len(cfg.CLASS_NAMES) else str(cls_id)
            conf    = float(det.conf[0])
            box     = det.xyxy[0].tolist()  # [x1, y1, x2, y2]

            if cls_name == "welder":
                welder_boxes.append(box)
                draw_box(display_frame, box, "WELDER", cfg.COLOR_WELDER, conf)

            elif cls_name == "non_welder":
                # Orang bukan welder — abaikan untuk cek APD
                draw_box(display_frame, box, "non-welder", (128, 128, 128), conf)

            elif cls_name in cfg.REQUIRED_APD:
                apd_boxes.setdefault(cls_name, []).append(box)
                draw_box(display_frame, box, cfg.APD_DISPLAY_NAME.get(cls_name, cls_name),
                         cfg.COLOR_APD_OK, conf)

            else:
                # APD lain (face shield, boots, dll) — tampilkan tapi tidak dicek wajib
                display_name = cfg.APD_DISPLAY_NAME.get(cls_name, cls_name)
                draw_box(display_frame, box, display_name, (200, 160, 0), conf)

        # ── Cek Pelanggaran APD per Welder ──
        current_missing: list = []
        apd_status: dict = {apd: False for apd in cfg.REQUIRED_APD}

        if welder_boxes:
            for w_box in welder_boxes:
                has_face_protection = False
                for apd_cls in cfg.REQUIRED_APD:
                    if apd_cls in apd_boxes:
                        near = any(is_apd_near_welder(w_box, a_box) for a_box in apd_boxes[apd_cls])
                        if near:
                            apd_status[apd_cls] = True
                            has_face_protection = True
                        else:
                            apd_status[apd_cls] = False
                    else:
                        apd_status[apd_cls] = False

                if not has_face_protection:
                    # Tidak pakai pelindung wajah satupun
                    if "Pelindung Wajah" not in current_missing:
                        current_missing.append("Pelindung Wajah")
        else:
            # Tidak ada welder di frame — reset counter, tidak ada pelanggaran
            apd_status = {apd: True for apd in cfg.REQUIRED_APD}

        # ── Frame Buffer Logic ──
        if current_missing and welder_boxes:
            violation_frame_count += 1
            clear_frame_count      = 0
            last_missing_apd       = current_missing
        else:
            clear_frame_count      += 1
            violation_frame_count   = max(0, violation_frame_count - 1)

        # ── Aktifkan Alarm ──
        if violation_frame_count >= cfg.VIOLATION_FRAME_THRESHOLD and not is_alarming:
            is_alarming    = True
            snapshot_taken = False  # Reset untuk insiden baru
            print(f"\n🚨 ALARM AKTIF! APD missing: {last_missing_apd}")

            # Putuskan arus mesin via ESP32
            send_relay_command(cfg.ESP32_RELAY_ON)

        # ── Nonaktifkan Alarm ──
        if is_alarming and clear_frame_count >= cfg.CLEAR_FRAME_THRESHOLD:
            is_alarming           = False
            violation_frame_count = 0
            print("\n✅ APD lengkap kembali. Alarm dimatikan.")

            # Sambungkan kembali arus mesin
            send_relay_command(cfg.ESP32_RELAY_OFF)

        # ── Ambil Snapshot & Kirim Insiden (sekali per alarm) ──
        if is_alarming and not snapshot_taken:
            snap_file = save_snapshot(frame)
            post_incident(last_missing_apd, snap_file)
            snapshot_taken = True

        # ── Update Status ke Backend (throttled) ──
        now = time.time()
        if now - last_status_time >= cfg.STATUS_UPDATE_INTERVAL:
            post_status(apd_status, is_alarming)
            last_status_time = now

        # ── Tampilan ──
        draw_status_panel(display_frame, apd_status, violation_frame_count, is_alarming)

        # Flash frame merah saat alarm aktif
        if is_alarming and (frame_count % 20 < 10):
            overlay = display_frame.copy()
            cv2.rectangle(overlay, (0, 0),
                          (display_frame.shape[1], display_frame.shape[0]),
                          (0, 0, 180), -1)
            cv2.addWeighted(overlay, 0.12, display_frame, 0.88, 0, display_frame)

        if cfg.SHOW_PREVIEW:
            cv2.imshow(cfg.WINDOW_NAME, display_frame)

        # Encode dan simpan frame untuk dikirim ke backend (Live Streaming)
        ret_enc, buffer = cv2.imencode('.jpg', display_frame, [cv2.IMWRITE_JPEG_QUALITY, 75])
        if ret_enc:
            with frame_lock:
                last_frame_bytes = buffer.tobytes()

        key = cv2.waitKey(1) & 0xFF
        if key == ord('q'):
            print("[INFO] Keluar dari inference engine.")
            break
        elif key == ord('s'):
            # Snapshot manual
            f = save_snapshot(frame)
            print(f"[INFO] Snapshot manual: {f}")

    cap.stop()
    cv2.destroyAllWindows()

    # Pastikan relay OFF saat program berhenti
    if cfg.ESP32_ENABLED:
        send_relay_command(cfg.ESP32_RELAY_OFF)
    print("[INFO] Inference engine berhenti.")


if __name__ == "__main__":
    main()

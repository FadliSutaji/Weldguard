import cv2
import sys
import os
import time
import datetime
import threading
import requests
import serial
import json

# ── Konfigurasi ── 
# Path model otomatis menunjuk ke folder script ini berada
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
MODEL_PATH = os.path.join(SCRIPT_DIR, "best.pt")

# Ganti dengan IP Publik VPS kamu setelah deploy!
# Contoh: "http://103.123.45.67"
BACKEND_URL = "http://100.99.34.23:30800"
API_SCAN_ENDPOINT  = f"{BACKEND_URL}/api/scan"
API_FRAME_ENDPOINT = f"{BACKEND_URL}/api/frame/LAS-01"
STATION_ID = "LAS-01"

# Sesuaikan dengan port COM ESP32 kamuq
# Windows: COM3, COM4, dll. | Linux/Mac: /dev/ttyUSB0
SERIAL_PORT = "COM8"
BAUD_RATE = 115200

# Konfigurasi APD — Hanya cek Kacamata Las
# Salah satu dari class berikut dianggap sebagai "memakai kacamata las"
GLASSES_CLASSES = {"welding_helmet"}
REQUIRED_APD = ["kacamata_las"]  # Label tampilan
CLASS_NAMES = [
    "face_shield",
    "non_welder",
    "protective_suit",
    "respirator",
    "safety_glasses",
    "welder",
    "welding_apron",
    "welding_boots",
    "welding_cap",
    "welding_gloves",
    "welding_helmet",
    "welding_jacket"
]

try:
    from ultralytics import YOLO
except ImportError:
    print("[ERROR] ultralytics belum terinstall!")
    sys.exit(1)

# Inisialisasi Serial
def safe_serial_write(data: bytes):
    """Kirim data ke serial dengan error handling"""
    global ser
    try:
        if ser and ser.is_open:
            ser.write(data)
            return True
    except Exception as e:
        print(f"[SERIAL] ⚠ Gagal menulis ke serial: {e}")
        # Coba reconnect
        try:
            ser.close()
        except:
            pass
        try:
            ser = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=0.1, write_timeout=1)
            print(f"[SERIAL] Reconnected ke {SERIAL_PORT}")
        except:
            ser = None
    return False

try:
    ser = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=0.1, write_timeout=1)
    print(f"[INFO] Terhubung ke ESP32 di port {SERIAL_PORT}")
except Exception as e:
    print(f"[ERROR] Gagal membuka port {SERIAL_PORT}: {e}")
    ser = None

# Global state untuk frame terakhir
last_frame_bytes = None
frame_lock = threading.Lock()
current_missing_apd = []
current_apd_ok = False
last_relay_state = None  # Lacak status relay terakhir agar tidak spam serial

def frame_sender_worker():
    """Mengirim live frame ke backend untuk stream di website"""
    while True:
        frame_to_send = None
        with frame_lock:
            frame_to_send = last_frame_bytes
        
        if frame_to_send:
            try:
                requests.post(API_FRAME_ENDPOINT, 
                              data=frame_to_send, 
                              headers={'Content-Type': 'application/octet-stream'}, 
                              timeout=3.0)
            except Exception as e:
                print(f"[STREAM ERROR] Gagal mengirim frame: {e}")
        time.sleep(0.1)  # Sekitar 10 FPS (agar Tailscale tidak kewalahan)

def relay_command_poller():
    """Mengecek command relay pending dari backend secara berkala"""
    global ser
    url = f"{BACKEND_URL}/api/relay/pending/{STATION_ID}"
    while True:
        try:
            r = requests.get(url, timeout=2.0)
            if r.status_code == 200:
                data = r.json()
                command = data.get("command")
                if command in ["on", "off"]:
                    print(f"\n[RELAY] Menerima command dari Web: {command.upper()}")
                    if ser and ser.is_open:
                        if command == "on":
                            safe_serial_write(b"RELAY_ON\n")
                            print("[RELAY] Serial sent: RELAY_ON")
                        else:
                            safe_serial_write(b"RELAY_OFF\n")
                            print("[RELAY] Serial sent: RELAY_OFF")
                    else:
                        print("[RELAY] Serial port tidak terbuka, gagal mengirim command")
        except Exception as e:
            pass
        time.sleep(1.5)

threading.Thread(target=frame_sender_worker, daemon=True).start()
threading.Thread(target=relay_command_poller, daemon=True).start()

def process_scan(uid: str, frame):
    """Memproses saat kartu di-tap: Cek status APD, trigger Relay, kirim ke Backend"""
    global current_apd_ok, current_missing_apd
    print(f"\n[SCAN] Pekerja tap kartu RFID: {uid}")
    
    status_apd = "ALLOWED" if current_apd_ok else "DENIED"
    missing_str = ", ".join(current_missing_apd)
    
    print(f"[SCAN] Status APD: {status_apd} | Missing: {missing_str}")
    
    # 1. Kirim perintah ke ESP32
    if ser and ser.is_open:
        if status_apd == "ALLOWED":
            safe_serial_write(b"RELAY_ON\n")  # Nyalakan mesin
        else:
            safe_serial_write(b"RELAY_OFF\n") # Matikan mesin
    
    # 2. Encode gambar
    ret_enc, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
    if not ret_enc:
        return
        
    # 3. Kirim data ke Backend VPS
    try:
        files = {
            'image': ('snapshot.jpg', buffer.tobytes(), 'image/jpeg')
        }
        data = {
            'station_id': STATION_ID,
            'rfid_uid': uid,
            'status_apd': status_apd,
            'missing_apd': missing_str
        }
        r = requests.post(API_SCAN_ENDPOINT, data=data, files=files, timeout=3.0)
        print(f"[BACKEND] Sinkronisasi berhasil: {r.status_code}")
    except Exception as e:
        print(f"[BACKEND] Gagal sinkronisasi: {e}")

def send_status_update(apd_ok, frame):
    """Kirim update status real-time ke backend VPS (tanpa perlu RFID)"""
    try:
        status_apd = "ALLOWED" if apd_ok else "DENIED"
        missing_str = "" if apd_ok else "kacamata_las"
        ret_enc, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
        if not ret_enc:
            return
        files = {'image': ('snapshot.jpg', buffer.tobytes(), 'image/jpeg')}
        data = {
            'station_id': STATION_ID,
            'rfid_uid': 'AUTO-AI',
            'status_apd': status_apd,
            'missing_apd': missing_str
        }
        r = requests.post(API_SCAN_ENDPOINT, data=data, files=files, timeout=3.0)
        print(f"[AI→VPS] Status update: {status_apd} | Response: {r.status_code}")
    except Exception as e:
        print(f"[AI→VPS] Gagal kirim update: {e}")

def main():
    global last_frame_bytes, current_apd_ok, current_missing_apd, last_relay_state
    print("[INFO] Memuat model YOLO...")
    if not os.path.exists(MODEL_PATH):
        print(f"[ERROR] Model {MODEL_PATH} tidak ditemukan.")
        sys.exit(1)
        
    model = YOLO(MODEL_PATH)
    
    print("[INFO] Membuka Webcam...")
    cap = cv2.VideoCapture(0) # 0 untuk webcam bawaan
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
    
    if not cap.isOpened():
        print("[ERROR] Kamera gagal dibuka.")
        sys.exit(1)
        
    print("[INFO] Inference Engine Berjalan. Menunggu tap RFID...")
    
    while True:
        ret, frame = cap.read()
        if not ret:
            continue
            
        display_frame = frame.copy()
        
        # ── Jalankan YOLOv8 Inference ──
        results = model(frame, conf=0.6, iou=0.45, verbose=False)[0]
        
        detected_classes = set()
        glasses_detected = False
        for det in results.boxes:
            cls_id = int(det.cls[0])
            cls_name = model.names[cls_id] if cls_id in model.names else str(cls_id)
            conf = float(det.conf[0])
            x1, y1, x2, y2 = map(int, det.xyxy[0].tolist())
            
            detected_classes.add(cls_name)
            
            # Cek apakah class ini termasuk kacamata las
            if cls_name in GLASSES_CLASSES:
                glasses_detected = True
            
            # Gambar bounding box
            color = (0, 255, 0) if cls_name in GLASSES_CLASSES else (255, 0, 0)
            cv2.rectangle(display_frame, (x1, y1), (x2, y2), color, 2)
            cv2.putText(display_frame, f"{cls_name} {conf:.2f}", (x1, y1-10), cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)
        
        # ── Cek Kacamata Las ──
        current_apd_ok = glasses_detected
        current_missing_apd = [] if glasses_detected else ["kacamata_las"]
        
        # ── REAL-TIME RELAY CONTROL ──
        # Kirim perintah ke Arduino HANYA jika status berubah
        if last_relay_state is None or last_relay_state != current_apd_ok:
            if ser and ser.is_open:
                if current_apd_ok:
                    safe_serial_write(b"RELAY_ON\n")
                    print(f"\n[AI→RELAY] Kacamata Las TERDETEKSI → RELAY ON (Mesin Menyala)")
                else:
                    safe_serial_write(b"RELAY_OFF\n")
                    print(f"\n[AI→RELAY] Kacamata Las TIDAK ADA → RELAY OFF (Mesin Mati)")
            # Kirim status update ke VPS secara async
            threading.Thread(target=send_status_update, args=(current_apd_ok, display_frame.copy()), daemon=True).start()
            last_relay_state = current_apd_ok
        
        # Overlay status di pojok (Disesuaikan untuk 1280x720)
        status_color = (0, 255, 0) if current_apd_ok else (0, 0, 255)
        status_text = "KACAMATA LAS: OK" if current_apd_ok else "KACAMATA LAS: TIDAK TERDETEKSI"
        cv2.putText(display_frame, status_text, (20, 50), cv2.FONT_HERSHEY_SIMPLEX, 1.0, status_color, 3)
        
        # Encode frame untuk stream
        ret_enc, buffer = cv2.imencode('.jpg', display_frame, [cv2.IMWRITE_JPEG_QUALITY, 60])
        if ret_enc:
            with frame_lock:
                last_frame_bytes = buffer.tobytes()
        
        cv2.imshow("WeldGuard Edge AI", display_frame)
        
        # Cek data Serial dari ESP32 (RFID Tap)
        if ser and ser.in_waiting > 0:
            try:
                line = ser.readline().decode('utf-8').strip()
                if line.startswith("UID:"):
                    uid = line.split("UID:")[1]
                    # Proses dalam thread agar video tidak freeze
                    threading.Thread(target=process_scan, args=(uid, display_frame.copy()), daemon=True).start()
            except Exception as e:
                pass
        
        key = cv2.waitKey(1) & 0xFF
        if key == ord('q'):
            print("\n[INFO] Menutup kamera...")
            break
        elif key == ord('c'):
            print("\n[INFO] 📸 CAPTURE MANUAL! Menyimpan bukti foto...")
            # Mengirim frame saat ini ke backend sebagai manual capture
            threading.Thread(target=send_status_update, args=(False, display_frame.copy()), daemon=True).start()
            
    cap.release()
    cv2.destroyAllWindows()
    if ser:
        ser.close()

if __name__ == "__main__":
    main()

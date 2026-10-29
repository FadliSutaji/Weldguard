"""
WeldGuard — Konfigurasi Inference Engine
Ubah nilai-nilai di sini sesuai setup hardware kamu.
"""

# MODEL
MODEL_PATH = "inference_engine/best.pt"
CONFIDENCE_THRESHOLD = 0.50
IOU_THRESHOLD = 0.45

# KAMERA
# "webcam" = USB/laptop camera, "video" = file .mp4
CAMERA_MODE  = "webcam"
WEBCAM_INDEX = 0
VIDEO_PATH   = "sample_video.mp4"
FRAME_WIDTH  = 1280
FRAME_HEIGHT = 720
TARGET_FPS   = 25

# STASIUN
STATION_ID = "LAS-01"

# VIOLATION LOGIC
# ~30 frame ≈ 1.2 detik @25FPS — hindari false alarm
VIOLATION_FRAME_THRESHOLD = 30
CLEAR_FRAME_THRESHOLD     = 15

# APD wajah yang akan dideteksi
REQUIRED_APD = ["welding_helmet"]

# Kelas dataset Safeweld v15 (urutan sesuai data.yaml)
CLASS_NAMES = [
    "face_shield",    # 0
    "non_welder",     # 1
    "protective_suit",# 2
    "respirator",     # 3
    "safety_glasses", # 4
    "welder",         # 5
    "welding_apron",  # 6
    "welding_boots",  # 7
    "welding_cap",    # 8
    "welding_gloves", # 9
    "welding_helmet", # 10
    "welding_jacket", # 11
]

APD_DISPLAY_NAME = {
    "welding_helmet" : "Helm Las",
    "welding_gloves" : "Sarung Tangan",
    "welding_apron"  : "Apron Las",
    "face_shield"    : "Face Shield",
    "protective_suit": "Baju Pelindung",
    "respirator"     : "Respirator",
    "safety_glasses" : "Kacamata Safety",
    "welding_boots"  : "Sepatu Safety",
    "welding_cap"    : "Pelindung Kepala",
    "welding_jacket" : "Jaket Las",
}

# Jarak deteksi APD relatif terhadap bbox welder
APD_PROXIMITY_RATIO = 0.8

# BACKEND API
BACKEND_URL             = "http://100.99.34.23:30800"
API_INCIDENT_ENDPOINT   = f"{BACKEND_URL}/api/incidents"
API_STATUS_ENDPOINT     = f"{BACKEND_URL}/api/status"
API_FRAME_ENDPOINT      = f"{BACKEND_URL}/api/frame"
SNAPSHOT_DIR            = "backend/snapshots"
STATUS_UPDATE_INTERVAL  = 2.0  # detik

# ESP32 RELAY
# Pastikan ESP32 dan PC di jaringan WiFi yang sama!
ESP32_ENABLED = False
ESP32_IP      = "192.168.1.100"   # ← Ganti dengan IP ESP32 (cek Serial Monitor)
ESP32_PORT    = 80
ESP32_URL     = f"http://{ESP32_IP}:{ESP32_PORT}"
ESP32_RELAY_ON  = f"{ESP32_URL}/relay/on"   # Putuskan arus mesin
ESP32_RELAY_OFF = f"{ESP32_URL}/relay/off"  # Sambungkan arus mesin
ESP32_TIMEOUT   = 3  # detik

# TAMPILAN OpenCV
SHOW_PREVIEW = True
WINDOW_NAME  = "WeldGuard — AI Detection"
COLOR_WELDER   = (0, 200, 255)   # Kuning
COLOR_APD_OK   = (0, 255, 100)   # Hijau
COLOR_APD_MISS = (0, 50, 255)    # Merah

# SNAPSHOT
SNAPSHOT_QUALITY = 85  # JPEG quality 0-100

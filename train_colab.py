"""
╔══════════════════════════════════════════════════════════════════╗
║       WeldGuard — Training Script (Google Colab)                 ║
║       Dataset: Safeweld v15 (YOLOv8 format, 12 kelas)           ║
╚══════════════════════════════════════════════════════════════════╝

PANDUAN PENGGUNAAN:
1. Buka Google Colab (https://colab.research.google.com) -> New Notebook
2. Aktifkan GPU: Menu "Runtime" -> "Change runtime type" -> Pilih "T4 GPU"
3. Copy setiap block CELL di bawah ini ke dalam cell Colab
4. Jalankan berurutan dari Cell 1 sampai Cell 6
"""

# =================================================================
# CELL 1: Install Dependencies
# =================================================================
"""
Copy code di bawah ini ke Cell 1 Colab dan jalankan:
"""
# !pip install ultralytics roboflow -q
# !pip install torch torchvision --index-url https://download.pytorch.org/whl/cu118 -q
# import torch
# print(f"GPU Aktif: {torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'TIDAK ADA GPU'}")


# =================================================================
# CELL 2: Download Dataset dari Roboflow API
# =================================================================
"""
Copy code di bawah ini ke Cell 2 Colab dan jalankan:
(Ini lebih mudah daripada upload ZIP manual karena internet Google Colab sangat cepat)
"""
# import os
# from roboflow import Roboflow
# 
# # Setup folder
# os.makedirs('/content/welding_dataset', exist_ok=True)
# 
# # Tarik dataset dari Roboflow (ganti YOUR_API_KEY dengan API Key dari akun Roboflow kamu)
# rf = Roboflow(api_key="YOUR_API_KEY_DISINI")
# project = rf.workspace("josephs-workspace-gaago").project("safeweld-cb24e")
# version = project.version(15)
# dataset = version.download("yolov8", location="/content/welding_dataset")
# 
# print("Dataset berhasil didownload ke:", dataset.location)


# =================================================================
# CELL 3: Fix Path di data.yaml
# =================================================================
"""
Copy code di bawah ini ke Cell 3 Colab dan jalankan:
(Ini penting agar YOLO tahu persis letak gambar)
"""
# import yaml
# 
# DATASET_PATH = '/content/welding_dataset'
# yaml_file = f'{DATASET_PATH}/data.yaml'
# 
# with open(yaml_file, 'r') as f:
#     data = yaml.safe_load(f)
# 
# # Update path ke absolut folder Colab
# data['train'] = f'{DATASET_PATH}/train/images'
# data['val']   = f'{DATASET_PATH}/valid/images'
# data['test']  = f'{DATASET_PATH}/test/images'
# 
# with open(yaml_file, 'w') as f:
#     yaml.dump(data, f, default_flow_style=False)
# 
# print("File data.yaml sudah di-update!")


# =================================================================
# CELL 4: Mulai Training YOLOv8
# =================================================================
"""
Copy code di bawah ini ke Cell 4 Colab dan jalankan:
"""
# from ultralytics import YOLO
# 
# # Load pre-trained YOLOv8 Nano (paling ringan dan cepat untuk IoT)
# model = YOLO('yolov8n.pt')
# 
# # Mulai training
# results = model.train(
#     data='/content/welding_dataset/data.yaml',
#     epochs=50,          # Latih selama 50 putaran
#     imgsz=640,          # Resolusi gambar
#     batch=16,           # Sesuai kapasitas VRAM Colab T4
#     name='safeweld_model',
#     project='/content/runs',
#     device=0,           # Menggunakan GPU
#     patience=15         # Early stop jika 15 epoch tidak ada perbaikan
# )
# 
# print("Training selesai!")


# =================================================================
# CELL 5: Evaluasi Akurasi (Opsional)
# =================================================================
"""
Copy code di bawah ini ke Cell 5 Colab dan jalankan:
"""
# metrics = model.val(
#     data='/content/welding_dataset/data.yaml',
#     split='test',
#     imgsz=640,
#     device=0
# )
# print(f"Akurasi mAP50: {metrics.box.map50:.4f}")


# =================================================================
# CELL 6: Download Hasil Model ke PC
# =================================================================
"""
Copy code di bawah ini ke Cell 6 Colab dan jalankan:
(Mendownload best.pt otomatis ke PC kamu)
"""
# from google.colab import files
# 
# model_path = '/content/runs/safeweld_model/weights/best.pt'
# print(f"Mendownload model terbaik: {model_path} ...")
# files.download(model_path)

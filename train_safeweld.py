"""
WeldGuard — Local Training Script
=================================
Script untuk melatih model YOLOv8 secara lokal menggunakan dataset Safeweld v15.

Pastikan sebelum menjalankan ini, Anda telah menginstall:
pip install ultralytics roboflow opencv-python torch torchvision

Cara menjalankan:
python train_safeweld.py
"""

import os
import yaml
from ultralytics import YOLO
import torch

def setup_dataset():
    """
    Menyiapkan path absolute untuk dataset di data.yaml
    agar ultralytics bisa menemukan dataset dengan benar.
    """
    # Path dataset (asumsi script ini berada di root proyek)
    base_dir = os.path.dirname(os.path.abspath(__file__))
    dataset_dir = os.path.join(base_dir, "welding_dataset")
    yaml_path = os.path.join(dataset_dir, "data.yaml")
    
    if not os.path.exists(yaml_path):
        print(f"[ERROR] data.yaml tidak ditemukan di {yaml_path}")
        print("Pastikan folder 'welding_dataset' ada di root proyek dan berisi dataset.")
        return None

    # Baca yaml asli
    with open(yaml_path, 'r') as f:
        data = yaml.safe_load(f)

    # Update path ke absolut
    data['path'] = dataset_dir  # Base path untuk yolov8
    data['train'] = os.path.join(dataset_dir, 'train', 'images')
    data['val']   = os.path.join(dataset_dir, 'valid', 'images')
    data['test']  = os.path.join(dataset_dir, 'test', 'images')

    # Tulis ulang
    with open(yaml_path, 'w') as f:
        yaml.dump(data, f, default_flow_style=False)

    print("[INFO] data.yaml berhasil diupdate dengan path absolut.")
    return yaml_path

def train_model(yaml_path):
    print("=" * 60)
    print("Mulai proses training YOLOv8...")
    print(f"PyTorch version: {torch.__version__}")
    print(f"CUDA available:  {torch.cuda.is_available()}")
    if torch.cuda.is_available():
        print(f"GPU:             {torch.cuda.get_device_name(0)}")
    print("=" * 60)

    # Load pre-trained model nano (paling ringan)
    model = YOLO('yolov8n.pt')

    # Mulai training
    # Sesuaikan parameter batch dan epochs jika perlu
    # Jika tidak menggunakan GPU (CUDA false), proses akan sangat lama (bisa berjam-jam)
    device = 0 if torch.cuda.is_available() else 'cpu'
    
    print(f"[INFO] Menggunakan device: {device}")
    
    results = model.train(
        data=yaml_path,
        epochs=50,          # Cukup untuk fine-tuning dataset ~2000 gambar
        imgsz=640,          # Ukuran gambar
        batch=8,            # Kecilkan jika memori GPU/RAM terbatas (contoh: 4 atau 8)
        name='safeweld_local',
        device=device,
        patience=15,        # Early stopping
        workers=2           # Jumlah thread untuk data loading (turunkan jika error memori/CPU di Windows)
    )

    print("\n✅ Training selesai!")
    print("Model terbaik (best.pt) tersimpan di folder: runs/detect/safeweld_local/weights/")
    print("Silakan copy file 'best.pt' tersebut ke dalam folder 'inference_engine/'.")

if __name__ == "__main__":
    yaml_path = setup_dataset()
    if yaml_path:
        train_model(yaml_path)

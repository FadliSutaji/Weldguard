/*
  WeldGuard — Arduino Uno USB Serial RFID & Relay Controller
  Menghubungkan Arduino Uno dengan Laptop/PC menggunakan kabel USB (Serial).
  - Membaca RFID MFRC522 dan mengirim UID ke Laptop.
  - Menerima string "RELAY_ON\n" atau "RELAY_OFF\n" dari Laptop untuk mengontrol Relay.
*/

#include <SPI.h>
#include <MFRC522.h>

// --- KONFIGURASI PIN UNTUK ARDUINO UNO ---
// Pin SPI Wajib di Arduino Uno: SCK = 13, MISO = 12, MOSI = 11
#define SS_PIN    10  // SDA pin untuk RFID MFRC522
#define RST_PIN   9   // RST pin untuk RFID MFRC522
#define RELAY_PIN 7   // Pin Output ke IN Relay

// Biasanya modul relay aktif LOW (LOW = Relay tertutup / arus tersambung)
// Ubah jika relay kamu tipe aktif HIGH
const int RELAY_ON_STATE = LOW;   
const int RELAY_OFF_STATE = HIGH; 

MFRC522 mfrc522(SS_PIN, RST_PIN);

void setRelay(bool turnOn) {
  pinMode(RELAY_PIN, OUTPUT);
  if (turnOn) {
    digitalWrite(RELAY_PIN, RELAY_ON_STATE);
  } else {
    digitalWrite(RELAY_PIN, RELAY_OFF_STATE);
  }
}

void setup() {
  Serial.begin(115200);
  
  // Posisi awal: Mesin mati (arus terputus)
  setRelay(false);
  
  // Inisialisasi SPI & RFID
  SPI.begin();
  mfrc522.PCD_Init();
  
  Serial.println("[INFO] WeldGuard Arduino Uno Serial Interface Berjalan.");
  Serial.println("[INFO] Silakan tap kartu RFID...");

  // === TES RELAY SAAT BOOT ===
  Serial.println("[TEST] Memulai tes relay 3x ceklek...");
  for (int i = 0; i < 3; i++) {
    Serial.print("[TEST] Relay ON - ceklek ");
    Serial.println(i + 1);
    setRelay(true);
    delay(500);
    
    Serial.print("[TEST] Relay OFF ");
    Serial.println(i + 1);
    setRelay(false);
    delay(500);
  }
  Serial.println("[TEST] Tes relay selesai.");
}

void loop() {
  // 1. CEK DATA DARI LAPTOP (SERIAL RX)
  if (Serial.available() > 0) {
    String command = Serial.readStringUntil('\n');
    command.trim();
    
    if (command == "RELAY_ON") {
      setRelay(true);
      // Serial.println("[UNO] Mesin Dinyalakan (Aman)");
    } 
    else if (command == "RELAY_OFF") {
      setRelay(false);
      // Serial.println("[UNO] Mesin Dimatikan (Pelanggaran/Selesai)");
    }
  }

  // 2. CEK KARTU RFID (TAP)
  if (mfrc522.PICC_IsNewCardPresent() && mfrc522.PICC_ReadCardSerial()) {
    String uid = "";
    for (byte i = 0; i < mfrc522.uid.size; i++) {
      uid += String(mfrc522.uid.uidByte[i] < 0x10 ? "0" : "");
      uid += String(mfrc522.uid.uidByte[i], HEX);
    }
    uid.toUpperCase();
    
    // Kirim UID ke Laptop melalui Serial
    Serial.println("UID:" + uid);
    
    // Beri delay agar tidak double tap dalam waktu singkat
    delay(2000); 
  }
}
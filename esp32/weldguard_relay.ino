/*
  WeldGuard — ESP32 Relay Controller
  Menerima HTTP Request dari Inference Engine untuk memutus/menyambung arus mesin las.
*/

#include <WiFi.h>
#include <WebServer.h>

// --- KONFIGURASI WIFI ---
const char* ssid = "NAMA_WIFI_KAMU";       // Ganti dengan SSID WiFi kamu
const char* password = "PASSWORD_WIFI_KAMU"; // Ganti dengan password WiFi kamu

// --- PIN KONFIGURASI ---
// Pin relay (sesuaikan dengan koneksi pin di ESP32 kamu, misal GPIO 26)
const int RELAY_PIN = 26; 

// Indikator LED built-in (biasanya GPIO 2)
const int LED_PIN = 2;

// Jika menggunakan relay modul, biasanya relay aktif LOW (Low = ON)
// Ubah jika relay kamu aktif HIGH
const int RELAY_ON_STATE = LOW;   
const int RELAY_OFF_STATE = HIGH;

WebServer server(80);

void setup() {
  Serial.begin(115200);
  delay(100);

  // Inisialisasi Pin
  pinMode(RELAY_PIN, OUTPUT);
  pinMode(LED_PIN, OUTPUT);
  
  // Posisi awal: Mesin menyala (arus tersambung)
  digitalWrite(RELAY_PIN, RELAY_OFF_STATE); 
  digitalWrite(LED_PIN, LOW);

  // Koneksi WiFi
  Serial.print("Menghubungkan ke ");
  Serial.println(ssid);
  WiFi.begin(ssid, password);

  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }

  Serial.println("");
  Serial.println("WiFi Terhubung!");
  Serial.print("IP Address ESP32: ");
  Serial.println(WiFi.localIP()); 
  // CATAT IP ADDRESS INI, MASUKKAN KE inference_engine/config.py

  // Routing HTTP Server
  server.on("/", handleRoot);
  server.on("/relay/on", handleRelayOn);    // Trigger untuk PELANGGARAN (Matikan Mesin)
  server.on("/relay/off", handleRelayOff);  // Trigger untuk AMAN (Nyalakan Mesin)

  server.begin();
  Serial.println("HTTP Server siap melayani!");
}

void loop() {
  server.handleClient();
}

// --- Handler Functions ---

void handleRoot() {
  server.send(200, "text/plain", "WeldGuard ESP32 Relay API Status: Online");
}

void handleRelayOn() {
  // PELANGGARAN TERDETEKSI: Putuskan arus mesin!
  Serial.println("[ALARM] Pelanggaran! Memutus arus mesin las...");
  digitalWrite(RELAY_PIN, RELAY_ON_STATE);
  digitalWrite(LED_PIN, HIGH); // LED Menyala tanda alarm
  
  // Kirim response CORS agar bisa diakses dari mana saja (termasuk dashboard jika perlu)
  server.sendHeader("Access-Control-Allow-Origin", "*");
  server.send(200, "application/json", "{\"status\": \"success\", \"relay\": \"ON\", \"mesin\": \"MATI\"}");
}

void handleRelayOff() {
  // KONDISI AMAN: Sambungkan kembali arus mesin
  Serial.println("[AMAN] APD lengkap. Arus mesin las tersambung kembali.");
  digitalWrite(RELAY_PIN, RELAY_OFF_STATE);
  digitalWrite(LED_PIN, LOW); // LED Mati tanda aman
  
  server.sendHeader("Access-Control-Allow-Origin", "*");
  server.send(200, "application/json", "{\"status\": \"success\", \"relay\": \"OFF\", \"mesin\": \"NYALA\"}");
}

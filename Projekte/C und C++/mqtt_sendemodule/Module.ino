#include <Arduino.h>
#include <Wire.h>
#include <Adafruit_ADS1X15.h>
#include <ArduinoJson.h>
#include <Ethernet.h>
#include <WebServer.h>
#include <Preferences.h>
#include <FS.h>
#include <SPIFFS.h> // Interner Flash-Speicher für das SSL-Zertifikat

// ---------- PIN-DEFINITIONEN (Lilygo T-SIM7080G-S3 + Basisplatine) ----------
// WIZnet W5500 Ethernet SPI-Pins auf ESP32-S3
#define ETH_CS_PIN    5
#define ETH_RST_PIN   33

// SIM7080G Mobilfunk-Modem Pins
#define MODEM_TX      27
#define MODEM_RX      26
#define MODEM_PWRKEY  4

// I2C Pins für den ADS1115 ADC
#define I2C_SDA       21
#define I2C_SCL       22

// Die 4 Digitaleingänge (über Optokoppler, aktiv LOW)
#define PIN_IN1       12
#define PIN_IN2       13
#define PIN_IN3       14
#define PIN_IN4       15

// Die 4 Relais-Ausgänge (aktiv HIGH über Transistorstufe)
#define PIN_REL1      34
#define PIN_REL2      35
#define PIN_REL3      36
#define PIN_REL4      37

// ---------- NETZWERK FALLBACK CONFIGURATION ----------
IPAddress fallback_ip(192, 168, 8, 200);
IPAddress dns_server(192, 168, 8, 1);
IPAddress gateway(192, 168, 8, 1);
IPAddress subnet(255, 255, 255, 0);

// ---------- GLOBALE VARIABLEN & INSTANZEN ----------
String config_apn = "internet.telekom"; // Beispiel-APN, über Web GUI änderbar
String config_broker = "://kadlubski.com"; 
int config_port = 8883;                 // MQTTS (Verschlüsselt via Nginx)
int config_interval = 300;              // Standard: 5 Minuten Sendeintervall

String deviceID = "";
String topicPub = "";
String topicSub = "";
unsigned long lastSendTime = 0;

HardwareSerial ModemSerial(1);
Adafruit_ADS1115 ads;
WebServer server(80);
Preferences preferences;
File fsUploadFile;

const float SHUNT_RESISTOR = 250.0; // 250 Ohm Präzisions-Shunt (0.1%)
// Eindeutige Seriennummer aus der Hardware-MAC generieren
void initDeviceID() {
  uint64_t chipid = ESP.getEfuseMac();
  deviceID = "MQTTSNODE_" + String((uint32_t)(chipid >> 32), HEX) + String((uint32_t)chipid, HEX);
  deviceID.toUpperCase();
  topicPub = "sensoren/" + deviceID + "/daten";
  topicSub = "sensoren/" + deviceID + "/relais/#";
}

// Einstellungen aus dem NVS-Flash laden
void loadSettings() {
  preferences.begin("iot-config", true);
  config_apn = preferences.getString("apn", config_apn);
  config_broker = preferences.getString("broker", config_broker);
  config_port = preferences.getInt("port", config_port);
  config_interval = preferences.getInt("interval", config_interval);
  preferences.end();
}

// Einstellungen im NVS-Flash speichern
void saveSettings(String apn, String broker, int port, int interval) {
  preferences.begin("iot-config", false);
  preferences.putString("apn", apn);
  preferences.putString("broker", broker);
  preferences.putInt("port", port);
  preferences.putInt("interval", interval);
  preferences.end();
}

// AT-Befehle an das LTE-Modem senden und auf Antwort warten
bool sendATCommand(String cmd, String expected, unsigned int timeout_ms) {
  ModemSerial.println(cmd);
  unsigned long start = millis();
  String response = "";
  while ((millis() - start) < timeout_ms) {
    while (ModemSerial.available()) {
      response += (char)ModemSerial.read();
    }
    if (response.indexOf(expected) != -1) return true;
  }
  return false;
}

// Auslesen des ADS1115 Kanals und Umrechnung in mA
float readChannelmA(uint8_t channel) {
  int16_t adc_raw = ads.readADC_SingleEnded(channel);
  float voltage = adc_raw * 0.0001875; // 0.1875 mV pro Bit bei GAIN_TWOTHIRDS
  return (voltage / SHUNT_RESISTOR) * 1000.0;
}

// HTML-Code der integrierten Konfigurations-Homepage
void handleRoot() {
  String html = "<!DOCTYPE html><html><head><meta charset='UTF-8'><meta name='viewport' content='width=device-width, initial-scale=1.0'>";
  html += "<title>Gateway Konfiguration</title>";
  html += "<style>body{font-family:Arial,sans-serif;background:#f4f4f9;padding:20px;} .card{background:white;padding:20px;border-radius:8px;max-width:500px;margin:auto;box-shadow:0 2px 5px rgba(0,0,0,0.1);} input{width:100%;padding:8px;margin:5px 0 15px 0;box-sizing:border-box;} button{width:100%;padding:10px;border:none;border-radius:4px;color:white;font-weight:bold;cursor:pointer;}</style></head><body>";
  html += "<div class='card'><h2>⚙️ Gateway-Einstellungen</h2>";
  html += "<p><strong>Seriennummer (Device ID):</strong> " + deviceID + "</p>";
  html += "<form action='/save' method='POST'>";
  html += "<label>Mobilfunk APN:</label><input type='text' name='apn' value='" + config_apn + "'>";
  html += "<label>MQTT Broker Host/IP:</label><input type='text' name='broker' value='" + config_broker + "'>";
  html += "<label>MQTT Port:</label><input type='number' name='port' value='" + String(config_port) + "'>";
  html += "<label>Sendeintervall (Sekunden):</label><input type='number' name='interval' value='" + String(config_interval) + "'>";
  html += "<button type='submit' style='background:#28a745;'>Speichern & Neustarten</button></form><br><hr><br>";
  html += "<h3>🔒 SSL Zertifikat hochladen (ca_cert.pem)</h3>";
  html += "<form method='POST' action='/upload' enctype='multipart/form-data'>";
  html += "<input type='file' name='file'><br><br>";
  html += "<button type='submit' style='background:#007bff;'>Zertifikat hochladen</button></form></div></body></html>";
  server.send(200, "text/html", html);
}

void handleSave() {
  if (server.hasArg("apn") && server.hasArg("broker") && server.hasArg("port") && server.hasArg("interval")) {
    saveSettings(server.arg("apn"), server.arg("broker"), server.arg("port").toInt(), server.arg("interval").toInt());
    server.send(200, "text/html", "<h3>Einstellungen erfolgreich gespeichert! Neustart...</h3>");
    delay(2000);
    ESP.restart();
  } else {
    server.send(400, "text/plain", "Fehlerhafte Anfrage");
  }
}

// Verarbeitet den Datei-Upload des SSL-Zertifikats in den SPIFFS Flash
void handleFileUpload() {
  HTTPUpload& upload = server.upload();
  if (upload.status == UPLOAD_FILE_START) {
    String filename = "/ca_cert.pem"; // Festgelegter Name im lokalen System
    fsUploadFile = SPIFFS.open(filename, "w");            
  } else if (upload.status == UPLOAD_FILE_WRITE) {
    if (fsUploadFile) fsUploadFile.write(upload.buf, upload.currentSize);
  } else if (upload.status == UPLOAD_FILE_END) {
    if (fsUploadFile) {
      fsUploadFile.close();
      server.send(200, "text/html", "<h3>Zertifikat erfolgreich empfangen! Neustart...</h3>");
      delay(2000);
      ESP.restart();
    } else {
      server.send(500, "text/plain", "Fehler beim Dateizugriff.");
    }
  }
}
// Prüft eingehende LTE-MQTTS-Downlinks für alle 4 Relais
void checkIncomingModemData() {
  if (ModemSerial.available()) {
    String incoming = ModemSerial.readString();
    
    // Parsen der MQTT-Nachrichten für die 4 Relais Kanäle
    if (incoming.indexOf("relais/1") != -1) {
      digitalWrite(PIN_REL1, (incoming.indexOf("ON") != -1) ? HIGH : LOW);
    }
    if (incoming.indexOf("relais/2") != -1) {
      digitalWrite(PIN_REL2, (incoming.indexOf("ON") != -1) ? HIGH : LOW);
    }
    if (incoming.indexOf("relais/3") != -1) {
      digitalWrite(PIN_REL3, (incoming.indexOf("ON") != -1) ? HIGH : LOW);
    }
    if (incoming.indexOf("relais/4") != -1) {
      digitalWrite(PIN_REL4, (incoming.indexOf("ON") != -1) ? HIGH : LOW);
    }
  }
}

void setup() {
  Serial.begin(115200);
  SPIFFS.begin(true); // Internen Flash-Speicher starten
  
  initDeviceID();
  loadSettings();

  // GPIOs für die 4 Digitaleingänge konfigurieren
  pinMode(PIN_IN1, INPUT_PULLUP); pinMode(PIN_IN2, INPUT_PULLUP);
  pinMode(PIN_IN3, INPUT_PULLUP); pinMode(PIN_IN4, INPUT_PULLUP);

  // GPIOs für die 4 Relais konfigurieren
  pinMode(PIN_REL1, OUTPUT); pinMode(PIN_REL2, OUTPUT);
  pinMode(PIN_REL3, OUTPUT); pinMode(PIN_REL4, OUTPUT);
  digitalWrite(PIN_REL1, LOW); digitalWrite(PIN_REL2, LOW);
  digitalWrite(PIN_REL3, LOW); digitalWrite(PIN_REL4, LOW);

  // 1. RJ45 W5500 Ethernet & Webserver initialisieren
  Ethernet.init(ETH_CS_PIN);
  pinMode(ETH_RST_PIN, OUTPUT);
  digitalWrite(ETH_RST_PIN, LOW); delay(10); digitalWrite(ETH_RST_PIN, HIGH);
  
  Serial.println("Starte W5500 Ethernet...");
  if (Ethernet.begin() == 0) {
    Serial.println("DHCP fehlgeschlagen. Nutze feste Fallback-IP: 192.168.8.200");
    Ethernet.begin(fallback_ip, dns_server, gateway, subnet);
  }
  Serial.print("Web GUI erreichbar unter: http://"); Serial.println(Ethernet.localIP());

  server.on("/", handleRoot);
  server.on("/save", handleSave);
  server.on("/upload", HTTP_POST, [](){ server.send(200); }, handleFileUpload); 
  server.begin();

  // 2. I2C und Mess-ADC (ADS1115) starten
  Wire.begin(I2C_SDA, I2C_SCL);
  ads.setGain(GAIN_TWOTHIRDS); // Bereich bis +/- 6.144V
  ads.begin();

  // 3. LTE-Modem (SIM7080G) starten & verschlüsseltes MQTTS aufbauen
  ModemSerial.begin(115200, SERIAL_8N1, MODEM_RX, MODEM_TX);
  pinMode(MODEM_PWRKEY, OUTPUT);
  digitalWrite(MODEM_PWRKEY, HIGH); delay(1000); digitalWrite(MODEM_PWRKEY, LOW);
  delay(4000); // Auf Modem-Boot warten

  // MQTTS Konfiguration über AT-Befehle füttern
  sendATCommand("AT+CGDCONT-1,\"IP\",\"" + config_apn + "\"", "OK", 3000);
  sendATCommand("AT+SMSSL-1,\"ca_cert.pem\"", "OK", 3000); 
  sendATCommand("AT+SMCONF=\"URL\",\"" + config_broker + "\",\"" + String(config_port) + "\"", "OK", 3000);
  sendATCommand("AT+SMCONF=\"KEEPALIVE\",60", "OK", 3000); // Tunnel offen halten für schnelle Befehle
  sendATCommand("AT+SMCONF=\"CLIENTID\",\"" + deviceID + "\"", "OK", 3000);

  if (sendATCommand("AT+SMCONN", "OK", 15000)) {
    Serial.println("Verschlüsselte Mobilfunk-MQTTS Verbindung steht!");
    sendATCommand("AT+SMSUB=\"" + topicSub + "\",1", "OK", 3000); // Auf eigene Relais-Befehle lauschen
  } else {
    Serial.println("LTE-MQTTS fehlgeschlagen. Nur lokaler LAN-Wartungsmodus aktiv.");
  }
}

void loop() {
  server.handleClient();     // Weboberfläche über LAN bedienen
  checkIncomingModemData();  // Mobilfunk-Downlinks (Relais) permanent abfragen

  // Zyklischer LTE Sende-Timer basierend auf eingestelltem Intervall
  unsigned long currentMillis = millis();
  if (currentMillis - lastSendTime >= ((unsigned long)config_interval * 1000) || lastSendTime == 0) {
    lastSendTime = currentMillis;

    // Analogkanäle hochpräzise auslesen
    float ch1_mA = readChannelmA(0);
    float ch2_mA = readChannelmA(1);

    // 4x Digitaleingänge einlesen (Optokoppler zieht bei Signal LOW)
    int dig1 = (digitalRead(PIN_IN1) == LOW) ? 1 : 0;
    int dig2 = (digitalRead(PIN_IN2) == LOW) ? 1 : 0;
    int dig3 = (digitalRead(PIN_IN3) == LOW) ? 1 : 0;
    int dig4 = (digitalRead(PIN_IN4) == LOW) ? 1 : 0;

    // JSON Payload erstellen
    StaticJsonDocument<384> doc;
    doc["serial"] = deviceID;
    doc["ch1_mA"] = serialized(String(ch1_mA, 4)); // 4 Nachkommastellen für µA
    doc["ch2_mA"] = serialized(String(ch2_mA, 4));
    doc["dig1"] = dig1; doc["dig2"] = dig2; doc["dig3"] = dig3; doc["dig4"] = dig4;
    doc["rel1"] = digitalRead(PIN_REL1); doc["rel2"] = digitalRead(PIN_REL2);
    doc["rel3"] = digitalRead(PIN_REL3); doc["rel4"] = digitalRead(PIN_REL4);

    String jsonPayload;
    serializeJson(doc, jsonPayload);

    // Daten via Mobilfunk abschicken
    String pubCmd = "AT+SMPUB=\"" + topicPub + "\"," + String(jsonPayload.length()) + ",1,0";
    if (sendATCommand(pubCmd, ">", 5000)) {
      ModemSerial.print(jsonPayload);
      Serial.println("Daten via LTE gesendet: " + jsonPayload);
    }
  }
}

#include <Arduino.h>
#include <Wire.h>
#include <Adafruit_ADS1X15.h>
#include <ArduinoJson.h>
#include <Ethernet.h>
#include <WebServer.h>
#include <Preferences.h>

// ==================== PIN-DEFINITIONEN (Lilygo T-SIM7080G-S3) ====================
#define ETH_CS_PIN    5
#define ETH_RST_PIN   33
#define MODEM_TX      27
#define MODEM_RX      26
#define MODEM_PWRKEY   4
#define PIN_IN1       12  
#define PIN_IN2       13  
#define PIN_REL1      14  
#define PIN_REL2      15  
#define PIN_REL3      16  
#define PIN_REL4      17  
#define I2C_SDA       21
#define I2C_SCL       22

// ==================== DYNAMISCH SPEICHERBARE WERTE ====================
String config_apn        = "iot.telekom.net";
String config_broker     = "://kadlubski.com";
int config_port          = 8883;
int config_interval      = 300; 
String config_ip         = "192.168.8.200";

// Sicherheits-Credentials
String config_mqtt_user  = "m2m_user";
String config_mqtt_pass  = "m2m_secure_password";
String config_admin_pass = "admin123"; // Login-Passwort für die RJ45-Homepage
String config_cert       = "-----BEGIN CERTIFICATE-----\n[Zertifikat einkopieren]\n-----END CERTIFICATE-----";

// Skalierung & Regeln für Kanal 1 (Steuert Relais 1 und Relais 3)
float ch1_min_val = 0.0;   
float ch1_max_val = 20.0;  
float ch1_r1_on   = 15.0;   
float ch1_r1_off  = 5.0;   
float ch1_r3_on   = 18.0;   
float ch1_r3_off  = 12.0;  
bool ch1_rule_active = false;

// Skalierung & Regeln für Kanal 2 (Steuert Relais 2 und Relais 4)
float ch2_min_val = 0.0;   
float ch2_max_val = 100.0; 
float ch2_r2_on   = 80.0;   
float ch2_r2_off  = 20.0;  
float ch2_r4_on   = 90.0;   
float ch2_r4_off  = 50.0;  
bool ch2_rule_active = false;

// Globale System-Variablen
String deviceID = "";
unsigned long lastSendTime = 0;
String topicPub = "";
String topicSub = "";
bool lte_online = false;

IPAddress gateway(192, 168, 8, 1);
IPAddress subnet(255, 255, 255, 0);

HardwareSerial ModemSerial(1); 
Adafruit_ADS1115 ads;          
WebServer server(80); 
Preferences preferences;

const float SHUNT_RESISTOR = 250.0; 

// Hilfsfunktion: Wandelt IP-String in IPAddress-Objekt
IPAddress parseIP(String ipStr) {
  int parts[4] = {0, 0, 0, 0};
  for (int i = 0; i < 4; i++) {
    int dotIndex = ipStr.indexOf('.');
    if (dotIndex != -1) {
      parts[i] = ipStr.substring(0, dotIndex).toInt();
      ipStr = ipStr.substring(dotIndex + 1);
    } else {
      parts[i] = ipStr.toInt();
    }
  }
  return IPAddress(parts[0], parts[1], parts[2], parts[3]);
}

void initDeviceID() {
  uint64_t chipid = ESP.getEfuseMac(); 
  deviceID = "MQTTSNODE_" + String((uint32_t)(chipid >> 32), HEX) + String((uint32_t)chipid, HEX);
  deviceID.toUpperCase();
  topicPub = "sensoren/" + deviceID + "/daten";
  topicSub = "sensoren/" + deviceID + "/relais/#";
}
void loadSettings() {
  preferences.begin("iot-config", true);
  config_apn        = preferences.getString("apn", config_apn);
  config_broker     = preferences.getString("broker", config_broker);
  config_port       = preferences.getInt("port", config_port);
  config_interval   = preferences.getInt("interval", config_interval);
  config_ip         = preferences.getString("ip", config_ip);
  config_mqtt_user  = preferences.getString("mq_user", config_mqtt_user);
  config_mqtt_pass  = preferences.getString("mq_pass", config_mqtt_pass);
  config_admin_pass = preferences.getString("ad_pass", config_admin_pass);
  config_cert       = preferences.getString("cert", config_cert);
  
  ch1_min_val = preferences.getFloat("c1min", ch1_min_val);
  ch1_max_val = preferences.getFloat("c1max", ch1_max_val);
  ch1_r1_on   = preferences.getFloat("c1r1_on", ch1_r1_on);
  ch1_r1_off  = preferences.getFloat("c1r1_off", ch1_r1_off);
  ch1_r3_on   = preferences.getFloat("c1r3_on", ch1_r3_on);
  ch1_r3_off  = preferences.getFloat("c1r3_off", ch1_r3_off);
  ch1_rule_active = preferences.getBool("c1act", ch1_rule_active);

  ch2_min_val = preferences.getFloat("c2min", ch2_min_val);
  ch2_max_val = preferences.getFloat("c2max", ch2_max_val);
  ch2_r2_on   = preferences.getFloat("c2r2_on", ch2_r2_on);
  ch2_r2_off  = preferences.getFloat("c2r2_off", ch2_r2_off);
  ch2_r4_on   = preferences.getFloat("c2r4_on", ch2_r4_on);
  ch2_r4_off  = preferences.getFloat("c2r4_off", ch2_r4_off);
  ch2_rule_active = preferences.getBool("c2act", ch2_rule_active);
  preferences.end();
}

void saveSettings() {
  preferences.begin("iot-config", false);
  preferences.putString("apn", config_apn);
  preferences.putString("broker", config_broker);
  preferences.putInt("port", config_port);
  preferences.putInt("interval", config_interval);
  preferences.putString("ip", config_ip);
  preferences.putString("mq_user", config_mqtt_user);
  preferences.putString("mq_pass", config_mqtt_pass);
  preferences.putString("ad_pass", config_admin_pass);
  preferences.putString("cert", config_cert);
  
  preferences.putFloat("c1min", ch1_min_val); preferences.putFloat("c1max", ch1_max_val);
  preferences.putFloat("c1r1_on", ch1_r1_on); preferences.putFloat("c1r1_off", ch1_r1_off);
  preferences.putFloat("c1r3_on", ch1_r3_on); preferences.putFloat("c1r3_off", ch1_r3_off);
  preferences.putBool("c1act", ch1_rule_active);

  preferences.putFloat("c2min", ch2_min_val); preferences.putFloat("c2max", ch2_max_val);
  preferences.putFloat("c2r2_on", ch2_r2_on); preferences.putFloat("c2r2_off", ch2_r2_off);
  preferences.putFloat("c2r4_on", ch2_r4_on); preferences.putFloat("c2r4_off", ch2_r4_off);
  preferences.putBool("c2act", ch2_rule_active);
  preferences.end();
}

void handleRoot() {
  String html = "<!DOCTYPE html><html><head><meta charset='UTF-8'><meta name='viewport' content='width=device-width, initial-scale=1.0'>";
  html += "<title>Gateway Konfiguration</title>";
  html += "<style>body{font-family:Arial,sans-serif;background:#f4f4f9;padding:20px;} .card{background:#fff;padding:20px;border-radius:8px;max-width:650px;margin:0 auto;box-shadow:0 4px 8px rgba(0,0,0,0.1);} h2,h3{color:#333;border-bottom:1px solid #ddd;padding-bottom:5px;} label{display:block;margin:10px 0 5px;font-weight:bold;} input[type='text'],input[type='number'],textarea{width:100%;padding:8px;box-sizing:border-box;border:1px solid #ccc;border-radius:4px;} .row{display:flex;gap:10px;margin-bottom:10px;} .row div{flex:1;} .check-row{display:flex;align-items:center;gap:10px;margin:15px 0;} button{background:#28a745;color:#fff;border:0;padding:12px;width:100%;border-radius:4px;font-size:16px;cursor:pointer;} button:hover{background:#218838;}</style></head><body>";
  html += "<div class='card'><h2>⚙️ Gateway Gesamteinstellungen</h2><p><strong>Seriennummer:</strong> " + deviceID + "</p><form action='/save' method='POST'>";
  
  html += "<h3>🌐 Netzwerkeinstellungen & Sicherheit</h3>";
  html += "<label>Feste Fallback IP-Adresse:</label><input type='text' name='ip' value='" + config_ip + "'>";
  html += "<label>Web-Interface Admin-Passwort:</label><input type='text' name='ad_pass' value='" + config_admin_pass + "'>";
  html += "<label>Mobilfunk APN:</label><input type='text' name='apn' value='" + config_apn + "'>";
  html += "<label>MQTT Broker Host/IP:</label><input type='text' name='broker' value='" + config_broker + "'>";
  html += "<div class='row'><div><label>MQTT Port:</label><input type='number' name='port' value='" + String(config_port) + "'></div><div><label>Intervall (Sek):</label><input type='number' name='interval' value='" + String(config_interval) + "'></div></div>";
  html += "<div class='row'><div><label>MQTT Benutzername:</label><input type='text' name='mq_user' value='" + config_mqtt_user + "'></div><div><label>MQTT Passwort:</label><input type='text' name='mq_pass' value='" + config_mqtt_pass + "'></div></div>";
  html += "<label>MQTTS SSL Root Zertifikat (ca_cert.pem):</label><textarea name='cert' rows='6' style='font-family:monospace;'>" + config_cert + "</textarea>";
  
  html += "<h3>🎯 Kanal 1 (Skalierung & Offline-Regeln für Relais 1 + 3)</h3>";
  html += "<div class='row'><div><label>Wert bei 4mA:</label><input type='text' name='c1min' value='" + String(ch1_min_val,2) + "'></div><div><label>Wert bei 20mA:</label><input type='text' name='c1max' value='" + String(ch1_max_val,2) + "'></div></div>";
  html += "<strong>[Relais 1]</strong><div class='row'><div><label>Einschalten (>):</label><input type='text' name='c1r1_on' value='" + String(ch1_r1_on,2) + "'></div><div><label>Ausschalten (<):</label><input type='text' name='c1r1_off' value='" + String(ch1_r1_off,2) + "'></div></div>";
  html += "<strong>[Relais 3]</strong><div class='row'><div><label>Einschalten (>):</label><input type='text' name='c1r3_on' value='" + String(ch1_r3_on,2) + "'></div><div><label>Ausschalten (<):</label><input type='text' name='c1r3_off' value='" + String(ch1_r3_off,2) + "'></div></div>";
  html += "<div class='check-row'><input type='checkbox' name='c1act' id='c1act' " + String(ch1_rule_active ? "checked" : "") + "><label for='c1act'>Offline-Regeln 1 für Relais 1 & 3 aktivieren</label></div>";

  html += "<h3>🎯 Kanal 2 (Skalierung & Offline-Regeln für Relais 2 + 4)</h3>";
  html += "<div class='row'><div><label>Wert bei 4mA:</label><input type='text' name='c2min' value='" + String(ch2_min_val,2) + "'></div><div><label>Wert bei 20mA:</label><input type='text' name='c2max' value='" + String(ch2_max_val,2) + "'></div></div>";
  html += "<strong>[Relais 2]</strong><div class='row'><div><label>Einschalten (>):</label><input type='text' name='c2r2_on' value='" + String(ch2_r2_on,2) + "'></div><div><label>Ausschalten (<):</label><input type='text' name='c2r2_off' value='" + String(ch2_r2_off,2) + "'></div></div>";
  html += "<strong>[Relais 4]</strong><div class='row'><div><label>Einschalten (>):</label><input type='text' name='c2r4_on' value='" + String(ch2_r4_on,2) + "'></div><div><label>Ausschalten (<):</label><input type='text' name='c2r4_off' value='" + String(ch2_r4_off,2) + "'></div></div>";
  html += "<div class='check-row'><input type='checkbox' name='c2act' id='c2act' " + String(ch2_rule_active ? "checked" : "") + "><label for='c2act'>Offline-Regeln 2 für Relais 2 & 4 aktivieren</label></div>";

  html += "<button type='submit'>Speichern & Neustarten</button></form></div></body></html>";
  server.send(200, "text/html", html);
}

void handleSave() {
  if (server.hasArg("ip")) {
    config_ip = server.arg("ip"); config_apn = server.arg("apn"); config_broker = server.arg("broker");
    config_port = server.arg("port").toInt(); config_interval = server.arg("interval").toInt();
    config_mqtt_user = server.arg("mq_user"); config_mqtt_pass = server.arg("mq_pass");
    config_admin_pass = server.arg("ad_pass"); config_cert = server.arg("cert");
    
    ch1_min_val = server.arg("c1min").toFloat(); ch1_max_val = server.arg("c1max").toFloat();
    ch1_r1_on = server.arg("c1r1_on").toFloat(); ch1_r1_off = server.arg("c1r1_off").toFloat();
    ch1_r3_on = server.arg("c1r3_on").toFloat(); ch1_r3_off = server.arg("c1r3_off").toFloat();
    ch1_rule_active = server.hasArg("c1act");

    ch2_min_val = server.arg("c2min").toFloat(); ch2_max_val = server.arg("c2max").toFloat();
    ch2_r2_on = server.arg("c2r2_on").toFloat(); ch2_r2_off = server.arg("c2r2_off").toFloat();
    ch2_r4_on = server.arg("c2r4_on").toFloat(); ch2_r4_off = server.arg("c2r4_off").toFloat();
    ch2_rule_active = server.hasArg("c2act");

    saveSettings();
    server.send(200, "text/html", "<h3>Einstellungen erfolgreich gespeichert! Neustart...</h3>");
    delay(2000); ESP.restart();
  }
}
bool sendATCommand(String cmd, String expected, unsigned int timeout_ms);
float readChannelmA(uint8_t channel);
float getScaledValue(float mA, float min_val, float max_val);

void setup() {
  Serial.begin(115200); initDeviceID(); loadSettings();
  
  pinMode(PIN_IN1, INPUT_PULLUP); pinMode(PIN_IN2, INPUT_PULLUP);
  pinMode(PIN_REL1, OUTPUT); pinMode(PIN_REL2, OUTPUT); pinMode(PIN_REL3, OUTPUT); pinMode(PIN_REL4, OUTPUT);

  // W5500 Ethernet mit Passwort-geschütztem Webserver starten
  Ethernet.init(ETH_CS_PIN);
  pinMode(ETH_RST_PIN, OUTPUT); digitalWrite(ETH_RST_PIN, LOW); delay(10); digitalWrite(ETH_RST_PIN, HIGH);
  if (Ethernet.begin() == 0) { Ethernet.begin(parseIP(config_ip), gateway, gateway, subnet); }
  
  // Passwort-Schutz für die Homepage aktivieren (HTTP Basic Auth)
  server.on("/", []() {
    if (!server.authenticate("admin", config_admin_pass.c_str())) {
      return server.requestAuthentication();
    }
    handleRoot();
  });
  server.on("/save", handleSave); 
  server.begin();
  
  Wire.begin(I2C_SDA, I2C_SCL); ads.setGain(GAIN_TWOTHIRDS); ads.begin();

  // LTE-Modem (SIM7080G) wecken und MQTTS konfigurieren
  ModemSerial.begin(115200, SERIAL_8N1, MODEM_RX, MODEM_TX);
  pinMode(MODEM_PWRKEY, OUTPUT); digitalWrite(MODEM_PWRKEY, HIGH); delay(1000); digitalWrite(MODEM_PWRKEY, LOW); delay(4000);

  // Zertifikat dynamisch in den Flash des Modems schreiben
  sendATCommand("AT+SMCFS=0", "OK", 1000);
  sendATCommand("AT+SMWRITE=\"ca_cert.pem\"," + String(config_cert.length()), ">", 2000);
  ModemSerial.print(config_cert);
  delay(1000);

  // Mobilfunk- und SSL-Verbindungsparameter anwenden
  sendATCommand("AT+CGDCONT=1,\"IP\",\"" + config_apn + "\"", "OK", 3000);
  sendATCommand("AT+SMSSL=1,\"ca_cert.pem\"", "OK", 3000);
  sendATCommand("AT+SMCONF=\"URL\",\"" + config_broker + "\"," + String(config_port), "OK", 3000);
  sendATCommand("AT+SMCONF=\"USERNAME\",\"" + config_mqtt_user + "\"", "OK", 3000);
  sendATCommand("AT+SMCONF=\"PASSWORD\",\"" + config_mqtt_pass + "\"", "OK", 3000);
  sendATCommand("AT+SMCONF=\"KEEPALIVE\",60", "OK", 3000);
  sendATCommand("AT+SMCONF=\"CLIENTID\",\"" + deviceID + "\"", "OK", 3000);
  
  if (sendATCommand("AT+SMCONN", "OK", 15000)) { 
    lte_online = true; 
    sendATCommand("AT+SMSUB=\"" + topicSub + "\",1", "OK", 3000); 
  }
}

void loop() {
  server.handleClient();

  // Eingehende MQTTS-Fernschaltbefehle für alle 4 Relais auswerten
  if (lte_online && ModemSerial.available()) {
    String incoming = ModemSerial.readString();
    if (incoming.indexOf("relais/1") != -1) digitalWrite(PIN_REL1, (incoming.indexOf("ON") != -1));
    if (incoming.indexOf("relais/2") != -1) digitalWrite(PIN_REL2, (incoming.indexOf("ON") != -1));
    if (incoming.indexOf("relais/3") != -1) digitalWrite(PIN_REL3, (incoming.indexOf("ON") != -1));
    if (incoming.indexOf("relais/4") != -1) digitalWrite(PIN_REL4, (incoming.indexOf("ON") != -1));
  }

  // Hochpräzise Messung im µA-Bereich
  float ch1_mA = readChannelmA(0);
  float ch2_mA = readChannelmA(1);

  // Skalierung ausschließlich für die lokale Schwellenwertprüfung
  float ch1_scaled = getScaledValue(ch1_mA, ch1_min_val, ch1_max_val);
  float ch2_scaled = getScaledValue(ch2_mA, ch2_min_val, ch2_max_val);

  // WENN OFFLINE: Autarke 2-Punkt-Schaltung auf Basis der Webeinstellungen ausführen
  if (!lte_online) {
    if (ch1_rule_active) {
      if (ch1_scaled >= ch1_r1_on) digitalWrite(PIN_REL1, HIGH);
      else if (ch1_scaled <= ch1_r1_off) digitalWrite(PIN_REL1, LOW);
      
      if (ch1_scaled >= ch1_r3_on) digitalWrite(PIN_REL3, HIGH);
      else if (ch1_scaled <= ch1_r3_off) digitalWrite(PIN_REL3, LOW);
    }
    if (ch2_rule_active) {
      if (ch2_scaled >= ch2_r2_on) digitalWrite(PIN_REL2, HIGH);
      else if (ch2_scaled <= ch2_r2_off) digitalWrite(PIN_REL2, LOW);
      
      if (ch2_scaled >= ch2_r4_on) digitalWrite(PIN_REL4, HIGH);
      else if (ch2_scaled <= ch2_r4_off) digitalWrite(PIN_REL4, LOW);
    }
  }

  // Zyklischer Sende-Timer: Sendet REINE mA-Werte an ://kadlubski.com
  unsigned long currentMillis = millis();
  if (currentMillis - lastSendTime >= ((unsigned long)config_interval * 1000) || lastSendTime == 0) {
    lastSendTime = currentMillis;

    StaticJsonDocument<256> doc;
    doc["serial"] = deviceID;
    doc["ch1_mA"] = serialized(String(ch1_mA, 4)); // Immer rein in Milliampere (µA-Auflösung)
    doc["ch2_mA"] = serialized(String(ch2_mA, 4)); 
    doc["dig1"]   = (digitalRead(PIN_IN1) == LOW) ? 1 : 0;
    doc["dig2"]   = (digitalRead(PIN_IN2) == LOW) ? 1 : 0;
    doc["rel1"]   = digitalRead(PIN_REL1); doc["rel2"] = digitalRead(PIN_REL2);
    doc["rel3"]   = digitalRead(PIN_REL3); doc["rel4"] = digitalRead(PIN_REL4);

    String jsonPayload;
    serializeJson(doc, jsonPayload);

    if (lte_online) {
      String pubCmd = "AT+SMPUB=\"" + topicPub + "\"," + String(jsonPayload.length()) + ",1,0";
      if (!sendATCommand(pubCmd, ">", 5000)) { 
        lte_online = false; // Bei Timeout in den Offline-Modus wechseln
      } else { 
        ModemSerial.print(jsonPayload); 
      }
    } else {
      // Wenn offline, periodisch versuchen die MQTTS-Verbindung wiederaufzubauen
      if (sendATCommand("AT+SMCONN", "OK", 5000)) { 
        lte_online = true; 
        sendATCommand("AT+SMSUB=\"" + topicSub + "\",1", "OK", 3000); 
      }
    }
  }
}

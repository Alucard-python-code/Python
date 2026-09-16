#include <SPI.h>
#include <Ethernet.h>
#include <PubSubClient.h>
#include <EEPROM.h>


// --- NETZWERK STANDARDWERTE ---
byte mac[] = { 0xDE, 0xAD, 0xBE, 0xEF, 0xFE, 0x01 };

// --- EEPROM SPEICHER-STRUKTUR ---
struct Config {
  uint32_t ip;
  uint32_t subnet;
  uint32_t gateway;
  uint32_t brokerIp;
  char schrankName[32];
  char mqttUser[32];
  char mqttPass[32];
  int nullOffset;
  char pin[5];
} config;

EthernetServer server(80);
EthernetClient ethClient;
PubSubClient mqttClient(ethClient);

// --- HARDWARE PINS ---
const int SENSOR_PIN = 26; 
const int TACHO_PIN = 22;
const int LED_GRUEN = 10;
const int LED_GELB = 11;
const int LED_ROT = 12;

enum SystemState { BOOTING, HEATING, RUNNING, ALARM, SYSTEM_ERROR };
SystemState currentState = BOOTING;

volatile unsigned long impulsZaehler = 0;
unsigned long letzteRPMZeit = 0;
int aktuelleRPM = 0;
unsigned long startZeit;
unsigned long letzteSendeZeit = 0;
unsigned long ledAnimationZeit = 0;
int ledSchritt = 0;

String activeSessionToken = "";
unsigned long sessionExpiration = 0;

void IRAM_ATTR tachoImpuls() { impulsZaehler++; }

void loadConfig() {
  EEPROM.begin(512);
  EEPROM.get(0, config);
  
  if (config.ip == 0xFFFFFFFF || config.ip == 0) {
    config.ip = IPAddress(192, 168, 178, 101);
    config.subnet = IPAddress(255, 255, 255, 0);
    config.gateway = IPAddress(192, 168, 178, 1);
    config.brokerIp = IPAddress(192, 168, 178, 200);
    strcpy(config.schrankName, "Schrank_PV");
    strcpy(config.mqttUser, "pico_user");
    strcpy(config.mqttPass, "pico_password");
    config.nullOffset = 0;
    strcpy(config.pin, "1234");
    EEPROM.put(0, config);
    EEPROM.commit();
  }
}

void saveConfig() {
  EEPROM.put(0, config);
  EEPROM.commit();
}

void reconnectMQTT() {
  while (!mqttClient.connected()) {
    if (Ethernet.linkStatus() == LinkOFF) return;
    
    Serial.print("Verbinde mit MQTT Broker...");
    if (mqttClient.connect(config.schrankName, config.mqttUser, config.mqttPass)) {
      Serial.println("Erfolgreich verbunden!");
    } else {
      Serial.print("Fehler, rc="); Serial.print(mqttClient.state());
      Serial.println(" Neuer Versuch in 5 Sekunden...");
      delay(5000);
    }
  }
}

void setup() {
  Serial.begin(115200);
  startZeit = millis();
  
  loadConfig();

  pinMode(LED_GRUEN, OUTPUT); pinMode(LED_GELB, OUTPUT); pinMode(LED_ROT, OUTPUT);
  pinMode(TACHO_PIN, INPUT_PULLUP);
  attachInterrupt(digitalPinToInterrupt(TACHO_PIN), tachoImpuls, FALLING);

  SPI.setRX(16); SPI.setCS(17); SPI.setSCK(18); SPI.setTX(19);
  
  Ethernet.begin(mac, IPAddress(config.ip), IPAddress(config.subnet), IPAddress(config.gateway));
  server.begin();
  
  mqttClient.setServer(IPAddress(config.brokerIp), 1883);
}
void loop() {
  unsigned long jetzt = millis();
  
  if (jetzt > sessionExpiration && activeSessionToken != "") {
    activeSessionToken = "";
  }
  
  // 1. DREHZAHLBERECHNUNG
  if (jetzt - letzteRPMZeit >= 2000) {
    noInterrupts(); unsigned long impulse = impulsZaehler; impulsZaehler = 0; interrupts();
    aktuelleRPM = (impulse / 2.0) * (60000.0 / (jetzt - letzteRPMZeit));
    letzteRPMZeit = jetzt;
  }

  int rawValue = analogRead(SENSOR_PIN);
  int korrigierterWert = rawValue - config.nullOffset;
  if(korrigierterWert < 0) korrigierterWert = 0;

  // 2. MQTT VERBINDUNG HALTEN
  if (!mqttClient.connected()) {
    reconnectMQTT();
  }
  mqttClient.loop();

  // 3. ZUSTANDSMASCHINE FÜR DIODEN
  bool netzwerkFehler = (Ethernet.linkStatus() == LinkOFF);
  bool luefterFehler = (aktuelleRPM < 3500 && (jetzt - startZeit > 10000));

  if (netzwerkFehler || !mqttClient.connected()) {
    currentState = SYSTEM_ERROR; 
  } else if (luefterFehler) {
    currentState = SYSTEM_ERROR; 
  } else if (jetzt - startZeit < 60000) { 
    currentState = HEATING;
  } else {
    currentState = RUNNING; 
  }

  handleLEDs(luefterFehler, jetzt);

  // 4. DATEN PER MQTT SENDEN (JSON Format)
  if (mqttClient.connected() && (jetzt - letzteSendeZeit >= 1000)) {
    String payload = "{\"ip\":\"" + IPAddress(config.ip).toString() + 
                     "\",\"name\":\"" + String(config.schrankName) + 
                     "\",\"ppm\":" + String(korrigierterWert) + 
                     ",\"rpm\":" + String(aktuelleRPM) + 
                     ",\"status\":" + String((int)currentState) + "}";
    
    mqttClient.publish("schaltschrank/messung", payload.c_str());
    letzteSendeZeit = jetzt;
  }

  handleSecureWebserver(rawValue, korrigierterWert);
}

void handleLEDs(bool luefterDefekt, unsigned long jetzt) {
  if (currentState == SYSTEM_ERROR) {
    if (luefterDefekt) {
      digitalWrite(LED_GRUEN, HIGH); digitalWrite(LED_GELB, HIGH); digitalWrite(LED_ROT, HIGH);
    } else {
      if (jetzt - ledAnimationZeit >= 150) {
        ledAnimationZeit = jetzt; ledSchritt = (ledSchritt + 1) % 3;
        digitalWrite(LED_GELB, ledSchritt == 0 ? HIGH : LOW);
        digitalWrite(LED_GRUEN, ledSchritt == 1 ? HIGH : LOW);
        digitalWrite(LED_ROT, ledSchritt == 2 ? HIGH : LOW);
      }
    }
    return;
  }
  switch (currentState) {
    case HEATING: digitalWrite(LED_GELB, HIGH); digitalWrite(LED_GRUEN, LOW);  digitalWrite(LED_ROT, LOW);  break;
    case RUNNING: digitalWrite(LED_GELB, LOW);  digitalWrite(LED_GRUEN, HIGH); digitalWrite(LED_ROT, LOW);  break;
    default: break;
  }
}
void handleSecureWebserver(int raw, int korrigiert) {
  EthernetClient client = server.available();
  if (!client) return;

  String HTTP_req = "";
  boolean currentLineIsBlank = true;
  
  while (client.connected()) {
    if (client.available()) {
      char c = client.read();
      HTTP_req += c;
      
      if (c == '\n' && currentLineIsBlank) {
        bool isAuthorized = (activeSessionToken != "" && HTTP_req.indexOf("Cookie: session=" + activeSessionToken) >= 0);

        if (HTTP_req.indexOf("GET /login?pin=") >= 0) {
          int pinPos = HTTP_req.indexOf("GET /login?pin=") + 15;
          String submittedPin = HTTP_req.substring(pinPos, pinPos + 4); 
          
          if (submittedPin == String(config.pin)) {
            activeSessionToken = String(random(10000, 99999));
            sessionExpiration = millis() + 600000; 
            
            client.println("HTTP/1.1 303 See Other");
            client.print("Set-Cookie: session="); client.println(activeSessionToken);
            client.println("Location: /");
            client.println();
          } else {
            sendLoginResponse(client, true);
          }
        }
        else if (HTTP_req.indexOf("GET /logout") >= 0) {
          activeSessionToken = "";
          client.println("HTTP/1.1 303 See Other\nSet-Cookie: session=expired; Expires=Thu, 01 Jan 1970 00:00:00 GMT\nLocation: /\n");
        }
        else if (isAuthorized) {
          if (HTTP_req.indexOf("GET /tar") >= 0) {
            config.nullOffset = raw; 
            saveConfig();
            client.println("HTTP/1.1 303 See Other\nLocation: /\n");
          } 
          else if (HTTP_req.indexOf("GET /save_config") >= 0) {
            config.ip = parseIPFromURL(HTTP_req, "ip");
            config.subnet = parseIPFromURL(HTTP_req, "sub");
            config.gateway = parseIPFromURL(HTTP_req, "gw");
            config.brokerIp = parseIPFromURL(HTTP_req, "brk");
            
            parseTextFromURL(HTTP_req, "name=", config.schrankName, 32);
            parseTextFromURL(HTTP_req, "muser=", config.mqttUser, 32);
            parseTextFromURL(HTTP_req, "mpass=", config.mqttPass, 32);
            parseTextFromURL(HTTP_req, "npin=", config.pin, 5);

            saveConfig();
            
            client.println("HTTP/1.1 200 OK\nContent-Type: text/html\n\n<h3>Einstellungen erfolgreich gespeichert! Reboot läuft...</h3>");
            delay(1000);
            client.stop();
            rp2040.reboot(); 
            return;
          }
          else {
            sendAdminPage(client, raw, korrigiert);
          }
        } 
        else {
          sendLoginResponse(client, false);
        }
        break;
      }
      if (c == '\n') currentLineIsBlank = true;
      else if (c != '\r') currentLineIsBlank = false;
    }
  }
  delay(1);
  client.stop();
}

void sendLoginResponse(EthernetClient& client, bool error) {
  client.println("HTTP/1.1 200 OK\nContent-Type: text/html; charset=utf-8\n\n");
  client.println("<!DOCTYPE html><html><head><meta name='viewport' content='width=device-width, initial-scale=1.0'>");
  client.println("<style>body{font-family:sans-serif;text-align:center;background:#1e293b;color:white;margin-top:100px;} .box{background:#334155;padding:40px;border-radius:8px;display:inline-block;box-shadow:0 4px 10px rgba(0,0,0,0.3);} input{padding:10px;font-size:18px;width:100px;text-align:center;border-radius:4px;border:0;}</style></head><body>");
  client.println("<div class='box'><h2>🔒 Melder IoT-Anmeldung</h2>");
  if(error) client.println("<p style='color:#ef4444;'>❌ Falsche Sicherheits-PIN!</p>");
  client.println("<form action='/login' method='get'><p>Bitte 4-stellige PIN eingeben:</p><input type='password' name='pin' maxlength='4' required><br><br><input type='submit' value='Anmelden' style='background:#10b981;color:white;cursor:pointer;width:120px;padding:10px;border:0;border-radius:4px;'></form></div></body></html>");
}

void sendAdminPage(EthernetClient& client, int raw, int korrigiert) {
  client.println("HTTP/1.1 200 OK\nContent-Type: text/html; charset=utf-8\n\n");
  client.println("<!DOCTYPE html><html><head><meta name='viewport' content='width=device-width, initial-scale=1.0'>");
  client.println("<style>body{font-family:sans-serif;background:#f1f5f9;margin:20px;} .card{background:white;padding:25px;border-radius:8px;max-width:500px;margin:auto;box-shadow:0 4px 6px rgba(0,0,0,0.05)} input[type=text]{width:40px;text-align:center;padding:5px} .large-in{width:150px !important; text-align:left !important;} .section{border-top:1px solid #e2e8f0;margin-top:20px;padding-top:15px} button{background:#3b82f6;color:white;border:0;padding:10px 20px;border-radius:4px;cursor:pointer;}</style></head><body>");
  client.println("<div class='card'><h2>⚙️ IoT Melder Setup (Berechtigt)</h2>");
  
  client.print("<p><b>Sensor Rohwert:</b> "); client.print(raw); client.println("</p>");
  client.print("<p><b>Kompensiert:</b> <span style='color:#10b981;'>"); client.print(korrigiert); client.println("</span></p>");
  client.print("<p><b>Lüfter:</b> "); client.print(aktuelleRPM); client.println(" U/min</p>");
  client.print("<p><b>MQTT-Broker:</b> "); client.print(mqttClient.connected() ? "<span style='color:green;'>OK</span>" : "<span style='color:red;'>DISCONNECTED</span>"); client.println("</p>");
  client.println("<p><a href='/tar'><button style='background:#10b981;'>Aktuellen Nullabgleich brennen</button></a></p>");
  
  client.println("<div class='section'><h3>System-Parameter ändern</h3><form action='/save_config' method='get'>");
  client.print("<p><b>Schrank-Name (ID):</b> <input type='text' name='name' value='"); client.print(config.schrankName); client.println("' class='large-in' maxlength='31'></p>");
  
  printIPInputFields(client, "Pico IP:", "ip", IPAddress(config.ip));
  printIPInputFields(client, "Subnetzmaske:", "sub", IPAddress(config.subnet));
  printIPInputFields(client, "Gateway:", "gw", IPAddress(config.gateway));
  printIPInputFields(client, "Raspberry Pi IP:", "brk", IPAddress(config.brokerIp));
  
  client.print("<p><b>MQTT Benutzername:</b> <input type='text' name='muser' value='"); client.print(config.mqttUser); client.println("' class='large-in' maxlength='31'></p>");
  client.print("<p><b>MQTT Passwort:</b> <input type='text' name='mpass' value='"); client.print(config.mqttPass); client.println("' class='large-in' maxlength='31'></p>");
  client.print("<p><b>System-PIN (4 Stellen):</b> <input type='text' name='npin' value='"); client.print(config.pin); client.println("' style='width:60px;' maxlength='4'></p>");
  
  client.println("<br><input type='submit' value='Speichern & Übernehmen' style='background:#ef4444;color:white;padding:10px;border:0;border-radius:4px;cursor:pointer;'></form>");
  client.println("<br><p><a href='/logout' style='color:#64748b;'>Sitzung sperren (Logout)</a></p></div></div></body></html>");
}

void printIPInputFields(EthernetClient& client, String label, String prefix, IPAddress currentIp) {
  client.print("<p><b>"); client.print(label); client.print("</b> ");
  for(int i=0; i<4; i++) {
    client.print("<input type='text' name='"); client.print(prefix); client.print(i+1);
    client.print("' value='"); client.print(currentIp[i]); client.print("' maxlength='3'>");
    if(i<3) client.print(".");
  }
  client.println("</p>");
}

uint32_t parseIPFromURL(String req, String prefix) {
  int arg1 = req.substring(req.indexOf(prefix + "1=") + prefix.length() + 2).toInt();
  int arg2 = req.substring(req.indexOf(prefix + "2=") + prefix.length() + 2).toInt();
  int arg3 = req.substring(req.indexOf(prefix + "3=") + prefix.length() + 2).toInt();
  int arg4 = req.substring(req.indexOf(prefix + "4=") + prefix.length() + 2).toInt();
  return (uint32_t)IPAddress(arg1, arg2, arg3, arg4);
}

void parseTextFromURL(String req, String key, char* dest, int maxLen) {
  int pos = req.indexOf(key);
  if (pos >= 0) {
    pos += key.length();
    int endPos = req.indexOf('&', pos);
    if (endPos < 0) endPos = req.indexOf(' ', pos);
    String val = req.substring(pos, endPos);
    val.replace("%20", " "); 
    val.toCharArray(dest, maxLen);
  }
}

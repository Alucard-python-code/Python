#include <SPI.h>
#include <Wire.h>
#include <Ethernet.h>
#include <PubSubClient.h>
#include <Adafruit_ADS1X15.h>
#include <EEPROM.h>

// --- NETZWERK- & MQTT-OBJEKTE (FÜR KERN 1) ---
byte mac[] = { 0xDE, 0xAD, 0xBE, 0xEF, 0xFE, 0xED };
EthernetServer webServer(80);
EthernetClient ethClient;
PubSubClient mqttClient(ethClient);

// --- RECHTE- UND GEOMETRIE-KONSTANTEN ---
const float R_BURDEN = 100.0;           // 100 Ohm Shunt
const float SENSOR_FAULT_LIMIT = 3.6;   // NAMUR NE43 Drahtbruch
const float MAX_PHYSICAL_DELTA = 0.4;   // Signalsprung-Limit pro Sekunde (~1 bar)
const int FILTER_SIZE = 10;
const int EVENT_HOLD_DURATION = 30;

const byte adsAddresses[] = {0x48, 0x49, 0x4A, 0x4B};
const byte mcpAddresses[] = {0x20, 0x21, 0x22, 0x23, 0x24, 0x25, 0x26, 0x27};

// Globale Systemvariablen
String slotTypen = {"LEER","LEER","LEER","LEER","LEER","LEER","LEER","LEER"};
float sensorHistory[FILTER_SIZE];
int historyIdx = {0};
float filteredMaValues = {0.0};
float previousMaValues = {0.0};
uint16_t sensorFaultFlags = 0;
bool isFirstRun = true;

// Zeit- und Hysterese-Variablen (Kern-übergreifend geschützt via volatile)
volatile unsigned long lastExecutionTime = 0;
volatile unsigned long lastMqttSendTime = 0;
volatile int eventHoldTimer = 0;
volatile float aktuelleVersorgungsSpannung = 0.0;
volatile bool triggerMqttSendNow = false;
String currentMode = "STANDARD";

Adafruit_ADS1115 ads; // Globales ADC-Objekt

// --- SPEICHER-KONFIGURATION IM FLASH (EEPROM) ---
struct LokaleRegel {
  int sensorKanal;    // 1-32 (0 = Inaktiv)
  float grenzwert;    // mA Wert
  int zielRelais;     // 1-64
  bool schaltZustand; // true = AN, false = AUS
};

const int MAX_REGELN = 5; // Bis zu 5 dynamische Regeln im Webinterface

struct SystemConfig {
  char web_user[32];
  char web_password[32];
  char web_session[16];
  int connection_type; // 0 = LAN, 1 = GSM
  char mqtt_server[64];
  int mqtt_port;
  char mqtt_user[64];
  char mqtt_password[64];
  char mqtt_topic[128];
  
  LokaleRegel regeln[MAX_REGELN]; // Die dynamische SPS-Matrix im Flash
} config;

byte relaisZustand[8] = {0x00};
bool relaisDurchAutomatikGesperrt[64] = {false};
// --- KERN 0: SETUP (Wird beim Booten als Erstes ausgeführt) ---
void setup() {
  Serial.begin(115200);
  EEPROM.begin(1024); // Genug Platz für die große Struktur reservieren
  loadConfiguration();

  // I2C auf Pins GP8 (SDA) und GP9 (SCL) mit 100 kHz für Signalqualität starten
  Wire.setSDA(8); Wire.setSCL(9);
  Wire.begin(); Wire.setClock(100000);
  delay(500);

  endloseKartenErkennung(); // Erkennt Slots geometrisch von links nach rechts
  Serial.println("[KERN 0] Echtzeit-SPS gestartet.");
}

// --- KERN 0: ENDLOSSCHLEIFE (DETERMINISTISCHER TAKT) ---
void loop() {
  unsigned long now = millis();
  
  // Exakter 1-Sekunden-Takt für Messung und SPS-Entscheidung
  if (now - lastExecutionTime >= 1000) {
    lastExecutionTime = now;

    // 1. Spannungsanalyse des Netzteils (GP26)
    float pinVoltage = (analogRead(26) / 4095.0) * 3.3;
    aktuelleVersorgungsSpannung = pinVoltage * 13.0; // 12k/1k Spannungsteiler

    // 2. Analog-Frontend über die kaskadierten Schleusen einlesen
    bool changeDetected = checkSensorsAndDetectSpikes();

    // 3. Lokale SPS-Regelmatrix aus dem EEPROM abarbeiten
    verarbeiteLokaleSPSRegeln();

    // 4. Hysterese-Zustandsautomat für Sende-Triggerung
    if (changeDetected || aktuelleVersorgungsSpannung < 18.0) {
      currentMode = "EVENT";
      eventHoldTimer = EVENT_HOLD_DURATION;
      triggerMqttSendNow = true; // Signalisiert Kern 1, dass sofort gesendet werden muss
    } else if (eventHoldTimer > 0) {
      eventHoldTimer--;
      if (eventHoldTimer == 0) currentMode = "STANDARD";
    }

    // Standard-Sendeintervall (5 min) für Kern 1 antriggern
    if (now - lastMqttSendTime >= 300000 || lastMqttSendTime == 0) {
      triggerMqttSendNow = true;
    }
  }
  delay(1); // Verhindert Watchdog-Triggerung auf Kern 0
}

void aktiviereSlotKette(int bisZuSlot) {
  Wire.beginTransmission(0x70);
  Wire.write(0); // Alle Schleusen schließen
  Wire.endTransmission();

  for (int i = 0; i <= bisZuSlot; i++) {
    Wire.beginTransmission(0x70);
    if (i == bisZuSlot) Wire.write(1 << 0); // Eigene Karte aktivieren
    else Wire.write(1 << 1);                // Nach rechts weiterleiten
    Wire.endTransmission();
    delayMicroseconds(150);
  }
}

void endloseKartenErkennung() {
  for (int slot = 0; slot < 8; slot++) {
    aktiviereSlotKette(slot);
    Wire.beginTransmission(0x48);
    if (Wire.endTransmission() == 0) { slotTypen[slot] = "ANALOG_IN"; continue; }
    Wire.beginTransmission(0x20);
    if (Wire.endTransmission() == 0) { slotTypen[slot] = "DIGITAL_IO"; continue; }
    slotTypen[slot] = "LEER";
  }
  aktiviereSlotKette(0);
}

void verarbeiteLokaleSPSRegeln() {
  for (int i = 0; i < 64; i++) relaisDurchAutomatikGesperrt[i] = false;

  for (int r = 0; r < MAX_REGELN; r++) {
    if (config.regeln[r].sensorKanal == 0) continue; // Inaktive Regel überspringen

    int sKanal = config.regeln[r].sensorKanal - 1;
    float aktuellerWert = filteredMaValues[sKanal];
    int rNum = config.regeln[r].zielRelais;
    
    bool bedingungErfuellt = false;
    // Wenn Grenzwert > 12mA -> Überdruck-Überwachung, sonst Unterfüllung/Drahtbruch
    if (config.regeln[r].grenzwert > 12.0) {
      if (aktuellerWert > config.regeln[r].grenzwert) bedingungErfuellt = true;
    } else {
      if (aktuellerWert < config.regeln[r].grenzwert && aktuellerWert >= SENSOR_FAULT_LIMIT) bedingungErfuellt = true;
    }

    if (bedingungErfuellt) {
      relaisDurchAutomatikGesperrt[rNum - 1] = true; // Cloud-Befehle sperren
      int kartenIdx = (rNum - 1) / 8;
      int pinIdx = (rNum - 1) % 8;
      bool aktuellerStatus = (relaisZustand[kartenIdx] & (1 << pinIdx)) != 0;
      
      if (aktuellerStatus != config.regeln[r].schaltZustand) {
        schalteRelais(rNum, config.regeln[r].schaltZustand);
      }
    }
  }
}

void schalteRelais(int relaisNummer, bool status) {
  int kartenIndex = (relaisNummer - 1) / 8;
  int lokalerPin = (relaisNummer - 1) % 8;
  
  aktiviereSlotKette(kartenIndex);
  if (status) relaisZustand[kartenIndex] |= (1 << lokalerPin);
  else relaisZustand[kartenIndex] &= ~(1 << lokalerPin);
  
  Wire.beginTransmission(0x20);
  Wire.write(0x13); // GPIOB
  Wire.write(relaisZustand[kartenIndex]);
  Wire.endTransmission();
  aktiviereSlotKette(0);
}

// [Die Sensor-Mittelwertbildung "checkSensorsAndDetectSpikes()" bleibt identisch zu Teil 2]
// --- KERN 1: SETUP (Netzwerk-Start im Hintergrund) ---
void setup1() {
  delay(1000); // Warten bis Kern 0 gestartet ist
  
  if (config.connection_type == 0) {
    Ethernet.init(17); // CS Pin für Wiznet auf GP17
    if (Ethernet.begin(mac) != 0) {
      webServer.begin();
      mqttClient.setServer(config.mqtt_server, config.mqtt_port);
      mqttClient.setCallback(mqttCallback);
    }
  } else {
    // GSM-Serial initialisieren, falls Mobilfunk gewählt ist
  }
  Serial.println("[KERN 1] Kommunikations-Prozess gestartet.");
}

// --- KERN 1: ENDLOSSCHLEIFE (NETZWERK & CLOUD) ---
void loop1() {
  if (config.connection_type == 0) {
    if (!mqttClient.connected()) reconnectMQTT();
    mqttClient.loop();
    handleWebTraffic(); // Antwortet dem Techniker im Browser
  }

  // Wenn Kern 0 Daten senden möchte, führt Kern 1 das aus
  if (triggerMqttSendNow) {
    triggerMqttSendNow = false;
    lastMqttSendTime = millis();
    sendData(); // Sendet das Hex-Paket an Datacake
  }
  delay(1);
}

// ERZEUGT DAS DYNAMISCHE CONFIG-MENÜ INKLUSIVE DER AUTOMATIK-MASKE
void handleWebTraffic() {
  EthernetClient client = webServer.available();
  if (client) {
    String requestHeader = "";
    boolean currentLineIsBlank = true;
    while (client.connected()) {
      if (client.available()) {
        char c = client.read();
        requestHeader += c;
        
        if (c == '\n' && currentLineIsBlank) {
          // HTML Maske senden
          client.println("HTTP/1.1 200 OK");
          client.println("Content-Type: text/html; charset=utf-8");
          client.println();
          
          client.println("<!DOCTYPE html><html><head><title>SPS Edge Config</title>");
          client.println("<style>body{font-family:sans-serif;margin:25px;background:#f4f4f4;}.box{background:white;padding:20px;border-radius:6px;margin-bottom:20px;box-shadow:0 2px 5px rgba(0,0,0,0.1);max-width:700px;}input,select{width:95%;padding:6px;margin:6px 0;}</style></head><body>");
          
          // 1. Visuelle Rack-Anzeige (Ist vs Soll)
          client.println("<div class='box'><h2>1. Physisches SPS-Rack</h2><table>");
          for(int i=0; i<8; i++) {
            client.println("<tr><td><b>Slot " + String(i+1) + ":</b></td><td>" + slotTypen[i] + "</td></tr>");
          }
          client.println("</table><p>Spannung: " + String(aktuelleVersorgungsSpannung,2) + " V DC</p></div>");
          
          // 2. FORMULAR FÜR DIE DYNAMISCHE EDGE-SPS-AUTOMATIK
          client.println("<div class='box'><h2>2. Lokale SPS-Regeln (Autarke Sicherheit)</h2>");
          client.println("<form method='POST' action='/save_rules'>");
          for(int r=0; r<MAX_REGELN; r++) {
            client.println("<h3>Regel " + String(r+1) + "</h3>");
            client.println("Wenn Analog-Kanal (1-32): <input type='number' name='r_ch_" + String(r) + "' value='" + String(config.regeln[r].sensorKanal) + "' min='0' max='32'>");
            client.println("Grenzwert (mA): <input type='text' name='r_gt_" + String(r) + "' value='" + String(config.regeln[r].grenzwert) + "'>");
            client.println("Schalte Relais (1-64): <input type='number' name='r_rel_" + String(r) + "' value='" + String(config.regeln[r].zielRelais) + "' min='1' max='64'>");
            client.println("Zustand: <select name='r_st_" + String(r) + "'><option value='1' " + String(config.regeln[r].schaltZustand ? "selected":"") + ">EINSCHALTEN (AN)</option><option value='0' " + String(!config.regeln[r].schaltZustand ? "selected":"") + ">AUSSCHALTEN (AUS)</option></select><hr>");
          }
          client.println("<input type='submit' value='SPS-Automatik-Regeln speichern' style='background:#0066cc;color:white;font-weight:bold;border:none;padding:10px;cursor:pointer;'>");
          client.println("</form></div></body></html>");
          break;
        }
        if (c == '\n') currentLineIsBlank = true;
        else if (c != '\r') currentLineIsBlank = false;
      }
    }
    delay(1); client.stop();
  }
}

// [Die Hilfsfunktionen "reconnectMQTT()", "sendData()" und "loadConfiguration()" bleiben identisch zu Teil 3]
void loadConfiguration() {
  EEPROM.get(0, config);
  if (config.mqtt_port == 0 || config.mqtt_port == -1) {
    strcpy(config.web_user, "admin"); strcpy(config.web_password, "admin123");
    strcpy(config.mqtt_server, "mqtt.datacake.co"); config.mqtt_port = 1883;
    strcpy(config.mqtt_topic, "dtck-pub/v1/default/payload");
    config.connection_type = 0;
    
    // Leere Regeln vorbelegen
    for(int i=0; i<MAX_REGELN; i++) { config.regeln[i].sensorKanal = 0; config.regeln[i].grenzwert = 0.0; config.regeln[i].zielRelais = 1; config.regeln[i].schaltZustand = false; }
  }
}

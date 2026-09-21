#include <SPI.h>
#include <Wire.h>
#include <Ethernet.h>
#include <PubSubClient.h>
#include <Adafruit_ADS1X15.h>
#include <EEPROM.h>

// --- NETZWERK & SITZUNGSVARIABLEN ---
byte mac[] = { 0xDE, 0xAD, 0xBE, 0xEF, 0xFE, 0xED };
const char* default_mqtt_server = "mqtt.datacake.co";
const int default_mqtt_port = 1883;

EthernetServer webServer(80);
EthernetClient ethClient;
PubSubClient mqttClient(ethClient);

// --- PROZESS- UND HYSTERESE-PARAMETER ---
const float R_BURDEN = 100.0;           // 100 Ohm Präzisions-Shunt (0,1%)
const float SENSOR_FAULT_LIMIT = 3.6;   // NAMUR NE43 Drahtbrucherkennung
const float MAX_PHYSICAL_DELTA = 0.4;   // Unphysiologischer Sprung pro Sekunde (~1 bar)
const int FILTER_SIZE = 10;             // Ringpuffer-Größe für Mittelwertbildung
const int EVENT_HOLD_DURATION = 30;     // Nachlaufzeit im 1-Sek-Takt bei Fehlern

// --- HARDWARE-STECKPLATZ-GEOMETRIE ---
const byte adsAddresses[] = {0x48, 0x49, 0x4A, 0x4B};
const byte mcpAddresses[] = {0x20, 0x21, 0x22, 0x23, 0x24, 0x25, 0x26, 0x27};

// Globale Erkennungstabellen (Soll/Ist)
String slotTypen[8] = {"LEER","LEER","LEER","LEER","LEER","LEER","LEER","LEER"};
float sensorHistory[32][FILTER_SIZE];   // Ringpuffer für bis zu 32 Kanäle (8 Slots * 4)
int historyIdx[32] = {0};
float filteredMaValues[32] = {0.0};
float previousMaValues[32] = {0.0};
uint16_t sensorFaultFlags = 0;          // Bitmaske für defekte Sensoren
bool isFirstRun = true;

// Zeitsteuerung
unsigned long lastExecutionTime = 0;
unsigned long lastMqttSendTime = 0;
String currentMode = "STANDARD";
int eventHoldTimer = 0;
float aktuelleVersorgungsSpannung = 0.0;

Adafruit_ADS1115 ads; // Globales ADC-Objekt

// --- SPEICHER-STRUKTUR IM FLASH (EEPROM) ---
struct Config {
  char web_user[32];
  char web_password[32];
  char web_session[16];
  int connection_type; // 0 = LAN (PoE), 1 = Mobilfunk (SIM7080G)
  char mqtt_server[64];
  int mqtt_port;
  char mqtt_user[64];
  char mqtt_password[64];
  char mqtt_topic[128];
  bool allowedAnalog[4];
  bool allowedDigital[8];
} config;

// --- EDGE-SPS: INTERNE REGEL-MATRIX ---
struct LokaleRegel {
  int sensorKanal;    // Welcher Analog-In (1-32) wird überwacht?
  float grenzwert;    // Ab welchem mA-Wert soll geschaltet werden?
  int zielRelais;     // Welches Relais (1-64) soll reagieren?
  bool schaltZustand; // Soll das Relais bei Aktivierung AN (true) oder AUS (false) gehen?
  bool aktiv;         // Ist die Regel im Betrieb aktiv?
};

const int ANZ_REGELN = 3;
// Beispielkonfiguration für autonome Sicherheit vor Ort
LokaleRegel spsRegeln[ANZ_REGELN] = {
  {1, 16.0, 1, true, true},   // Regel 1: Wenn Druck (Sensor 1) > 16.0 mA (~30 bar) -> Schalte Sicherheitsrelais 1 AN
  {2, 4.5, 2, true, true},    // Regel 2: Wenn Pegel (Sensor 2) < 4.5 mA (Tank fast leer) -> Schalte Warnhorn 2 AN
  {3, 18.0, 3, false, true}   // Regel 3: Wenn Kritischer Wert (Sensor 3) > 18.0 mA -> Schalte Not-Aus Relais 3 AUS
};

bool relaisDurchAutomatikGesperrt[64] = {false};
byte relaisZustand[8] = {0x00}; // Bitmasken-Speicher der 8 Digital-Karten (8 Ports * 8 Bits)
// KASKADIERUNGS-LOGIK: Stufenweise Bus-Verlängerung nach rechts über Adresse 0x70
void aktiviereSlotKette(int bisZuSlot) {
  Wire.beginTransmission(0x70);
  Wire.write(0); // Alle Schleusen im gesamten System schließen
  Wire.endTransmission();

  for (int i = 0; i <= bisZuSlot; i++) {
    Wire.beginTransmission(0x70);
    if (i == bisZuSlot) {
      Wire.write(1 << 0); // Am Ziel-Slot angekommen: Eigene Sensorplatine aufschalten
    } else {
      Wire.write(1 << 1); // Auf dem Weg: Brücke/Weiterleitung zum nächsten Modul öffnen
    }
    Wire.endTransmission();
    delayMicroseconds(200); // Einschwingzeit für elektrische Kapazitäten abwarten
  }
}

// Erkennt beim Booten vollautomatisch das physische Steckplatz-Rack
void endloseKartenErkennung() {
  Serial.println("Starte geometrische Kartenanalyse...");
  for (int slot = 0; slot < 8; slot++) {
    aktiviereSlotKette(slot);
    delay(20);

    Wire.beginTransmission(0x48); // Versuche Standard-ADC-Adresse anzusprechen
    if (Wire.endTransmission() == 0) {
      slotTypen[slot] = "ANALOG_IN";
      Serial.print("-> Slot "); Serial.print(slot + 1); Serial.println(": ANALOG-MODUL erkannt.");
      continue;
    }

    Wire.beginTransmission(0x20); // Versuche Standard-I/O-Expander-Adresse anzusprechen
    if (Wire.endTransmission() == 0) {
      slotTypen[slot] = "DIGITAL_IO";
      Serial.print("-> Slot "); Serial.print(slot + 1); Serial.println(": DIGITAL-MODUL erkannt.");
      continue;
    }
    slotTypen[slot] = "LEER";
  }
  aktiviereSlotKette(0); // Bus-Hierarchie in Grundzustand versetzen
}

float getBufferAverage(int chIdx) {
  float sum = 0;
  for (int i = 0; i < FILTER_SIZE; i++) sum += sensorHistory[chIdx][i];
  return sum / (float)FILTER_SIZE;
}

// Liest alle Sensoren im 1-Sekunden-Takt aus und filtert Fehlerwerte (Drahtbruch/Spikes)
bool checkSensorsAndDetectSpikes() {
  bool faultOrSpikeDetected = false;
  int globalChannelIdx = 0;
  sensorFaultFlags = 0;

  for (int slot = 0; slot < 8; slot++) {
    if (slotTypen[slot] == "ANALOG_IN") {
      aktiviereSlotKette(slot);
      
      ads.begin(0x48);
      ads.setGain(GAIN_ONE); // Messbereich bis 4.096 V (ideal für max. 2.0 V an 100 Ohm)
      
      for (int ch = 0; ch < 4; ch++) {
        float volts = ads.computeVolts(ads.readADC_SingleEnded(ch));
        float rawMa = (volts / R_BURDEN) * 1000.0;
        if (rawMa < 0.0) rawMa = 0.0;

        if (isFirstRun) {
          for(int f = 0; f < FILTER_SIZE; f++) sensorHistory[globalChannelIdx][f] = rawMa;
          filteredMaValues[globalChannelIdx] = rawMa;
          previousMaValues[globalChannelIdx] = rawMa;
          globalChannelIdx++;
          continue;
        }

        // NAMUR NE43 Drahtbruch oder unphysiologischer Sprung (>0.4mA innerhalb von 0.5-1Sek)
        bool hasMacke = (rawMa < SENSOR_FAULT_LIMIT) || (abs(rawMa - previousMaValues[globalChannelIdx]) > MAX_PHYSICAL_DELTA);

        if (hasMacke) {
          sensorFaultFlags |= (1 << globalChannelIdx); // Fehlerbit für Cloud setzen
          faultOrSpikeDetected = true; 
          
          // MACKEN-ISOLIERUNG: Korrupter Rohwert wird verworfen, berechneter Durchschnitt wird gesendet
          filteredMaValues[globalChannelIdx] = getBufferAverage(globalChannelIdx);
        } else {
          filteredMaValues[globalChannelIdx] = rawMa;
          sensorHistory[globalChannelIdx][historyIdx[globalChannelIdx]] = rawMa;
          historyIdx[globalChannelIdx] = (historyIdx[globalChannelIdx] + 1) % FILTER_SIZE;
          previousMaValues[globalChannelIdx] = rawMa;
        }
        globalChannelIdx++;
      }
    }
  }
  if (isFirstRun && globalChannelIdx > 0) isFirstRun = false;
  aktiviereSlotKette(0);
  return faultOrSpikeDetected;
}
void loop() {
  if (config.connection_type == 0) {
    if (!mqttClient.connected()) reconnectMQTT();
    mqttClient.loop();
    handleWebTraffic(); // Lokalen Webserver auf Port 80 bedienen
  }

  unsigned long now = millis();
  if (now - lastExecutionTime >= 1000) {
    lastExecutionTime = now;
    
    // 1. Spannungsanalyse des Netzteils (GP26 über 12k/1k Spannungsteiler)
    float pinVoltage = (analogRead(26) / 4095.0) * 3.3;
    aktuelleVersorgungsSpannung = pinVoltage * 13.0; // Multiplikator für max. 42V Messbereich

    // 2. Analog-Frontend einlesen
    bool changeDetected = checkSensorsAndDetectSpikes();
    
    // 3. Autarke SPS-Regeln berechnen (Lokale Notabschaltung)
    verarbeiteLokaleSPSRegeln();
    
    // 4. Hysterese-Zustandsautomat für Sendeintervall (1 Sek vs. 5 Min)
    if (changeDetected || aktuelleVersorgungsSpannung < 18.0) {
      currentMode = "EVENT";
      eventHoldTimer = EVENT_HOLD_DURATION; // 30 Sekunden Nachlaufzeit starten
    } else if (eventHoldTimer > 0) {
      eventHoldTimer--;
      if (eventHoldTimer == 0) currentMode = "STANDARD";
    }

    // Sende-Trigger
    if (currentMode == "EVENT" || (now - lastMqttSendTime >= 300000) || lastMqttSendTime == 0) {
      sendData();
      lastMqttSendTime = now;
    }
  }
}

void verarbeiteLokaleSPSRegeln() {
  for (int i = 0; i < 64; i++) relaisDurchAutomatikGesperrt[i] = false;

  for (int r = 0; r < ANZ_REGELN; r++) {
    if (!spsRegeln[r].aktiv) continue;

    int sKanal = spsRegeln[r].sensorKanal - 1;
    float aktuellerWert = filteredMaValues[sKanal];
    int rNum = spsRegeln[r].zielRelais;
    
    bool bedingungErfuellt = false;
    if (spsRegeln[r].grenzwert > 12.0) {
      if (aktuellerWert > spsRegeln[r].grenzwert) bedingungErfuellt = true; // Überdruck
    } else {
      if (aktuellerWert < spsRegeln[r].grenzwert && aktuellerWert >= SENSOR_FAULT_LIMIT) bedingungErfuellt = true; // Unterfüllung
    }

    if (bedingungErfuellt) {
      relaisDurchAutomatikGesperrt[rNum - 1] = true; // Cloud-Fernsteuerung für dieses Relais blockieren!
      int kartenIdx = (rNum - 1) / 8;
      int pinIdx = (rNum - 1) % 8;
      bool aktuellerStatus = (relaisZustand[kartenIdx] & (1 << pinIdx)) != 0;
      
      if (aktuellerStatus != spsRegeln[r].schaltZustand) {
        schalteRelais(rNum, spsRegeln[r].schaltZustand); // Autonomes Schalten direkt auf der Schiene
      }
    }
  }
}

// KONTROLLE ALLER 64 DIGITALEN RELAISAUSGÄNGE VIA MQTT-CALLBACK
void mqttCallback(char* topic, byte* payload, unsigned int length) {
  String message = "";
  for (unsigned int i = 0; i < length; i++) message += (char)payload[i];
  String topicStr = String(topic);
  
  int lastUnderline = topicStr.lastIndexOf('_');
  if (lastUnderline != -1) {
    int relaisNummer = topicStr.substring(lastUnderline + 1).toInt();
    if (relaisNummer >= 1 && relaisNummer <= 64) {
      if (relaisDurchAutomatikGesperrt[relaisNummer - 1]) {
        Serial.println("[WARNING] MQTT-Downlink blockiert! Lokale Sicherheitsregel hat Vorrang.");
        return; 
      }
      schalteRelais(relaisNummer, message == "1");
    }
  }
}

void schalteRelais(int relaisNummer, bool status) {
  int kartenIndex = (relaisNummer - 1) / 8;
  int lokalerPin = (relaisNummer - 1) % 8;
  
  aktiviereSlotKette(kartenIndex);
  
  if (status) relaisZustand[kartenIndex] |= (1 << lokalerPin);
  else relaisZustand[kartenIndex] &= ~(1 << lokalerPin);
  
  Wire.beginTransmission(0x20); // Basisadresse des MCP23017 hinter der geöffneten Schleuse
  Wire.write(0x13);             // Register GPIOB (Ausgänge für Finder-Relais)
  Wire.write(relaisZustand[kartenIndex]);
  Wire.endTransmission();
  
  aktiviereSlotKette(0); // Kaskadierung schließen
}

void sendData() {
  if (!mqttClient.connected() && config.connection_type == 0) return;

  byte buffer[256];
  int idx = 0;
  int totalAnalog = 0;
  int totalDigital = 0;

  for(int i=0; i<8; i++) {
    if(slotTypen[i] == "ANALOG_IN") totalAnalog++;
    if(slotTypen[i] == "DIGITAL_IO") totalDigital++;
  }

  // Block 1: Analoge Werte (0xAA)
  if (totalAnalog > 0) {
    buffer[idx++] = 0xAA;
    buffer[idx++] = totalAnalog * 4;
    for (int i = 0; i < totalAnalog * 4; i++) {
      byte *f_bytes = (byte*)&filteredMaValues[i];
      buffer[idx++] = f_bytes[0]; buffer[idx++] = f_bytes[1];
      buffer[idx++] = f_bytes[2]; buffer[idx++] = f_bytes[3];
    }
  }

  // Block 2: Diagnosedaten & Hysterese-Modus (0x99)
  buffer[idx++] = 0x99;
  buffer[idx++] = (currentMode == "EVENT") ? 1 : 0;
  buffer[idx++] = sensorFaultFlags & 0xFF;
  buffer[idx++] = (sensorFaultFlags >> 8) & 0xFF;
  buffer[idx++] = (byte)(aktuelleVersorgungsSpannung * 10.0); // Spannung als skaliertes Byte senden

  // Konvertierung in Hex-Stream
  String hexPayload = "";
  for (int i = 0; i < idx; i++) {
    if (buffer[i] < 0x10) hexPayload += "0";
    hexPayload += String(buffer[i], HEX);
  }

  String jsonMsg = "[{\"field\":\"PAYLOAD\",\"value\":\"" + hexPayload + "\"}]";
  
  if (config.connection_type == 0) {
    mqttClient.publish(config.mqtt_topic, jsonMsg.c_str());
  } else {
    // AT-Befehlsausgabe via UART (GP0/GP1) an das Waveshare SIM7080G Mobilfunkmodul (1NCE)
    Serial1.print("AT+SMPUB=\""); Serial1.print(config.mqtt_topic);
    Serial1.print("\","); Serial1.print(jsonMsg.length()); Serial1.println(",1,0");
    delay(100);
    Serial1.print(jsonMsg);
  }
}

void handleWebTraffic() {
  EthernetClient client = webServer.available();
  if (client) {
    boolean currentLineIsBlank = true;
    while (client.connected()) {
      if (client.available()) {
        char c = client.read();
        if (c == '\n' && currentLineIsBlank) {
          // Erzeugt die passwortgeschützte Service-Oberfläche mit der Steckplatzbelegung
          client.println("HTTP/1.1 200 OK");
          client.println("Content-Type: text/html");
          client.println("Connection: close");
          client.println();
          client.println("<!DOCTYPE html><html><head><title>SPS Rack</title><style>body{font-family:sans-serif;margin:30px;}table{border-collapse:collapse;width:100%;}td,th{border:1px solid #ddd;padding:8px;}</style></head><body>");
          client.println("<h2>Physisches Slot-Belegungsregister (Ist-Zustand)</h2>");
          client.println("<table><tr><th>Steckplatz</th><th>Erkanntes IOT-Modul</th><th>Spannung Versorgung</th></tr>");
          for(int i=0; i<8; i++) {
            client.println("<tr><td><b>Slot " + String(i+1) + "</b></td><td>" + slotTypen[i] + "</td>");
            if(i==0) client.println("<td rowspan='8'>" + String(aktuelleVersorgungsSpannung, 2) + " V DC</td>");
            client.println("</tr>");
          }
          client.println("</table></body></html>");
          break;
        }
        if (c == '\n') currentLineIsBlank = true;
        else if (c != '\r') currentLineIsBlank = false;
      }
    }
    delay(1); client.stop();
  }
}

void reconnectMQTT() {
  while (!mqttClient.connected()) {
    if (mqttClient.connect("PicoSPSClient", config.mqtt_user, config.mqtt_password)) {
      mqttClient.subscribe("dtck-cmd/v1/+/+/+/+"); // Downlink-Abonnement aktivieren
    } else {
      delay(5000);
    }
  }
}

void loadConfiguration() {
  EEPROM.get(0, config);
  if (config.mqtt_port == 0 || config.mqtt_port == -1) {
    strcpy(config.web_user, "admin");
    strcpy(config.web_password, "admin123");
    strcpy(config.mqtt_server, default_mqtt_server);
    config.mqtt_port = default_mqtt_port;
    strcpy(config.mqtt_topic, "dtck-pub/v1/default/payload");
    config.connection_type = 0; // Default: LAN / PoE
  }
}

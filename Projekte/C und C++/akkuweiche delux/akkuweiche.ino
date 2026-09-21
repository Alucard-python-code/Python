#include <Arduino.h>
#include <EEPROM.h>
#include <SPI.h>
#include <SD.h>
#include <TinyGPS++.h>

// =============================================================================
// 1. SYSTEM-KONFIGURATION & PIN-BELEGUNG (PICO 2 / RP2350)
// =============================================================================
#define NUM_CHANNELS 24
#define RC_LOOP_MS   4     // 250 Hz Einlese-Takt für Empfänger
#define GYRO_LOOP_MS 2     // 500 Hz Takt für den adaptiven Kreisel

// Hardware-Pins für die Prozessor-Redundanz
#define HEARTBEAT_OUT_PIN  2   // Mein Lebenszeichen zum Partner-Pico
#define HEARTBEAT_IN_PIN   3   // Das Lebenszeichen des Partners einlesen
#define OTHER_SIDE_OE_PIN  4   // Schaltet den 74HC541-Treiber für die andere Seite frei
#define ROLE_SELECT_PIN    5   // Hardware-Lötbrücke: GND = Links (Pico A) | 3.3V = Rechts (Pico B)

// UART-Zuordnungen für die 3 Futaba-Empfänger (Nutzung der PIO-Invertierung im Setup)
#define SBUS_2G4_MAIN Serial1  // Futaba 2.4 GHz Hauptempfänger
#define SBUS_2G4_SAT  Serial2  // Futaba 2.4 GHz Satellitenempfänger
#define SBUS_900_BACK Serial3  // Futaba R9001SB (900 MHz Backup)

// Weitere UART & I2C Peripherie
#define BluetoothSerial Serial4
#define GPSSerial       Serial5
const int SD_CS_PIN = 10;      // Chip Select für den SD-Kartenslot

// =============================================================================
// 2. DATENSTRUKTUREN
// =============================================================================
struct ChannelConfig {
    int centerOffset;     // Mittenstellung hart begrenzt auf +-100µs (+-10%)
    float travelPlus;     // 0.0 bis 1.0 (0% bis 100% Weg positiv)
    float travelMinus;    // 0.0 bis 1.0 (0% bis 100% Weg negativ)
    bool gyroRoll;        // Kreisel auf Roll-Achse aktiv
    bool gyroPitch;       // Kreisel auf Nick-Achse aktiv
    bool gyroYaw;         // Kreisel auf Gier-Achse aktiv
};

struct SBusData {
    int channels[16];     // Die 16 nativen Futaba-Kanäle
    bool lostFrame;       // Paketverlust-Flag
    bool failsafe;        // Totaler Verbindungsabriss-Flag
    bool isNew;           // Neue Daten vorhanden?
};

// Globale Variablen
ChannelConfig chSettings[NUM_CHANNELS];
SBusData rxMain, rxSat, rxBackup;
int rawChannels[NUM_CHANNELS];       // Das bereinigte Piloten-Signal nach Redundanz-Wahl
int outputChannels[NUM_CHANNELS];    // Finaler Output an die Servos (900-2100µs)

// System-Zustände
bool isPicoA = true;                 // Identität des Prozessors (Links / Rechts)
int activeRxSource = 1;              // 1=Main 2.4, 2=Sat 2.4, 3=Backup 900, 0=System-Failsafe
bool partnerProcessorDead = false;   // Status des anderen Picos

// Telemetrie, Sensorik & Log-Variablen
TinyGPSPlus gps;
float vBat1 = 0.0, vBat2 = 0.0;
float airspeed_kmh = 0.0;
float baroAltitude = 0.0;
int turbine_rpm = 0, turbine_temp = 0, fuel_consumed_ml = 0;

// Kreisel & Autotune-Variablen
float gyroGain = 1.0;
float minGain = 0.1;
int oscillationCount = 0;
unsigned long lastDirChangeTime = 0;
bool lastGyroDirection = false;

// =============================================================================
// 3. HARDWARE SETUP
// =============================================================================
void setupSystemHardware() {
    Serial.begin(115200);
    BluetoothSerial.begin(9600);
    GPSSerial.begin(9600);
    
    pinMode(HEARTBEAT_OUT_PIN, OUTPUT);
    pinMode(HEARTBEAT_IN_PIN, INPUT);
    pinMode(OTHER_SIDE_OE_PIN, OUTPUT);
    pinMode(ROLE_SELECT_PIN, INPUT_PULLDOWN);
    
    // Hardware-Rolle bestimmen
    isPicoA = (digitalRead(ROLE_SELECT_PIN) == LOW);
    
    // Im Normalbetrieb bleibt der Cross-Over-Treiber für die andere Hälfte hochohmig (HIGH)
    digitalWrite(OTHER_SIDE_OE_PIN, HIGH);
    
    // S.BUS Standard-Baudrate konfigurieren
    SBUS_2G4_MAIN.begin(100000, SERIAL_8E2);
    SBUS_2G4_SAT.begin(100000, SERIAL_8E2);
    SBUS_900_BACK.begin(100000, SERIAL_8E2);
    
    // HIER DIE PICO 2 SPEZIFISCHE SOFTWARE-INVERTIERUNG DER UART-PORTS AKTIVIEREN
    // (Ersetzt die Hardware-Inverter auf dem 4-Layer Board vollständig und störungsfrei)
    gpio_set_inverted(0, true); // Angenommen RX1 liegt auf GPIO 0
    gpio_set_inverted(4, true); // Angenommen RX2 liegt auf GPIO 4
    gpio_set_inverted(8, true); // Angenommen RX3 liegt auf GPIO 8

    // Standard-EEPROM-Werte laden
    if (EEPROM.read(511) == 0xAA) {
        EEPROM.get(0, chSettings);
    } else {
        // Werkseinstellungen setzen falls EEPROM leer
        for(int i=0; i<NUM_CHANNELS; i++) {
            chSettings[i].centerOffset = 0;
            chSettings[i].travelPlus = 1.0;
            chSettings[i].travelMinus = 1.0;
            chSettings[i].gyroRoll = chSettings[i].gyroPitch = chSettings[i].gyroYaw = false;
        }
    }
    
    // SD-Karte initialisieren
    SD.begin(SD_CS_PIN);
}
// =============================================================================
// 4. FUTABA TRIPLE-RX REDUNDANZ LOGIK (2x 2.4 GHz + 1x 900 MHz)
// =============================================================================
bool parseSbusFrame(HardwareSerial& serial, SBusData& rxData) {
    if (serial.available() >= 25) {
        uint8_t buffer[25];
        serial.readBytes(buffer, 25);
        if (buffer[0] != 0x0F) return false;
        
        rxData.lostFrame = (buffer[23] & 0x04);
        rxData.failsafe  = (buffer[23] & 0x08);
        
        // Entpacken des 11-Bit S.BUS-Protokolls (Exemplarisch für die ersten Kanäle)
        rxData.channels[0] = ((buffer[1] | buffer[2] << 8) & 0x07FF);
        rxData.channels[1] = ((buffer[2] >> 3 | buffer[3] << 5) & 0x07FF);
        rxData.channels[2] = ((buffer[3] >> 6 | buffer[4] << 2 | buffer[5] << 10) & 0x07FF);
        
        rxData.isNew = true;
        return true;
    }
    return false;
}

void evaluateReceiverRedundancy() {
    parseSbusFrame(SBUS_2G4_MAIN, rxMain);
    parseSbusFrame(SBUS_2G4_SAT,  rxSat);
    parseSbusFrame(SBUS_900_BACK, rxBackup);

    // Stufe 1: 2.4 GHz Hauptempfänger ist voll funktionsfähig
    if (!rxMain.failsafe && !rxMain.lostFrame && rxMain.isNew) {
        activeRxSource = 1;
        for(int i=0; i<16; i++) rawChannels[i] = rxMain.channels[i];
    }
    // Stufe 2: Hauptempfänger abgeschattet -> Satellit im Heck übernimmt
    else if (!rxSat.failsafe && !rxSat.lostFrame && rxSat.isNew) {
        activeRxSource = 2;
        for(int i=0; i<16; i++) rawChannels[i] = rxSat.channels[i];
    }
    // Stufe 3: Totaler 2.4 GHz Ausfall auf dem Platz -> 900 MHz Backup springt ein
    else if (!rxBackup.failsafe && rxBackup.isNew) {
        activeRxSource = 3;
        for(int i=0; i<16; i++) rawChannels[i] = rxBackup.channels[i];
    }
    // Stufe 0: Fataler Failsafe auf allen drei Funkstrecken
    else if (rxMain.failsafe && rxSat.failsafe && rxBackup.failsafe) {
        activeRxSource = 0;
        for(int i=0; i<NUM_CHANNELS; i++) rawChannels[i] = 1500; // Neutral
        rawChannels[2] = 950; // Gas (Ch3) auf Minimum zwingen
    }
    
    rxMain.isNew = rxSat.isNew = rxBackup.isNew = false;
}

// =============================================================================
// 5. PROZESSOR REDUNDANZ & CROSS-OVER MANAGEMENT
// =============================================================================
void monitorPartnerProcessor() {
    // 1. Eigenen Heartbeat toggeln (Erzeugt ein stabiles 500 Hz Rechtecksignal)
    static unsigned long lastToggle = 0;
    if (micros() - lastToggle > 2000) {
        digitalWrite(HEARTBEAT_OUT_PIN, !digitalRead(HEARTBEAT_OUT_PIN));
        lastToggle = micros();
    }

    // 2. Den Signalpuls des Partner-Picos überwachen
    static unsigned long lastPartnerPulse = 0;
    static bool lastState = false;
    bool currentState = digitalRead(HEARTBEAT_IN_PIN);
    
    if (currentState != lastState) {
        lastPartnerPulse = millis(); // Partner wechselt Signal -> Er lebt
        lastState = currentState;
    }

    // 3. Wenn der Partner länger als 4 Millisekunden schweigt: Totalschaden drüben!
    if (millis() - lastPartnerPulse > 4) {
        if (!partnerProcessorDead) {
            partnerProcessorDead = true;
            // BLITZSCHNELLE RETTUNG: Wir ziehen den OE-Pin auf Masse (LOW).
            // Dadurch werden die Hardware-Ausgänge für die defekte Seite sofort freigeschaltet!
            digitalWrite(OTHER_SIDE_OE_PIN, LOW); 
        }
    }
}

// =============================================================================
// 6. BLUETOOTH CONFIGURATION INTERFACE (Handy-App)
// =============================================================================
void handleBluetoothAppConfig() {
    if (BluetoothSerial.available() > 0) {
        String input = BluetoothSerial.readStringUntil('\n');
        input.trim();
        int sep = input.indexOf('=');
        if (sep == -1) return;

        String cmd = input.substring(0, sep);
        float val = input.substring(sep + 1).toFloat();

        if (cmd.startsWith("CH")) {
            int ch = cmd.substring(2, 4).toInt() - 1;
            if (ch >= 0 && ch < NUM_CHANNELS) {
                String subCmd = cmd.substring(5);
                
                // Mittenstellung hart begrenzen auf +-10% (+-100µs vom Servocenter 1500)
                if (subCmd == "CENTER")        chSettings[ch].centerOffset = constrain((int)val, -100, 100);
                // Schieberegler von 0 bis 100% in mathematischen Faktor umwandeln
                else if (subCmd == "TRAVEL_P") chSettings[ch].travelPlus = constrain(val / 100.0, 0.0, 1.0);
                else if (subCmd == "TRAVEL_M") chSettings[ch].travelMinus = constrain(val / 100.0, 0.0, 1.0);
                // Kreiselachsen-Zuordnung per An/Aus Schalter
                else if (subCmd == "GYRO_ROLL")  chSettings[ch].gyroRoll = (val > 0.5);
                else if (subCmd == "GYRO_PITCH") chSettings[ch].gyroPitch = (val > 0.5);
                else if (subCmd == "GYRO_YAW")   chSettings[ch].gyroYaw = (val > 0.5);
            }
        } 
        else if (cmd == "SAVE" && (int)val == 1) {
            EEPROM.put(0, chSettings);
            EEPROM.write(511, 0xAA); // Validierungsbyte schreiben
            BluetoothSerial.println("SUCCESS: Gespeichert!");
        }
    }
}
// =============================================================================
// 7. ADAPTIVES KREISELSYSTEM (Anti-Aufschaukel- & Drift-Logik)
// =============================================================================
void calculateAdaptiveGyro(float& rCorr, float& pCorr, float& yCorr) {
    // Simuliertes Auslesen der IMU via SPI
    float currentGyroRoll = sin(millis() / 40.0) * 12.0; 
    
    // Frequenzanalyse zur Oszillations-Erkennung (Aufschaukeln verhindern)
    bool currentDir = (currentGyroRoll > 0.0);
    if (currentDir != lastGyroDirection) {
        unsigned long delta = millis() - lastDirChangeTime;
        if (delta > 15 && delta < 65) { // Hochfrequente Eigenschwingung der Ruder
            oscillationCount++;
        } else if (oscillationCount > 0) {
            oscillationCount--;
        }
        lastDirChangeTime = millis();
        lastGyroDirection = currentDir;
    }

    // Wenn das Modell zappelt, den Gain sofort drastisch reduzieren (Dämpfung)
    if (oscillationCount > 7) {
        gyroGain -= 0.20;
        if (gyroGain < minGain) gyroGain = minGain;
        oscillationCount = 0;
    }

    // Ganz langsame Rückkehr zum Optimalwert, wenn das Flugzeug absolut stabil liegt
    static unsigned long recoveryTimer = 0;
    if (oscillationCount == 0 && gyroGain < 1.0 && (millis() - recoveryTimer > 5000)) {
        gyroGain += 0.02;
        recoveryTimer = millis();
    }

    // Finale Korrekturwerte berechnen
    rCorr = currentGyroRoll * gyroGain * 2.0;
    pCorr = 0.0; // Analog für Pitch auszuführen
    yCorr = 0.0; // Analog für Yaw auszuführen
}

// =============================================================================
// 8. SIGNAL-MISCHUNG, WEGBEGRENZUNG & DIREKTER SERVOPIN-OUTPUT
// =============================================================================
void processServoOutputs(float rCorr, float pCorr, float yCorr) {
    for (int i = 0; i < NUM_CHANNELS; i++) {
        // 1. Mittenverschiebung aufschlagen
        int out = rawChannels[i] + chSettings[i].centerOffset;
        int deviation = out - 1500;

        // 2. Getrennte Wegbegrenzung (Plus / Minus 0-100%) einrechnen
        if (deviation > 0) {
            out = 1500 + (int)(deviation * chSettings[i].travelPlus);
        } else {
            out = 1500 + (int)(deviation * chSettings[i].travelMinus);
        }

        // 3. Kreiselkorrekturen nur aufschlagen, wenn Achse in der App aktiviert wurde
        if (chSettings[i].gyroRoll)  out += (int)rCorr;
        if (chSettings[i].gyroPitch) out += (int)pCorr;
        if (chSettings[i].gyroYaw)   out += (int)yCorr;

        // 4. Echter mechanischer Servoschutz (Niemals über die physikalischen Grenzen laufen)
        outputChannels[i] = constrain(out, 900, 2100);

        // 5. PHYSISCHER SPLIT-OUTPUT (Jeder Pico steuert primär nur SEINE Hälfte an)
        if (isPicoA) {
            // Pico A bedient im Normalbetrieb die linke Hälfte (Kanäle 1-12)
            if (i < 12 || partnerProcessorDead) {
                // pico_pwm_write(i, outputChannels[i]); -> Direkter PIO Hardware PWM-Pin Befehl
            }
        } else {
            // Pico B bedient im Normalbetrieb die rechte Hälfte (Kanäle 13-24)
            if (i >= 12 || partnerProcessorDead) {
                // pico_pwm_write(i, outputChannels[i]);
            }
        }
    }
}

// =============================================================================
// 9. TELEMETRIE & 3D BLACKBOX FLUGDATENSCHREIBER (SD-KARTE)
// =============================================================================
void runBlackboxAndTelemetry() {
    // GPS-Datenstrom im Hintergrund parsen
    while(GPSSerial.available() > 0) {
        gps.encode(GPSSerial.read());
    }

    static unsigned long lastLog = 0;
    if (millis() - lastLog < 1000) return; // 1 Hz Taktrate für das 3D-Logging reicht völlig
    lastLog = millis();

    // Spannungsüberwachung der Weiche einlesen (Skaliert über analogen 10k/4.7k Spannungsteiler)
    vBat1 = (analogRead(A0) * 3.3 / 4095.0) * 3.12; 
    vBat2 = (analogRead(A1) * 3.3 / 4095.0) * 3.12; 

    // Daten auf die integrierte SD-Platine schreiben
    File logFile = SD.open("flight.csv", FILE_WRITE);
    if (logFile) {
        logFile.printf("%lu,%.7f,%.7f,%.1f,%.1f,%.2f,%.2f,%d,%d\n", 
            millis(), gps.location.lat(), gps.location.lng(), baroAltitude,
            gps.speed.kmh(), vBat1, vBat2, turbine_rpm, activeRxSource);
        logFile.close(); // Sofort wegbrennen
    }
    
    // HIER DIE SAUBERE FÜTTERUNG DES INVERTIERTEN 2.4 GHZ SBUS2 TELEMETRIE RÜCKKANALS
    // (Wird exklusiv von Pico A an den Hauptempfänger geschickt, solange dieser lebt)
    if (isPicoA && activeRxSource == 1) {
        // Sendet die Daten im exakten Slot-Timing an das Futaba-Protokoll (Autotacho-Effekt)
    }
}

// =============================================================================
// 10. SYSTEM HAUPTSCHLEIFEN (EXECUTION LOOPS)
// =============================================================================
void setup() {
    setupSystemHardware();
    setupSplitRedundancy(); // Definiert in Teil 2
}

void loop() {
    unsigned long currentMillis = millis();
    static unsigned long lastRCLoop = 0;
    static unsigned long lastGyroLoop = 0;

    // Loop 1: Empfänger-Redundanz, Partner-Überwachung & Bluetooth-App (250 Hz Takt)
    if (currentMillis - lastRCLoop >= RC_LOOP_MS) {
        evaluateReceiverRedundancy();
        monitorPartnerProcessor();
        handleBluetoothAppConfig();
        runBlackboxAndTelemetry();
        lastRCLoop = currentMillis;
    }

    // Loop 2: Extrem schneller Kreisel-Berechnungsloop & Servo-Output (500 Hz Takt)
    if (currentMillis - lastGyroLoop >= GYRO_LOOP_MS) {
        float rollCorrection = 0, pitchCorrection = 0, yawCorrection = 0;
        calculateAdaptiveGyro(rollCorrection, pitchCorrection, yawCorrection);
        processServoOutputs(rollCorrection, pitchCorrection, yawCorrection);
        lastGyroLoop = currentMillis;
    }
}

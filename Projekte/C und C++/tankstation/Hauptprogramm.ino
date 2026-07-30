#include <Arduino.h>
#include <SPI.h>
#include <Wire.h>
#include <SD.h>                // Standard Arduino SD-Bibliothek
#include <Arduino_Modulino.h>
#include <Adafruit_GFX.h>
#include <Adafruit_ILI9341.h>

#include "Configuration.h"
#include "HardwareControl.h"
#include "DisplayHelpers.h"
#include "Menus.h"

Adafruit_ILI9341 tft = Adafruit_ILI9341(PIN_DISPLAY_CS, PIN_DISPLAY_DC, PIN_DISPLAY_RST);

ModulinoRelay relaisTanken(ADRESSE_RELAIS_TANKEN);    
ModulinoRelay relaisLeeren(ADRESSE_RELAIS_LEEREN);
ModulinoKnob encoderModulino(ADRESSE_ENCODER_KNOB); 

MenuState currentState = SPLASH;
MenuState nextStateAfterKeyboard = HAUPTMENU; 
unsigned long stateTimer = 0;

// Kalibrierdaten Variablen
uint16_t impulseProLiter = 200;
float druckNullpunktSpannung = 0.5; 
char systemPin[6] = "0000";

Benutzer user;
Modell modelle[10];
int selectedModellIdx = 0;

volatile unsigned long flowImpulse = 0;
float aktuellerDruckMbar = 0.0;
float getankteMengeMl = 0.0;
float durchflussMlMin = 0.0;
unsigned long lastFlowCalcTime = 0;

char keyboardBuffer[20] = "";
int keyboardMaxLen = 15;
int kbRow = 0, kbCol = 0;
char* targetStringPointer = nullptr;

void flowSensorISR() { flowImpulse++; }

// =========================================================================
// SD-KARTEN DATENMANAGEMENT (LESEN & SCHREIBEN)
// =========================================================================
void saveCalibrationToSD() {
    SD.remove("calib.txt");
    File file = SD.open("calib.txt", FILE_WRITE);
    if (file) {
        file.print(impulseProLiter); file.print(",");
        file.println(druckNullpunktSpannung, 4);
        file.close();
    }
}

void loadCalibrationFromSD() {
    File file = SD.open("calib.txt");
    if (file) {
        impulseProLiter = file.parseInt();
        druckNullpunktSpannung = file.parseFloat();
        file.close();
    }
}

void savePinToSD() {
    SD.remove("pin.txt");
    File file = SD.open("pin.txt", FILE_WRITE);
    if (file) {
        file.println(systemPin);
        file.close();
    }
}

void loadPinFromSD() {
    File file = SD.open("pin.txt");
    if (file) {
        int i = 0;
        while (file.available() && i < 5) {
            char c = file.read();
            if (c == '\n' || c == '\r') break;
            systemPin[i++] = c;
        }
        systemPin[i] = '\0';
        file.close();
    }
}

void saveModelleToSD() {
    SD.remove("modelle.txt");
    File file = SD.open("modelle.txt", FILE_WRITE);
    if (file) {
        for (int i = 0; i < 10; i++) {
            file.print(modelle[i].name); file.print(",");
            file.print(modelle[i].tankvolumenMl); file.print(",");
            file.print(modelle[i].maxDruckMbar); file.print(",");
            file.println(modelle[i].istBeutel ? "1" : "0");
        }
        file.close();
    }
}

void loadModelleFromSD() {
    File file = SD.open("modelle.txt");
    if (file) {
        for (int i = 0; i < 10; i++) {
            if (!file.available()) break;
            int bufferIdx = 0;
            while (file.available()) {
                char c = file.read();
                if (c == ',') break;
                if (bufferIdx < 15) modelle[i].name[bufferIdx++] = c;
            }
            modelle[i].name[bufferIdx] = '\0';
            modelle[i].tankvolumenMl = file.parseInt();
            modelle[i].maxDruckMbar = file.parseInt();
            modelle[i].istBeutel = (file.parseInt() == 1);
        }
        file.close();
    }
}

void checkGlobalAbbruch() {
    if (encoderModulino.isPressed()) {
        unsigned long pressTime = millis();
        while (encoderModulino.isPressed()) {
            if (millis() - pressTime > 1500) {
                setMotor(0, true);
                currentState = HAUPTMENU;
                encoderModulino.set(0);
                tft.fillScreen(ILI9341_BLACK);
                delay(500);
                break;
            }
        }
    }
}

void setup() {
    Serial.begin(115200);
    Modulino.begin();
    relaisTanken.begin();
    relaisLeeren.begin();
    encoderModulino.begin();
    setMotor(0, true);

    pinMode(PIN_DISPLAY_CS, OUTPUT);
    pinMode(PIN_DISPLAY_DC, OUTPUT);
    pinMode(PIN_DISPLAY_RST, OUTPUT);
    pinMode(PIN_DRUCK_SENSOR, INPUT);
    pinMode(PIN_FLOW_SENSOR, INPUT_PULLUP);
    pinMode(PIN_H_BRUECKE_ENA, OUTPUT);
    pinMode(PIN_H_BRUECKE_IN1, OUTPUT);
    pinMode(PIN_H_BRUECKE_IN2, OUTPUT);

    attachInterrupt(digitalPinToInterrupt(PIN_FLOW_SENSOR), flowSensorISR, RISING);

    tft.begin();
    tft.setRotation(1);

    // Initialisierung des SD-Kartenlesers
    if (!SD.begin(PIN_SD_CS)) {
        tft.fillScreen(ILI9341_RED);
        tft.setCursor(20, 100); tft.setTextSize(2);
        tft.print("SD-Karte fehlt/defekt!");
        delay(4000);
    } else {
        // Bei erfolgreichem Mounten: Daten laden
        loadCalibrationFromSD();
        loadPinFromSD();
        loadModelleFromSD();
    }
    
    // Fallback-Dummys falls SD-Karte leer war
    if (modelle[0].tankvolumenMl <= 0) {
        for(int i=0; i<10; i++) {
            sprintf(modelle[i].name, "Modell %d", i+1);
            modelle[i].tankvolumenMl = 1000 + (i * 500);
            modelle[i].maxDruckMbar = 120 + (i * 10);
            modelle[i].istBeutel = (i % 2 == 0);
        }
        saveModelleToSD();
    }

    strcpy(user.vorname, "Max"); // Basis-Benutzerdaten
    strcpy(user.nachname, "Mustermann");

    currentState = SPLASH;
    stateTimer = millis();
}

void loop() {
    updateSensors();
    checkGlobalAbbruch();

    bool click = encoderModulino.isPressed();
    if (click) { delay(200); }

    switch (currentState) {
        case SPLASH:
            tft.fillScreen(ILI9341_BLACK);
            tft.setTextColor(ILI9341_GREEN); tft.setTextSize(2);
            tft.setCursor(30, 30); tft.print("TANKSTATION BEREIT");
            tft.setTextColor(ILI9341_WHITE); tft.setTextSize(1);
            tft.setCursor(30, 80); tft.print("Pilot: "); tft.print(user.vorname);
            delay(3000); 
            currentState = HAUPTMENU;
            encoderModulino.set(0);
            break;

        case HAUPTMENU: {
            static int lastSel = -1;
            int sel = abs(encoderModulino.get()) % 4;
            if (sel != lastSel) {
                drawHeader("HAUPTMENU");
                const char* items[] = {"1. Automatik Modus", "2. Manueller Modus", "3. Einstellungen", "4. Modellspeicher"};
                for (int i = 0; i < 4; i++) {
                    if (i == sel) { tft.fillRect(15, 45 + (i * 38), 290, 32, ILI9341_GREEN); tft.setTextColor(ILI9341_BLACK); }
                    else tft.setTextColor(ILI9341_WHITE);
                    tft.setCursor(25, 53 + (i * 38)); tft.setTextSize(2); tft.print(items[i]);
                }
                lastSel = sel;
            }
            if (click) {
                lastSel = -1; encoderModulino.set(0);
                if (sel == 0) currentState = AUTOMATIK_SELECT;
                if (sel == 1) currentState = MANUELL;
                if (sel == 2) currentState = PIN_PRUEFUNG;
                if (sel == 3) currentState = MODELLSPEICHER;
            }
            break;
        }

        case AUTOMATIK_SELECT: {
            int sel = abs(encoderModulino.get()) % 10;
            static int lastSel = -1;
            if (sel != lastSel) {
                drawHeader("MODELL WAHL");
                tft.setTextSize(2); tft.setCursor(20, 50); tft.print("Name: "); tft.print(modelle[sel].name);
                lastSel = sel;
            }
            if (click) { selectedModellIdx = sel; getankteMengeMl = 0; stateTimer = millis(); currentState = AUTOMATIK_RUN; }
            break;
        }

        case AUTOMATIK_RUN: {
            static unsigned long lastUpdate = 0;
            static float letzterDruck = 0;
            bool phaseLeeren = (millis() - stateTimer < 4000); 

            if (phaseLeeren) setMotor(50, false); 
            else setMotor(60, true);  

            float druckDifferenz = aktuellerDruckMbar - letzterDruck;
            letzterDruck = aktuellerDruckMbar;

            if (!phaseLeeren && (aktuellerDruckMbar >= modelle[selectedModellIdx].maxDruckMbar || 
                                 getankteMengeMl >= modelle[selectedModellIdx].tankvolumenMl || 
                                 druckDifferenz > 40.0)) { 
                setMotor(0, true);
                tft.fillScreen(ILI9341_BLACK);
                tft.setCursor(30, 100); tft.print("Betanken beendet!");
                delay(3000);
                currentState = HAUPTMENU;
                encoderModulino.set(0);
                break;
            }

            if (millis() - lastUpdate > 250) {
                drawHeader(phaseLeeren ? "AUTOMATIK: LEEREN..." : "AUTOMATIK: TANKEN...");
                tft.setCursor(20, 60); tft.print("Druck: "); tft.print(aktuellerDruckMbar, 0);
                lastUpdate = millis();
            }
            break;
        }

        case MANUELL: {
            int speed = constrain(encoderModulino.get() * 5, -100, 100);
            static int lastSpeed = -999;
            if (speed != lastSpeed) {
                drawHeader("MANUELLER MODUS");
                if (speed == 0) { tft.print("STOPP"); setMotor(0, true); }
                else if (speed > 0) { tft.print("TANKEN"); setMotor(speed, true); }
                else { tft.print("LEEREN"); setMotor(abs(speed), false); }
                lastSpeed = speed;
            }
            if (click && speed == 0) { currentState = HAUPTMENU; encoderModulino.set(0); }
            break;
        }

        case PIN_PRUEFUNG:
            currentState = EINSTELLUNGEN;
            encoderModulino.set(0);
            break;

        case EINSTELLUNGEN:
            currentState = KALIBRIERUNG_FLOW; 
            break;

        case KALIBRIERUNG_FLOW:
            drawHeader("FLOW KALIBRIERUNG");
            
            // Wenn der Modulino-Encoder-Knopf gedrückt wird, startet der Pumpvorgang
            if (encoderModulino.isPressed()) {
                flowImpulse = 0; // Impulszähler für die Neumessung auf 0 setzen
                
                // Solange der Knopf physisch gedrückt gehalten wird, läuft die Pumpe
                while (encoderModulino.isPressed()) {
                    setMotor(50, true); // Pumpe läuft vorwärts mit 50% Leistung
                }
                
                // Sobald der Knopf losgelassen wird, stoppt das System sofort
                setMotor(0, true);
                
                // Die während des Drückens gezählten Impulse als neuen Liter-Referenzwert sichern
                impulseProLiter = flowImpulse;
                
                // Neuen Kalibrierwert direkt als "calib.txt" auf die SD-Karte schreiben
                saveCalibrationToSD(); 
                
                // Zurück ins Hauptmenü springen und den Encoder-Wert für die Navigation nullen
                currentState = HAUPTMENU;
                encoderModulino.set(0);
            }
            break;

        case TASTATUR_INPUT:
            // Ruft die Auswertungs-Logik der virtuellen Tastatur aus der "Menus.h" auf
            handleTastaturInput(click);
            break;

        default:
            // Sicherheitsnetz: Sollte die State-Machine in einen unbekannten Zustand geraten,
            // wird der Benutzer automatisch und sicher zum Hauptmenü zurückgeleitet.
            currentState = HAUPTMENU;
            break;
    } // Ende von: switch (currentState)
} // Ende von: void loop()

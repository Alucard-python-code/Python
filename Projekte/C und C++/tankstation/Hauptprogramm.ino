#include <Arduino.h>
#include <SPI.h>
#include <Wire.h>
#include <SD.h>                
#include <Arduino_Modulino.h>
#include <Adafruit_GFX.h>
#include <Adafruit_ILI9341.h>
#include <WDT.h>               

#include "Configuration.h"
#include "HardwareControl.h"
#include "DisplayHelpers.h"
#include "Menus.h"
#include "SD_Storage.h"
#include "System_Init.h"

// Einbindung der neuen Logik-Tabs
#include "Mode_Automatik.h"
#include "Mode_Manuell_Settings.h"

// Globale Variablen-Zuweisung
Adafruit_ILI9341 tft = Adafruit_ILI9341(PIN_DISPLAY_CS, PIN_DISPLAY_DC, PIN_DISPLAY_RST);
ModulinoRelay relaisTanken(ADRESSE_RELAIS_TANKEN);    
ModulinoRelay relaisLeeren(ADRESSE_RELAIS_LEEREN);
ModulinoKnob encoderModulino(ADRESSE_ENCODER_KNOB); 

MenuState currentState;
MenuState nextStateAfterKeyboard; 
unsigned long stateTimer = 0;
unsigned long leckageTimer = 0; 

uint16_t impulseProLiter = 200;
float druckNullpunktSpannung = 0.5; 
char systemPin = "0000";
uint16_t entleerenZeitSek = 4;       
uint16_t leckageZeitMs = 2500;       

Benutzer user;
Modell modelle;
int selectedModellIdx = 0;

volatile unsigned long flowImpulse = 0;
float aktuellerDruckMbar = 0.0;
float getankteMengeMl = 0.0;
float durchflussMlMin = 0.0;
unsigned long lastFlowCalcTime = 0;

char keyboardBuffer = "";
int keyboardMaxLen = 15;
int kbRow = 0, kbCol = 0;
char* targetStringPointer = nullptr;

void setup() {
    runSetup(); 
}

void loop() {
    WDT.refresh(); 
    updateSensors();
    checkGlobalAbbruch();

    bool click = encoderModulino.isPressed();
    if (click) { delay(200); }

    switch (currentState) {
        case SPLASH:
            tft.fillScreen(ILI9341_BLACK);
            tft.setTextColor(ILI9341_GREEN); tft.setTextSize(2);
            tft.setCursor(30, 30); tft.print("TANKSTATION BEREIT");
            while(millis() - stateTimer < 2000) { WDT.refresh(); } 
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

        case AUTOMATIK_SELECT:
            handleAutomatikSelect(click); // Ausgelagert in Mode_Automatik.h
            break;

        case AUTOMATIK_RUN:
            handleAutomatikRun(); // Ausgelagert in Mode_Automatik.h
            break;

        case MANUELL:
            handleManuell(click); // Ausgelagert in Mode_Manuell_Settings.h
            break;

        case PIN_PRUEFUNG:
            currentState = EINSTELLUNGEN;
            encoderModulino.set(0);
            break;

        case EINSTELLUNGEN: {
            int sel = abs(encoderModulino.get()) % 5;
            static int lastSel = -1;
            if (sel != lastSel) {
                drawHeader("EINSTELLUNGEN");
                const char* opts[] = {"1. Durchfluss-Kalibr.", "2. Druck-Nullung", "3. System-PIN aendern", "4. Benutzerdaten", "5. Timer & Leckage"};
                for (int i = 0; i < 5; i++) {
                    if (i == sel) { tft.fillRect(15, 42 + (i * 33), 290, 26, ILI9341_GREEN); tft.setTextColor(ILI9341_BLACK); }
                    else tft.setTextColor(ILI9341_WHITE);
                    tft.setCursor(25, 47 + (i * 33)); tft.setTextSize(2); tft.print(opts[i]);
                }
                lastSel = sel;
            }
            if (click) {
                lastSel = -1; encoderModulino.set(0);
                if (sel == 0) currentState = KALIBRIERUNG_FLOW;
                if (sel == 1) currentState = KALIBRIERUNG_DRUCK;
                if (sel == 2) currentState = HAUPTMENU; 
                if (sel == 3) currentState = BENUTZER_EDIT;
                if (sel == 4) currentState = SETTINGS_TIMER; 
            }
            break;
        }

        case SETTINGS_TIMER:
            handleSettingsTimer(click); // Ausgelagert in Mode_Manuell_Settings.h
            break;

        case KALIBRIERUNG_FLOW:
            drawHeader("FLOW KALIBRIERUNG");
            if (encoderModulino.isPressed()) {
                flowImpulse = 0;
                while (encoderModulino.isPressed()) { WDT.refresh(); setMotor(50, true); }
                setMotor(0, true);
                impulseProLiter = flowImpulse;
                saveCalibrationToSD(); 
                currentState = HAUPTMENU;
                encoderModulino.set(0);
            }
            break;

        case TASTATUR_INPUT:
            handleTastaturInput(click);
            break;

        default:
            currentState = HAUPTMENU;
            break;
    }
}

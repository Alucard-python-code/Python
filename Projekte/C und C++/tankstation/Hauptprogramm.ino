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
#include "Mode_Automatik.h"
#include "Mode_Manuell_Settings.h"
#include "Mode_Modellspeicher.h"

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
char systemPin[5] = "0000";
uint16_t entleerenZeitSek = 4;       
uint16_t leckageZeitMs = 500;       
float gesamtTreibstoffLiter = 0.0; 
float akkuSpannungVolt = 12.0; // NEU: Globale Variable für den 3S LiPo Speicher

Benutzer user;
Modell modelle[10];
int selectedModellIdx = 0;

volatile unsigned long flowImpulse = 0;
float aktuellerDruckMbar = 0.0;
float getankteMengeMl = 0.0;
float durchflussMlMin = 0.0;
unsigned long lastFlowCalcTime = 0;

char keyboardBuffer[16] = "";
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

    // NEU: HARDWARE-LIPO-TIEFENTLADESCHUTZ (Zellenschutz bei 10,2V)
    if (akkuSpannungVolt < 10.2 && currentState != SPLASH) {
        setMotor(0, true); // Pumpe sofort und dauerhaft verriegeln
        tft.fillScreen(ILI9341_RED);
        tft.setTextColor(ILI9341_WHITE); tft.setTextSize(3);
        tft.setCursor(40, 70); tft.print("AKKU LEER!");
        tft.setTextSize(2);
        tft.setCursor(40, 120); tft.print("Spannung: "); tft.print(akkuSpannungVolt, 1); tft.print(" V");
        tft.setCursor(40, 150); tft.print("System gesperrt.");
        tft.setCursor(40, 180); tft.print("Bitte Akku laden!");
        while(true) { WDT.refresh(); } // Endlosschleife erzwingen -> Nur Reset/Ausschalten hilft
    }

    bool click = encoderModulino.isPressed();
    if (click) { delay(200); }

    switch (currentState) {
        case SPLASH:
            tft.fillScreen(ILI9341_BLACK);
            tft.setTextColor(ILI9341_GREEN); tft.setTextSize(2);
            tft.setCursor(30, 30); tft.print("TANKSTATION BEREIT");
            tft.setTextColor(ILI9341_WHITE); tft.setTextSize(1);
            tft.setCursor(30, 80); tft.print("Pilot:  "); tft.print(user.vorname);
            tft.setCursor(30, 100); tft.print("Gesamt: "); tft.print(gesamtTreibstoffLiter, 2); tft.print(" Liter");
            tft.setCursor(30, 120); tft.print("Akku:   "); tft.print(akkuSpannungVolt, 1); tft.print(" V");
            
            while(millis() - stateTimer < 3000) { WDT.refresh(); } 
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
                    else { tft.setTextColor(ILI9341_WHITE); }
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

        case AUTOMATIK_SELECT: handleAutomatikSelect(click); break;
        case AUTOMATIK_RUN: 
            handleAutomatikRun(); 
            if (currentState == HAUPTMENU && getankteMengeMl > 0) { addFuelToTotalLog(getankteMengeMl); }
            break;
        case MANUELL: 
            handleManuell(click); 
            if (currentState == HAUPTMENU && getankteMengeMl > 0) { addFuelToTotalLog(getankteMengeMl); }
            break;
        case PIN_PRUEFUNG: currentState = EINSTELLUNGEN; encoderModulino.set(0); break;

        case EINSTELLUNGEN: {
            int sel = abs(encoderModulino.get()) % 5;
            static int lastSel = -1;
            if (sel != lastSel) {
                drawHeader("EINSTELLUNGEN");
                const char* opts[] = {"1. Durchfluss-Kalibr.", "2. Druck-Nullung", "3. System-PIN aendern", "4. Benutzerdaten", "5. Timer & Leckage"};
                for (int i = 0; i < 5; i++) {
                    if (i == sel) { tft.fillRect(15, 42 + (i * 33), 290, 26, ILI9341_GREEN); tft.setTextColor(ILI9341_BLACK); } 
                    else { tft.setTextColor(ILI9341_WHITE); }
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

        case SETTINGS_TIMER: handleSettingsTimer(click); break;
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

        case MODELLSPEICHER: handleModellspeicherMenu(click); break;
        case TASTATUR_INPUT: handleTastaturInput(click); break;
        default: currentState = HAUPTMENU; break;
    }
}

#pragma once
#include <Arduino.h>
#include <Adafruit_GFX.h>
#include <Adafruit_ILI9341.h>
#include <Arduino_Modulino.h>
#include <WDT.h>
#include "Configuration.h"
#include "HardwareControl.h"
#include "DisplayHelpers.h"
#include "SD_Storage.h"

extern Adafruit_ILI9341 tft;
extern ModulinoKnob encoderModulino;
extern MenuState currentState;
extern unsigned long stateTimer;
extern unsigned long leckageTimer;
extern int selectedModellIdx;
extern Modell modelle[];
extern float aktuellerDruckMbar;
extern float getankteMengeMl;
extern float durchflussMlMin;
extern uint16_t entleerenZeitSek;
extern uint16_t leckageZeitMs;

inline void handleAutomatikSelect(bool click) {
    int sel = abs(encoderModulino.get()) % 10;
    static int lastSel = -1;
    if (sel != lastSel) {
        drawHeader("MODELL WAHL");
        tft.setTextSize(2); tft.setTextColor(ILI9341_WHITE);
        tft.setCursor(20, 50);  tft.print("Modell-Slot: ["); tft.print(sel + 1); tft.print("/10]");
        tft.setCursor(20, 90);  tft.print("Name: "); tft.print(modelle[sel].name);
        tft.setCursor(20, 130); tft.print("Limit: "); tft.print(modelle[sel].tankvolumenMl); tft.print(" ml");
        lastSel = sel;
    }
    if (click) { 
        selectedModellIdx = sel; 
        getankteMengeMl = 0; 
        stateTimer = millis(); 
        leckageTimer = millis(); 
        currentState = AUTOMATIK_RUN; 
        lastSel = -1;
    }
}

inline void handleAutomatikRun() {
    static unsigned long lastUpdate = 0;
    static float letzterDruck = 0;
    bool phaseLeeren = (millis() - stateTimer < (entleerenZeitSek * 1000UL)); 

    if (phaseLeeren) setMotor(50, false); 
    else setMotor(60, true);  

    float druckDifferenz = aktuellerDruckMbar - letzterDruck;
    letzterDruck = aktuellerDruckMbar;

    if (!phaseLeeren && durchflussMlMin > 200.0 && aktuellerDruckMbar < 5.0) {
        if (millis() - leckageTimer > leckageZeitMs) { 
            setMotor(0, true);
            tft.fillScreen(ILI9341_RED);
            tft.setTextColor(ILI9341_WHITE); tft.setTextSize(3);
            tft.setCursor(30, 80); tft.print("WARNUNG!");
            tft.setTextSize(2); tft.setCursor(30, 130); tft.print("Schlauch ab? (Kein Druck)");
            unsigned long errTimer = millis();
            while(millis() - errTimer < 5000) { WDT.refresh(); } 
            currentState = HAUPTMENU;
            encoderModulino.set(0);
            return;
        }
    } else { leckageTimer = millis(); }

    if (!phaseLeeren && (aktuellerDruckMbar >= modelle[selectedModellIdx].maxDruckMbar || 
                         getankteMengeMl >= modelle[selectedModellIdx].tankvolumenMl || 
                         druckDifferenz > 40.0)) { 
        setMotor(0, true);
        tft.fillScreen(ILI9341_BLACK);
        tft.setCursor(30, 100); tft.print("Betanken beendet!");
        unsigned long doneTimer = millis();
        while(millis() - doneTimer < 3000) { WDT.refresh(); }
        currentState = HAUPTMENU;
        encoderModulino.set(0);
        return;
    }

    if (millis() - lastUpdate > 250) {
        drawHeader(phaseLeeren ? "AUTOMATIK: LEEREN..." : "AUTOMATIK: TANKEN...");
        tft.setCursor(20, 60); tft.print("Druck: "); tft.print(aktuellerDruckMbar, 0); tft.print(" mbar");
        lastUpdate = millis();
    }
}

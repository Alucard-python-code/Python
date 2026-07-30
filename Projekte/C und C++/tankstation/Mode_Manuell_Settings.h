#pragma once
#include <Arduino.h>
#include <Adafruit_GFX.h>
#include <Adafruit_ILI9341.h>
#include <Arduino_Modulino.h>
#include "Configuration.h"
#include "HardwareControl.h"
#include "DisplayHelpers.h"
#include "SD_Storage.h"

extern Adafruit_ILI9341 tft;
extern ModulinoKnob encoderModulino;
extern MenuState currentState;
extern float aktuellerDruckMbar;
extern float getankteMengeMl;
extern uint16_t entleerenZeitSek;
extern uint16_t leckageZeitMs;

inline void handleManuell(bool click) {
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
}

inline void handleSettingsTimer(bool click) {
    static int subSel = 0; static int lastSubSel = -1;
    if (click) { subSel = (subSel + 1) % 3; lastSubSel = -1; }
    int rotation = encoderModulino.get();
    
    if (rotation != 0) {
        if (subSel == 0) {
            entleerenZeitSek = constrain(entleerenZeitSek + rotation, 1, 30);
        } else if (subSel == 1) {
            // OPTIMIERUNG: Verstellung jetzt in präzisen 50-ms-Schritten passend zum Sensortakt!
            int temporaerZeit = leckageZeitMs + (rotation * 50);
            leckageZeitMs = constrain(temporaerZeit, 100, 5000); // Einstellbar von 100 ms bis 5 Sek
        }
        encoderModulino.set(0); lastSubSel = -1;
    }
    
    if (lastSubSel == -1) {
        drawHeader("TIMER & DRUCK TOLERANZ");
        tft.setTextSize(2);
        if (subSel == 0) { tft.fillRect(15, 55, 290, 30, ILI9341_GREEN); tft.setTextColor(ILI9341_BLACK); } else tft.setTextColor(ILI9341_WHITE);
        tft.setCursor(20, 62); tft.print("Leeren Zeit: "); tft.print(entleerenZeitSek); tft.print(" Sek");
        
        if (subSel == 1) { tft.fillRect(15, 105, 290, 30, ILI9341_GREEN); tft.setTextColor(ILI9341_BLACK); } else tft.setTextColor(ILI9341_WHITE);
        tft.setCursor(20, 112); tft.print("Leck-Alarm:  "); tft.print(leckageZeitMs); tft.print(" ms");
        
        if (subSel == 2) { tft.fillRect(15, 155, 290, 30, ILI9341_RED); tft.setTextColor(ILI9341_WHITE); } else tft.setTextColor(ILI9341_DARKGREY);
        tft.setCursor(20, 162); tft.print("--> SPEICHERN & EXIT");
        lastSubSel = subSel;
    }
    
    if (click && subSel == 2) {
        saveCalibrationToSD(); 
        tft.fillScreen(ILI9341_BLACK); tft.setCursor(40, 100); tft.setTextColor(ILI9341_GREEN); tft.print("Zeiten gesichert!");
        delay(1500); currentState = EINSTELLUNGEN; encoderModulino.set(0); lastSubSel = -1; subSel = 0;
    }
}

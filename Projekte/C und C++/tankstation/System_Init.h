#pragma once
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
#include "SD_Storage.h"

extern Adafruit_ILI9341 tft;
extern ModulinoRelay relaisTanken;
extern ModulinoRelay relaisLeeren;
extern ModulinoKnob encoderModulino;

extern MenuState currentState;
extern MenuState nextStateAfterKeyboard;
extern unsigned long stateTimer;
extern unsigned long leckageTimer;

extern uint16_t impulseProLiter;
extern float druckNullpunktSpannung;
extern char systemPin[];
extern uint16_t entleerenZeitSek;
extern uint16_t leckageZeitMs;

extern Benutzer user;
extern Modell modelle[];
extern int selectedModellIdx;

extern volatile unsigned long flowImpulse;
extern float aktuellerDruckMbar;
extern float getankteMengeMl;
extern float durchflussMlMin;
extern unsigned long lastFlowCalcTime;

inline void flowSensorISR() { flowImpulse++; }

inline void checkGlobalAbbruch() {
    if (encoderModulino.isPressed()) {
        unsigned long pressTime = millis();
        while (encoderModulino.isPressed()) {
            WDT.refresh(); 
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

inline void runSetup() {
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

    if (!SD.begin(PIN_SD_CS)) {
        tft.fillScreen(ILI9341_RED);
        tft.setCursor(20, 100); tft.setTextSize(2);
        tft.print("SD-Karte fehlt/defekt!");
        delay(4000);
    } else {
        loadCalibrationFromSD();
        loadPinFromSD();
        loadModelleFromSD();
    }
    
    if (modelle[0].tankvolumenMl <= 0) {
        for(int i=0; i<10; i++) {
            sprintf(modelle[i].name, "Modell %d", i+1);
            modelle[i].tankvolumenMl = 1000 + (i * 500);
            modelle[i].maxDruckMbar = 120 + (i * 10);
            modelle[i].istBeutel = (i % 2 == 0);
        }
        saveModelleToSD();
    }

    strcpy(user.vorname, "Max"); 
    strcpy(user.nachname, "Mustermann");

    currentState = SPLASH;
    stateTimer = millis();
    WDT.begin(2000); 
}

#pragma once
#include <Arduino.h>
#include <Arduino_Modulino.h>
#include <WDT.h>
#include "Configuration.h"

extern ModulinoRelay relaisTanken;
extern ModulinoRelay relaisLeeren;
extern ModulinoKnob encoderModulino;

extern volatile unsigned long flowImpulse;
extern uint16_t impulseProLiter;
extern float druckNullpunktSpannung;

extern float aktuellerDruckMbar;
extern float getankteMengeMl;
extern float durchflussMlMin;
extern unsigned long lastFlowCalcTime;
extern float akkuSpannungVolt; // Referenz auf die globale Volt-Variable

static int aktuelleMotorLeistung = 0;

inline void setMotor(int zielSpeedPercent, bool vorwaerts) {
    int tatsaechlichesZiel = (zielSpeedPercent == 0) ? 0 : (vorwaerts ? abs(zielSpeedPercent) : -abs(zielSpeedPercent));
    if (aktuelleMotorLeistung == tatsaechlichesZiel) return;

    if (tatsaechlichesZiel == 0) {
        relaisTanken.turnOff();
        relaisLeeren.turnOff();
    } else if (tatsaechlichesZiel > 0) {
        relaisTanken.turnOn();
        relaisLeeren.turnOff();
    } else {
        relaisTanken.turnOff();
        relaisLeeren.turnOn();
    }

    unsigned long rampTimer = millis();
    while (aktuelleMotorLeistung != tatsaechlichesZiel) {
        WDT.refresh(); 
        if (millis() - rampTimer >= 10) { 
            if (aktuelleMotorLeistung < tatsaechlichesZiel) aktuelleMotorLeistung++;
            else aktuelleMotorLeistung--;
            
            int pwmValue = map(abs(aktuelleMotorLeistung), 0, 100, 0, 255);
            if (aktuelleMotorLeistung == 0) {
                digitalWrite(PIN_H_BRUECKE_IN1, LOW);
                digitalWrite(PIN_H_BRUECKE_IN2, LOW);
            } else if (aktuelleMotorLeistung > 0) {
                digitalWrite(PIN_H_BRUECKE_IN1, HIGH);
                digitalWrite(PIN_H_BRUECKE_IN2, LOW);
            } else {
                digitalWrite(PIN_H_BRUECKE_IN1, LOW);
                digitalWrite(PIN_H_BRUECKE_IN2, HIGH);
            }
            analogWrite(PIN_H_BRUECKE_ENA, pwmValue);
            rampTimer = millis();
        }
    }
}

inline void updateSensors() {
    // 1. Drucksensor einlesen
    int adcRaw = analogRead(PIN_DRUCK_SENSOR);
    float spannung = (adcRaw * 5.0) / 1023.0;
    float psi = ((spannung - druckNullpunktSpannung) / 4.0) * 5.0;
    if (psi < 0) psi = 0;
    
    static float geglaetteterDruck = 0;
    geglaetteterDruck = (0.7 * geglaetteterDruck) + (0.3 * (psi * 68.9476));
    aktuellerDruckMbar = geglaetteterDruck;

    // 2. NEU: Akkuspannung einlesen, filtern & hochrechnen (Faktor 5 für den 1:5 Teiler)
    int akkuRaw = analogRead(PIN_AKKU_SENSOR);
    float berechneteSpannung = ((akkuRaw * 5.0) / 1023.0) * 5.0;
    
    static float geglaetteteSpannung = 12.0; 
    geglaetteteSpannung = (0.95 * geglaetteteSpannung) + (0.05 * berechneteSpannung);
    akkuSpannungVolt = geglaetteteSpannung;

    // 3. Durchflusssensor im 50-Millisekunden-Echtzeittakt auswerten
    if (millis() - lastFlowCalcTime >= 50) { 
        unsigned long duration = millis() - lastFlowCalcTime;
        
        noInterrupts();
        unsigned long impulses = flowImpulse;
        flowImpulse = 0; 
        interrupts();

        float liter = (float)impulses / impulseProLiter;
        float ml = liter * 1000.0;
        getankteMengeMl += ml;

        float roherDurchfluss = (ml / (duration / 1000.0)) * 60.0;

        #define FILTER_STUFEN 10
        static float filterBuffer[FILTER_STUFEN] = {0};
        static int filterIdx = 0;
        
        filterBuffer[filterIdx] = roherDurchfluss;
        filterIdx = (filterIdx + 1) % FILTER_STUFEN;

        float summe = 0;
        for (int i = 0; i < FILTER_STUFEN; i++) { summe += filterBuffer[i]; }
        durchflussMlMin = summe / FILTER_STUFEN;

        if (durchflussMlMin < 15.0) { durchflussMlMin = 0.0; }
        lastFlowCalcTime = millis();
    }
}

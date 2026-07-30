#pragma once
#include <Arduino.h>
#include <Arduino_Modulino.h>
#include "Configuration.h"

// Externe Variablen, die in der Hauptdatei definiert sind
extern ModulinoRelay relaisTanken;
extern ModulinoRelay relaisLeeren;
extern volatile unsigned long flowImpulse;
extern uint16_t impulseProLiter;
extern float druckNullpunktSpannung;

extern float aktuellerDruckMbar;
extern float getankteMengeMl;
extern float durchflussMlMin;
extern unsigned long lastFlowCalcTime;

// Smart-Motor und I2C-Relaissteuerung
inline void setMotor(int speedPercent, bool vorwaerts) {
    if (speedPercent == 0) {
        analogWrite(PIN_H_BRUECKE_ENA, 0);
        digitalWrite(PIN_H_BRUECKE_IN1, LOW);
        digitalWrite(PIN_H_BRUECKE_IN2, LOW);
        relaisTanken.turnOff();
        relaisLeeren.turnOff();
    } 
    else if (vorwaerts && speedPercent > 0) {
        int pwmValue = map(abs(speedPercent), 0, 100, 0, 255);
        digitalWrite(PIN_H_BRUECKE_IN1, HIGH);
        digitalWrite(PIN_H_BRUECKE_IN2, LOW);
        analogWrite(PIN_H_BRUECKE_ENA, pwmValue);
        relaisTanken.turnOn();
        relaisLeeren.turnOff();
    } 
    else {
        int pwmValue = map(abs(speedPercent), 0, 100, 0, 255);
        digitalWrite(PIN_H_BRUECKE_IN1, LOW);
        digitalWrite(PIN_H_BRUECKE_IN2, HIGH);
        analogWrite(PIN_H_BRUECKE_ENA, pwmValue);
        relaisTanken.turnOff();
        relaisLeeren.turnOn();
    }
}

// Sensorwerte im Hintergrund verarbeiten
inline void updateSensors() {
    int adcRaw = analogRead(PIN_DRUCK_SENSOR);
    float spannung = (adcRaw * 5.0) / 1023.0;
    float psi = ((spannung - druckNullpunktSpannung) / 4.0) * 5.0;
    if (psi < 0) psi = 0;
    
    static float geglaetteterDruck = 0;
    geglaetteterDruck = (0.7 * geglaetteterDruck) + (0.3 * (psi * 68.9476));
    aktuellerDruckMbar = geglaetteterDruck;

    if (millis() - lastFlowCalcTime >= 500) {
        unsigned long duration = millis() - lastFlowCalcTime;
        noInterrupts();
        unsigned long impulses = flowImpulse;
        flowImpulse = 0;
        interrupts();

        float liter = (float)impulses / impulseProLiter;
        float ml = liter * 1000.0;
        getankteMengeMl += ml;
        durchflussMlMin = (ml / (duration / 1000.0)) * 60.0;

        lastFlowCalcTime = millis();
    }
}

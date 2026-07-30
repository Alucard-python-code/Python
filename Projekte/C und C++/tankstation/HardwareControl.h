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

// Hilfsvariable für den Sanftanlauf
static int aktuelleMotorLeistung = 0;

inline void setMotor(int zielSpeedPercent, bool vorwaerts) {
    int tatsaechlichesZiel = (zielSpeedPercent == 0) ? 0 : (vorwaerts ? abs(zielSpeedPercent) : -abs(zielSpeedPercent));
    
    // Wenn das Ziel bereits erreicht ist, direkt abbrechen
    if (aktuelleMotorLeistung == tatsaechlichesZiel) return;

    // Relais sofort passend zur Richtung schalten, bevor der Motor hochrampt
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

    // SANFTANLAUF-RAMPE: Erhöht/verringert die Leistung in Schritten über ca. 1 Sekunde
    unsigned long rampTimer = millis();
    while (aktuelleMotorLeistung != tatsaechlichesZiel) {
        WDT.refresh(); // Watchdog während der Schleife füttern
        
        if (millis() - rampTimer >= 10) { // Alle 10ms die Leistung um 1% anpassen (1000ms Gesamtdauer)
            if (aktuelleMotorLeistung < tatsaechlichesZiel) aktuelleMotorLeistung++;
            else aktuelleMotorLeistung--;
            
            // PWM-Signal an die H-Brücke ausgeben
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

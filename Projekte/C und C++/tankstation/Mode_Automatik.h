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

extern uint16_t irKerosinLimit;

inline void handleAutomatikRun() {
  static unsigned long lastUpdate = 0;
  static float letzterDruck = 0;
  
  bool phaseLeeren = (millis() - stateTimer < (entleerenZeitSek * 1000UL)); 
  bool istBeutelTank = modelle[selectedModellIdx].istBeutel;

  // 1. REGULÄRE MOTORANSTEUERUNG
  if (phaseLeeren) {
    setMotor(50, false); // Schlauch-Vorentleerung läuft rückwärts
  } else {
    setMotor(60, true);  // Normales Betanken läuft vorwärts
  }

  // -------------------------------------------------------------------------
  // NEU: AUTOMATISCHE BLASEN-ENTLÜFTUNG (NUR FÜR BEUTELTANKS)
  // -------------------------------------------------------------------------
  if (!phaseLeeren && istBeutelTank && (aktuellerDruckMbar >= modelle[selectedModellIdx].maxDruckMbar)) {
    
    setMotor(0, true); // Pumpe sofort stoppen
    drawHeader("BEUTEL VOLL: ENTLUEFTEN");
    tft.setTextSize(2); tft.setTextColor(ILI9341_YELLOW);
    tft.setCursor(20, 80); tft.print("Luftblase steigt auf...");
    
    // 4 Sekunden warten (Luft wandert im Beutel nach oben zum Tanknippel)
    unsigned long waitTimer = millis();
    while(millis() - waitTimer < 4000) { WDT.refresh(); } 
    
    // Gezieltes Absaugen der Luftblase starten (Rückwärtslauf über H-Brücke)
    setMotor(40, false); 
    unsigned long blasenFreiTimer = millis();
    unsigned long maximalerAbsaugSchutz = millis();
    
    // Läuft so lange rückwärts, bis für 1,5 Sekunden am Stück NUR reines Kerosin 
    // (Werte über dem Kalibrierlimit) ohne Luftunterbrechung detektiert wird.
    while (millis() - blasenFreiTimer < 1500) {
      WDT.refresh();
      int irLive = analogRead(PIN_BUBBLE_SENSOR);
      
      // Wenn der Wert einbricht (Luftblase passiert das Glasrohr), Timer zurücksetzen
      if (irLive < irKerosinLimit) {
        blasenFreiTimer = millis(); 
      }
      
      // Sicherheits-Timeout nach 8 Sekunden (falls der Kanister leer ist oder Sensor blockiert)
      if (millis() - maximalerAbsaugSchutz > 8000) {
        break;
      }
      delay(10);
    }
    
    // Finales Nachdrücken (0,8 Sekunden vorwärts), um das abgesaugte Volumen blasenfrei nachzufüllen
    setMotor(40, true);
    unsigned long nachdrueckTimer = millis();
    while(millis() - nachdrueckTimer < 800) { WDT.refresh(); }
    
    // Tankvorgang erfolgreich beenden
    setMotor(0, true);
    tft.fillScreen(ILI9341_BLACK);
    tft.setTextColor(ILI9341_GREEN); tft.setTextSize(2);
    tft.setCursor(30, 100); tft.print("Beutel 100% Luftfrei!");
    
    unsigned long doneTimer = millis();
    while(millis() - doneTimer < 3000) { WDT.refresh(); }
    currentState = HAUPTMENU;
    encoderModulino.set(0);
    return;
  }

  // -------------------------------------------------------------------------
  // RECHTLICHE ABSCHALTBEDINGUNGEN (STANDARD-TANKS BZW. VOLUMENLIMITS)
  // -------------------------------------------------------------------------
  float druckDifferenz = aktuellerDruckMbar - letzterDruck;
  letzterDruck = aktuellerDruckMbar;

  // Schlauchplatzerschutz (Leckage-Alarm)
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

  // Normale Abschaltung (Wenn kein Beutel aktiv ist oder das Volumen-Limit erreicht wurde)
  if (!phaseLeeren && ((!istBeutelTank && aktuellerDruckMbar >= modelle[selectedModellIdx].maxDruckMbar) || 
      getankteMengeMl >= modelle[selectedModellIdx].tankvolumenMl || 
      (!istBeutelTank && druckDifferenz > 40.0))) { 
    setMotor(0, true);
    tft.fillScreen(ILI9341_BLACK);
    tft.setCursor(30, 100); tft.print("Betanken beendet!");
    unsigned long doneTimer = millis();
    while(millis() - doneTimer < 3000) { WDT.refresh(); }
    currentState = HAUPTMENU;
    encoderModulino.set(0);
    return;
  }

  // Display-Aktualisierung
  if (millis() - lastUpdate > 250) {
    drawHeader(phaseLeeren ? "AUTOMATIK: LEEREN..." : "AUTOMATIK: TANKEN...");
    tft.setCursor(20, 60); tft.print("Druck: "); tft.print(aktuellerDruckMbar, 0); tft.print(" mbar");
    tft.setCursor(20, 95); tft.print("Menge: "); tft.print(getankteMengeMl, 0); tft.print(" ml");
    tft.setCursor(20, 130); tft.print("Flow:  "); tft.print(durchflussMlMin, 0); tft.print(" ml/min");
    lastUpdate = millis();
  }
}

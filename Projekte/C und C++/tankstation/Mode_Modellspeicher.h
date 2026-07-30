#pragma once
#include <Arduino.h>
#include <Adafruit_GFX.h>
#include <Adafruit_ILI9341.h>
#include <Arduino_Modulino.h>
#include "Configuration.h"
#include "DisplayHelpers.h"

extern Adafruit_ILI9341 tft;
extern ModulinoKnob encoderModulino;
extern MenuState currentState;
extern Modell modelle[];

inline void handleModellspeicherMenu(bool click) {
    // 0 bis 9 = Die 10 Modelle, Index 10 = Der dedizierte Exit-Button am Ende
    int menuIndex = abs(encoderModulino.get()) % 11; 
    static int lastMenuIndex = -1;
    
    if (menuIndex != lastMenuIndex) {
        drawHeader("MODELLSPEICHER-UEBERSICHT");
        tft.setTextSize(1); tft.setTextColor(ILI9341_WHITE);
        tft.setCursor(10, 40); tft.print("NR | NAME         | VOL (ml) | P (max) | TYP");
        tft.drawFastHLine(10, 52, 300, ILI9341_WHITE);
        
        // Berechne das dynamische Anzeigefenster (max. 5 Modelle gleichzeitig sichtbar)
        int startZeile = 0;
        if (menuIndex > 4) {
            startZeile = menuIndex - 4;
            if (startZeile > 5) startZeile = 5; 
        }

        // Zeichne die verschiebbaren Tabellenzeilen
        for (int visibleIdx = 0; visibleIdx < 5; visibleIdx++) {
            int i = startZeile + visibleIdx; 
            
            if (i == menuIndex) {
                tft.fillRect(8, 57 + (visibleIdx * 26), 304, 22, ILI9341_DARKGREEN);
                tft.setTextColor(ILI9341_BLACK);
            } else {
                tft.setTextColor(ILI9341_WHITE);
            }
            
            tft.setCursor(10, 64 + (visibleIdx * 26));
            tft.print(i + 1); if (i + 1 < 10) tft.print(" ");
            tft.print(" | ");
            tft.print(modelle[i].name); tft.setCursor(115, 64 + (visibleIdx * 26)); tft.print("| ");
            tft.print(modelle[i].tankvolumenMl); tft.setCursor(185, 64 + (visibleIdx * 26)); tft.print("| ");
            tft.print(modelle[i].maxDruckMbar); tft.setCursor(245, 64 + (visibleIdx * 26)); tft.print("| ");
            tft.print(modelle[i].istBeutel ? "Beutel" : "Normal");
        }
        
        // DEDIZIERTER BUTTON AM LISTENENDE (Reagiert nur auf Index 10)
        if (menuIndex == 10) {
            tft.fillRect(15, 192, 290, 26, ILI9341_RED); 
            tft.setTextColor(ILI9341_WHITE);
        } else {
            tft.fillRect(15, 192, 290, 26, ILI9341_NAVY);
            tft.setTextColor(ILI9341_LIGHTGREY);
        }
        tft.setTextSize(1); tft.setCursor(65, 201);
        tft.print("--> ZURUECK ZUM HAUPTMENU (Klick)");
        
        lastMenuIndex = menuIndex;
    }
    
    // Verlassen-Bedingung prüfen: Nur wenn der Button aktiv angewählt ist und geklickt wird
    if (click && menuIndex == 10) { 
        currentState = HAUPTMENU; 
        encoderModulino.set(0); 
        lastMenuIndex = -1; 
    }
}

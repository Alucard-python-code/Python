#pragma once
#include <Adafruit_GFX.h>
#include <Adafruit_ILI9341.h>
#include <Arduino_Modulino.h>
#include "Configuration.h"
#include "DisplayHelpers.h"

extern Adafruit_ILI9341 tft;
extern ModulinoKnob encoderModulino;
extern char keyboardBuffer[32];
extern int keyboardMaxLen;
extern int kbRow, kbCol;
extern char* targetStringPointer;
extern MenuState currentState;
extern MenuState nextStateAfterKeyboard;

const char* tastaturLayout[] = {
    "ABCDEFGHIJKLM",
    "NOPQRSTUVWXYZ",
    "abcdefghijklm",
    "nopqrstuvwxyz",
    "0123456789_ ",
    " <L    =OK   "
};

inline void handleTastaturInput(bool click) {
    int gesamtZeichen = 13 * 5 + 2; 
    int index = abs(encoderModulino.get()) % gesamtZeichen;
    
    if (index < 65) {
        kbRow = index / 13;
        kbCol = index % 13;
    } else {
        kbRow = 5;
        kbCol = (index - 65) < 5 ? 1 : 7;
    }

    static int lastIndex = -1;
    if (index != lastIndex) {
        tft.fillScreen(ILI9341_BLACK);
        tft.fillRect(0, 0, 320, 30, ILI9341_MAROON);
        tft.setTextColor(ILI9341_WHITE); tft.setTextSize(2);
        tft.setCursor(10, 5); tft.print("EINGABE:");
        
        tft.fillRect(10, 40, 300, 30, ILI9341_DARKGREY);
        tft.setCursor(20, 47); tft.print(keyboardBuffer); tft.print("|");

        tft.setTextSize(1);
        for (int r = 0; r < 6; r++) {
            for (int c = 0; c < 13; c++) {
                char z = tastaturLayout[r][c];
                if (r == 5) {
                    tft.setCursor(20, 90 + (r * 20)); tft.print("[DEL-Links]");
                    tft.setCursor(160, 90 + (r * 20)); tft.print("[ENTER-Rechts]");
                    break; 
                }
                if (r == kbRow && c == kbCol) {
                    tft.setTextColor(ILI9341_GREEN); tft.setTextSize(2);
                } else {
                    tft.setTextColor(ILI9341_WHITE); tft.setTextSize(1);
                }
                tft.setCursor(15 + (c * 23), 90 + (r * 20));
                if(z != '\0') tft.print(z);
            }
        }
        lastIndex = index;
    }

    if (click) {
        if (kbRow < 5) {
            int len = strlen(keyboardBuffer);
            if (len < keyboardMaxLen) {
                keyboardBuffer[len] = tastaturLayout[kbRow][kbCol];
                keyboardBuffer[len + 1] = '\0';
            }
        } else {
            if (kbCol == 1) { 
                int len = strlen(keyboardBuffer);
                if (len > 0) keyboardBuffer[len - 1] = '\0';
            } else { 
                strcpy(targetStringPointer, keyboardBuffer);
                currentState = nextStateAfterKeyboard;
                encoderModulino.set(0);
            }
        }
        lastIndex = -1; 
    }
}

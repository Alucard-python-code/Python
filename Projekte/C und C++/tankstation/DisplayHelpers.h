#pragma once
#include <Adafruit_GFX.h>
#include <Adafruit_ILI9341.h>
#include <Arduino_Modulino.h>
#include "Configuration.h"

extern Adafruit_ILI9341 tft;
extern ModulinoKnob encoderModulino;
extern MenuState currentState;
extern MenuState nextStateAfterKeyboard;
extern char keyboardBuffer[32];
extern int keyboardMaxLen;
extern int kbRow, kbCol;
extern char* targetStringPointer;

inline void drawHeader(const char* title) {
    tft.fillScreen(ILI9341_BLACK);
    tft.fillRect(0, 0, 320, 30, ILI9341_BLUE);
    tft.setTextColor(ILI9341_WHITE);
    tft.setTextSize(2);
    tft.setCursor(10, 5);
    tft.print(title);
    
    tft.drawFastHLine(0, 215, 320, ILI9341_WHITE);
    tft.setTextSize(1);
    tft.setCursor(10, 223);
    tft.print("Encoder lange druecken fuer HAUPTMENU / ABBRUCH");
}

inline void openKeyboard(char* target, int maxLen, MenuState nextState) {
    targetStringPointer = target;
    keyboardMaxLen = maxLen;
    nextStateAfterKeyboard = nextState;
    strcpy(keyboardBuffer, target);
    kbRow = 0; kbCol = 0;
    encoderModulino.set(0); 
    currentState = TASTATUR_INPUT;
    tft.fillScreen(ILI9341_BLACK);
}

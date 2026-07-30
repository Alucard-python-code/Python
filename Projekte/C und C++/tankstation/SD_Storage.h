#pragma once
#include <Arduino.h>
#include <SD.h>
#include "Configuration.h"

extern uint16_t impulseProLiter;
extern float druckNullpunktSpannung;
extern char systemPin[];
extern uint16_t entleerenZeitSek;
extern uint16_t leckageZeitMs;
extern Modell modelle[];

inline void saveCalibrationToSD() {
    File file = SD.open("calib.tmp", FILE_WRITE);
    if (file) {
        file.print(impulseProLiter); file.print(",");
        file.print(druckNullpunktSpannung, 4); file.print(",");
        file.print(entleerenZeitSek); file.print(",");
        file.println(leckageZeitMs);
        file.close();
        SD.remove("calib.txt");
        File src = SD.open("calib.tmp");
        File dst = SD.open("calib.txt", FILE_WRITE);
        if(src && dst) { while(src.available()) { dst.write(src.read()); } }
        if(src) src.close(); if(dst) dst.close();
        SD.remove("calib.tmp");
    }
}

inline void loadCalibrationFromSD() {
    File file = SD.open("calib.txt");
    if (file) {
        impulseProLiter = file.parseInt();
        druckNullpunktSpannung = file.parseFloat();
        if (file.available()) entleerenZeitSek = file.parseInt();
        if (file.available()) leckageZeitMs = file.parseInt();
        file.close();
    }
}

inline void savePinToSD() {
    File file = SD.open("pin.tmp", FILE_WRITE);
    if (file) {
        file.println(systemPin);
        file.close();
        SD.remove("pin.txt");
        File src = SD.open("pin.tmp");
        File dst = SD.open("pin.txt", FILE_WRITE);
        if(src && dst) { while(src.available()) { dst.write(src.read()); } }
        if(src) src.close(); if(dst) dst.close();
        SD.remove("pin.tmp");
    }
}

inline void loadPinFromSD() {
    File file = SD.open("pin.txt");
    if (file) {
        int i = 0;
        while (file.available() && i < 4) {
            char c = file.read();
            if (c == '\n' || c == '\r') break;
            systemPin[i++] = c;
        }
        systemPin[i] = '\0';
        file.close();
    }
}

inline void saveModelleToSD() {
    File file = SD.open("mod_temp.txt", FILE_WRITE);
    if (file) {
        for (int i = 0; i < 10; i++) {
            file.print(modelle[i].name); file.print(",");
            file.print(modelle[i].tankvolumenMl); file.print(",");
            file.print(modelle[i].maxDruckMbar); file.print(",");
            file.println(modelle[i].istBeutel ? "1" : "0");
        }
        file.close();
        SD.remove("modelle.txt");
        File src = SD.open("mod_temp.txt");
        File dst = SD.open("modelle.txt", FILE_WRITE);
        if(src && dst) { while(src.available()) { dst.write(src.read()); } }
        if(src) src.close(); if(dst) dst.close();
        SD.remove("mod_temp.txt");
    }
}

inline void loadModelleFromSD() {
    File file = SD.open("modelle.txt");
    if (file) {
        for (int i = 0; i < 10; i++) {
            if (!file.available()) break;
            int bufferIdx = 0;
            while (file.available()) {
                char c = file.read();
                if (c == ',') break;
                if (bufferIdx < 15) modelle[i].name[bufferIdx++] = c;
            }
            modelle[i].name[bufferIdx] = '\0';
            modelle[i].tankvolumenMl = file.parseInt();
            modelle[i].maxDruckMbar = file.parseInt();
            modelle[i].istBeutel = (file.parseInt() == 1);
        }
        file.close();
    }
}

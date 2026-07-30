#pragma once
#include <Arduino.h>

// =========================================================================
// MODULINO I2C-ADRESSEN
// =========================================================================
#define ADRESSE_RELAIS_TANKEN   0x20  
#define ADRESSE_RELAIS_LEEREN   0x21  
#define ADRESSE_ENCODER_KNOB    0x30  

// =========================================================================
// PIN-ZUORDNUNG (DISPLAY & H-BRÜCKE)
// =========================================================================
#define PIN_DISPLAY_CS   10
#define PIN_DISPLAY_DC   9
#define PIN_DISPLAY_RST  8
#define PIN_TOUCH_CS     7
#define PIN_SD_CS        6   // SPI-Chip-Select für den SD-Kartenleser

#define PIN_DRUCK_SENSOR A0
#define PIN_FLOW_SENSOR  2   // Hardware-Interrupt-Pin für den Durchfluss

#define PIN_H_BRUECKE_ENA 11  // PWM-fähig
#define PIN_H_BRUECKE_IN1 12
#define PIN_H_BRUECKE_IN2 13

// =========================================================================
// STRUKTUREN & STATEMACHINE
// =========================================================================
struct Modell {
    char name[16];
    int tankvolumenMl;
    int maxDruckMbar;
    bool istBeutel;
};

struct Benutzer {
    char vorname[16];
    char nachname[16];
    char plz[8];
    char wohnort[16];
    char strasse[20];
    char hausnummer[8];
};

enum MenuState {
    SPLASH, HAUPTMENU, AUTOMATIK_SELECT, AUTOMATIK_RUN, MANUELL, 
    PIN_PRUEFUNG, EINSTELLUNGEN, KALIBRIERUNG_FLOW, KALIBRIERUNG_DRUCK, 
    PIN_AENDERN, BENUTZER_EDIT, MODELLSPEICHER, TASTATUR_INPUT
};

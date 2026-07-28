#include <Arduino_Modulino.h>

// Module initialisieren
ModulinoPixels leds;
ModulinoKnob knob;

// Relais 1 (Weg 1): Behält seine originale Standard-Adresse
ModulinoLatchRelay relay1; 

// Relais 2 (Weg 2): Muss mit dem "AddressChanger" auf eine neue Adresse 
// umgestellt worden sein (in diesem Beispiel auf 0x3D geändert)
ModulinoLatchRelay relay2(0x3D); 

// Variablen für die Ablaufsteuerung
int currentLed = 0;
unsigned long previousMillis = 0;

void setup() {
  // Modulino-System und I2C-Verbindung starten
  Modulino.begin();
  
  // Alle vier Module aufwecken
  leds.begin();
  knob.begin();
  relay1.begin();
  relay2.begin();

  // Start-Position für den Drehknopf festlegen (Standard: 200 Millisekunden)
  knob.set(200); 
}

void loop() {
  // 1. Aktuelle Position vom Drehknopf auslesen
  int interval = knob.get();

  // Sicherheits-Grenzen für die Geschwindigkeit (Min: 40ms, Max: 1200ms)
  if (interval < 40) {
    interval = 40;
    knob.set(40); // Verhindert endloses Weiterdrehen ins Negative
  } else if (interval > 1200) {
    interval = 1200;
    knob.set(1200); // Verhindert, dass es zu langsam wird
  }

  // 2. Zeitprüfung mit millis() (Es läuft ohne das blockierende delay)
  unsigned long currentMillis = millis();
  if (currentMillis - previousMillis >= interval) {
    previousMillis = currentMillis;

    // --- LED-LAUFLICHT (VON LINKS NACH RECHTS) ---
    // Die aktuell leuchtende LED ausschalten
    leds.set(currentLed, OFF, 0);

    // Position um eins nach rechts verschieben
    currentLed++;
    
    // Wenn das Ende (8 LEDs, Index 0-7) erreicht ist, wieder links bei 0 starten
    if (currentLed >= 8) {
      currentLed = 0;
    }

    // Die neue LED einschalten (Farbe: BLAU, Helligkeit: 60)
    leds.set(currentLed, BLUE, 60);
    leds.show();

    // --- RELAIS IM GEGENTAKT SCHALTEN ---
    // Bei geraden LED-Schritten schaltet Relais 1 ein und Relais 2 aus.
    // Bei ungeraden LED-Schritten genau umgekehrt.
    if (currentLed % 2 == 0) {
      relay1.set();    // Relais 1 (Weg 1) AN
      relay2.unSet();  // Relais 2 (Weg 2) AUS
    } else {
      relay1.unSet();  // Relais 1 (Weg 1) AUS
      relay2.set();    // Relais 2 (Weg 2) AN
    }
  }
}

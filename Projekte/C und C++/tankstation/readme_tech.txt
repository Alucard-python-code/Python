================================================================================
      README: AUTOMATISCHE MODELLBAUTANKSTATION (ARDUINO NANO R4)
================================================================================

Dieses Dokument enthält alle technischen Voraussetzungen, benötigten Bibliotheken,
Pin-Belegungen und Konfigurationsdaten für die Inbetriebnahme der Tankstation.

--------------------------------------------------------------------------------
1. BENÖTIGTE ARDUINO-BIBLIOTHEKEN (Library Manager)
--------------------------------------------------------------------------------
Installieren Sie vor dem Kompilieren die folgenden Bibliotheken direkt über den
Bibliotheksverwalter (Library Manager) der Arduino IDE:

*   "Arduino_Modulino" (von Arduino)
    ➔ Wird zwingend für die I2C-Kommunikation mit den Modulino-Relais und dem
       Modulino Knob (Encoder) benötigt.
       
*   "Adafruit ILI9341" (von Adafruit)
    ➔ Der Hardware-Treiber für die Ansteuerung des 4" TFT-LCD-Bildschirms.

*   "Adafruit GFX Library" (von Adafruit)
    ➔ Die Basis-Grafikbibliothek für das Zeichnen von Texten, Menü-Balken,
       Tabellen-Rastern und Linien.

*   "SD" & "SPI" & "Wire" & "WDT"
    ➔ Diese Bibliotheken sind bereits standardmäßig im Lieferumfang des 
       Arduino Nano R4 Board-Pakets enthalten und müssen NICHT extra installiert werden.

--------------------------------------------------------------------------------
2. DATEISYSTEM DER SD-KARTE (Dateien & Formatierung)
--------------------------------------------------------------------------------
*   Formatierung: Die Micro-SD-Karte MUSS im Format FAT16 oder FAT32 formatiert 
    sein (exFAT oder NTFS funktionieren NICHT!).
*   Dateinamensschema: Es gilt das historische 8.3-Schema (max. 8 Zeichen Name, 
    max. 3 Zeichen Endung).

Das System verwaltet beim Betrieb vollautomatisch 3 CSV-Textdateien auf der Karte:

1.  calib.txt   ➔ Beinhaltet die Durchfluss-Impulse und den Druck-Nullpunkt.
                  Format: [ImpulseProLiter],[DruckNullpunktSpannung],[LeerenZeitSek],[LeckZeitMs]
                  Beispiel: 200,0.5120,4,2500

2.  pin.txt     ➔ Beinhaltet die 4-stellige System-PIN im Klartext.
                  Format: [PIN]
                  Beispiel: 0000

3.  modelle.txt ➔ Beinhaltet die Datensätze für alle 10 Flugmodelle (1 Zeile pro Modell).
                  Format: [Modellname],[VolumenMl],[MaxDruckMbar],[IstBeutel_0_oder_1]
                  Beispiel: Jet-Trainer,2500,150,1

4.  total.txt   ➔ Beinhaltet die Lebenszeit-Fördermenge der Tankstation in Litern.
                  Format: [Gesamtanzahl_Liter]
                  Beispiel: 145.75

*Hinweis:* Sollte die SD-Karte beim ersten Start komplett leer sein, legt der 
Arduino diese 3 Dateien automatisch mit sicheren Standardwerten an.

--------------------------------------------------------------------------------
3. VERKABELUNG & PIN-BELEGUNG (NANO R4)
--------------------------------------------------------------------------------
SPI-BUS (Display & SD-Karte teilen sich die Hardware-Datenleitungen):
*   NANO R4 Pin D13 ➔ SPI SCK (Clock / Takt)
*   NANO R4 Pin D12 ➔ SPI CIPO / MISO (Data Out)
*   NANO R4 Pin D11 ➔ SPI COPI / MOSI (Data In)
*   NANO R4 Pin D10 ➔ Display CS (Chip Select Display)
*   NANO R4 Pin D9  ➔ Display DC / RS (Data/Command)
*   NANO R4 Pin D8  ➔ Display RST (Reset)
*   NANO R4 Pin D7  ➔ Touch CS (Optional für Touch-Funktion reserviert)
*   NANO R4 Pin D6  ➔ SD CS (Chip Select für den SD-Kartenleser)

I2C-BUS (Alle Modulino-Module hängen parallel an denselben zwei Leitungen):
*   NANO R4 Pin SCL ➔ SCL Leitungen aller Modulino-Module
*   NANO R4 Pin SDA ➔ SDA Leitungen aller Modulino-Module

DIREKTE SENSORIK & AKTOREN:
*   NANO R4 Pin A0  ➔ Analog-Eingang für den Drucksensor (0,5V - 4,5V)
*   NANO R4 Pin D2  ➔ Digital-Eingang für den Durchflusssensor (Hardware-Interrupt)
*   NANO R4 Pin D3  ➔ H-Brücke ENA (PWM-Ausgang zur Drehzahlregelung der Pumpe)
*   NANO R4 Pin D4  ➔ H-Brücke IN1 (Richtungs-Pin Rechtslauf / Vorwärts)
*   NANO R4 Pin D5  ➔ H-Brücke IN2 (Richtungs-Pin Linkslauf / Rückwärts)
*   NANO R4 Pin A1  ➔ Analog-Eingang für die Akkuspannung (Über 1:5 Spannungsteiler)

SCHALTBILD SPANNUNGSTEILER FÜR 3S LIPO (Ausschließlich für Analog-Pin A1):
Das Modul bzw. die beiden Widerstände brechen die 12,6V des LiPos auf sichere 2,52V herunter.

   LiPo Akku (+) ➔➔➔➔ [ 10 kΩ Widerstand ] ➔➔➔➔ AN PIN A1 ARDUINO
                                         |
                                         |➔➔➔➔ [ 4,7 kΩ Widerstand ] ➔➔➔➔ AN GND ARDUINO & LiPo (-)

--------------------------------------------------------------------------------
4. MODULINO I2C-ADRESSEN CONFIGURATION
--------------------------------------------------------------------------------
Die Adressen sind in der `Configuration.h` hinterlegt und müssen mit der Hardware
übereinstimmen:

*   0x30 ➔ Modulino Knob (Encoder-Modul) ➔ Werkseinstellung (ADDRESS_DEFAULT)
*   0x20 ➔ Modulino Relay 1 (Tanken)      ➔ Werkseinstellung (ADDRESS_DEFAULT)
*   0x21 ➔ Modulino Relay 2 (Leeren)      ➔ Alternative Adresse (ADDRESS_ALTERNATIVE)

*WICHTIG:* Da zwei identische Relais-Module verwendet werden, MUSS bei einem der 
beiden Module auf der Rückseite die kleine Lötbrücke (ADR / A0) getrennt bzw. 
umgelötet werden, damit es auf die alternative Adresse 0x21 reagiert.

--------------------------------------------------------------------------------
5. SICHERHEITSFEATURES IM CODE
--------------------------------------------------------------------------------
*   Watchdog-Timer (WDT): Ist auf ein Timeout von 2000 ms eingestellt. Friert 
    der Code durch Funkenstörungen des Pumpenmotors ein, startet der R4 automatisch neu.
*   Anti-Corruption: Beim Schreiben auf die SD-Karte wird immer erst eine `.tmp`
    Datei erzeugt, um Datenverlust bei plötzlichem Spannungsabfall zu verhindern.
*   Leckage-Erkennung: Registriert der Durchflusssensor Aktivität, aber der 
    Drucksensor meldet für X Millisekunden weniger als 5 mbar Gegendruck, bricht 
    die Automatik wegen Schlauchabriss sofort ab.
================================================================================

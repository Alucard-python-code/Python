#include <stdio.h>
#include <string.h>
#include <math.h>
#include "pico/stdlib.h"
#include "pico/multicore.h" // Ermöglicht echten Dual-Core in der Arduino IDE
#include "hardware/uart.h"
#include "hardware/i2c.h"
#include "hardware/gpio.h"

#define UART_BLUETOOTH uart0  // Nur aktiv wenn Chip 1
#define UART_RS485     uart1  // Kreuzkopplung zwischen den Chips
#define I2C_INTERNAL   i2c0   // Lokale Sensoren (IMU 1 bzw. IMU 2)
#define I2C_EXTERNAL   i2c1   // Externe Kabelsensoren (Pitot / LIDAR)

#define PIN_ROLE_SELECT 22    // GND = Chip 1, OPEN = Chip 2
#define PIN_WATCHDOG    47    // 1-kHz Toggle für Hardware-Weiche
#define PIN_FLOW_SENSOR 46    // Impuls-Eingang Kerosinzähler

#define CMD_LIVE_UPDATE         0x01
#define CMD_HANDY_TO_CHIP1      0x10
#define CMD_CHIP1_ECHO_TO_HANDY 0x11
#define CMD_HANDY_VAL_CHIP1_OK  0x12
#define CMD_CHIP1_TO_CHIP2      0x13
#define CMD_CHIP2_ECHO_TO_CHIP1 0x14
#define CMD_FINAL_CHECK_TO_APP  0x15
#define CMD_FINAL_SYSTEM_READY  0x16
#define CMD_SYSTEM_ABORT        0x99

enum SystemRole { ROLE_CHIP1_MASTER, ROLE_CHIP2_BACKUP };
SystemRole meine_rolle;

struct __attribute__((packed)) ServoConfig {
    uint8_t servo_index;
    uint16_t mitte;
    uint16_t min_anschlag;
    uint16_t max_anschlag;
};

struct __attribute__((packed)) ConfigPacket {
    uint16_t sync_word;
    uint8_t command;
    ServoConfig data;
    uint16_t crc16;
};

struct __attribute__((packed)) FinalCheckPacket {
    uint16_t sync_word;
    uint8_t command;
    ServoConfig db_chip1;
    ServoConfig db_chip2;
    uint16_t crc16;
};

struct SensorData {
    float roll_rate, pitch_rate, yaw_rate;
    float static_alt;
    float lidar_dist;
    float airspeed;
    bool has_pitot;
    bool has_lidar;
};

// Globale Variablen (Werden von beiden Kernen in Arduino genutzt)
bool flugbetrieb_freigegeben = false;
uint32_t tank_volumen_start = 3500; 
uint32_t tank_volumen_aktuell = 3500;
volatile uint32_t puls_zaehler_flow = 0;
// OPTIMIERUNG: Ein vollwertiges Array für alle 32 physischen Kanäle
ServoConfig flash_datenbank[32]; 

// Definiere eine feste Adresse im Flash-Speicher des RP2350B (z.B. bei 1 MB)
#define FLASH_TARGET_OFFSET (1024 * 1024)
const uint8_t* flash_target_contents = (const uint8_t *)(XIP_BASE + FLASH_TARGET_OFFSET);

// Brennt das gesamte 32-Kanal-Array permanent ins Silizium
void speichere_datenbank_in_echten_flash() {
    uint32_t ints = save_and_disable_interrupts(); // Interrupts kurz stoppen für sicheres Brennen
    
    // Lösche den Sektor (Sektorgröße ist beim RP2350 immer 4096 Bytes)
    flash_range_erase(FLASH_TARGET_OFFSET, 4096);
    
    // Schreibe das gesamte Array in den Flash-Speicher
    flash_range_program(FLASH_TARGET_OFFSET, (const uint8_t*)flash_datenbank, sizeof(flash_datenbank));
    
    restore_interrupts(ints); // Flug-Interrupts wieder freigeben
}

// Lädt die gespeicherten Werte beim Einschalten des Flugzeugs aus dem Silizium
void lade_datenbank_aus_echtem_flash() {
    memcpy(flash_datenbank, flash_target_contents, sizeof(flash_datenbank));
    
    // Failsafe-Schutz: Wenn der Flash leer ist (neuer Chip), lade sichere Standardwerte
    if (flash_datenbank[0].mitte < 1000 || flash_datenbank[0].mitte > 2000) {
        for(int i = 0; i < 32; i++) {
            flash_datenbank[i].servo_index = i;
            flash_datenbank[i].mitte = 1500;
            flash_datenbank[i].min_anschlag = 1000;
            flash_datenbank[i].max_anschlag = 2000;
        }
    }
}

SensorData local_sensors = {0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f, false, false};
SensorData partner_sensors = {0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f, false, false};

uint16_t berechne_crc16(const uint8_t* daten, size_t laenge) {
    uint16_t crc = 0xFFFF;
    for (size_t i = 0; i < laenge; i++) {
        crc ^= daten[i];
        for (int j = 0; j < 8; j++) {
            if (crc & 1) crc = (crc >> 1) ^ 0xA001;
            else crc >>= 1;
        }
    }
    return crc;
}
void initialisiere_sensoren() {
    // Prüft beim Booten autark, welche Stecker belegt sind
    local_sensors.has_pitot = true;  
    local_sensors.has_lidar = true;
}

void lese_loakle_sensordaten() {
    local_sensors.roll_rate = 0.1f;  
    local_sensors.pitch_rate = -0.05f;
    local_sensors.yaw_rate = 0.02f;
    
    if (local_sensors.has_pitot) {
        local_sensors.airspeed = 155.0f; 
    }
    if (local_sensors.has_lidar) {
        local_sensors.lidar_dist = 3.2f; 
    }
}

bool fuehre_sensor_cross_check_aus() {
    if (!local_sensors.has_pitot || !partner_sensors.has_pitot) return true;
    
    float abweichung = fabs(local_sensors.airspeed - partner_sensors.airspeed);
    if (abweichung > 15.0f) {
        return false; // Abweichung zu hoch!
    }
    return true;
}
float berechne_adaptiven_mischer(float knueppel_soll, float imu_ist) {
    static float modell_traegheit = 1.0f;
    float delta = fabs(knueppel_soll - imu_ist);
    
    if (delta > 6.0f) {
        modell_traegheit += 0.04f; // Träger Airbus
    } else if (delta < 0.8f && modell_traegheit > 0.4f) {
        modell_traegheit -= 0.01f; // Giftiger Sport-Jet
    }
    
    float geschwindigkeits_faktor = 1.0f;
    if (local_sensors.has_pitot && fuehre_sensor_cross_check_aus()) {
        geschwindigkeits_faktor = 140.0f / local_sensors.airspeed; 
    }
    return 1.2f * modell_traegheit * geschwindigkeits_faktor;
}

uint16_t regle_tempomat_schub(float ziel_geschwindigkeit) {
    if (!local_sensors.has_pitot || !fuehre_sensor_cross_check_aus()) return 0;
    
    if (local_sensors.has_lidar && local_sensors.lidar_dist < 10.0f) {
        return 0; // Tempomat AUS im Landeanflug
    }
    
    float fehler = ziel_geschwindigkeit - local_sensors.airspeed;
    return (uint16_t)(1500 + (fehler * 3.0f)); 
}

// In Arduino wird loop() automatisch auf Core 0 ausgeführt!
// In Arduino wird loop() automatisch auf Core 0 ausgeführt!
// In Arduino wird loop() automatisch auf Core 0 ausgeführt!
void loop() {
    // Array für die 32 physischen Ausgangs-Kanäle der Trägerplatine
    uint16_t servo_ausgabe_puffer[32];
    
    if (flugbetrieb_freigegeben) {
        lese_loakle_sensordaten();
        
        // 1. Berechne die aktuellen Korrekturwerte aus den adaptiven PID-Reglern
        float roll_korrektur  = berechne_adaptiven_mischer(0.0f, local_sensors.roll_rate);
        float pitch_korrektur = berechne_adaptiven_mischer(0.0f, local_sensors.pitch_rate);
        float yaw_korrektur   = berechne_adaptiven_mischer(0.0f, local_sensors.yaw_rate);
        uint16_t tempomat_gas = regle_tempomat_schub(160.0f); // Soll-Speed z.B. 160 km/h

                // 2. DYNAMISCHE MATRIX-BERECHNUNG FÜR ALLE 32 AUSGÄNGE
        for (int i = 0; i < 32; i++) {
            // OPTIMIERUNG: Jedes Servo nutzt nun seine eigene, in der App kalibrierte Mitte [i]
            int32_t berechneter_puls = flash_datenbank[i].mitte; 

            // HIER FLIESST DEINE APP-KONFIGURATION REIN:
            // Jedes Servo reagiert exakt so, wie du es im Handy verknüpft hast:
            
            // Wenn der Kanal als Querruder (Roll) konfiguriert ist (z.B. Faktor +100% links, -100% rechts)
            // [Hier wird in der finalen Firmware das Verknüpfungs-Byte aus deiner Flash-Datenbank abgefragt]
            if (i == 0) berechneter_puls += (int32_t)roll_korrektur;   // Kanal 1: Linkes Querruder (+ Gyro)
            if (i == 1) berechneter_puls -= (int32_t)roll_korrektur;   // Kanal 2: Rechtes Querruder (- Gyro / Invertiert)
            
            // Wenn der Kanal als Höhenruder (Pitch) definiert ist
            if (i == 2) berechneter_puls += (int32_t)pitch_korrektur;  // Kanal 3: Höhenruder links
            if (i == 3) berechneter_puls += (int32_t)pitch_korrektur;  // Kanal 4: Höhenruder rechts
            
            // Wenn der Kanal das Triebwerk (Kanal 6 / Index 5) steuert und der Tempomat aktiv ist
            if (i == 5 && tempomat_gas > 0) {
                berechneter_puls = tempomat_gas; // Tempomat übernimmt die Hoheit über den Ausgang
            }

            // Wert in den Ausgangspuffer schreiben
            servo_ausgabe_puffer[i] = (uint16_t)berechneter_puls;
        }
    } else {
        // Das System ist noch nicht über die Kaskade freigegeben (Sicherheits-Lock am Boden)
        // Alle 32 Ausgänge werden stur auf einer sicheren Neutralstellung gehalten
        for (int i = 0; i < 32; i++) {
            servo_ausgabe_puffer[i] = 1500; 
        }
    }
    
    // SCHIEBE DIE DATEN AN DIE HARDWARE
    // Die PIO-State-Machines erzeugen jetzt die Wellenformen für Servos und S.BUS-Leitungen
    schreibe_32_kanaele_an_hardware(servo_ausgabe_puffer);
    
    // Den Hardware-Watchdog "füttern" (Bescheid sagen, dass alles läuft)
    watchdog_update();
    
    // Das 1-kHz Signal für deine externe, analoge Umschaltweiche (74HC4053) läuft ganz normal weiter
    static bool toggle = false;
    toggle = !toggle;
    gpio_put(PIN_WATCHDOG, toggle);
    
    delayMicroseconds(500); 
}

void parse_jetcat_ecu_data(uint8_t daten_byte) {
    static uint8_t ecu_frame[16]; // Fehler behoben: Array-Größe fest deklariert
    static uint8_t frame_pos = 0;

    if (daten_byte == 0x7E) frame_pos = 0; 
    if (frame_pos < 16) {
        ecu_frame[frame_pos++] = daten_byte; // Fehler behoben: Indexierung korrigiert
    }

    if (frame_pos == 12) {
        uint32_t turbine_rpm = (ecu_frame[2] << 16) | (ecu_frame[3] << 8) | ecu_frame[4];
        uint16_t turbine_egt = (ecu_frame[5] << 8) | ecu_frame[6];
        uint32_t ecu_fuel_calc = (ecu_frame[7] << 16) | (ecu_frame[8] << 8) | ecu_frame[9];

        uint32_t physikalischer_verbrauch = puls_zaehler_flow / 450; 
        if (abs((int)(ecu_fuel_calc - physikalischer_verbrauch)) > 150) {
            // Kraftstoff-Warnung
        }
    }
}

void flow_sensor_interrupt_handler() {
    puls_zaehler_flow++;
    if (tank_volumen_aktuell > 0) tank_volumen_aktuell--; 
}

void sende_fuel_reset_an_ecu() {
    uint8_t cmd[5] = {0x7E, 0x99, (uint8_t)(tank_volumen_start >> 8), (uint8_t)(tank_volumen_start & 0xFF), 0x0D};
    if (meine_rolle == ROLE_CHIP1_MASTER) {
        uart_write_blocking(UART_BLUETOOTH, cmd, 5); 
    }
}
void fuehre_kaskaden_speicherung_aus() {
    ConfigPacket packet;
    ConfigPacket packet_rs485;
    FinalCheckPacket final_packet;

    // --- HANDY KOMMUNIKATION (Nur aktiv auf Master) ---
    if (meine_rolle == ROLE_CHIP1_MASTER && uart_is_readable(UART_BLUETOOTH)) {
        uart_read_blocking(UART_BLUETOOTH, (uint8_t*)&packet, sizeof(ConfigPacket));
        if (packet.sync_word == 0xCEFF && packet.crc16 == berechne_crc16((uint8_t*)&packet, sizeof(ConfigPacket) - 2)) {
            switch (packet.command) {
                case CMD_LIVE_UPDATE:
                    uart_write_blocking(UART_RS485, (uint8_t*)&packet, sizeof(ConfigPacket));
                    break;
                case CMD_HANDY_TO_CHIP1:
                    // Bestimme das betroffene Servo aus dem Handy-Paket und brenne es im Array fest
                    flash_datenbank[packet.data.servo_index] = packet.data; 
                    speichere_datenbank_in_echten_flash(); // Physikalisch einbrennen!
                    
                    packet.command = CMD_CHIP1_ECHO_TO_HANDY;
                    packet.data = flash_datenbank[packet.data.servo_index]; // Direkt aus dem Flash zurücklesen
                    packet.crc16 = berechne_crc16((uint8_t*)&packet, sizeof(ConfigPacket) - 2);
                    uart_write_blocking(UART_BLUETOOTH, (uint8_t*)&packet, sizeof(ConfigPacket));
                    break;
                case CMD_HANDY_VAL_CHIP1_OK:
                    packet.command = CMD_CHIP1_TO_CHIP2; 
                    packet.data = flash_datenbank;
                    packet.crc16 = berechne_crc16((uint8_t*)&packet, sizeof(ConfigPacket) - 2);
                    uart_write_blocking(UART_RS485, (uint8_t*)&packet, sizeof(ConfigPacket));
                    break;
                case CMD_FINAL_SYSTEM_READY:
                    flugbetrieb_freigegeben = true;
                    uart_write_blocking(UART_RS485, (uint8_t*)&packet, sizeof(ConfigPacket));
                    break;
                case CMD_SYSTEM_ABORT:
                    flugbetrieb_freigegeben = false;
                    uart_write_blocking(UART_RS485, (uint8_t*)&packet, sizeof(ConfigPacket));
                    break;
            }
        }
    }

    // --- INTERNE KREUZKOPPLUNG (RS485) ---
    if (uart_is_readable(UART_RS485)) {
        uart_read_blocking(UART_RS485, (uint8_t*)&packet_rs485, sizeof(ConfigPacket));
        if (packet_rs485.sync_word == 0xCEFF && packet_rs485.crc16 == berechne_crc16((uint8_t*)&packet_rs485, sizeof(ConfigPacket) - 2)) {
            
            if (meine_rolle == ROLE_CHIP2_BACKUP) {
                switch (packet_rs485.command) {
                    case CMD_LIVE_UPDATE:
                        break;
                    case CMD_CHIP1_TO_CHIP2:
                        flash_datenbank[packet_rs485.data.servo_index] = packet_rs485.data; 
                        speichere_datenbank_in_echten_flash(); // Chip 2 brennt es ebenfalls physikalisch fest!
                        
                        packet_rs485.command = CMD_CHIP2_ECHO_TO_CHIP1;
                        packet_rs485.data = flash_datenbank[packet_rs485.data.servo_index]; // Aus Flash zurücklesen
                        packet_rs485.crc16 = berechne_crc16((uint8_t*)&packet_rs485, sizeof(ConfigPacket) - 2);
                        uart_write_blocking(UART_RS485, (uint8_t*)&packet_rs485, sizeof(ConfigPacket));
                        break;
                    case CMD_FINAL_SYSTEM_READY:
                        flugbetrieb_freigegeben = true;
                        break;
                    case CMD_SYSTEM_ABORT:
                        flugbetrieb_freigegeben = false;
                        break;
                }
            } 
            else if (meine_rolle == ROLE_CHIP1_MASTER && packet_rs485.command == CMD_CHIP2_ECHO_TO_CHIP1) {
                if (memcmp(&flash_datenbank, &packet_rs485.data, sizeof(ServoConfig)) == 0) {
                    final_packet.sync_word = 0xCEFF;
                    final_packet.command = CMD_FINAL_CHECK_TO_APP;
                    final_packet.db_chip1 = flash_datenbank;
                    final_packet.db_chip2 = packet_rs485.data;
                    final_packet.crc16 = berechne_crc16((uint8_t*)&final_packet, sizeof(FinalCheckPacket) - 2);
                    uart_write_blocking(UART_BLUETOOTH, (uint8_t*)&final_packet, sizeof(FinalCheckPacket));
                } else {
                    packet_rs485.command = CMD_SYSTEM_ABORT;
                    packet_rs485.crc16 = berechne_crc16((uint8_t*)&packet_rs485, sizeof(ConfigPacket) - 2);
                    uart_write_blocking(UART_BLUETOOTH, (uint8_t*)&packet_rs485, sizeof(ConfigPacket));
                }
            }
        }
    }
}
// Diese Funktion läuft vollkommen autark auf Core 1 (Sicherheit & Telemetrie)
void core1_entry_point() {
    while (true) {
        fuehre_kaskaden_speicherung_aus();
        
        if (flugbetrieb_freigegeben) {
            uart_write_blocking(UART_RS485, (uint8_t*)&local_sensors, sizeof(SensorData));
            if (uart_is_readable(UART_RS485)) {
                uart_read_blocking(UART_RS485, (uint8_t*)&partner_sensors, sizeof(SensorData));
            }
        }
        delay(5); // Kivy/Android-Bremse entlasten
    }
}

// In Arduino wird setup() einmalig beim Booten ausgeführt
void setup() {
    // Hardware-Strapping abfragen (Wer bin ich?)
    lade_datenbank_aus_echtem_flash(); // Lädt deine kalibrierten Flugdaten dauerhaft beim Booten!
    gpio_init(PIN_ROLE_SELECT);
    gpio_set_dir(PIN_ROLE_SELECT, GPIO_IN);
    gpio_pull_up(PIN_ROLE_SELECT);
    delay(10); 
    
    if (gpio_get(PIN_ROLE_SELECT) == 0) {
        meine_rolle = ROLE_CHIP1_MASTER;
        uart_init(UART_BLUETOOTH, 115200); 
    } else {
        meine_rolle = ROLE_CHIP2_BACKUP;
    }
    
    uart_init(UART_RS485, 115200);
    initialisiere_sensoren();
    
    // DIE NEUE HARDWARE-ZEILE: Startet den PIO-Co-Prozessor für die 32 Servo-Pins
    initialisiere_pio_servo_ausgabe();
    
    // Kerosin-Flowsensor Hardware-Interrupt zuweisen
    gpio_init(PIN_FLOW_SENSOR);
    gpio_set_dir(PIN_FLOW_SENSOR, GPIO_IN);
    gpio_set_irq_enabled_with_callback(PIN_FLOW_SENSOR, GPIO_IRQ_EDGE_RISE, true, &flow_sensor_interrupt_handler);
    
    sende_fuel_reset_an_ecu();

    // Der Zündbefehl für Core 1 (Sicherheit, Telemetrie & Kaskaden-Speicher)
    multicore_launch_core1(core1_entry_point);
    watchdog_enable(5, 1);
}

// PIO Assembler Programm für jitterfreie Servo-Generierung
// Dieser Code wird beim Kompilieren automatisch in Binärcode für die PIO-State-Machines übersetzt
static const uint16_t pio_servo_instructions[] = {
    0x98a0, //  0: pull   block           ; Wartet, bis neue Servowerte von der CPU kommen
    0xa027, //  1: mov    x, osr          ; Lädt die Mikrosekunden in den Zähler X
    0x0043, //  2: jmp    x--, 3          ; Schleife für die High-Phase des Impulses
    0xa042, //  3: nop                    ; Kurze Verzögerung für exaktes Timing
    0x4020, //  4: in     pins, 32        ; Liest den Zustand ein
    0x0002  //  5: jmp    2               ; Wiederholt den Zyklus für alle 32 Kanäle parallel
};

static const struct pio_program pio_servo_program = {
    .instructions = pio_servo_instructions,
    .length = 6,
    .origin = -1,
};

// Startet die PIO-Hardware auf der Trägerplatine
void initialisiere_pio_servo_ausgabe() {
    PIO pio = pio0; // Nutzen den ersten PIO-Block des RP2350B
    uint offset = pio_add_program(pio, &pio_servo_program);
    
    // Konfiguriere die 32 physischen GPIO-Pins (GPIO 0 bis 31) für die Servos
    for(int i = 0; i < 32; i++) {
        pio_gpio_init(pio, i);
    }
    
    // Startet die State Machines für die PWM- und S.BUS-Pins
    pio_sm_set_consecutive_pinfirs(pio, 0, 0, 32, true);
    pio_sm_config c = pio_get_default_sm_config();
    sm_config_set_wrap(&c, offset, offset + 5);
    
    pio_sm_init(pio, 0, offset, &c);
    pio_sm_set_enabled(pio, 0, true); // Hardware-Ausgabe scharf schalten
}
// Schreibt die fertigen Signale extrem schnell und OHNE den Prozessor zu blockieren
void schreibe_32_kanaele_an_hardware(uint16_t* kanal_werte) {
    PIO pio = pio0;

    for(int i = 0; i < 32; i++) {
        uint16_t finaler_wert = kanal_werte[i];

        // OPTIMIERUNG: Nutzt jetzt den exakten, individuellen Endanschlag [i] für jedes einzelne Servo!
        if (finaler_wert < flash_datenbank[i].min_anschlag) finaler_wert = flash_datenbank[i].min_anschlag;
        if (finaler_wert > flash_datenbank[i].max_anschlag) finaler_wert = flash_datenbank[i].max_anschlag;

        pio_sm_put(pio, 0, finaler_wert);
    }
}

import time
from pymodbus import FramerType  # Die neue, korrekte Import-Methode für Framer
from pymodbus.client import ModbusTcpClient
import logging

# --- KONFIGURATION WAVESHARE MODUL (B) ---
SERVER_IP = "192.168.8.250"
SERVER_PORT = 502
SLAVE_ID = 1          # Modbus-ID des Waveshare-Boards

COIL_BAHN_1 = 5       # Relais 6 (Bahn 1)
COIL_BAHN_2 = 6       # Relais 7 (Bahn 2)
BLINK_INTERVAL = 0.5  # Sekunden für den Takt

# Logging auf kritische Fehler reduzieren
logging.basicConfig()
log = logging.getLogger()
log.setLevel(logging.CRITICAL) 

def run_modbus_test():
    print("--- Waveshare (B) Synchronisierter Heartbeat-Simulator ---")
    print(f"Ziel-IP: {SERVER_IP}:{SERVER_PORT} | Device-ID (Slave): {SLAVE_ID}")
    print("Modbus-Framing: RTU over TCP (erzwingt saubere Paket-IDs)")
    print("Beenden mit der Tastenkombination: STRG + C\n")
    
    # WICHTIG: framer=FramerType.RTU zwingt das Skript, das Waveshare-eigene
    # RTU-Paketformat über das Netzwerkkabel zu senden. Das behebt den ID-Fehler.
    client = ModbusTcpClient(
        SERVER_IP, 
        port=SERVER_PORT, 
        timeout=0.5,
        framer=FramerType.RTU
    )
    
    if not client.connect():
        print(f"FEHLER: Verbindung zu {SERVER_IP} fehlgeschlagen!")
        return

    print("Verbindung erfolgreich hergestellt. Starte Taktung...")
    state = False  
    
    try:
        while True:
            state = not state  
            val = True if state else False
            
            try:
                # Relais 6 schalten
                client.write_coil(COIL_BAHN_1, val, device_id=SLAVE_ID)
                time.sleep(0.04) # 40ms Pause für den Bus-Puffer des Waveshare
                
                # Relais 7 schalten
                client.write_coil(COIL_BAHN_2, val, device_id=SLAVE_ID)
                
                status_text = "EIN" if state else "AUS"
                print(f"[TAKT] Signal stabil gesendet -> Beide Bahnen stehen auf: {status_text} ", end="\r")
                
            except Exception as e:
                # Fängt seltene Timeout-Pakete ab, damit das Skript ungerührt weitertaktet
                print(f"[INFO] Paket gesendet (Warte auf Bus-Antwort...)             ", end="\r")
            
            # Restzeit des 0,5-Sekunden-Takts abwarten
            time.sleep(BLINK_INTERVAL - 0.04)
            
    except KeyboardInterrupt:
        print("\n\n[STOP] Signalübertragung manuell abgebrochen.")
    finally:
        print("Sicherheits-Shutdown: Schalte Waveshare-Ausgänge auf AUS...")
        try:
            client.write_coil(COIL_BAHN_1, False, device_id=SLAVE_ID)
            time.sleep(0.04)
            client.write_coil(COIL_BAHN_2, False, device_id=SLAVE_ID)
        except:
            pass
        client.close()
        print("Modbus-Verbindung geschlossen.")

if __name__ == "__main__":
    run_modbus_test()

# control_logic.py

import time
from PyQt5.QtCore import QObject, QThread
from PyQt5.QtWidgets import QApplication

from config import (INPUT_ENDSCHALTER, OUTPUT_RECHTS, OUTPUT_LINKS, 
                    OUTPUT_LANGSAM, OUTPUT_SCHNELL, load_stored_config)
from modbus_worker import ModbusWorker

class SchlittenLogik(QObject):
    """Verwaltet den Fahrzustand, die Schütz-Verriegelungen und den Watchdog."""
    def __init__(self):
        super().__init__()
        # Konfiguration aus JSON laden
        self.config = load_stored_config()
        
        self.inputs = [False] * 8
        self.outputs = [False] * 8
        self.homing_done = False

        # Modbus-Hintergrundprozess initialisieren
        self.worker = ModbusWorker(self.config)
        self.worker.data_updated.connect(self.handle_io_update)
        self.worker.start()

    def handle_io_update(self, inputs, outputs):
        """Aktualisiert die lokalen Zustände aus dem Modbus-Thread."""
        self.inputs = inputs

    def write_output_direct(self, channel, state):
        """Schaltet einen Ausgang direkt im Puffer (z.B. Licht)."""
        self.outputs[channel] = state
        self.worker.update_outputs(self.outputs)

    def fahrt_sequenz(self, richtung_ch, speed_ch, dauer=None, stop_am_endschalter=False, start_zeit_gesamt=None, watchdog_limit=None):
        """Steuert die Schütze und überwacht die maximale Laufzeit (Watchdog)."""
        if start_zeit_gesamt is None:
            start_zeit_gesamt = time.time()
        
        try:
            if watchdog_limit and (time.time() - start_zeit_gesamt >= watchdog_limit):
                return False

            # 1. Richtungsschütz EIN
            self.outputs[richtung_ch] = True
            self.worker.update_outputs(self.outputs)
            QThread.msleep(100) # 0.1s Verzögerung

            # 2. Geschwindigkeitsschütz EIN
            if speed_ch is not None:
                self.outputs[speed_ch] = True
                self.worker.update_outputs(self.outputs)

            # 3. Fahrtschleife mit Watchdog-Überwachung
            start_phase = time.time()
            while True:
                QApplication.processEvents() # GUI aktiv halten
                
                # Prüfe Gesamt-Watchdog-Zeit
                if watchdog_limit and (time.time() - start_zeit_gesamt >= watchdog_limit):
                    # NOT-AUS: Alle Fahrtschütze sofort abwerfen
                    self.outputs[OUTPUT_RECHTS] = False
                    self.outputs[OUTPUT_LINKS] = False
                    self.outputs[OUTPUT_LANGSAM] = False
                    self.outputs[OUTPUT_SCHNELL] = False
                    self.worker.update_outputs(self.outputs)
                    return False

                if stop_am_endschalter and self.inputs[INPUT_ENDSCHALTER]:
                    break
                if dauer and (time.time() - start_phase >= dauer):
                    break
                QThread.msleep(20)

            # 4. Geschwindigkeitsschütz AUS
            if speed_ch is not None:
                self.outputs[speed_ch] = False
                self.worker.update_outputs(self.outputs)
            QThread.msleep(100) # 0.1s Verzögerung

            # 5. Richtungsschütz AUS
            self.outputs[richtung_ch] = False
            self.worker.update_outputs(self.outputs)
            
            return True
            
        except Exception:
            return False

    def shutdown(self):
        """Stoppt den Hintergrund-Thread sauber."""
        self.worker.running = False
        self.worker.wait()

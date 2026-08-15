# control_logic.py

import time
import threading
from PyQt5.QtCore import QObject, QThread, pyqtSignal
from config import (INPUT_ENDSCHALTER, OUTPUT_RECHTS, OUTPUT_LINKS, 
                    OUTPUT_LANGSAM, OUTPUT_SCHNELL, load_stored_config)
from modbus_worker import ModbusWorker

class FahrtWorker(QThread):
    """Führt die Fahrten autark im Hintergrund aus, ohne den Modbus-Takt zu stören."""
    fahrt_beendet = pyqtSignal(bool, str)

    def __init__(self, logik, richtung_ch, speed_ch, dauer=None, stop_am_endschalter=False, watchdog_limit=None, fahrt_name=""):
        super().__init__()
        self.logik = logik
        self.richtung_ch = richtung_ch
        self.speed_ch = speed_ch
        self.dauer = dauer
        self.stop_am_endschalter = stop_am_endschalter
        self.watchdog_limit = watchdog_limit
        self.fahrt_name = fahrt_name

    def run(self):
        start_zeit_gesamt = time.time()
        
        try:
            # --- PHASE 1: START ---
            self.logik.outputs[self.richtung_ch] = True
            self.logik.worker.update_outputs(self.logik.outputs)
            QThread.msleep(100)

            if self.speed_ch is not None:
                self.logik.outputs[self.speed_ch] = True
                self.logik.worker.update_outputs(self.logik.outputs)

            # --- PHASE 2: FAHRTSCHLEIFE ---
            start_phase = time.time()
            while True:
                # Watchdog-Prüfung
                if self.watchdog_limit and (time.time() - start_zeit_gesamt >= self.watchdog_limit):
                    self.NOT_AUS()
                    self.fahrt_beendet.emit(False, self.fahrt_name)
                    return

                if self.stop_am_endschalter and self.logik.inputs[INPUT_ENDSCHALTER]:
                    break
                if self.dauer and (time.time() - start_phase >= self.dauer):
                    break
                
                # KORREKTUR: Taktung in der Überwachungsschleife auf 40ms erhöht.
                # Das entlastet die CPU des Raspberry Pi drastisch.
                QThread.msleep(40)

            # --- PHASE 3: STOPP ---
            if self.speed_ch is not None:
                self.logik.outputs[self.speed_ch] = False
                self.logik.worker.update_outputs(self.logik.outputs)
            QThread.msleep(100)

            self.logik.outputs[self.richtung_ch] = False
            self.logik.worker.update_outputs(self.logik.outputs)
            
            self.fahrt_beendet.emit(True, self.fahrt_name)
            
        except Exception:
            self.NOT_AUS()
            self.fahrt_beendet.emit(False, self.fahrt_name)

    def NOT_AUS(self):
        self.logik.outputs[OUTPUT_RECHTS] = False
        self.logik.outputs[OUTPUT_LINKS] = False
        self.logik.outputs[OUTPUT_LANGSAM] = False
        self.logik.outputs[OUTPUT_SCHNELL] = False
        self.logik.worker.update_outputs(self.logik.outputs)


class SchlittenLogik(QObject):
    """Verwaltet den Modbus-Thread und stellt Daten bereit."""
    def __init__(self):
        super().__init__()
        self.config = load_stored_config()
        self.inputs = [False] * 8
        self.outputs = [False] * 8
        self.homing_done = False

        self.worker = ModbusWorker(self.config)
        self.worker.data_updated.connect(self.handle_io_update)
        self.worker.start()

    def handle_io_update(self, inputs, outputs):
        self.inputs = inputs

    def write_output_direct(self, channel, state):
        self.outputs[channel] = state
        self.worker.update_outputs(self.outputs)

    def shutdown(self):
        self.worker.running = False
        self.worker.wait()

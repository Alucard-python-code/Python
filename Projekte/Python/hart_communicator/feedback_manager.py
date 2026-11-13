"""
feedback_manager.py – Fühlbare und hörbare Rückmeldung für laute Umgebungen.

* Haptik: TI DRV2605L (I2C1 @ 0x5A), Effektbibliothek (ERM oder LRA), Sequenzen mit Pausen
* Audio:  MAX98357A (I2S, dtoverlay=max98357a) über ALSA `aplay`. Die Töne werden zur
          Laufzeit synthetisiert (keine Audiodateien im Repo) und als WAV gecacht.
          Frequenzen 2–3,2 kHz: dort ist das Gehör am empfindlichsten und Industrielärm
          (meist tieffrequent) maskiert am wenigsten.
* Ereignisse statt Einzelbefehle: notify("scan_ok"), notify("alarm") …
  -> zentrale, konsistente Zuordnung von Vibration + Ton, abschaltbar in den Einstellungen
* Nicht blockierend: eigener Worker-Thread; Alarme/Fehler unterbrechen laufende Töne
"""
from __future__ import annotations

import array
import itertools
import json
import logging
import math
import queue
import shutil
import subprocess
import threading
import time
import wave
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional

import config
from hw_compat import get_i2c_bus, simulation_requested

log = logging.getLogger(__name__)

# =============================================================================
# DRV2605L
# =============================================================================
REG_STATUS, REG_MODE, REG_RTP, REG_LIBRARY = 0x00, 0x01, 0x02, 0x03
REG_WAVESEQ1, REG_GO, REG_FEEDBACK = 0x04, 0x0C, 0x1A
MODE_INTERNAL_TRIGGER, MODE_STANDBY, MODE_RESET = 0x00, 0x40, 0x80
DEVICE_ID_DRV2605L = 7

# Effekt-IDs der ROM-Bibliothek (Datenblatt Tabelle 11.2)
FX_STRONG_CLICK, FX_DOUBLE_CLICK, FX_TRIPLE_CLICK = 1, 10, 12
FX_STRONG_BUZZ, FX_ALERT_1000MS, FX_SHARP_TICK = 14, 16, 24
FX_BUZZ, FX_PULSING_STRONG = 47, 52


def wait_ms(ms: int) -> int:
    """Pause in einer Wellenform-Sequenz (Bit 7 gesetzt, Einheit 10 ms)."""
    return 0x80 | max(1, min(127, ms // 10))


class DRV2605L:
    def __init__(self, bus, addr: int = config.I2CAddr.DRV2605L, actuator: str = config.HAPTIC_ACTUATOR):
        self.bus, self.addr = bus, addr
        self._lock = threading.Lock()
        dev_id = self.bus.read_byte_data(addr, REG_STATUS) >> 5
        if dev_id != DEVICE_ID_DRV2605L:
            log.warning("DRV2605x Device-ID %d (erwartet 7 = DRV2605L)", dev_id)
        self.bus.write_byte_data(addr, REG_MODE, MODE_RESET)
        time.sleep(0.01)
        self.bus.write_byte_data(addr, REG_MODE, MODE_INTERNAL_TRIGGER)   # Standby verlassen
        self.bus.write_byte_data(addr, REG_RTP, 0)
        fb = self.bus.read_byte_data(addr, REG_FEEDBACK)
        if actuator.upper() == "LRA":
            self.bus.write_byte_data(addr, REG_FEEDBACK, fb | 0x80)
            self.bus.write_byte_data(addr, REG_LIBRARY, 6)
        else:
            self.bus.write_byte_data(addr, REG_FEEDBACK, fb & 0x7F)
            self.bus.write_byte_data(addr, REG_LIBRARY, 1)

    def play(self, sequence: list[int]) -> None:
        seq = sequence[:8]
        with self._lock:
            for i, fx in enumerate(seq):
                self.bus.write_byte_data(self.addr, REG_WAVESEQ1 + i, fx)
            if len(seq) < 8:
                self.bus.write_byte_data(self.addr, REG_WAVESEQ1 + len(seq), 0)   # Ende
            self.bus.write_byte_data(self.addr, REG_GO, 1)

    def stop(self) -> None:
        with self._lock:
            self.bus.write_byte_data(self.addr, REG_GO, 0)


# =============================================================================
# Ton-Synthese
# =============================================================================
SAMPLE_RATE = 44100
# Ton = Liste aus (Frequenz Hz | 0 = Pause, Dauer ms)
SOUNDS: dict[str, list[tuple[int, int]]] = {
    "click":     [(3000, 12)],
    "beep":      [(2700, 90)],
    "success":   [(2000, 90), (0, 30), (2700, 140)],
    "chime":     [(1800, 80), (0, 20), (2300, 80), (0, 20), (2900, 160)],
    "warning":   [(2200, 160), (0, 90), (2200, 160)],
    "error":     [(1400, 220), (0, 40), (950, 380)],
    "alarm":     [(2500, 150), (3150, 150)] * 4,
    "blocked":   [(1100, 110), (0, 60), (1100, 110)],
    "attention": [(2900, 100), (0, 70)] * 3,
    "shutdown":  [(2400, 120), (1800, 120), (1200, 250)],
}


def synthesize(tones: list[tuple[int, int]], volume: float) -> bytes:
    """16-bit Mono-PCM. 5-ms-Rampen an jedem Ton verhindern Knackgeräusche."""
    amp = int(32767 * max(0.0, min(1.0, volume)) * 0.9)
    pcm = array.array("h")
    ramp = int(SAMPLE_RATE * 0.005)
    for freq, ms in tones:
        n = int(SAMPLE_RATE * ms / 1000)
        if freq == 0:
            pcm.extend([0] * n)
            continue
        for i in range(n):
            env = min(1.0, i / ramp, (n - i) / ramp)
            # leichte 3. Harmonische -> durchsetzungsfähiger auf kleinen Lautsprechern
            s = math.sin(2 * math.pi * freq * i / SAMPLE_RATE) + 0.25 * math.sin(6 * math.pi * freq * i / SAMPLE_RATE)
            pcm.append(int(amp * env * s / 1.25))
    pcm.extend([0] * int(SAMPLE_RATE * 0.03))   # Nachlauf gegen abgeschnittene Enden
    return pcm.tobytes()


def write_wav(path: Path, pcm: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with wave.open(str(tmp), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(pcm)
    tmp.replace(path)


# =============================================================================
# Ereignis-Zuordnung
# =============================================================================
@dataclass(frozen=True)
class FeedbackEvent:
    haptic: tuple[int, ...]
    sound: Optional[str]
    priority: int          # höher = wichtiger, unterbricht niedrigere


EVENTS: dict[str, FeedbackEvent] = {
    "touch":             FeedbackEvent((FX_SHARP_TICK,), None, 0),
    "key":               FeedbackEvent((), "click", 0),
    "scan_ok":           FeedbackEvent((FX_DOUBLE_CLICK,), "beep", 1),
    "device_found":      FeedbackEvent((FX_STRONG_CLICK, wait_ms(80), FX_STRONG_CLICK), "chime", 2),
    "success":           FeedbackEvent((FX_STRONG_CLICK,), "success", 2),
    "calibration_ok":    FeedbackEvent((FX_STRONG_CLICK, wait_ms(100), FX_STRONG_CLICK), "success", 2),
    "point_captured":    FeedbackEvent((FX_DOUBLE_CLICK,), "beep", 1),
    "warning":           FeedbackEvent((FX_BUZZ, wait_ms(120), FX_BUZZ), "warning", 3),
    "safe_mode_block":   FeedbackEvent((FX_STRONG_BUZZ,), "blocked", 3),
    "device_swap":       FeedbackEvent((FX_PULSING_STRONG, wait_ms(150), FX_PULSING_STRONG), "attention", 4),
    "analog_mismatch":   FeedbackEvent((FX_BUZZ, wait_ms(120), FX_BUZZ), "warning", 3),
    "error":             FeedbackEvent((FX_STRONG_BUZZ, wait_ms(100), FX_STRONG_BUZZ), "error", 4),
    "calibration_fail":  FeedbackEvent((FX_STRONG_BUZZ, wait_ms(100), FX_STRONG_BUZZ), "error", 4),
    "alarm":             FeedbackEvent((FX_ALERT_1000MS,), "alarm", 5),
    "battery_critical":  FeedbackEvent((FX_ALERT_1000MS,), "alarm", 5),
    "shutdown":          FeedbackEvent((FX_TRIPLE_CLICK,), "shutdown", 5),
}


@dataclass
class FeedbackSettings:
    haptic_enabled: bool = True
    sound_enabled: bool = True
    touch_haptic: bool = True        # Vibration bei jedem Tipp
    key_sound: bool = False
    volume: int = 80                 # 0..100

    @classmethod
    def load(cls, path: Optional[Path]) -> "FeedbackSettings":
        if path and path.exists():
            try:
                return cls(**{k: v for k, v in json.loads(path.read_text()).items()
                              if k in cls.__dataclass_fields__})
            except (OSError, ValueError, TypeError) as exc:
                log.warning("Feedback-Einstellungen ungültig: %s", exc)
        return cls()

    def save(self, path: Optional[Path]) -> None:
        if path:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(asdict(self), indent=2))


# =============================================================================
# FeedbackManager
# =============================================================================
class FeedbackManager:
    def __init__(self, *, simulate: Optional[bool] = None, sound_dir: Path = config.SOUND_DIR,
                 settings_file: Optional[Path] = config.FEEDBACK_SETTINGS_FILE,
                 audio_device: str = config.AUDIO_DEVICE):
        self.sound_dir = Path(sound_dir)
        self.settings_file = settings_file
        self.settings = FeedbackSettings.load(settings_file)
        self.audio_device = audio_device
        self.history: list[tuple[float, str]] = []      # für Tests / Diagnose
        self._queue: "queue.PriorityQueue[tuple[int, int, str]]" = queue.PriorityQueue(maxsize=32)
        self._seq = itertools.count()          # thread-sicher, FIFO bei gleicher Priorität
        self._current_proc: Optional[subprocess.Popen] = None
        self._current_prio = -1
        self._proc_lock = threading.Lock()
        self._stop = threading.Event()

        if simulate is None:
            simulate = simulation_requested("feedback")
        self.simulated = simulate
        self.haptic: Optional[DRV2605L] = None
        if not simulate:
            bus = get_i2c_bus(config.I2C_BUS, component="feedback")
            if bus and bus.probe(config.I2CAddr.DRV2605L):
                try:
                    self.haptic = DRV2605L(bus)
                except OSError as exc:
                    log.error("DRV2605L-Initialisierung fehlgeschlagen: %s", exc)
            else:
                log.error("DRV2605L an 0x%02X nicht gefunden – Haptik deaktiviert", config.I2CAddr.DRV2605L)
        self.audio_available = not simulate and shutil.which("aplay") is not None
        self._worker = threading.Thread(target=self._run, name="feedback", daemon=True)
        self._worker.start()

    # ---------- Einstellungen ----------
    def update_settings(self, **changes) -> FeedbackSettings:
        for k, v in changes.items():
            if k in FeedbackSettings.__dataclass_fields__:
                setattr(self.settings, k, type(getattr(self.settings, k))(v))
        self.settings.volume = max(0, min(100, self.settings.volume))
        self.settings.save(self.settings_file)
        return self.settings

    # ---------- Ereignisse ----------
    def notify(self, event: str) -> None:
        """Nicht blockierend. Unbekannte Ereignisse werden geloggt und ignoriert."""
        ev = EVENTS.get(event)
        if ev is None:
            log.warning("Unbekanntes Feedback-Ereignis: %s", event)
            return
        with self._proc_lock:
            if ev.priority > self._current_prio and self._current_proc is not None:
                self._current_proc.terminate()       # Alarm unterbricht Bestätigungston
        try:
            self._queue.put_nowait((-ev.priority, next(self._seq), event))
        except queue.Full:
            log.debug("Feedback-Queue voll – %s verworfen", event)

    def test(self) -> None:
        """Einstellungen: 'Test'-Knopf."""
        self.notify("success")

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                _, _, name = self._queue.get(timeout=0.5)
            except queue.Empty:
                continue
            ev = EVENTS[name]
            self.history.append((time.time(), name))
            del self.history[:-100]
            s = self.settings
            if s.haptic_enabled and ev.haptic and (name != "touch" or s.touch_haptic):
                self._vibrate(ev.haptic)
            if s.sound_enabled and ev.sound and (name != "key" or s.key_sound):
                self._play(ev.sound, ev.priority)

    def _vibrate(self, seq: tuple[int, ...]) -> None:
        if self.haptic:
            try:
                self.haptic.play(list(seq))
            except OSError as exc:
                log.warning("Haptik-Fehler: %s", exc)
        elif self.simulated:
            log.debug("[SIM] Vibration %s", seq)

    def sound_file(self, sound: str) -> Path:
        vol = self.settings.volume
        path = self.sound_dir / f"{sound}_v{vol}.wav"
        if not path.exists():
            write_wav(path, synthesize(SOUNDS[sound], vol / 100.0))
        return path

    def _play(self, sound: str, priority: int) -> None:
        path = self.sound_file(sound)
        if not self.audio_available:
            log.debug("[SIM] Ton %s", path.name)
            return
        try:
            proc = subprocess.Popen(["aplay", "-q", "-D", self.audio_device, str(path)],
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError as exc:
            log.warning("aplay fehlgeschlagen: %s", exc)
            return
        with self._proc_lock:
            self._current_proc, self._current_prio = proc, priority
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
        with self._proc_lock:
            self._current_proc, self._current_prio = None, -1

    def close(self) -> None:
        self._stop.set()
        with self._proc_lock:
            if self._current_proc:
                self._current_proc.terminate()
        if self.haptic:
            try:
                self.haptic.stop()
            except OSError:
                pass


if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG, format="%(levelname)s %(name)s: %(message)s")
    fb = FeedbackManager(simulate=True, settings_file=None)
    for e in ("scan_ok", "device_found", "alarm"):
        fb.notify(e)
    time.sleep(0.8)
    print("Abgespielt:", [n for _, n in fb.history])
    print("WAV-Cache:", sorted(p.name for p in fb.sound_dir.glob("*.wav")))

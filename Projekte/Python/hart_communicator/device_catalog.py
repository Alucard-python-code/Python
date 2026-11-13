"""
device_catalog.py – Klartext-Erkennung von HART-Feldgeräten.

Ordnet die Identifikation aus HART Command 0 (Hersteller-ID + erweiterter
Gerätetyp) einem Geräteprofil zu und liefert:
  * Klartextnamen ("Emerson / Rosemount 3051 – Druckmessumformer")
  * Geräteklasse (Transmitter vs. Stellungsregler -> Kalibrierablauf, Command 40)
  * Standard-Einheit und Bezeichnung der Primärvariable

Mehrstufige Zuordnung:
  1. exakt     – (Hersteller-ID, Gerätetyp) steht im Katalog bzw. Benutzerkatalog
  2. Hersteller – nur Hersteller bekannt -> Hersteller-Standardprofil
  3. unbekannt – generischer Transmitter

WICHTIG – Gerätetyp-Codes:
  Die Hersteller-IDs entsprechen der HART-Herstellertabelle (FieldComm Group,
  Common Table 8). Die Gerätetyp-Codes der Modelle hängen von Modell UND
  Gerätegeneration (HART 5/6/7, Device Revision) ab und sind hier als
  `verified=False` markiert. Vor dem Produktiveinsatz bitte mit der FCG-DD-
  Library bzw. den Herstellerdokumenten abgleichen. Unbekannte Typen können
  der Techniker direkt im Feld per `learn()` zuordnen – das wird in
  data/device_catalog_user.json gespeichert und hat Vorrang.
"""
from __future__ import annotations

import json
import logging
import threading
from dataclasses import asdict, dataclass, field, replace
from enum import Enum
from pathlib import Path
from typing import Optional

import config

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# HART-Herstellertabelle (Auszug, Common Table 8)
# ---------------------------------------------------------------------------
MANUFACTURERS: dict[int, str] = {
    0x0A: "Brooks Instrument",
    0x11: "Endress+Hauser",
    0x13: "Fisher Controls",
    0x14: "Foxboro",
    0x15: "Fuji Electric",
    0x16: "ABB Automation",
    0x17: "Honeywell",
    0x1A: "ABB",
    0x1F: "Micro Motion",
    0x20: "Moore Industries",
    0x26: "Rosemount",
    0x2A: "Siemens",
    0x2E: "Rosemount Analytical",
    0x2F: "Metso / Neles",
    0x30: "Flowserve",
    0x37: "Yokogawa",
    0x3E: "Smar",
    0x42: "Samson",
    0x45: "Krohne",
    0x47: "Druck",
}

# Konzern-/Markenzugehörigkeit für die Klartextanzeige
BRANDS: dict[int, str] = {
    0x13: "Emerson",
    0x1F: "Emerson",
    0x26: "Emerson",
    0x2E: "Emerson",
    0x2A: "Siemens",
    0x11: "Endress+Hauser",
    0x16: "ABB",
    0x1A: "ABB",
}


class DeviceClass(str, Enum):
    PRESSURE = "Druckmessumformer"
    DP_FLOW = "Differenzdruck / Durchfluss"
    TEMPERATURE = "Temperaturmessumformer"
    FLOW_CORIOLIS = "Coriolis-Durchflussmesser"
    FLOW_MAG = "Magnetisch-induktiver Durchflussmesser"
    LEVEL = "Füllstandsmessung"
    POSITIONER = "Stellungsregler"
    ANALYTICAL = "Analysenmesstechnik"
    GENERIC = "Generisches HART-Gerät"


# HART-Einheitencodes (Common Table 2) – nur die hier benötigten
_U_BAR, _U_MBAR, _U_KPA, _U_DEGC, _U_PCT, _U_KGH, _U_M3H, _U_M = 7, 8, 12, 32, 57, 75, 19, 45


@dataclass(frozen=True)
class DeviceProfile:
    key: str
    manufacturer_id: int
    model: str
    device_class: DeviceClass
    device_types: tuple[int, ...] = ()     # erweiterte 16-Bit-Gerätetypen
    default_unit: int = 251                # 251 = "none"
    pv_label: str = "PV"
    is_positioner: bool = False
    supports_cmd40_setpoint: bool = False  # digitale Sollwertvorgabe per Cmd 40
    verified: bool = False
    notes: str = ""

    @property
    def manufacturer(self) -> str:
        return manufacturer_name(self.manufacturer_id)

    @property
    def brand(self) -> str:
        return BRANDS.get(self.manufacturer_id, self.manufacturer)

    @property
    def display_name(self) -> str:
        brand, mfr = self.brand, self.manufacturer
        prefix = mfr if brand == mfr else f"{brand} / {mfr}"
        return f"{prefix} {self.model}".strip()

    def to_dict(self) -> dict:
        d = asdict(self)
        d.update(device_class=self.device_class.value, manufacturer=self.manufacturer,
                 brand=self.brand, display_name=self.display_name,
                 device_types=[f"0x{t:04X}" for t in self.device_types])
        return d


def _dt(mfr: int, legacy_type: int) -> int:
    """HART 5/6: erweiterter Gerätetyp = Hersteller-ID << 8 | Gerätetyp."""
    return (mfr << 8) | legacy_type


# ---------------------------------------------------------------------------
# Werkskatalog. Typcodes: siehe Hinweis im Modulkopf (verified=False).
# ---------------------------------------------------------------------------
_BUILTIN: list[DeviceProfile] = [
    # --- Emerson / Rosemount ------------------------------------------------
    DeviceProfile("rosemount_3051", 0x26, "3051", DeviceClass.PRESSURE,
                  (_dt(0x26, 0x06),), _U_MBAR, "Druck"),
    DeviceProfile("rosemount_3051s", 0x26, "3051S", DeviceClass.PRESSURE,
                  (_dt(0x26, 0x51),), _U_BAR, "Druck"),
    DeviceProfile("rosemount_2088", 0x26, "2088", DeviceClass.PRESSURE,
                  (_dt(0x26, 0x0E),), _U_BAR, "Druck"),
    DeviceProfile("rosemount_644", 0x26, "644", DeviceClass.TEMPERATURE,
                  (_dt(0x26, 0x0A),), _U_DEGC, "Temperatur"),
    DeviceProfile("rosemount_3144p", 0x26, "3144P", DeviceClass.TEMPERATURE,
                  (_dt(0x26, 0x18),), _U_DEGC, "Temperatur"),
    DeviceProfile("rosemount_5300", 0x26, "5300 Radar", DeviceClass.LEVEL,
                  (_dt(0x26, 0x45),), _U_M, "Füllstand"),
    DeviceProfile("rosemount_8700", 0x26, "8700 Magmeter", DeviceClass.FLOW_MAG,
                  (_dt(0x26, 0x1C),), _U_M3H, "Durchfluss"),
    # --- Emerson / Micro Motion --------------------------------------------
    DeviceProfile("micromotion_2700", 0x1F, "Transmitter 1700/2700", DeviceClass.FLOW_CORIOLIS,
                  (_dt(0x1F, 0x29),), _U_KGH, "Massedurchfluss"),
    DeviceProfile("micromotion_5700", 0x1F, "Transmitter 5700", DeviceClass.FLOW_CORIOLIS,
                  (_dt(0x1F, 0x57),), _U_KGH, "Massedurchfluss"),
    # --- Emerson / Fisher ---------------------------------------------------
    DeviceProfile("fisher_dvc6000", 0x13, "FIELDVUE DVC6000", DeviceClass.POSITIONER,
                  (_dt(0x13, 0x02),), _U_PCT, "Ventilstellung", True, True,
                  notes="Digitaler Sollwert ggf. gerätespezifisch (DD) – Cmd 40 als Basis."),
    DeviceProfile("fisher_dvc6200", 0x13, "FIELDVUE DVC6200", DeviceClass.POSITIONER,
                  (_dt(0x13, 0x09),), _U_PCT, "Ventilstellung", True, True,
                  notes="Digitaler Sollwert ggf. gerätespezifisch (DD) – Cmd 40 als Basis."),
    # --- Siemens ------------------------------------------------------------
    DeviceProfile("siemens_sipart_ps2", 0x2A, "SIPART PS2", DeviceClass.POSITIONER,
                  (_dt(0x2A, 0xE4),), _U_PCT, "Ventilstellung", True, True),
    DeviceProfile("siemens_sipart_ps100", 0x2A, "SIPART PS100", DeviceClass.POSITIONER,
                  (_dt(0x2A, 0xE9),), _U_PCT, "Ventilstellung", True, True),
    DeviceProfile("siemens_sitrans_p_ds3", 0x2A, "SITRANS P DS III", DeviceClass.PRESSURE,
                  (_dt(0x2A, 0x0B),), _U_BAR, "Druck"),
    DeviceProfile("siemens_sitrans_th300", 0x2A, "SITRANS TH300", DeviceClass.TEMPERATURE,
                  (_dt(0x2A, 0x3A),), _U_DEGC, "Temperatur"),
]

# Hersteller-Standardprofile, falls nur die Hersteller-ID bekannt ist
_MANUFACTURER_DEFAULTS: dict[int, DeviceProfile] = {
    0x26: DeviceProfile("rosemount_generic", 0x26, "(Modell unbekannt)", DeviceClass.PRESSURE,
                        default_unit=_U_MBAR, pv_label="PV"),
    0x1F: DeviceProfile("micromotion_generic", 0x1F, "(Modell unbekannt)", DeviceClass.FLOW_CORIOLIS,
                        default_unit=_U_KGH, pv_label="Massedurchfluss"),
    0x13: DeviceProfile("fisher_generic", 0x13, "(Modell unbekannt)", DeviceClass.POSITIONER,
                        default_unit=_U_PCT, pv_label="Ventilstellung", is_positioner=True,
                        supports_cmd40_setpoint=True),
    0x2A: DeviceProfile("siemens_generic", 0x2A, "(Modell unbekannt)", DeviceClass.GENERIC),
    0x42: DeviceProfile("samson_generic", 0x42, "(Modell unbekannt)", DeviceClass.POSITIONER,
                        default_unit=_U_PCT, pv_label="Ventilstellung", is_positioner=True,
                        supports_cmd40_setpoint=True),
}

# Hersteller, deren HART-Geräte überwiegend Stellungsregler sind
_POSITIONER_MAKERS = {0x13, 0x2F, 0x30, 0x42}


def manufacturer_name(mfr_id: int) -> str:
    return MANUFACTURERS.get(mfr_id, f"Hersteller 0x{mfr_id:04X}")


@dataclass
class CatalogMatch:
    profile: DeviceProfile
    confidence: str            # "exact" | "user" | "manufacturer" | "heuristic" | "unknown"
    manufacturer_id: int
    device_type: int
    hints: list[str] = field(default_factory=list)

    @property
    def display_name(self) -> str:
        return self.profile.display_name

    @property
    def needs_confirmation(self) -> bool:
        return self.confidence not in ("exact", "user")

    def to_dict(self) -> dict:
        return {
            "display_name": self.display_name,
            "confidence": self.confidence,
            "needs_confirmation": self.needs_confirmation,
            "manufacturer_id": f"0x{self.manufacturer_id:04X}",
            "device_type": f"0x{self.device_type:04X}",
            "hints": self.hints,
            "profile": self.profile.to_dict(),
        }


class DeviceCatalog:
    """Katalog mit Werks- und Benutzereinträgen (thread-sicher)."""

    def __init__(self, user_file: Optional[Path] = None):
        self.user_file = Path(user_file or config.USER_DEVICE_CATALOG)
        self._lock = threading.Lock()
        self._profiles: dict[str, DeviceProfile] = {p.key: p for p in _BUILTIN}
        self._index: dict[tuple[int, int], DeviceProfile] = {}
        self._user_index: dict[tuple[int, int], DeviceProfile] = {}
        for p in _BUILTIN:
            for t in p.device_types:
                self._index[(p.manufacturer_id, t)] = p
        self._load_user()

    # ---------------- Persistenz ----------------
    def _load_user(self) -> None:
        if not self.user_file.exists():
            return
        try:
            entries = json.loads(self.user_file.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            log.error("Benutzerkatalog %s unlesbar: %s", self.user_file, exc)
            return
        for e in entries:
            try:
                prof = DeviceProfile(
                    key=e["key"], manufacturer_id=int(e["manufacturer_id"], 0),
                    model=e["model"], device_class=DeviceClass(e["device_class"]),
                    device_types=tuple(int(t, 0) for t in e["device_types"]),
                    default_unit=int(e.get("default_unit", 251)), pv_label=e.get("pv_label", "PV"),
                    is_positioner=bool(e.get("is_positioner", False)),
                    supports_cmd40_setpoint=bool(e.get("supports_cmd40_setpoint", False)),
                    verified=True, notes=e.get("notes", "Vom Techniker zugeordnet"))
            except (KeyError, ValueError) as exc:
                log.warning("Ungültiger Benutzerkatalog-Eintrag %s: %s", e, exc)
                continue
            self._profiles[prof.key] = prof
            for t in prof.device_types:
                self._user_index[(prof.manufacturer_id, t)] = prof

    def _save_user(self) -> None:
        seen, out = set(), []
        for prof in self._user_index.values():
            if prof.key in seen:
                continue
            seen.add(prof.key)
            out.append({
                "key": prof.key, "manufacturer_id": f"0x{prof.manufacturer_id:04X}",
                "model": prof.model, "device_class": prof.device_class.value,
                "device_types": [f"0x{t:04X}" for t in prof.device_types],
                "default_unit": prof.default_unit, "pv_label": prof.pv_label,
                "is_positioner": prof.is_positioner,
                "supports_cmd40_setpoint": prof.supports_cmd40_setpoint, "notes": prof.notes,
            })
        self.user_file.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.user_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.user_file)   # atomar – eMMC-schonend und stromausfallsicher

    # ---------------- Abfrage ----------------
    def profile(self, key: str) -> DeviceProfile:
        return self._profiles[key]

    def profiles(self) -> list[DeviceProfile]:
        return list(self._profiles.values())

    def lookup(self, manufacturer_id: int, device_type: int, pv_unit: Optional[int] = None) -> CatalogMatch:
        mfr8 = manufacturer_id  # HART 7: 16 Bit, Altgeräte < 0x100
        with self._lock:
            prof = self._user_index.get((mfr8, device_type))
            if prof:
                return CatalogMatch(prof, "user", mfr8, device_type)
            prof = self._index.get((mfr8, device_type))
        if prof:
            hints = [] if prof.verified else ["Typcode nicht gegen DD-Library verifiziert"]
            return CatalogMatch(prof, "exact", mfr8, device_type, hints)

        hints: list[str] = []
        base = _MANUFACTURER_DEFAULTS.get(mfr8)
        if base:
            confidence = "manufacturer"
            hints.append(f"Gerätetyp 0x{device_type:04X} nicht im Katalog – Herstellerprofil verwendet")
        else:
            confidence = "unknown"
            base = DeviceProfile("generic", mfr8, f"Typ 0x{device_type:04X}", DeviceClass.GENERIC)
            hints.append("Hersteller/Gerätetyp unbekannt – bitte Geräteklasse bestätigen")

        # Heuristik: PV in % bei typischem Ventilhersteller => Stellungsregler
        if pv_unit == _U_PCT and (mfr8 in _POSITIONER_MAKERS or base.device_class == DeviceClass.GENERIC):
            base = replace(base, device_class=DeviceClass.POSITIONER, is_positioner=True,
                           supports_cmd40_setpoint=True, pv_label="Ventilstellung")
            confidence = "heuristic"
            hints.append("PV-Einheit % -> vermutlich Stellungsregler")
        if base.model.startswith("(") or base.key == "generic":
            base = replace(base, model=f"{base.model} Typ 0x{device_type:04X}")
        return CatalogMatch(base, confidence, mfr8, device_type, hints)

    # ---------------- Lernen im Feld ----------------
    def learn(self, manufacturer_id: int, device_type: int, *, model: str,
              device_class: DeviceClass | str, is_positioner: Optional[bool] = None,
              default_unit: int = 251, pv_label: str = "PV", notes: str = "") -> DeviceProfile:
        """Ordnet einen unbekannten Gerätetyp dauerhaft einem Profil zu."""
        dc = device_class if isinstance(device_class, DeviceClass) else DeviceClass(device_class)
        pos = dc == DeviceClass.POSITIONER if is_positioner is None else is_positioner
        mfr8 = manufacturer_id  # HART 7: 16 Bit, Altgeräte < 0x100
        key = f"user_{mfr8:04x}_{device_type:04x}"
        prof = DeviceProfile(key, mfr8, model, dc, (device_type,), default_unit, pv_label,
                             pos, pos, True, notes or "Vom Techniker zugeordnet")
        with self._lock:
            self._profiles[key] = prof
            self._user_index[(mfr8, device_type)] = prof
            self._save_user()
        log.info("Gerätetyp gelernt: %s -> %s", key, prof.display_name)
        return prof


_default_catalog: Optional[DeviceCatalog] = None
_default_lock = threading.Lock()


def get_catalog() -> DeviceCatalog:
    global _default_catalog
    with _default_lock:
        if _default_catalog is None:
            _default_catalog = DeviceCatalog()
        return _default_catalog


def describe(manufacturer_id: int, device_type: int, pv_unit: Optional[int] = None) -> CatalogMatch:
    """Kurzform: get_catalog().lookup(...)"""
    return get_catalog().lookup(manufacturer_id, device_type, pv_unit)


if __name__ == "__main__":
    cat = DeviceCatalog()
    for p in cat.profiles():
        print(f"{p.key:24s} {p.display_name:45s} {p.device_class.value}")
    print(cat.lookup(0x13, 0x13FF, pv_unit=57).to_dict())

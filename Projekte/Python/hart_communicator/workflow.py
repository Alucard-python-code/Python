"""
workflow.py – Arbeitsablauf an der Messstelle (Identifikation → Fall A/B/C → 5-Punkt-Kalibrierung).

Zustände:
  idle         – kein Gerät ausgewählt (ggf. QR-Vorauswahl gemerkt)
  identified   – Gerät per HART erkannt und mit der Datenbank abgeglichen (Fall A/B/C)
  calibrating  – 5-Punkt-Messung läuft
  done         – Kalibrierung abgeschlossen (Etikett drucken, nächstes Gerät)

Sicherheit:
  * Alles läuft nur innerhalb des OFFENEN Auftrags und strikt beim Kunden dieses Auftrags.
  * Schreibzugriffe aufs Feldgerät (Neuaufnahme: Cmd 18/35/44, Stellungsregler: Cmd 40) prüft
    zusätzlich der Safe-Mode im HART-Modem (Whitelist) – hier nur verständliche Meldungen.
  * Nach Command 40 wird der Festwertmodus IMMER verlassen (finish, abort, Fehler, Shutdown).
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Optional

from calibration import CAL_POINTS, evaluate_point, nominal_setpoint
from camera_qr import parse_qr_payload
from database import CASE_NEW, CASE_RECAL, CASE_SWAP, DatabaseError
from hart_modem import HartError, SafeModeError, unit_name
from telemetry_logger import EV_CALIBRATION, EV_DEVICE_SWAP, EV_NEW_DEVICE

log = logging.getLogger(__name__)


class WorkflowError(RuntimeError):
    """Bedienfehler / fachlicher Fehler – Text wird in der UI angezeigt."""


class Workflow:
    def __init__(self, services):
        self.s = services
        self._lock = threading.RLock()
        self.busy = False                 # True während einer Bus-intensiven Aktion (Messung)
        self.reset()

    # ------------------------------------------------------------------ Zustand
    def reset(self) -> dict:
        with self._lock:
            self.stage = "idle"
            self.info: Optional[dict] = None          # Ergebnis HartModem.identify()
            self.match: Optional[dict] = None         # DeviceMatch.to_dict()
            self.device_id: Optional[int] = None
            self.calibration_id: Optional[int] = None
            self.points: dict[float, dict] = {}
            self.fixed_current_active = False
            self.swap_confirmations = 0
            self.qr: Optional[dict] = None
            self.last_result: Optional[dict] = None
            self.messages: list[dict] = []
        return self.public()

    def _msg(self, level: str, text: str) -> None:
        self.messages.append({"level": level, "text": text, "t": time.time()})
        del self.messages[:-8]

    def public(self) -> dict:
        """JSON-fähiger Zustand für die UI."""
        dev = self.s.db.device(self.device_id) if self.device_id else None
        info = None
        if self.info:
            info = {k: v for k, v in self.info.items() if k != "identity"}
        cal = self.s.db.calibration(self.calibration_id) if self.calibration_id else None
        return {"stage": self.stage, "info": info, "match": self.match, "device": dev, "calibration": cal,
                "points": {str(int(k)): v for k, v in sorted(self.points.items())},
                "cal_points": list(CAL_POINTS), "fixed_current_active": self.fixed_current_active,
                "swap_confirmations": self.swap_confirmations, "qr": self.qr, "busy": self.busy,
                "last_result": self.last_result, "messages": self.messages,
                "is_positioner": bool(dev and dev["is_positioner"]) or bool(self.info and self.info.get("is_positioner"))}

    def _order(self) -> dict:
        o = self.s.db.get_open_order()
        if not o:
            raise WorkflowError("Kein offener Auftrag – bitte zuerst einen Auftrag öffnen")
        return o

    # ------------------------------------------------------------------ Identifikation
    def identify_qr(self, text: str) -> dict:
        """QR-Typenschild/Prüfplakette: Vorauswahl. Gemessen wird erst nach dem HART-Scan."""
        order = self._order()
        q = parse_qr_payload(text)
        if q is None:
            raise WorkflowError("Kein Prüfplaketten-Code (erwartet CUST:…|TAG:…|UID:…)")
        cust = self.s.db.customer(order["customer_id"])
        if q.customer_id not in (str(cust["id"]), str(cust.get("customer_no") or ""), "SIM"):
            raise WorkflowError(f"Plakette gehört zu Kunde '{q.customer_id}', offener Auftrag ist für "
                                f"'{cust['name']}' – Kunden strikt getrennt")
        dev = None
        if q.uid:
            dev = self.s.db.q1("SELECT * FROM devices WHERE customer_id=? AND hart_unique_id=? AND active=1",
                               (cust["id"], q.uid))
        if dev is None:
            dev = self.s.db.q1("SELECT * FROM devices WHERE customer_id=? AND tag=? AND active=1",
                               (cust["id"], q.tag))
        with self._lock:
            self.qr = {**q.to_dict(), "known_device": dev}
            self._msg("info", f"QR erkannt: {q.tag}" + (" (in Datenbank)" if dev else " (neu)") +
                      " – Gerät anklemmen und HART-Scan starten")
        self.s.feedback.notify("scan_ok")
        return self.public()

    def identify_hart(self, poll_address: int = 0) -> dict:
        order = self._order()
        if self.stage == "calibrating":
            raise WorkflowError("Kalibrierung läuft – erst abschließen oder abbrechen")
        try:
            info = self.s.modem.identify(poll_address)
        except HartError as exc:
            raise WorkflowError(f"HART-Kommunikation fehlgeschlagen: {exc}") from exc
        if info is None:
            self.s.feedback.notify("error")
            raise WorkflowError(f"Kein HART-Gerät an Polling-Adresse {poll_address} – Anschluss, Bürde (250 Ω) "
                                "und Schleifenspeisung prüfen")
        ident = info["identity"]
        match = self.s.db.match_device(order["customer_id"], ident.unique_id, info["tag"])
        with self._lock:
            self.reset_keep_qr()
            self.info, self.match = info, match.to_dict()
            self.stage = "identified"
            self.device_id = match.device["id"] if match.case == CASE_RECAL else None
            if self.qr and self.qr.get("uid") and self.qr["uid"] != ident.unique_id:
                self._msg("warn", f"Achtung: QR-Plakette nennt UID {self.qr['uid']}, angeschlossen ist "
                                  f"{ident.unique_id}")
            for h in match.hints:
                self._msg("warn" if match.case == CASE_SWAP else "info", h)
            if info["catalog"]["needs_confirmation"]:
                self._msg("info", f"Geräteerkennung: {info['display_name']} – bitte prüfen")
        self.s.feedback.notify("device_swap" if match.case == CASE_SWAP else "device_found")
        return self.public()

    def reset_keep_qr(self) -> None:
        qr = self.qr
        self.reset()
        self.qr = qr

    def _device_info_from_hart(self) -> dict:
        i = self.info
        rng = i.get("range") or {}
        prof = i["catalog"]["profile"]
        ident = i["identity"]
        return {"manufacturer_id": ident.manufacturer_id, "device_type": ident.device_type,
                "display_name": i["display_name"], "device_class": prof["device_class"],
                "is_positioner": i["is_positioner"], "descriptor": i.get("descriptor", ""),
                "lrv": rng.get("lower_range"), "urv": rng.get("upper_range"), "unit_code": rng.get("unit_code"),
                "unit": rng.get("unit"), "universal_rev": ident.universal_rev, "software_rev": ident.software_rev}

    # ------------------------------------------------------------------ Fall B: Gerätetausch
    def confirm_swap(self, step: int) -> dict:
        """Zwei getrennte Bestätigungen. Erst die zweite schreibt in die Datenbank."""
        if self.stage != "identified" or not self.match or self.match["case"] != CASE_SWAP:
            raise WorkflowError("Kein Gerätetausch zu bestätigen")
        order = self._order()
        with self._lock:
            if step == 1:
                self.swap_confirmations = 1
                self._msg("warn", "Gerätetausch 1/2 bestätigt – bitte ein zweites Mal bestätigen")
                return self.public()
            if step != 2 or self.swap_confirmations != 1:
                raise WorkflowError("Bitte zuerst die erste Bestätigung geben")
            try:
                new_id = self.s.db.confirm_device_swap(self.match["swap_token"], True, self._device_info_from_hart(),
                                                       order["id"], order["technician"])
            except DatabaseError as exc:
                raise WorkflowError(str(exc)) from exc
            old = self.match["device"]
            self.device_id = new_id
            self.swap_confirmations = 2
            self._msg("ok", f"Gerätetausch gespeichert: {old['tag']} {old['hart_unique_id']} → "
                            f"{self.info['unique_id']}. Historie bleibt erhalten.")
        self.s.telemetry.event(EV_DEVICE_SWAP, f"Gerätetausch {old['tag']}", order_no=order["order_no"],
                               device_tag=old["tag"], old_uid=old["hart_unique_id"], new_uid=self.info["unique_id"])
        self.s.feedback.notify("success")
        return self.public()

    # ------------------------------------------------------------------ Fall C: Neuaufnahme
    def register_new(self, *, tag: str, descriptor: str = "", lrv: Optional[float] = None,
                     urv: Optional[float] = None, unit_code: Optional[int] = None, tolerance_pct: float = 0.25,
                     location: str = "", write_to_device: bool = False) -> dict:
        if self.stage != "identified" or not self.match or self.match["case"] != CASE_NEW:
            raise WorkflowError("Neuaufnahme nur für ein neu erkanntes Gerät möglich")
        order = self._order()
        info = self._device_info_from_hart()
        tag = (tag or self.info["tag"]).strip().upper()
        if lrv is not None:
            info["lrv"] = float(lrv)
        if urv is not None:
            info["urv"] = float(urv)
        if unit_code is not None:
            info["unit_code"], info["unit"] = int(unit_code), unit_name(int(unit_code))
        if info["lrv"] is None or info["urv"] is None or info["lrv"] == info["urv"]:
            raise WorkflowError("Bitte einen gültigen Messbereich (0 % / 100 %) angeben")
        if not 0.01 <= float(tolerance_pct) <= 10:
            raise WorkflowError("Toleranz muss zwischen 0,01 % und 10 % liegen")
        info.update(descriptor=descriptor or info["descriptor"], tolerance_pct=float(tolerance_pct),
                    location=location)

        written = []
        if write_to_device:
            ident = self.info["identity"]
            if self.s.modem.safe_mode:
                raise WorkflowError("24/7-Safe-Mode aktiv: TAG/Messbereich können nicht ins Gerät geschrieben "
                                    "werden. Safe-Mode bewusst deaktivieren oder nur in der Datenbank anlegen.")
            try:
                if tag != self.info["tag"] or info["descriptor"] != self.info.get("descriptor"):
                    self.s.modem.write_tag_info(ident, tag, info["descriptor"])
                    written.append("TAG/Beschreibung (Cmd 18)")
                rng = self.info.get("range") or {}
                if info["unit_code"] != rng.get("unit_code"):
                    self.s.modem.write_pv_unit(ident, info["unit_code"])
                    written.append("Einheit (Cmd 44)")
                if (info["lrv"], info["urv"]) != (rng.get("lower_range"), rng.get("upper_range")):
                    self.s.modem.write_range(ident, info["unit_code"], info["lrv"], info["urv"])
                    written.append("Messbereich (Cmd 35)")
            except SafeModeError as exc:
                raise WorkflowError(str(exc)) from exc
            except HartError as exc:
                raise WorkflowError(f"Schreiben ins Gerät fehlgeschlagen: {exc}") from exc
        try:
            self.device_id = self.s.db.create_device(order["customer_id"], tag, self.info["unique_id"], info,
                                                     order["id"], order["technician"])
        except DatabaseError as exc:
            raise WorkflowError(str(exc)) from exc
        self._msg("ok", f"Neuaufnahme {tag} gespeichert" + (f" – ins Gerät geschrieben: {', '.join(written)}"
                                                            if written else ""))
        self.s.telemetry.event(EV_NEW_DEVICE, f"Neuaufnahme {tag}", order_no=order["order_no"], device_tag=tag,
                               written=written)
        self.s.feedback.notify("success")
        return self.public()

    # ------------------------------------------------------------------ Kalibrierung
    def start_calibration(self) -> dict:
        order = self._order()
        if self.stage != "identified" or not self.device_id:
            raise WorkflowError("Gerät zuerst identifizieren und ggf. Tausch/Neuaufnahme abschließen")
        meter = self.s.meter.status()
        if not meter["range_ok"]:
            self._msg("warn", f"True-mA-Messbereich nur bis {meter['max_measurable_ma']} mA (Shunt "
                              f"{meter['shunt_ohm']} Ω) – Messpunkte darüber nicht messbar")
        if meter["calibration"]["is_due"]:
            self._msg("warn", "Prüfmittel (True-mA) ohne gültige Kalibrierung – im Bericht vermerkt")
        try:
            self.calibration_id = self.s.db.start_calibration(
                order["id"], self.device_id, self.match["case"], order["technician"],
                {"name": f"INA226 True-mA (Shunt {meter['shunt_ohm']} Ω)", **meter["calibration"]})
        except DatabaseError as exc:
            raise WorkflowError(str(exc)) from exc
        with self._lock:
            self.points = {}
            self.stage = "calibrating"
            self.t_start = time.monotonic()
        return self.public()

    def _cal_device(self) -> dict:
        if self.stage != "calibrating":
            raise WorkflowError("Keine Kalibrierung aktiv")
        return self.s.db.device(self.device_id)

    def apply_setpoint(self, pct: float) -> dict:
        """Stellungsregler: Sollwert per Command 40 vorgeben. Transmitter: nur Anzeige des Sollwerts."""
        dev = self._cal_device()
        if pct not in CAL_POINTS:
            raise WorkflowError("Ungültiger Prüfpunkt")
        target = nominal_setpoint(pct, dev["lrv"], dev["urv"])
        if dev["is_positioner"]:
            ma = 4.0 + 16.0 * pct / 100.0
            try:
                self.s.modem.set_fixed_current(self.info["identity"], ma)
            except SafeModeError as exc:
                self.s.feedback.notify("safe_mode_block")
                raise WorkflowError("24/7-Safe-Mode aktiv: Sollwertvorgabe (Cmd 40) gesperrt. Für die "
                                    "Stellungsregler-Prüfung den Safe-Mode bewusst deaktivieren.") from exc
            except HartError as exc:
                raise WorkflowError(f"Sollwertvorgabe fehlgeschlagen: {exc}") from exc
            self.fixed_current_active = True
            self._msg("info", f"Sollwert {pct:.0f} % ({ma:.2f} mA) vorgegeben – Ventil fährt …")
        return {"point_pct": pct, "setpoint_value": target, "unit": dev["unit"],
                "positioner": bool(dev["is_positioner"])}

    def live(self) -> Optional[dict]:
        """Momentanwerte für die Live-Anzeige (ohne Stabilitätsprüfung)."""
        if self.busy or self.stage not in ("identified", "calibrating") or not self.info:
            return None
        try:
            dyn = self.s.modem.read_dynamic_variables(self.info["identity"])
        except HartError:
            return {"error": "HART antwortet nicht"}
        r = self.s.meter.latest() or self.s.meter.read()
        pv = dyn.get("pv", {})
        out = {"hart_pv": pv.get("value"), "unit": pv.get("unit"), "hart_ma": dyn["loop_current_ma"],
               "true_ma": r.current_ma, "overrange": r.overrange, "namur": r.namur_state,
               "status_texts": dyn.get("status_texts", [])}
        if r.current_ma is not None:
            out["da_mismatch_pct"] = (r.current_ma - dyn["loop_current_ma"]) / 16.0 * 100.0
        return out

    def measure_point(self, pct: float, reference_value: Optional[float] = None) -> dict:
        dev = self._cal_device()
        if pct not in CAL_POINTS:
            raise WorkflowError("Ungültiger Prüfpunkt")
        if dev["is_positioner"] and not self.fixed_current_active:
            raise WorkflowError("Erst den Sollwert vorgeben (Stellungsregler)")
        self.busy = True
        try:
            from current_meter import OverrangeError
            try:
                true_ma, _span = self.s.meter.read_stable()
            except OverrangeError as exc:
                true_ma = None
                self._msg("warn", f"True-mA nicht messbar: {exc}")
            except TimeoutError as exc:
                raise WorkflowError(f"{exc} – Prozess/Druck stabilisieren und erneut messen") from exc
            try:
                dyn = self.s.modem.read_dynamic_variables(self.info["identity"])
            except HartError as exc:
                raise WorkflowError(f"HART-Messwert nicht lesbar: {exc}") from exc
        finally:
            self.busy = False
        point = evaluate_point(pct, lrv=dev["lrv"], urv=dev["urv"], tolerance_pct=dev["tolerance_pct"],
                               hart_pv=dyn.get("pv", {}).get("value"), hart_ma=dyn["loop_current_ma"],
                               true_ma=true_ma, reference_value=reference_value)
        self.s.db.add_point(self.calibration_id, point)
        with self._lock:
            self.points[pct] = point
            for w in point["warnings"]:
                self._msg("warn", f"{pct:.0f} %: {w}")
        if any("Digital/Analog" in w for w in point["warnings"]):
            self.s.feedback.notify("analog_mismatch")
        else:
            self.s.feedback.notify("point_captured" if point["passed"] else "warning")
        return point

    def attach_photo(self, pct: Optional[float] = None, note: str = "") -> dict:
        order = self._order()
        if not self.device_id:
            raise WorkflowError("Kein Gerät ausgewählt")
        dev = self.s.db.device(self.device_id)
        photo = self.s.camera.capture_photo(order_id=order["order_no"], tag=dev["tag"], note=note)
        self.s.db.add_photo(photo, order["id"], self.device_id, self.calibration_id, pct)
        self._msg("ok", "Beweisfoto gespeichert")
        self.s.feedback.notify("scan_ok")
        return photo

    def _release_fixed_current(self) -> None:
        if self.fixed_current_active and self.info:
            try:
                self.s.modem.exit_fixed_current(self.info["identity"])
            except HartError as exc:
                log.error("Festwertmodus konnte nicht beendet werden: %s", exc)
                self._msg("error", "ACHTUNG: Festwertmodus (Cmd 40) konnte nicht beendet werden – Gerät prüfen!")
                return
            self.fixed_current_active = False

    def finish(self, notes: str = "") -> dict:
        self._cal_device()
        order = self._order()
        if len(self.points) < len(CAL_POINTS):
            missing = [f"{p:.0f} %" for p in CAL_POINTS if p not in self.points]
            raise WorkflowError(f"Noch nicht gemessen: {', '.join(missing)}")
        self._release_fixed_current()
        try:
            cal = self.s.db.finish_calibration(self.calibration_id, notes=notes)
        except DatabaseError as exc:
            raise WorkflowError(str(exc)) from exc
        dev = self.s.db.device(self.device_id)
        self.s.telemetry.event(EV_CALIBRATION, f"{dev['tag']}: {cal['result']}", order_no=order["order_no"],
                               device_tag=dev["tag"], duration_sec=cal["duration_s"], result=cal["result"],
                               case=cal["case_type"], max_error_pct=cal["max_error_pct"])
        with self._lock:
            self.stage = "done"
            self.last_result = cal
        self.s.feedback.notify("calibration_ok" if cal["result"] == "BESTANDEN" else "calibration_fail")
        return self.public()

    def abort(self, reason: str = "Vom Prüfer abgebrochen") -> dict:
        self._release_fixed_current()
        if self.stage == "calibrating" and self.calibration_id:
            try:
                self.s.db.finish_calibration(self.calibration_id, aborted=True, notes=reason)
            except DatabaseError:
                pass
        self.reset_keep_qr()
        return self.public()

    # ------------------------------------------------------------------ Etikett
    def label_data(self):
        from datetime import date, datetime
        from label_printer import LabelData
        if not self.device_id:
            raise WorkflowError("Kein Gerät ausgewählt")
        order = self._order()
        dev = self.s.db.device(self.device_id)
        cust = self.s.db.customer(dev["customer_id"])
        last = self.s.db.last_calibration(self.device_id)
        kind = "PRUEFUNG"
        if not last and self.match:
            kind = "GERAETETAUSCH" if self.match["case"] == CASE_SWAP else "NEUAUFNAHME"
        test_date = datetime.fromtimestamp(last["finished_at"]).date() if last else date.today()
        months = self.s.config.Company.RECAL_INTERVAL_MONTHS
        y, m = divmod(test_date.month - 1 + months, 12)
        due = date(test_date.year + y, m + 1, 1) if last and last["result"] == "BESTANDEN" else None
        return LabelData(customer_id=cust.get("customer_no") or cust["id"], tag=dev["tag"],
                         uid=dev["hart_unique_id"], kind=kind,
                         passed=None if not last else last["result"] == "BESTANDEN", test_date=test_date,
                         next_due=due, technician=order["technician"], order_no=order["order_no"])

    def print_label(self, copies: int = 1) -> dict:
        res = self.s.printer.print_label(self.label_data(), copies)
        self.s.feedback.notify("success" if res["ok"] else "error")
        return res

    def shutdown(self) -> None:
        """Beim Herunterfahren: Festwertmodus lösen, laufende Kalibrierung als abgebrochen markieren."""
        try:
            self.abort("Gerät heruntergefahren")
        except Exception:
            log.exception("Workflow beim Herunterfahren")

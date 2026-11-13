"""
calibration.py – Auswertung der 5-Punkt-Kalibrierung (rechnerischer Kern).

Je Prüfpunkt (0/25/50/75/100 %) werden verglichen:
  Soll        – Nennwert bzw. tatsächlich aufgegebener Referenzwert (z.B. Druckkalibrator)
  HART-Ist    – digitaler Messwert (Command 3, PV)
  HART-mA     – vom Gerät GEMELDETER Schleifenstrom (Command 3)
  True-mA     – mit dem INA226 GEMESSENER Schleifenstrom

Abweichungen in % der Spanne:
  error_pv_pct    = (HART-Ist − Soll) / Spanne            -> Sensor/Digitalteil
  error_ma_pct    = (True-mA − Soll-mA) / 16 mA           -> gesamte analoge Kette
  da_mismatch_pct = (True-mA − HART-mA) / 16 mA           -> D/A-Wandler bzw. Schleife
Ein Punkt ist bestanden, wenn |error_pv| und |error_ma| innerhalb der Toleranz liegen.
Eine D/A-Abweichung über der Warnschwelle löst zusätzlich eine Warnung aus.
"""
from __future__ import annotations

from typing import Optional

CAL_POINTS = (0.0, 25.0, 50.0, 75.0, 100.0)
DA_WARN_PCT = 0.25          # 40 µA – Warnung "Digital ≠ Analog"


def nominal_setpoint(point_pct: float, lrv: float, urv: float) -> float:
    return lrv + (urv - lrv) * point_pct / 100.0


def ma_for_value(value: float, lrv: float, urv: float) -> float:
    return 4.0 + 16.0 * (value - lrv) / (urv - lrv)


def evaluate_point(point_pct: float, *, lrv: float, urv: float, tolerance_pct: float,
                   hart_pv: Optional[float], hart_ma: Optional[float], true_ma: Optional[float],
                   reference_value: Optional[float] = None, da_warn_pct: float = DA_WARN_PCT) -> dict:
    span = urv - lrv
    if span == 0:
        raise ValueError("Messspanne ist 0")
    setpoint = nominal_setpoint(point_pct, lrv, urv) if reference_value is None else reference_value
    setpoint_ma = ma_for_value(setpoint, lrv, urv)
    err_pv = None if hart_pv is None else (hart_pv - setpoint) / span * 100.0
    err_ma = None if true_ma is None else (true_ma - setpoint_ma) / 16.0 * 100.0
    da = None if (true_ma is None or hart_ma is None) else (true_ma - hart_ma) / 16.0 * 100.0
    checks = [e for e in (err_pv, err_ma) if e is not None]
    if not checks:
        raise ValueError("Weder HART-Messwert noch Schleifenstrom vorhanden")
    passed = all(abs(e) <= tolerance_pct for e in checks)
    warnings = []
    if da is not None and abs(da) > da_warn_pct:
        warnings.append(f"Digital/Analog-Abweichung {da:+.3f} % ({(true_ma - hart_ma) * 1000:+.0f} µA)")
    if err_pv is not None and abs(err_pv) > tolerance_pct:
        warnings.append(f"HART-Messwert außerhalb Toleranz ({err_pv:+.3f} %)")
    if err_ma is not None and abs(err_ma) > tolerance_pct:
        warnings.append(f"Schleifenstrom außerhalb Toleranz ({err_ma:+.3f} %)")
    return {"point_pct": point_pct, "setpoint_value": setpoint, "setpoint_ma": setpoint_ma,
            "hart_pv": hart_pv, "hart_ma": hart_ma, "true_ma": true_ma,
            "error_pv_pct": err_pv, "error_ma_pct": err_ma, "da_mismatch_pct": da,
            "passed": passed, "warnings": warnings}

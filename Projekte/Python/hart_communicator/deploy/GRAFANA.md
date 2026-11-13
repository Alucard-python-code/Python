# Grafana: Telemetrie auswerten

Datenquelle: Plugin **SQLite** (`frser-sqlite-datasource`), Datei `telemetry_logs.db`
(z.B. vom USB-Export oder per Netzwerkfreigabe im Dock). Die Datenbank läuft im WAL-Modus:
Grafana kann lesen, während das Gerät schreibt.

In jeder Abfrage `timestamp_unix` als **Time-formatted column** eintragen.

## Akku: Spannung, Strom, Ladezustand
```sql
SELECT timestamp_unix, pack_voltage_v, pack_current_a, soc_percent
FROM telemetry_timeseries
WHERE timestamp_unix BETWEEN $__unixEpochFrom() AND $__unixEpochTo()
ORDER BY timestamp_unix
```

## Einzelzellen Z1–Z8 und Drift
```sql
SELECT timestamp_unix, cell_1_v, cell_2_v, cell_3_v, cell_4_v,
       cell_5_v, cell_6_v, cell_7_v, cell_8_v, cell_drift_mv
FROM telemetry_timeseries
WHERE timestamp_unix BETWEEN $__unixEpochFrom() AND $__unixEpochTo()
ORDER BY timestamp_unix
```

## Betriebsstunden (Stat-Panel, letzter Wert)
```sql
SELECT timestamp_unix,
       total_runtime_sec / 3600.0 AS gesamt_h,
       field_runtime_sec / 3600.0 AS feld_h,
       dock_runtime_sec  / 3600.0 AS dock_h,
       active_hart_sec   / 3600.0 AS hart_h
FROM telemetry_timeseries ORDER BY timestamp_unix DESC LIMIT 1
```

## Feld/Dock-Zeitleiste (State timeline)
```sql
SELECT timestamp_unix, mode FROM telemetry_timeseries
WHERE timestamp_unix BETWEEN $__unixEpochFrom() AND $__unixEpochTo()
ORDER BY timestamp_unix
```

## Ereignisse als Annotationen
```sql
SELECT timestamp_unix AS time, event_type || ': ' || message AS text, event_type AS tags
FROM system_events
WHERE timestamp_unix BETWEEN $__unixEpochFrom() AND $__unixEpochTo()
```

## Kalibrierungen pro Tag mit Ergebnis (Tabelle)
```sql
SELECT date(timestamp_unix, 'unixepoch', 'localtime') AS tag,
       COUNT(*) AS anzahl,
       SUM(result = 'BESTANDEN') AS bestanden,
       ROUND(AVG(duration_sec) / 60.0, 1) AS dauer_min
FROM system_events WHERE event_type = 'CALIBRATION'
GROUP BY tag ORDER BY tag DESC
```

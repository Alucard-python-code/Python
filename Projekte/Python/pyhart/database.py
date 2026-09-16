import sqlite3
from datetime import datetime

DB_FILE = 'kalibrierung.db'

def init_database():
    """Erstellt die Tabellen für Sensor-Typen und das Kalibrier-Log."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS sensoren (
            tag TEXT PRIMARY KEY,
            serial_number TEXT,
            model TEXT,
            hart_address INTEGER,
            range_min REAL,
            range_max REAL,
            unit TEXT,
            tolerance REAL,
            steps_json TEXT
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS protokolle (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT,
            tag TEXT,
            serial_number TEXT,
            status TEXT,
            notiz TEXT
        )
    """)
    conn.commit()
    conn.close()

def get_all_tags():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT tag FROM sensoren")
    tags = [row[0] for row in cursor.fetchall()]
    conn.close()
    return tags

def get_sensor_by_tag(tag):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM sensoren WHERE tag = ?", (tag,))
    row = cursor.fetchone()
    conn.close()
    if row:
        return {
            "tag": row[0], "serial_number": row[1], "model": row[2], "hart_address": row[3],
            "min": row[4], "max": row[5], "unit": row[6], "tol": row[7], "steps": eval(row[8])
        }
    return None

def check_tag_existence(tag):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT serial_number FROM sensoren WHERE tag = ?", (tag,))
    row = cursor.fetchone()
    conn.close()
    return row[0] if row else None

def save_or_replace_sensor(tag, serial_number, model, address, r_min, r_max, unit, tol, steps):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT OR REPLACE INTO sensoren VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (tag, serial_number, model, address, r_min, r_max, unit, tol, str(steps)))
    conn.commit()
    conn.close()

def log_calibration(tag, serial_number, status, value, unit):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    notiz = f"Kalibriert bei Endprüfwert: {value} {unit}"
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("INSERT INTO protokolle (timestamp, tag, serial_number, status, notiz) VALUES (?, ?, ?, ?, ?)",
                   (timestamp, tag, serial_number, status, notiz))
    conn.commit()
    conn.close()
    return timestamp

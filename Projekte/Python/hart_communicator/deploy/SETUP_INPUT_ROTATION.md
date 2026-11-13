# Einrichtung: Rotation & Eingabegeräte

1. **Rechte für evdev (Touch-Sperre, Geräteerkennung):**
   `sudo usermod -aG input hart`, danach neu anmelden.
2. **I2C für den Lagesensor:** `sudo usermod -aG i2c hart`. Prüfen mit
   `i2cdetect -y 1`: an Adresse 0x18 muss der LIS3DH antworten.
3. **Touch an Display binden:** `deploy/labwc-rc.xml` übernehmen und den Gerätenamen eintragen.
4. **Wayland-Umgebung:** Läuft die App als systemd-*User*-Service in der Kiosk-Sitzung, sind
   `WAYLAND_DISPLAY`/`XDG_RUNTIME_DIR` gesetzt. Sonst findet `rotation_daemon.py` den Socket
   unter `/run/user/<uid>/wayland-*` selbst.
5. **Einbaulage kalibrieren:** `python rotation_daemon.py --calibrate`. Das Gerät nacheinander
   aufrecht, rechts, kopfüber und links halten. Stimmt die angezeigte Lage nicht, Achsen per
   `ACCEL_AXIS_X/Y` und `ACCEL_SIGN_X/Y` anpassen. Ist das Bild um 180° falsch herum,
   `Display.TRANSFORM_FOR` in `config.py` tauschen (90 ↔ 270).
6. **Eingabegeräte live prüfen:** `python input_monitor.py --hw`, dann Maus/Tastatur an- und abstecken.

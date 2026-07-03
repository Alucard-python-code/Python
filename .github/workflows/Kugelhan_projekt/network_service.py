import socket
import time
import _thread
import machine
from config import settings, state, save_calibration, load_password, save_password
import motor

# =========================================================================
# 1. MODBUS TCP PROTOKOLL ENGINE
# =========================================================================
def handle_modbus_client(client_sock):
    """Verarbeitet eingehende Modbus-TCP Binärtelegramme mit Fehler-Exceptions."""
    global state
    try:
        client_sock.settimeout(2.0)
        while True:
            data = client_sock.recv(1024)
            if not data or len(data) < 12: 
                break
                
            # Modbus Aktivität registrieren (Watchdog zurücksetzen)
            state["last_modbus_activity"] = time.ticks_ms()
            if state["watchdog_triggered"]:
                state["watchdog_triggered"] = False
                if state["fehler_code"] == 2: 
                    state["fehler_code"] = 0
            
            # MBAP Header & PDU extrahieren
            tx_id = data[0:2]
            proto_id = data[2:4]
            unit_id = data[6]
            func_code = data[7]
            reg_addr = (data[8] << 8) | data[9]
            
            # --- INDUSTRIELLE FEHLERBEHANDLUNG ---
            # Wenn ein kritischer Hardwarefehler vorliegt, antwortet der RP2040 aktiv mit
            # einem offiziellen Modbus Exception Code 04 (Server/Slave Device Failure)
            if state["fehler_code"] != 0:
                pdu = bytearray([func_code + 0x80, 0x04]) # 0x04 = Slave Device Failure
                header = bytearray([tx_id[0], tx_id[1], proto_id[0], proto_id[1], 0x00, len(pdu) + 1, unit_id])
                client_sock.sendall(header + pdu)
                continue # Springe zum naechsten Paket, ueberspringe normale Verarbeitung
            
            # --- NORMALE VERARBEITUNG (Wenn kein Fehler vorliegt) ---
            # --- FUNCTION CODE 03: Read Holding Registers ---
            if func_code == 3:
                num_regs = (data[10] << 8) | data[11]
                byte_count = num_regs * 2
                pdu = bytearray([3, byte_count])
                
                for i in range(num_regs):
                    curr = reg_addr + i
                    val = 0
                    if curr == 0: val = state["soll_oeffnung"]
                    elif curr == 1: val = state["ist_oeffnung"]
                    elif curr == 2: val = int(state["temperatur"] * 10) # z.B. 24.5°C -> 245
                    elif curr == 3: val = state["status_code"]
                    elif curr == 4: val = state["fehler_code"]
                    
                    pdu.append((val >> 8) & 0xFF)
                    pdu.append(val & 0xFF)
                    
            # --- FUNCTION CODE 06: Write Single Register ---
            elif func_code == 6:
                val = (data[10] << 8) | data[11]
                if reg_addr == 0 and 0 <= val <= 100: 
                    state["soll_oeffnung"] = val
                pdu = data[7:12] # Echo zurücksenden
            else:
                pdu = bytearray([func_code + 0x80, 0x01]) # Illegal Function
                
            header = bytearray([tx_id[0], tx_id[1], proto_id[0], proto_id[1], 0x00, len(pdu) + 1, unit_id])
            client_sock.sendall(header + pdu)
    except: 
        pass
    finally: 
        client_sock.close()

def modbus_server_loop():
    """Lauscht permanent auf Verbindungen am konfigurierten Modbus-Port."""
    s = socket.socket()
    s.bind(('0.0.0.0', settings["modbus_port"]))
    s.listen(2)
    print(f"[Modbus] Server laeuft auf Port {settings['modbus_port']}")
    while True:
        try:
            c, a = s.accept()
            _thread.start_new_thread(handle_modbus_client, (c,))
        except: 
            time.sleep_ms(100)

def watchdog_check_loop():
    """Prüft im Hintergrund, ob die Modbus-Verbindung unterbrochen wurde (Puffer-Logik)."""
    while True:
        diff = time.ticks_diff(time.ticks_ms(), state["last_modbus_activity"])
        if diff > settings["watchdog_timeout_ms"] and not state["watchdog_triggered"]:
            state["watchdog_triggered"] = True
            state["fehler_code"] = 2
            print("[Watchdog] Timeout ausgeloest! Keine Modbus-Aktivitaet.")
        time.sleep_ms(500)
# =========================================================================
# 2. WEBINTERFACE HTML GENERIERUNG
# =========================================================================
def get_login_html(error_msg=""):
    """Erzeugt die Login-Maske, falls der Nutzer nicht angemeldet ist."""
    err_line = f"<p style='color:red; font-weight:bold;'>{error_msg}</p>" if error_msg else ""
    return f"""<!DOCTYPE html><html><head><meta charset='utf-8'><title>PR2020 Login</title>
    <style>
        body {{ font-family:Arial; margin:100px auto; width:300px; background:#f4f4f4; text-align:center; }}
        .box {{ background:white; padding:20px; border-radius:5px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }}
        input {{ width:90%; padding:8px; margin:10px 0; border:1px solid #ccc; border-radius:4px; }}
        .btn {{ background:#007bff; color:white; border:none; cursor:pointer; font-weight:bold; }}
    </style></head><body>
    <h2>PR2020 Steuerung</h2>
    <div class="box">
        <h3>Login erforderlich</h3>
        {err_line}
        <form action="/login" method="GET">
            <input type="password" name="pwd" placeholder="Passwort eingeben" autofocus>
            <input type="submit" class="btn" value="Anmelden">
        </form>
    </div></body></html>"""

def get_html():
    """Erzeugt das geschützte Haupt-Webinterface (nur sichtbar nach Login)."""
    msg, style = "Alles i.O.", "color: green; font-weight: bold;"
    if state["fehler_code"] == 1: msg, style = "FEHLER: Poti defekt!", "color: red; font-weight: bold;"
    elif state["fehler_code"] == 2: msg, style = "FEHLER: Watchdog Timeout!", "color: red; font-weight: bold;"
    elif state["fehler_code"] == 3: msg, style = "FEHLER: Motor blockiert!", "color: red; font-weight: bold;"
    
    st_txt = ["Bereit", "Oeffnet...", "Schliesst..."][state["status_code"]]
    calib_status = "Inaktiv"
    if state["auto_calib_active"]:
        calib_status = f"Aktiv - Schritt {state['auto_calib_step']} laeuft..."
    
    return f"""<!DOCTYPE html><html><head><meta charset='utf-8'><title>PR2020 Control</title>
    <style>
        body {{ font-family:Arial; margin:30px; background:#f4f4f4; }}
        .box {{ background:white; padding:15px; border-radius:5px; margin-bottom:15px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }}
        .btn {{ padding:8px 12px; margin:4px; background:#007bff; color:white; border:none; border-radius:4px; cursor:pointer; text-decoration:none; display:inline-block; font-weight:bold; }}
        .btn-stop {{ background:#dc3545; }} .btn-save {{ background:#28a745; }}
    </style>
    </head>
    <body>
        <div style="float:right;"><a class="btn btn-stop" href="/logout">Abmelden</a></div>
        <h2>1 1/2" Ventilsteuerung Live-Daten</h2>
        <div class="box">
            <p>Zustand: <span style='{style}'>{msg}</span></p>
            <p>Motor-Zustand: <b>{st_txt}</b></p>
            <p>Soll-Vorgabe: <b>{state['soll_oeffnung']}%</b> | Position: <b>{state['ist_oeffnung']}%</b></p>
            <p>Poti Live-Rohwert: <b>{state['poti_raw_live']}</b> (Bereich: {state['poti_min']} bis {state['poti_max']})</p>
            <p>Temperatur: <b>{state['temperatur']}&deg;C</b></p>
        </div>

        <h2>Vollautomatische Endschalter-Kalibrierung</h2>
        <div class="box">
            <p><b>Status der Auto-Kalibrierung:</b> <span style="color:orange; font-weight:bold;">{calib_status}</span></p>
            <p><i>Klicken Sie auf den Button, um den Kugelhahn vollautomatisch beide Endanschlaege anfahren zu lassen. Das System speichert die Werte danach von allein.</i></p>
            <a class="btn btn-save" style="background:#17a2b8;" href="/autocalib">Vollautomatische Kalibrierung JETZT starten</a>
        </div>

        <h2>Manueller Motortest (Fehlersuche)</h2>
        <div class="box">
            <a class="btn" href="/motor?cmd=open">Motor RECHTS (Auf)</a>
            <a class="btn" href="/motor?cmd=close">Motor LINKS (Zu)</a>
            <a class="btn btn-stop" href="/motor?cmd=stop">MOTOR STOPP</a>
        </div>

        <h2>System-Konfiguration & Passwort aendern</h2>
        <div class="box">
            <form action='/save' method='GET'>
                IP-Adresse: <input type='text' name='ip' value='{settings['ip']}'><br><br>
                Watchdog (ms): <input type='number' name='wdt' value='{settings['watchdog_timeout_ms']}'><br><br>
                Motor-Blockadezeit (ms): <input type='number' name='blk' value='{settings['motor_block_ms']}'><br><br>
                Neues Passwort: <input type='password' name='new_pwd' placeholder='Leer lassen für kein Wechsel'><br><br>
                <input type='submit' class="btn btn-save" value='Einstellungen uebernehmen'>
            </form>
        </div>
    </body></html>"""
# =========================================================================
# 3. WEBSERVER REQUEST ROUTING LOOP
# =========================================================================
def web_server_loop():
    """Lauscht auf Port 80, validiert Logins und steuert Handlauf/Settings/Auto-Calib."""
    s = socket.socket()
    s.bind(('0.0.0.0', settings["web_port"]))
    s.listen(2)
    print(f"[Webserver] Server laeuft auf Port {settings['web_port']}")
    
    while True:
        try:
            c, a = s.accept()
            client_ip = a[0]
            req = c.recv(1024).decode('utf-8')
            
            current_password = load_password()
            
            # --- LOGIN VERARBEITEN ---
            if "GET /login" in req:
                try:
                    submitted_pwd = req.split("pwd=")[1].split(" ")[0]
                    if submitted_pwd == current_password:
                        if client_ip not in state["logged_in_users"]:
                            state["logged_in_users"].append(client_ip)
                        c.send("HTTP/1.1 302 Found\r\nLocation: /\r\nSet-Cookie: auth=1; HttpOnly; Path=/\r\n\r\n".encode('utf-8'))
                        c.close()
                        continue
                    else:
                        c.send("HTTP/1.1 200 OK\r\nContent-Type: text/html\r\n\r\n".encode('utf-8'))
                        c.sendall(get_login_html("Falsches Passwort!").encode('utf-8'))
                        c.close()
                        continue
                except: pass

            # --- LOGOUT VERARBEITEN ---
            if "GET /logout" in req:
                if client_ip in state["logged_in_users"]:
                    state["logged_in_users"].remove(client_ip)
                c.send("HTTP/1.1 302 Found\r\nLocation: /\r\nSet-Cookie: auth=0; Max-Age=0; Path=/\r\n\r\n".encode('utf-8'))
                c.close()
                continue

            # --- AUTHENTIFIZIERUNGSPRUEFUNG ---
            is_authenticated = (client_ip in state["logged_in_users"]) or ("Cookie: auth=1" in req)
            if not is_authenticated:
                c.send("HTTP/1.1 200 OK\r\nContent-Type: text/html\r\n\r\n".encode('utf-8'))
                c.sendall(get_login_html().encode('utf-8'))
                c.close()
                continue

            # --- AB HIER NUR EINGELOGGTE NUTZER ---
            
            # --- AUTO-KALIBRIERUNG TRIGGERN ---
            if "GET /autocalib" in req:
                state["auto_calib_active"] = True
                state["auto_calib_step"] = 1 # Startet mit der Fahrt zu ZU
                print("[Web] Vollautomatische Kalibrierung gestartet.")

            # --- MANUELLER MOTOR-HANDLAUF ---
            elif "GET /motor" in req:
                if "cmd=open" in req:
                    motor.stop_motor()
                    state["status_code"] = 1
                    _thread.start_new_thread(motor.drive_motor_soft, (motor.m_open_pwm,))
                elif "cmd=close" in req:
                    motor.stop_motor()
                    state["status_code"] = 2
                    _thread.start_new_thread(motor.drive_motor_soft, (motor.m_close_pwm,))
                elif "cmd=stop" in req:
                    motor.stop_motor()
                    state["status_code"] = 0
                    state["soll_oeffnung"] = state["ist_oeffnung"]
            
            # --- CONFIG SPEICHERN ---
            elif "GET /save" in req:
                try:
                    # Parameter-String isolieren und in Paare splitten
                    query_string = req.split(" ")[1].split("?")[1]
                    params = query_string.split("&")
                    reboot_needed = False
                    for p in params:
                        k, v = p.split("=")
                        if k == "ip" and v != settings["ip"]: 
                            settings["ip"] = v
                            reboot_needed = True
                        elif k == "wdt": settings["watchdog_timeout_ms"] = int(v)
                        elif k == "blk": settings["motor_block_ms"] = int(v)
                        elif k == "new_pwd" and v != "": save_password(v)
                    
                    if reboot_needed:
                        c.send("HTTP/1.1 200 OK\r\n\r\nIP geandert. Controller startet neu...".encode('utf-8'))
                        c.close()
                        time.sleep(1)
                        machine.reset()
                except: pass
                
            # Standard: Seite ausliefern
            c.send("HTTP/1.1 200 OK\r\nContent-Type: text/html\r\n\r\n".encode('utf-8'))
            c.sendall(get_html().encode('utf-8'))
            c.close()
        except: 
            time.sleep_ms(100)

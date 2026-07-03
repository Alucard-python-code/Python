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
    """Verarbeitet eingehende Modbus-TCP Binärtelegramme mit Fehler-Exceptions (Punkt 2)."""
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
            unit_id = data
            func_code = data
            reg_addr = (data << 8) | data
            
            # --- PUNKT 2: INDUSTRIELLE FEHLERBEHANDLUNG ---
            # Wenn ein kritischer Hardwarefehler vorliegt, antwortet der RP2040 aktiv mit
            # einem offiziellen Modbus Exception Code 04 (Server/Slave Device Failure)
            if state["fehler_code"] != 0:
                pdu = bytearray([func_code + 0x80, 0x04]) # 0x04 = Slave Device Failure
                header = bytearray([tx_id, tx_id, proto_id, proto_id, 0x00, len(pdu) + 1, unit_id])
                client_sock.sendall(header + pdu)
                continue # Springe zum naechsten Paket, ueberspringe normale Verarbeitung
            
            # --- NORMALE VERARBEITUNG (Wenn kein Fehler vorliegt) ---
            # --- FUNCTION CODE 03: Read Holding Registers ---
            if func_code == 3:
                num_regs = (data << 8) | data
                byte_count = num_regs * 2
                pdu = bytearray([3, byte_count])
                
                for i in range(num_regs):
                    curr = reg_addr + i
                    val = 0
                    if curr == 0: val = state["soll_oeffnung"]
                    elif curr == 1: val = state["ist_oeffnung"]
                    elif curr == 2: val = int(state["temperatur"] * 10)
                    elif curr == 3: val = state["status_code"]
                    elif curr == 4: val = state["fehler_code"]
                    
                    pdu.append((val >> 8) & 0xFF)
                    pdu.append(val & 0xFF)
                    
            # --- FUNCTION CODE 06: Write Single Register ---
            elif func_code == 6:
                val = (data << 8) | data
                if reg_addr == 0 and 0 <= val <= 100: 
                    state["soll_oeffnung"] = val
                pdu = data[7:12] # Echo zurücksenden
            else:
                pdu = bytearray([func_code + 0x80, 0x01]) # Illegal Function
                
            header = bytearray([tx_id, tx_id, proto_id, proto_id, 0x00, len(pdu) + 1, unit_id])
            client_sock.sendall(header + pdu)
    except: 
        pass
    finally: 
        client_sock.close()

def modbus_server_loop():
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
    while True:
        diff = time.ticks_diff(time.ticks_ms(), state["last_modbus_activity"])
        if diff > settings["watchdog_timeout_ms"] and not state["watchdog_triggered"]:
            state["watchdog_triggered"] = True
            state["fehler_code"] = 2
            print("[Watchdog] Timeout ausgeloest! Keine Modbus-Aktivitaet.")
        time.sleep_ms(500)

# =========================================================================
# 2. WEBINTERFACE HTML & LOGIC SERVER
# =========================================================================
def get_login_html(error_msg=""):
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
    msg, style = "Alles i.O.", "color: green; font-weight: bold;"
    if state["fehler_code"] == 1: msg, style = "FEHLER: Poti defekt!", "color: red; font-weight: bold;"
    elif state["fehler_code"] == 2: msg, style = "FEHLER: Watchdog Timeout!", "color: red; font-weight: bold;"
    elif state["fehler_code"] == 3: msg, style = "FEHLER: Motor blockiert!", "color: red; font-weight: bold;"
    
    st_txt = ["Bereit", "Oeffnet...", "Schliesst..."][state["status_code"]]
    
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

        <h2>Automatisches Poti-Kalibrierwerkzeug</h2>
        <div class="box">
            <p><i>Schritt 1: Ventil manuell an die Anschlaege fahren.</i></p>
            <a class="btn" href="/motor?cmd=open">Motor RECHTS (Auf)</a>
            <a class="btn" href="/motor?cmd=close">Motor LINKS (Zu)</a>
            <a class="btn btn-stop" href="/motor?cmd=stop">MOTOR STOPP</a>
            <hr>
            <p><i>Schritt 2: Endpunkte im laufenden Betrieb setzen.</i></p>
            <a class="btn" href="/calib?set=min">Aktuellen Wert als ZU (0%) setzen</a> <small>(Gespeichert: {state['poti_min']})</small><br><br>
            <a class="btn" href="/calib?set=max">Aktuellen Wert als AUF (100%) setzen</a> <small>(Gespeichert: {state['poti_max']})</small><br><br>
            <a class="btn btn-save" href="/calib?set=save">Kalibrierung permanent speichern</a>
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

def web_server_loop():
    s = socket.socket()
    s.bind(('0.0.0.0', settings["web_port"]))
    s.listen(2)
    print(f"[Webserver] Server laeuft auf Port {settings['web_port']}")
    
    while True:
        try:
            c, a = s.accept()
            client_ip = a
            req = c.recv(1024).decode('utf-8')
            
            current_password = load_password()
            
            if "GET /login" in req:
                try:
                    submitted_pwd = req.split("pwd=").split(" ")
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

            if "GET /logout" in req:
                if client_ip in state["logged_in_users"]:
                    state["logged_in_users"].remove(client_ip)
                c.send("HTTP/1.1 302 Found\r\nLocation: /\r\nSet-Cookie: auth=0; Max-Age=0; Path=/\r\n\r\n".encode('utf-8'))
                c.close()
                continue

            # --- 3. AUTHENTIFIZIERUNGSPRUEFUNG ---
            is_authenticated = (client_ip in state["logged_in_users"]) or ("Cookie: auth=1" in req)
            if not is_authenticated:
                c.send("HTTP/1.1 200 OK\r\nContent-Type: text/html\r\n\r\n".encode('utf-8'))
                c.sendall(get_login_html().encode('utf-8'))
                c.close()
                continue

            # --- 4. MOTOR-HANDSTEUERUNG (NUR EINGELOGGT) ---
            if "GET /motor" in req:
                if "cmd=open" in req:
                    motor.stop_motor()
                    # Bei Handsteuerung wird der Motor ebenfalls sanft angefahren
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
            
            # --- 5. KALIBRIERUNG (NUR EINGELOGGT) ---
            elif "GET /calib" in req:
                if "set=min" in req: state["poti_min"] = state["poti_raw_live"]
                elif "set=max" in req: state["poti_max"] = state["poti_raw_live"]
                elif "set=save" in req: save_calibration()
            
            # --- 6. SPEICHERN & ENGINES (NUR EINGELOGGT) ---
            elif "GET /save" in req:
                try:
                    params = req.split(" ").split("?").split("&")
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
                
            c.send("HTTP/1.1 200 OK\r\nContent-Type: text/html\r\n\r\n".encode('utf-8'))
            c.sendall(get_html().encode('utf-8'))
            c.close()
        except: 
            time.sleep_ms(100)


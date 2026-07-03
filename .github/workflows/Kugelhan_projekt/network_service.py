import socket
import time
import _thread
import machine
from config import settings, state, save_calibration, load_password, save_password
import motor

# ... (handle_modbus_client, modbus_server_loop und watchdog_check_loop bleiben unverändert) ...

def get_login_html(error_msg=""):
    """Erzeugt die Login-Maske, falls der Nutzer nicht eingeloggt ist."""
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
    
    st_txt = ["Bereit", "Öffnet...", "Schließt..."][state["status_code"]]
    
    return f"""<!DOCTYPE html><html><head><meta charset='utf-8'><title>PR2020</title>
    <style>
        body {{ font-family:Arial; margin:30px; background:#f4f4f4; }}
        .box {{ background:white; padding:15px; border-radius:5px; margin-bottom:15px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }}
        .btn {{ padding:8px 12px; margin:4px; background:#007bff; color:white; border:none; border-radius:4px; cursor:pointer; text-decoration:none; display:inline-block; }}
        .btn-stop {{ background:#dc3545; }} .btn-save {{ background:#28a745; }}
    </style>
    </head>
    <body>
        <div style="float:right;"><a class="btn btn-stop" href="/logout">Abmelden</a></div>
        <h2>1 1/2" Ventilsteuerung Live-Daten</h2>
        <div class="box">
            <p>Zustand: <span style='{style}'>{msg}</span> ({st_txt})</p>
            <p>Soll-Vorgabe: <b>{state['soll_oeffnung']}%</b> | Position: <b>{state['ist_oeffnung']}%</b></p>
            <p>Poti Live-Rohwert: <b>{state['poti_raw_live']}</b> (Bereich: {state['poti_min']} bis {state['poti_max']})</p>
            <p>Temperatur: <b>{state['temperatur']}&deg;C</b></p>
        </div>

        <h2>Automatisches Poti-Kalibrierwerkzeug</h2>
        <div class="box">
            <a class="btn" href="/motor?cmd=open">Motor RECHTS (Auf)</a>
            <a class="btn" href="/motor?cmd=close">Motor LINKS (Zu)</a>
            <a class="btn btn-stop" href="/motor?cmd=stop">MOTOR STOPP</a>
            <hr>
            <a class="btn" href="/calib?set=min">Aktuellen Wert als ZU (0%) setzen</a> <small>({state['poti_min']})</small><br><br>
            <a class="btn" href="/calib?set=max">Aktuellen Wert als AUF (100%) setzen</a> <small>({state['poti_max']})</small><br><br>
            <a class="btn btn-save" href="/calib?set=save">Kalibrierung permanent speichern</a>
        </div>

        <h2>System-Konfiguration & Passwort ändern</h2>
        <div class="box">
            <form action='/save' method='GET'>
                IP-Adresse: <input type='text' name='ip' value='{settings['ip']}'><br><br>
                Watchdog (ms): <input type='number' name='wdt' value='{settings['watchdog_timeout_ms']}'><br><br>
                Neues Passwort: <input type='password' name='new_pwd' placeholder='Leer lassen für kein Wechsel'><br><br>
                <input type='submit' class="btn btn-save" value='Einstellungen übernehmen'>
            </form>
        </div>
    </body></html>"""

def web_server_loop():
    s = socket.socket()
    s.bind(('0.0.0.0', settings["web_port"]))
    s.listen(2)
    
    while True:
        try:
            c, a = s.accept()
            client_ip = a[0]
            req = c.recv(1024).decode('utf-8')
            
            # Aktuelles Passwort aus dem Flash holen
            current_password = load_password()
            
            # --- 1. LOGIN VERARBEITEN ---
            if "GET /login" in req:
                try:
                    submitted_pwd = req.split("pwd=")[1].split(" ")[0]
                    if submitted_pwd == current_password:
                        if client_ip not in state["logged_in_users"]:
                            state["logged_in_users"].append(client_ip)
                        # Erfolgreich: Weiterleitung zur Hauptseite mit Cookie
                        c.send("HTTP/1.1 302 Found\r\nLocation: /\r\nSet-Cookie: auth=1; HttpOnly; Path=/\r\n\r\n".encode('utf-8'))
                        c.close()
                        continue
                    else:
                        c.send("HTTP/1.1 200 OK\r\nContent-Type: text/html\r\n\r\n".encode('utf-8'))
                        c.sendall(get_login_html("Falsches Passwort!").encode('utf-8'))
                        c.close()
                        continue
                except:
                    pass

            # --- 2. LOGOUT VERARBEITEN ---
            if "GET /logout" in req:
                if client_ip in state["logged_in_users"]:
                    state["logged_in_users"].remove(client_ip)
                c.send("HTTP/1.1 302 Found\r\nLocation: /\r\nSet-Cookie: auth=0; Max-Age=0; Path=/\r\n\r\n".encode('utf-8'))
                c.close()
                continue

            # --- 3. AUTHENTIFIZIERUNGSPRÜFUNG ---
            # Wir prüfen ob die IP in unserer Sessionliste ist oder das Cookie im Header mitsendet
            is_authenticated = (client_ip in state["logged_in_users"]) or ("Cookie: auth=1" in req)
            
            if not is_authenticated:
                c.send("HTTP/1.1 200 OK\r\nContent-Type: text/html\r\n\r\n".encode('utf-8'))
                c.sendall(get_login_html().encode('utf-8'))
                c.close()
                continue

            # --- ab hier nur erreichbar wenn EINGELOGGT ---

            # --- 4. MOTOR-HANDSTEUERUNG ---
            if "GET /motor" in req:
                if "cmd=open" in req:
                    motor.stop_motor(); motor.m_open.value(1); state["status_code"] = 1
                elif "cmd=close" in req:
                    motor.stop_motor(); motor.m_close.value(1); state["status_code"] = 2
                elif "cmd=stop" in req:
                    motor.stop_motor(); state["status_code"] = 0; state["soll_oeffnung"] = state["ist_oeffnung"]
            
            # --- 5. KALIBRIERUNG ---
            elif "GET /calib" in req:
                if "set=min" in req: state["poti_min"] = state["poti_raw_live"]
                elif "set=max" in req: state["poti_max"] = state["poti_raw_live"]
                elif "set=save" in req: save_calibration()
            
            # --- 6. SPEICHERN & PASSWORT-ÄNDERUNG ---
            elif "GET /save" in req:
                try:
                    # Parameter parsen
                    params = req.split(" ")[1].split("?")[1].split("&")
                    reboot_needed = False
                    for p in params:
                        k, v = p.split("=")
                        if k == "ip" and v != settings["ip"]: 
                            settings["ip"] = v
                            reboot_needed = True
                        elif k == "wdt": 
                            settings["watchdog_timeout_ms"] = int(v)
                        elif k == "new_pwd" and v != "": 
                            # Passwort im Flash überschreiben
                            save_password(v)
                    
                    if reboot_needed:
                        c.send("HTTP/1.1 200 OK\r\n\r\nIP geandert. Controller startet neu...".encode('utf-8'))
                        c.close()
                        time.sleep(1)
                        machine.reset()
                except: pass
                
            # Normalen Seiteninhalt senden
            c.send("HTTP/1.1 200 OK\r\nContent-Type: text/html\r\n\r\n".encode('utf-8'))
            c.sendall(get_html().encode('utf-8'))
            c.close()
        except: 
            time.sleep_ms(100)

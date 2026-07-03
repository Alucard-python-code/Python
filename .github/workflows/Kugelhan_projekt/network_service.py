# network_services.py - v1.2.2
import socket
import time
import _thread
import machine
from config import settings, state, save_calibration, load_password, save_password

# =========================================================================
# 1. MODBUS TCP ENGINE (Korrektur: FC 06 Echo = exakt 6 Bytes)
# =========================================================================
def handle_modbus_client(client_sock):
    global state
    try:
        client_sock.settimeout(2.0)
        while True:
            data = client_sock.recv(1024)
            if not data or len(data) < 12: break
                
            state["last_modbus_activity"] = time.ticks_ms()
            if state["watchdog_triggered"]:
                state["watchdog_triggered"] = False
                if state["fehler_code"] == 2: state["fehler_code"] = 0
            
            tx_id, proto_id, unit_id, func_code = data[0:2], data[2:4], data[6], data[7]
            reg_addr = (data[8] << 8) | data[9]
            
            if state["fehler_code"] != 0:
                pdu = bytearray([func_code + 0x80, 0x04])
                header = bytearray([tx_id[0], tx_id[1], proto_id[0], proto_id[1], 0x00, len(pdu) + 1, unit_id])
                client_sock.sendall(header + pdu)
                continue
            
            if func_code == 3:
                num_regs = (data[10] << 8) | data[11]
                pdu = bytearray([3, num_regs * 2])
                for i in range(num_regs):
                    curr, val = reg_addr + i, 0
                    if curr == 0: val = state["soll_oeffnung"]
                    elif curr == 1: val = state["ist_oeffnung"]
                    elif curr == 2: val = int(state["temperatur"] * 10)
                    elif curr == 3: val = state["status_code"]
                    elif curr == 4: val = state["fehler_code"]
                    pdu.append((val >> 8) & 0xFF); pdu.append(val & 0xFF)
            elif func_code == 6:
                val = (data[10] << 8) | data[11]
                if reg_addr == 0 and 0 <= val <= 100: state["soll_oeffnung"] = val
                pdu = data[7:13] # FEHLERBEHEBUNG: Exakt 6 Bytes für valides Echo
            else:
                pdu = bytearray([func_code + 0x80, 0x01])
                
            header = bytearray([tx_id[0], tx_id[1], proto_id[0], proto_id[1], 0x00, len(pdu) + 1, unit_id])
            client_sock.sendall(header + pdu)
    except: pass
    finally: client_sock.close()

def modbus_server_loop():
    s = socket.socket()
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(('0.0.0.0', settings["modbus_port"]))
    s.listen(2)
    print(f"[Modbus] Server laeuft auf Port {settings['modbus_port']}")
    while True:
        try:
            c, a = s.accept()
            _thread.start_new_thread(handle_modbus_client, (c,))
        except: time.sleep_ms(100)

def watchdog_check_loop():
    while True:
        diff = time.ticks_diff(time.ticks_ms(), state["last_modbus_activity"])
        if diff > settings["watchdog_timeout_ms"] and not state["watchdog_triggered"]:
            state["watchdog_triggered"] = True
            state["fehler_code"] = 2
            print("[Watchdog] Timeout! Keine Modbus-Aktivitaet.")
        time.sleep_ms(500)

# =========================================================================
# 2. WEBINTERFACE HTML & ROUTING (Korrektur: Keine Thread-Erzeugung bei Klick)
# =========================================================================
def get_login_html(error_msg=""):
    err_line = f"<p style='color:red; font-weight:bold;'>{error_msg}</p>" if error_msg else ""
    return f"""<!DOCTYPE html><html><head><meta charset='utf-8'><title>PR2020 Login</title>
    <style>body {{ font-family:Arial; margin:100px auto; width:300px; background:#f4f4f4; text-align:center; }}
    .box {{ background:white; padding:20px; border-radius:5px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }}
    input {{ width:90%; padding:8px; margin:10px 0; border:1px solid #ccc; border-radius:4px; }}
    .btn {{ background:#007bff; color:white; border:none; width:95%; padding:10px; cursor:pointer; font-weight:bold; border-radius:4px; }}</style></head>
    <body><h2>PR2020 Steuerung</h2><div class="box"><h3>Login erforderlich</h3>{err_line}
    <form action="/login" method="GET"><input type="password" name="pwd" placeholder="Passwort" autofocus><input type="submit" class="btn" value="Anmelden"></form></div></body></html>"""

def get_html():
    msg, style = "Alles i.O.", "color: green; font-weight: bold;"
    if state["fehler_code"] == 1: msg, style = "FEHLER: Poti defekt!", "color: red; font-weight: bold;"
    elif state["fehler_code"] == 2: msg, style = "FEHLER: Watchdog Timeout!", "color: red; font-weight: bold;"
    elif state["fehler_code"] == 3: msg, style = "FEHLER: Motor blockiert!", "color: red; font-weight: bold;"
    st_txt = ["Bereit", "Oeffnet...", "Schliesst..."][state["status_code"]]
    calib_status = f"Aktiv (Schritt {state['auto_calib_step']})" if state["auto_calib_active"] else "Inaktiv"
    
    return f"""<!DOCTYPE html><html><head><meta charset='utf-8'><title>PR2020 Control</title><meta http-equiv='refresh' content='4'>
    <style>body {{ font-family:Arial; margin:30px; background:#f4f4f4; }} .box {{ background:white; padding:15px; border-radius:5px; margin-bottom:15px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }}
    .btn {{ padding:8px 12px; margin:4px; background:#007bff; color:white; border:none; border-radius:4px; cursor:pointer; text-decoration:none; display:inline-block; font-weight:bold; }}
    .btn-stop {{ background:#dc3545; }} .btn-save {{ background:#28a745; }}</style></head><body>
    <div style="float:right;"><a class="btn btn-stop" href="/logout">Abmelden</a></div><h2>1 1/2" Ventilsteuerung Live-Daten</h2>
    <div class="box"><p>Zustand: <span style='{style}'>{msg}</span></p><p>Motor-Zustand: <b>{st_txt}</b></p>
    <p>Soll-Vorgabe: <b>{state['soll_oeffnung']}%</b> | Position: <b>{state['ist_oeffnung']}%</b></p>
    <p>Poti Live: <b>{state['poti_raw_live']}</b> (Spanne: {state['poti_min']} bis {state['poti_max']})</p><p>Temperatur: <b>{state['temperatur']}&deg;C</b></p></div>
    <h2>Vollautomatische Kalibrierung</h2><div class="box"><p>Status: <span style="color:orange; font-weight:bold;">{calib_status}</span></p>
    <a class="btn btn-save" style="background:#17a2b8;" href="/autocalib">Kalibrierung JETZT starten</a></div>
    <h2>Manueller Handlauf</h2><div class="box"><a class="btn" href="/motor?cmd=open">AUF fahren</a><a class="btn btn-stop" href="/motor?cmd=stop">STOPP</a><a class="btn" href="/motor?cmd=close">ZU fahren</a></div>
    <h2>Systemeinstellungen</h2><div class="box"><form action="/save" method="GET">
    <p>IP-Adresse: <input type="text" name="ip" value="{settings['ip']}" style="width:120px;"></p>
    <p>Watchdog (ms): <input type="text" name="wdt" value="{settings['watchdog_timeout_ms']}" style="width:80px;"></p>
    <p>Blockzeit (ms): <input type="text" name="blk" value="{settings['motor_block_ms']}" style="width:80px;"></p>
    <p>Neues Passwort: <input type="text" name="new_pwd" placeholder="Leer lassen = kein Wechsel" style="width:180px;"></p>
    <input type="submit" class="btn btn-save" value="Konfiguration speichern & uebernehmen"></form></div></body></html>"""

def web_server_loop():
    s = socket.socket()
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(('0.0.0.0', settings["web_port"]))
    s.listen(2)
    print(f"[Webserver] Server laeuft auf Port {settings['web_port']}")
    
    while True:
        try:
            c, a = s.accept()
            client_ip = a[0]
            req = c.recv(1024).decode('utf-8')
            if not req: 
                c.close(); continue
            
            current_password = load_password()
            
            if "GET /login" in req:
                try:
                    submitted_pwd = req.split("pwd=")[1].split(" ")[0]
                    if submitted_pwd == current_password:
                        if client_ip not in state["logged_in_users"]: state["logged_in_users"].append(client_ip)
                        c.send("HTTP/1.1 302 Found\r\nLocation: /\r\nSet-Cookie: auth=1; HttpOnly; Path=/\r\n\r\n".encode('utf-8'))
                    else:
                        c.send("HTTP/1.1 200 OK\r\nContent-Type: text/html\r\n\r\n".encode('utf-8'))
                        c.sendall(get_login_html("Falsches Passwort!").encode('utf-8'))
                except: pass
                c.close(); continue

            if "GET /logout" in req:
                if client_ip in state["logged_in_users"]: state["logged_in_users"].remove(client_ip)
                c.send("HTTP/1.1 302 Found\r\nLocation: /\r\nSet-Cookie: auth=0; Max-Age=0; Path=/\r\n\r\n".encode('utf-8'))
                c.close(); continue

            is_authenticated = (client_ip in state["logged_in_users"]) or ("Cookie: auth=1" in req)
            if not is_authenticated:
                c.send("HTTP/1.1 200 OK\r\nContent-Type: text/html\r\n\r\n".encode('utf-8'))
                c.sendall(get_login_html().encode('utf-8'))
                c.close(); continue

            # --- GESCHÜTZTER BEREICH ---
            if "GET /autocalib" in req:
                state["auto_calib_step"] = 1
                state["auto_calib_active"] = True
                c.send("HTTP/1.1 302 Found\r\nLocation: /\r\n\r\n".encode('utf-8'))
            
            elif "GET /motor" in req:
                # Statusübergabe an Regelschleife (keine Thread-Erzeugung mehr!)
                if "cmd=open" in req:
                    state["status_code"] = 1
                    state["soll_oeffnung"] = 100
                elif "cmd=close" in req:
                    state["status_code"] = 2
                    state["soll_oeffnung"] = 0
                elif "cmd=stop" in req:
                    state["status_code"] = 0
                    state["soll_oeffnung"] = state["ist_oeffnung"]
                c.send("HTTP/1.1 302 Found\r\nLocation: /\r\n\r\n".encode('utf-8'))
                
            elif "GET /save" in req:
                try:
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
                        c.send("HTTP/1.1 200 OK\r\n\r\nIP geandert. System startet neu...".encode('utf-8'))
                        c.close()
                        time.sleep(1)
                        machine.reset()
                except: pass
                c.send("HTTP/1.1 302 Found\r\nLocation: /\r\n\r\n".encode('utf-8'))
            else:
                c.send("HTTP/1.1 200 OK\r\nContent-Type: text/html\r\n\r\n".encode('utf-8'))
                c.sendall(get_html().encode('utf-8'))
            c.close()
        except: 
            time.sleep_ms(50)


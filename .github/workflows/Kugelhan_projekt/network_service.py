import socket
import time
import _thread
import machine
from config import settings, state

def handle_modbus_client(client_sock):
    try:
        client_sock.settimeout(2.0)
        while True:
            data = client_sock.recv(1024)
            if not data or len(data) < 12: break
                
            state["last_modbus_activity"] = time.ticks_ms()
            if state["watchdog_triggered"]:
                state["watchdog_triggered"] = False
                if state["fehler_code"] == 2: state["fehler_code"] = 0
            
            tx_id, proto_id = data[0:2], data[2:4]
            unit_id, func_code = data[6], data[7]
            reg_addr = (data[8] << 8) | data[9]
            
            if func_code == 3: # Read
                num_regs = (data[10] << 8) | data[11]
                pdu = bytearray([3, num_regs * 2])
                for i in range(num_regs):
                    curr = reg_addr + i
                    val = 0
                    if curr == 0: val = state["soll_oeffnung"]
                    elif curr == 1: val = state["ist_oeffnung"]
                    elif curr == 2: val = int(state["temperatur"] * 10)
                    elif curr == 3: val = state["status_code"]
                    elif curr == 4: val = state["fehler_code"]
                    pdu.append((val >> 8) & 0xFF); pdu.append(val & 0xFF)
            elif func_code == 6: # Write
                val = (data[10] << 8) | data[11]
                if reg_addr == 0 and 0 <= val <= 100: state["soll_oeffnung"] = val
                pdu = data[7:12]
            else:
                pdu = bytearray([func_code + 0x80, 0x01])
                
            header = bytearray([tx_id[0], tx_id[1], proto_id[0], proto_id[1], 0x00, len(pdu)+1, unit_id])
            client_sock.sendall(header + pdu)
    except: pass
    finally: client_sock.close()

def modbus_server_loop():
    s = socket.socket()
    s.bind(('0.0.0.0', settings["modbus_port"]))
    s.listen(2)
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
        time.sleep_ms(500)

def get_html():
    msg, style = "Alles i.O.", "color: green; font-weight: bold;"
    if state["fehler_code"] == 1: msg, style = "FEHLER: Poti defekt!", "color: red; font-weight: bold;"
    elif state["fehler_code"] == 2: msg, style = "FEHLER: Watchdog Timeout!", "color: red; font-weight: bold;"
    elif state["fehler_code"] == 3: msg, style = "FEHLER: Motor blockiert!", "color: red; font-weight: bold;"
    
    st_txt = ["Bereit", "Öffnet...", "Schließt..."][state["status_code"]]
    
    return f"""<!DOCTYPE html><html><head><meta charset='utf-8'><title>PR2020</title></head>
    <body style='font-family:Arial; margin:30px;'>
        <h2>Ventilsteuerung Live-Daten</h2>
        <p>Zustand: <span style='{style}'>{msg}</span> ({st_txt})</p>
        <p>Soll: {state['soll_oeffnung']}% | Ist: {state['ist_oeffnung']}% | Temp: {state['temperatur']}&deg;C</p>
        <hr>
        <h3>Konfiguration</h3>
        <form action='/save' method='GET'>
            IP: <input type='text' name='ip' value='{settings['ip']}'><br><br>
            Watchdog (ms): <input type='number' name='wdt' value='{settings['watchdog_timeout_ms']}'><br><br>
            <input type='submit' value='Speichern & Reset'>
        </form>
    </body></html>"""

def web_server_loop():
    s = socket.socket()
    s.bind(('0.0.0.0', settings["web_port"]))
    s.listen(2)
    while True:
        try:
            c, a = s.accept()
            req = c.recv(1024).decode('utf-8')
            if "GET /save" in req:
                # Schnelles Abspeichern der Parameter (vereinfacht)
                try:
                    params = req.split(" ")[1].split("?")[1].split("&")
                    for p in params:
                        k, v = p.split("=")
                        if k == "ip": settings["ip"] = v
                        elif k == "wdt": settings["watchdog_timeout_ms"] = int(v)
                    c.send("HTTP/1.1 200 OK\r\n\r\nGespeichert. Neustart...".encode('utf-8'))
                    c.close()
                    time.sleep(1)
                    machine.reset()
                except: pass
            c.send("HTTP/1.1 200 OK\r\nContent-Type: text/html\r\n\r\n".encode('utf-8'))
            c.sendall(get_html().encode('utf-8'))
            c.close()
        except: time.sleep_ms(100)

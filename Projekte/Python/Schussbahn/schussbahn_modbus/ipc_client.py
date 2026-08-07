# -*- coding: utf-8 -*-
import socket
import json

class IpcClient:
    def __init__(self, host="127.0.0.1", port=65432):
        self.host = host
        self.port = port
        self.connected = False

    def query_backend(self, relays_to_write):
        """Kommuniziert mit dem Modbus-Hintergrundprozess über Sockets."""
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(0.1)
                s.connect((self.host, self.port))
                
                payload = {"set_relays": relays_to_write}
                s.sendall(json.dumps(payload).encode('utf-8'))
                
                response = s.recv(1024).decode('utf-8')
                data = json.loads(response)
                
                self.connected = True
                return data.get("inputs", [False] * 8)
        except Exception:
            self.connected = False
            return [False] * 8

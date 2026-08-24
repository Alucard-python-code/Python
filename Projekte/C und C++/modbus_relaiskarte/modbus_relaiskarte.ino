#include <SPI.h>
#include <Ethernet.h>
#include <ModbusRTU_PICO.h>  

// HIER ANPASSEN: Name der Relaiskarte für die Login-Seite und das Dashboard
const String dashboardTitle = "Modbus Relaiskarte Bahn 1";

// 8 Eingänge GPIOs
const int inPins[]  = {0, 1, 2, 3, 4, 5, 6, 7}; 
// 8 Relais-Ausgänge 
const int outPins[] = {8, 9, 10, 11, 12, 13, 14, 15};

// Modbus Register-Konfiguration
const int REGS_IN_OFFSET  = 0;  
const int REGS_OUT_OFFSET = 0;  
const int HEARTBEAT_OFFSET = 8; 

// Netzwerkdaten
byte mac[] = { 0x02, 0xAD, 0xBE, 0xEF, 0x08, 0x65 };
IPAddress currentIP(192, 168, 8, 101);
IPAddress gateway(192, 168, 8, 1);
IPAddress subnet(255, 255, 255, 0);
unsigned int modbusPort = 502;

EthernetServer webServer(80);         
EthernetServer modbusServer(502);     
EthernetClient rtuClient;             

ModbusRTU mbRTUBridge;                
bool pendingNetUpdate = false;        
const String correctPassword = "1234";

// Watchdog / Heartbeat Variablen
unsigned long lastHeartbeatChange = 0; 
bool lastHeartbeatState = false;       
bool watchdogTriggered = false;        

// Struktur für das Logbuch (Letzte 5 Abbrüche basierend auf Systemsekunden)
struct LogEntry {
  unsigned long startSecond = 0;
  unsigned long endSecond = 0;
  unsigned long duration = 0;
  bool valid = false;
};
LogEntry disconnectLog[5]; // Array für die 5 Log-Einträge
int logIndex = 0;

// Variablen für die aktuell aktive Modbus-Verbindung
unsigned long connectionStartSecond = 0;
bool clientWasConnected = false;

// Globale Puffer für den aktuellen I/O-Status (Größe fest auf 8 Elemente definiert)
bool currentInStates[8];
bool currentOutStates[8];

// Variablen zur automatischen Erkennung des Kabelstatus
bool lastLinkStatus = true;
unsigned long lastLinkCheckTime = 0;

// Vorwärtsdeklarationen
void handleWebTraffic(EthernetClient &client, String request);
IPAddress parseIP(String ipStr);
void initModbusRTU();
void checkWatchdog();
void checkNetworkLink();
String formatToTime(unsigned long totalSeconds);

void setup() {
  Serial.begin(115200);

  for (int i = 0; i < 8; i++) {
    pinMode(inPins[i], INPUT_PULLUP);
    pinMode(outPins[i], OUTPUT);
    digitalWrite(outPins[i], LOW);
  }

  Ethernet.init(17); 
  Ethernet.begin(mac, currentIP, gateway, gateway, subnet);
  
  webServer.begin();
  initModbusRTU();

  lastHeartbeatChange = millis(); 
  lastLinkStatus = (Ethernet.linkStatus() == LinkON);
}

void initModbusRTU() {
  modbusServer.begin();
  mbRTUBridge.slave(1); 

  for (int i = 0; i < 8; i++) {
    mbRTUBridge.addIsts(REGS_IN_OFFSET + i);
    mbRTUBridge.addCoil(REGS_OUT_OFFSET + i);
  }
  mbRTUBridge.addCoil(HEARTBEAT_OFFSET);
}
String formatToTime(unsigned long totalSeconds) {
  unsigned long hours = totalSeconds / 3600;
  unsigned long minutes = (totalSeconds % 3600) / 60;
  unsigned long seconds = totalSeconds % 60;
  return String(hours) + "h " + String(minutes) + "m " + String(seconds) + "s";
}

void checkWatchdog() {
  bool currentHeartbeatState = mbRTUBridge.Coil(HEARTBEAT_OFFSET);
  
  if (currentHeartbeatState != lastHeartbeatState) {
    lastHeartbeatState = currentHeartbeatState;
    lastHeartbeatChange = millis(); 
    watchdogTriggered = false;      
  }

  if (millis() - lastHeartbeatChange >= 400) {
    if (!watchdogTriggered) {
      watchdogTriggered = true;
      Serial.println("Sicherheitsabschaltung! Verbindung verloren.");
      if (rtuClient) rtuClient.stop(); 
    }
    for (int i = 0; i < 8; i++) {
      mbRTUBridge.Coil(REGS_OUT_OFFSET + i, false);
    }
  }
}

void checkNetworkLink() {
  if (millis() - lastLinkCheckTime >= 500) { 
    lastLinkCheckTime = millis();
    bool currentLink = (Ethernet.linkStatus() == LinkON);
    
    if (!currentLink && lastLinkStatus) {
      if (rtuClient) rtuClient.stop(); 
      clientWasConnected = false;
      lastLinkStatus = false;
    } 
    else if (currentLink && !lastLinkStatus) {
      delay(50);
      Ethernet.begin(mac, currentIP, gateway, gateway, subnet);
      webServer.begin();
      modbusServer.begin();
      lastLinkStatus = true;
    }
  }
}

void loop() {
  checkNetworkLink(); 
  checkWatchdog(); 

  // I/O Status-Arrays aktualisieren und an Modbus übergeben
  for (int i = 0; i < 8; i++) {
    currentInStates[i] = (digitalRead(inPins[i]) == LOW);
    mbRTUBridge.Ists(REGS_IN_OFFSET + i, currentInStates[i]);
    currentOutStates[i] = mbRTUBridge.Coil(REGS_OUT_OFFSET + i);
    digitalWrite(outPins[i], currentOutStates[i] ? HIGH : LOW);
  }

  if (pendingNetUpdate) {
    delay(100); 
    Ethernet.begin(mac, currentIP, gateway, gateway, subnet);
    modbusServer = EthernetServer(modbusPort);
    modbusServer.begin();
    pendingNetUpdate = false;
  }

  unsigned long currentSecond = millis() / 1000;

  if (!rtuClient || !rtuClient.connected()) {
    if (clientWasConnected) {
      unsigned long duration = currentSecond - connectionStartSecond;
      if (duration >= 1) {
        disconnectLog[logIndex].startSecond = connectionStartSecond;
        disconnectLog[logIndex].endSecond = currentSecond;
        disconnectLog[logIndex].duration = duration;
        disconnectLog[logIndex].valid = true;
        logIndex = (logIndex + 1) % 5; 
      }
      clientWasConnected = false;
    }
    if (lastLinkStatus) {
      rtuClient = modbusServer.available();
      if (rtuClient) {
        mbRTUBridge.begin(&rtuClient);
        connectionStartSecond = currentSecond;
        clientWasConnected = true;
      }
    }
  }

  if (rtuClient && rtuClient.connected() && lastLinkStatus) {
    mbRTUBridge.task(); 
  }

  EthernetClient webClient = webServer.available();
  if (webClient && lastLinkStatus) {
    String requestString = "";
    boolean currentLineIsBlank = true;
    unsigned long webTimeout = millis();
    
    while (webClient.connected() && webClient.available() && (millis() - webTimeout < 50)) {
      char c = webClient.read();
      if (requestString.length() < 100) requestString += c;
      if (c == '\n' && currentLineIsBlank) {
        webClient.print("HTTP/1.1 200 OK\r\nContent-Type: text/html\r\nConnection: close\r\n\r\n");
        handleWebTraffic(webClient, requestString);
        break;
      }
      if (c == '\n') { currentLineIsBlank = true; } 
      else if (c != '\r') { currentLineIsBlank = false; }
    }
    delay(5); 
    webClient.stop();
  }
}
void handleWebTraffic(EthernetClient &client, String request) {
  if (request.indexOf("update_net") != -1) {
    int ipPos = request.indexOf("ip="), portPos = request.indexOf("&port=");
    int endPos = request.indexOf(" HTTP");
    if (ipPos != -1 && portPos != -1) {
      currentIP = parseIP(request.substring(ipPos + 3, portPos));
      modbusPort = request.substring(portPos + 6, endPos).toInt();
      pendingNetUpdate = true; 
    }
  }

  if (request.indexOf("pw=" + correctPassword) == -1) {
    client.println("<html><head><title>Login</title>");
    client.println("<style>body{font-family:Arial; background-color:#fafafa; display:flex; justify-content:center; align-items:center; height:100vh; margin:0;} ");
    client.println(".box{background:#fff; padding:40px; border-radius:10px; box-shadow:0 4px 15px rgba(0,0,0,0.08); text-align:center; min-width:320px;} ");
    client.println("h2{margin-top:0; color:#333; font-size:1.6em;} p{color:#666; margin-bottom:25px;} ");
    client.println("input[type='password']{width:100%; padding:10px; margin-bottom:20px; border:1px solid #ddd; border-radius:5px; box-sizing:border-box; font-size:1em;} ");
    client.println("input[type='submit']{width:100%; padding:11px; background-color:#007BFF; color:#fff; border:none; border-radius:5px; font-size:1em; font-weight:bold; cursor:pointer;} ");
    client.println("input[type='submit']:hover{background-color:#0056b3;}</style></head><body>");
    client.println("<div class='box'><h2>"); client.print(dashboardTitle); client.println("</h2><p>Bitte melden Sie sich an</p>");
    client.println("<form method='GET'>Passwort: <input type='password' name='pw'><br>");
    client.println("<input type='submit' value='Anmelden'></form></div></body></html>");
    return;
  }

  client.println("<html><head><title>Pico PoE Dashboard</title><meta http-equiv='refresh' content='5'>");
  client.println("<style>body{font-family:Arial;margin:20px;background:#fafafa;} table{width:50%;border-collapse:collapse;background:#fff;margin-bottom:20px;} th,td{padding:8px;text-align:left;border:1px solid #ddd;} th{background-color:#007BFF;color:#fff;} .w-ch{width:30%;} .w-io{width:30%;} .w-st{width:40%;} .banner{padding:15px; margin-bottom:20px; border-radius:5px; font-size:1.2em; font-weight:bold; width:50%; text-align:center; color:#fff;} .online{background:#28a745;} .offline{background:#dc3545;} .connecting{background:#ffc107; color:#212529;} .state-active{color:#fff; background:#dc3545; padding:3px 8px; border-radius:3px; font-weight:bold;} .state-inactive{color:#fff; background:#28a745; padding:3px 8px; border-radius:3px; font-weight:bold;}</style></head><body>");
  client.print("<h1>"); client.print(dashboardTitle); client.println("</h1>");
  
  if (!lastLinkStatus) {
    client.println("<div class='banner offline'>STATUS: NETZWERKKABEL GETRENNT</div>");
  } else if (watchdogTriggered) {
    client.println("<div class='banner offline'>STATUS: VERBINDUNG ABGEBROCHEN (SPS VERLOREN)</div>");
  } else if (rtuClient && rtuClient.connected()) {
    client.println("<div class='banner online'>STATUS: VERBINDUNG STEHT OK</div>");
  } else {
    client.println("<div class='banner connecting'>STATUS: WARTEN AUF VERBINDUNG / IM AUFBAU...</div>");
  }

  client.print("<p><b>Uptime:</b> "); client.print(formatToTime(millis() / 1000)); client.println(" | Modus: RTU-over-TCP</p>");
  
  client.println("<h3>Netzwerk</h3><form method='GET'><input type='hidden' name='pw' value='1234'>");
  client.print("IP: <input type='text' name='ip' value='"); client.print(currentIP); client.print("'> ");
  client.print("Port: <input type='text' name='port' size='5' value='"); client.print(modbusPort); client.print("'> ");
  client.println("<input type='submit' name='update_net' value='Uebernehmen'></form><br>");

  client.println("<h3>Letzte 5 Abbrueche</h3><table><tr><th>Nr.</th><th>Verbunden bei</th><th>Getrennt bei</th><th>Dauer</th></tr>");
  int displayCount = 1;
  for (int i = 0; i < 5; i++) {
    int checkIdx = (logIndex - 1 - i + 5) % 5;
    if (disconnectLog[checkIdx].valid) {
      client.print("<tr><td>"); client.print(displayCount++); client.print("</td>");
      client.print("<td>"); client.print(formatToTime(disconnectLog[checkIdx].startSecond)); client.print("</td>");
      client.print("<td>"); client.print(formatToTime(disconnectLog[checkIdx].endSecond)); client.print("</td>");
      client.print("<td><b>"); client.print(formatToTime(disconnectLog[checkIdx].duration)); client.println("</b></td></tr>");
    }
  }
  if (displayCount == 1) client.println("<tr><td colspan='4' style='text-align:center;'>Keine Eintraege</td></tr>");
  client.println("</table><br>");
  
  client.println("<h3>Eingaenge (Status)</h3><table><tr><th class='w-ch'>Kanal</th><th class='w-io'>GPIO</th><th class='w-st'>Status</th></tr>");
  for (int i = 0; i < 8; i++) {
    client.print("<tr><td>Eingang "); client.print(i + 1); client.print("</td><td>GPIO "); client.print(inPins[i]); client.print("</td><td>");
    if (currentInStates[i]) {
      client.print("<span class='state-active'>AKTIV</span>"); 
    } else {
      client.print("<span class='state-inactive'>INAKTIV</span>"); 
    }
    client.println("</td></tr>");
  }
  client.println("</table><br>");

  client.println("<h3>Ausgaenge (Relais)</h3><table><tr><th class='w-ch'>Kanal</th><th class='w-io'>GPIO</th><th class='w-st'>Status</th></tr>");
  for (int i = 0; i < 8; i++) {
    client.print("<tr><td>Relais "); client.print(i + 1); client.print("</td><td>GPIO "); client.print(outPins[i]); client.print("</td><td>");
    if (currentOutStates[i]) {
      client.print("<span class='state-active'>AKTIV</span>"); 
    } else {
      client.print("<span class='state-inactive'>INAKTIV</span>"); 
    }
    client.println("</td></tr>");
  }
  client.println("</table></body></html>");
}

IPAddress parseIP(String ipStr) {
  uint8_t p1 = 0, p2 = 0, p3 = 0, p4 = 0;
  int idx = 0; 
  String current = "";

  for (unsigned int i = 0; i < ipStr.length(); i++) {
    if (ipStr[i] == '.' || ipStr[i] == '%') {
      if (idx == 0) p1 = current.toInt();
      else if (idx == 1) p2 = current.toInt();
      else if (idx == 2) p3 = current.toInt();
      
      idx++; 
      current = ""; 
      
      if (ipStr[i] == '%') {
        i += 2;
      }
    } else { 
      current += ipStr[i]; 
    }
  }

  if (idx == 3) {
    p4 = current.toInt();
  }

  return IPAddress(p1, p2, p3, p4);
}

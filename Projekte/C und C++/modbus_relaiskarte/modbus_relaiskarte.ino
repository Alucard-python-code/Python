#include <SPI.h>
#include <Ethernet.h>
#include <ModbusEthernet.h>  // Modbus-pico TCP Engine
#include <ModbusRTU_PICO.h>  // Modbus-pico RTU Engine

// 8 Eingänge GPIOs: 0, 1, 2, 3, 4, 5, 6, 7)
const int inPins[]  = {0, 1, 2, 3, 4, 5, 6, 7}; 

// 8 Relais-Ausgänge (Physische Pins: 34, 32, 31, 29, 27, 26, 11, 12)
const int outPins[] = {8, 9, 10, 11, 12, 13, 14, 15};

// Modbus Register-Konfiguration (Start bei Register 0)
const int REGS_IN_OFFSET  = 0;  // Discrete Inputs (10001)
const int REGS_OUT_OFFSET = 0;  // Coils (00001)

// Ihre gewünschten Netzwerkdaten im 20er-Bereich
byte mac[] = { 0x02, 0xAD, 0xBE, 0xEF, 0x08, 0x68 };
IPAddress currentIP(192, 168, 8, 104);
IPAddress gateway(192, 168, 8, 1);
IPAddress subnet(255, 255, 255, 0);
unsigned int modbusPort = 502;

EthernetServer webServer(80);         // Webserver auf Port 80
EthernetServer modbusServer(502);     // TCP-Server für Modbus

// Dynamische Pointer statt globaler Objekte, um Mbed-Startkonflikte zu verhindern
ModbusEthernet* mbTCP = nullptr;
ModbusRTU* mbRTUBridge = nullptr;
EthernetClient modbusClient;          // Netzwerk-Client für Modbus

bool useModbusTCPStandard = true;    // true = Standard Modbus TCP, false = RTU-over-TCP
const String correctPassword = "1234";

// Vorwärtsdeklarationen
void handleWebTraffic(EthernetClient &client, String request);
IPAddress parseIP(String ipStr);

void setup() {
  Serial.begin(115200);

  // Initialisierung der Relais und Taster-Eingänge
  for (int i = 0; i < 8; i++) {
    pinMode(inPins[i], INPUT_PULLUP);
    pinMode(outPins[i], OUTPUT);
    digitalWrite(outPins[i], LOW); // Alle Relais standardmäßig AUS
  }

  // W5500-EVB-Pico CS-Pin Zuweisung für den Mbed-Core initialisieren
  Ethernet.init(17); 

  // W5500 Ethernet Hardware-Start (Identisch zum funktionierenden Netzwerktest)
  Ethernet.begin(mac, currentIP, gateway, gateway, subnet);
  webServer.begin();
  modbusServer.begin();

  // Nach dem erfolgreichen Ethernet-Start die Modbus-Klassen erzeugen
  mbTCP = new ModbusEthernet();
  mbTCP->server(modbusPort);
  for (int i = 0; i < 8; i++) {
    mbTCP->addIsts(REGS_IN_OFFSET + i);
    mbTCP->addCoil(REGS_OUT_OFFSET + i);
  }

  mbRTUBridge = new ModbusRTU();
  mbRTUBridge->slave(1); // Modbus Slave-ID 1
  for (int i = 0; i < 8; i++) {
    mbRTUBridge->addIsts(REGS_IN_OFFSET + i);
    mbRTUBridge->addCoil(REGS_OUT_OFFSET + i);
  }
}

void loop() {
  // Sicherheitsabfrage: Falls die Pointer noch nicht bereit sind, Loop abbrechen
  if (mbTCP == nullptr || mbRTUBridge == nullptr) return;

  // 1. Protokoll-Verarbeitung je nach Auswahl in der Web-UI
  if (useModbusTCPStandard) {
    mbTCP->task();
  } else {
    if (!modbusClient || !modbusClient.connected()) {
      modbusClient = modbusServer.available();
      if (modbusClient) {
        mbRTUBridge->begin(&modbusClient); 
      }
    }
    if (modbusClient && modbusClient.connected()) {
      mbRTUBridge->task();
    }
  }

  // 2. Synchronisation der I/Os mit beiden Modbus-Engines
  for (int i = 0; i < 8; i++) {
    bool inState = (digitalRead(inPins[i]) == LOW);
    mbTCP->Ists(REGS_IN_OFFSET + i, inState);
    mbRTUBridge->Ists(REGS_IN_OFFSET + i, inState);

    // Zustand aus der aktuell aktiven Engine auslesen
    bool outState = useModbusTCPStandard ? mbTCP->Coil(REGS_OUT_OFFSET + i) : mbRTUBridge->Coil(REGS_OUT_OFFSET + i);
    digitalWrite(outPins[i], outState ? HIGH : LOW);

    // Die jeweils inaktive Engine spiegeln, um Umschalt-Sprünge zu verhindern
    if (useModbusTCPStandard) {
      mbRTUBridge->Coil(REGS_OUT_OFFSET + i, outState);
    } else {
      mbTCP->Coil(REGS_OUT_OFFSET + i, outState);
    }
  }

  // 3. Eingehende HTTP Webserver Anfragen abfangen
  EthernetClient client = webServer.available();
  if (client) {
    boolean currentLineIsBlank = true;
    String requestString = "";
    
    while (client.connected()) {
      if (client.available()) {
        char c = client.read();
        if (requestString.length() < 250) {
          requestString += c; 
        }
        if (c == '\n' && currentLineIsBlank) {
          client.println("HTTP/1.1 200 OK");
          client.println("Content-Type: text/html");
          client.println("Connection: close");
          client.println();
          
          handleWebTraffic(client, requestString);
          break;
        }
        if (c == '\n') { currentLineIsBlank = true; }
        else if (c != '\r') { currentLineIsBlank = false; }
      }
    }
    delay(1);
    client.stop();
  }
}

// Funktion zum sauberen Zerlegen des IP-Strings aus dem Web-Formular
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
      if (ipStr[i] == '%') i += 2; 
    } else { 
      current += ipStr[i]; 
    }
  }
  if (idx == 3) p4 = current.toInt();
  
  return IPAddress(p1, p2, p3, p4);
}

void handleWebTraffic(EthernetClient &client, String request) {
  if (request.indexOf("setmode=tcp") != -1) { useModbusTCPStandard = true; }
  if (request.indexOf("setmode=rtu_tcp") != -1) { useModbusTCPStandard = false; }
  
  if (request.indexOf("update_net=") != -1) {
    int ipPos = request.indexOf("ip=");
    int portPos = request.indexOf("&port=");
    int endPos = request.indexOf(" HTTP");
    if (ipPos != -1 && portPos != -1) {
      String ipStr = request.substring(ipPos + 3, portPos);
      String portStr = request.substring(portPos + 6, endPos);
      
      currentIP = parseIP(ipStr);
      modbusPort = portStr.toInt();
      
      Ethernet.begin(mac, currentIP, gateway, gateway, subnet);
      if (mbTCP != nullptr) mbTCP->server(modbusPort);
      modbusServer = EthernetServer(modbusPort);
      modbusServer.begin();
    }
  }

  if (request.indexOf("pw=" + correctPassword) == -1) {
    client.println("<html><head><style>body{font-family:Arial;text-align:center;margin-top:100px;background:#f4f4f4;} .box{display:inline-block;padding:30px;background:#fff;border-radius:8px;box-shadow:0 2px 4px rgba(0,0,0,0.1);}</style></head><body>");
    client.println("<div class='box'><h2>W5500 Modbus Gateway - Login</h2>");
    client.println("<form method='GET'>Passwort: <input type='password' name='pw'><br><br>");
    client.println("<input type='submit' value='Anmelden'></form></div></body></html>");
    return;
  }

  client.println("<html><head><title>Pico PoE Dashboard</title>");
  client.println("<style>body{font-family:Arial;margin:20px;background:#fafafa;} table{width:50%;border-collapse:collapse;background:#fff;margin-bottom:20px;} th,td{padding:8px;text-align:left;border:1px solid #ddd;} th{background-color:#007BFF;color:#fff;} .btn{padding:6px 12px;text-decoration:none;color:#fff;background:#28a745;border-radius:4px;}</style></head><body>");
  
  client.println("<h1>System-Uebersicht & Konfiguration</h1>");
  client.print("<p><b>Aktueller Modbus-Protokollmodus:</b> ");
  client.println(useModbusTCPStandard ? "<span style='color:green;font-weight:bold;'>Standard Modbus TCP</span>" : "<span style='color:orange;font-weight:bold;'>Modbus RTU-over-TCP</span>");
  client.println("</p><p>Modus umschalten: ");
  client.print("<a class='btn' href='?pw=1234&setmode=tcp'>Standard Modbus TCP</a> ");
  client.print("<a class='btn' style='background:#6c757d;' href='?pw=1234&setmode=rtu_tcp'>Modbus RTU-over-TCP</a></p><br>");

  client.println("<h3>Netzwerk-Einstellungen</h3><form method='GET'><input type='hidden' name='pw' value='1234'>");
  client.print("IP-Adresse: <input type='text' name='ip' value='"); client.print(currentIP); client.print("'> ");
  client.print("Modbus Port: <input type='text' name='port' size='5' value='"); client.print(modbusPort); client.print("'> ");
  client.println("<input type='submit' name='update_net' value='Uebernehmen'></form><br>");

  // Tabelle Eingänge
  const int physicalInputs[] = {1, 2, 4, 5, 6, 7, 9, 10};
  client.println("<h3>Eingaenge (Status)</h3><table><tr><th>Kanal</th><th>Physischer Pin</th><th>Status</th></tr>");
  for (int i = 0; i < 8; i++) {
    client.print("<tr><td>Eingang "); client.print(i + 1); client.print("</td><td>Pin "); client.print(physicalInputs[i]);
    client.print("</td><td>"); 
    client.print((digitalRead(inPins[i]) == LOW) ? "<b style='color:green;'>AKTIV (An)</b>" : "<span style='color:gray;'>Inaktiv (Aus)</span>");
    client.println("</td></tr>");
  }
  client.println("</table><br>");

  // Tabelle Ausgänge / Relais
  const int physicalOutputs[] = {34, 32, 31, 29, 27, 26, 11, 12};
  client.println("<h3>Ausgaenge (Relais)</h3><table><tr><th>Kanal</th><th>Physischer Pin</th><th>Status</th></tr>");
  for (int i = 0; i < 8; i++) {
    bool state = useModbusTCPStandard ? mbTCP->Coil(REGS_OUT_OFFSET + i) : mbRTUBridge->Coil(REGS_OUT_OFFSET + i);
    client.print("<tr><td>Relais "); client.print(i + 1); client.print("</td><td>Pin "); client.print(physicalOutputs[i]);
    client.print("</td><td>"); 
    client.print(state ? "<b style='color:green;'>RELAIS AN</b>" : "<span style='color:gray;'>Aus</span>");
    client.println("</td></tr>");
  }
  client.println("</table></body></html>");
}

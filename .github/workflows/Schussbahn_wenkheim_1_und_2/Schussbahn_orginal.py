#!/usr/bin/python
# Importe der Module 
import sys
from PyQt5.QtWidgets import QApplication, QWidget, QLabel, QPushButton
from PyQt5.QtGui import QFont
from PyQt5 import QtCore
import time
import socket
import pycrc


# Initalisierung des Fensters
class Fenster(QWidget):
    def __init__(self):
        super().__init__()
        self.socket = socket.socket()        
        self.cmd = [0, 0, 0, 0, 0, 0, 0, 0]
        self.host = '192.168.8.204'        # set ip
        self.port = 4196                 # Set port
        self.socket.connect((self.host, self.port))
        self.start()
        self.initMe()


# Definition / Erstelung des Fensters
    def initMe(self):

        # Definition der verwendeten Variablen
        # Timer Variablen fuer Fahrzeiten in sek.
        self.time_rechtslauf_schnell = 7
        self.time_rechtslauf_langsam = 2.5
        self.time_linkslauf_schnell = 6.5
        self.time_Anschlag = 0.4
              
        # Pusen Zeiten
        self.time_Bremse = 0.2
        self.time_Umschaltpause = 0.05
        
        # Speicher Variablen
        self.variable_relais_kanal = 0
        self.output = 0x00
        self.input = 0x00
        
        #Logik Variablen Eingaenge
        self.input_int = 0
        self.input_bin = []
        self.relais_rechtlauf = 0
        self.relais_langsam = 0
        self.relais_schnell = 0
        self.relais_linkslauf = 0
        self.motorschutz = 0
        self.endschalter = 0
        self.res_1 = 0
        self.res_2 = 0
        
        #Logik Variablen Ausgaenge
        self.output_int = 0
        self.output_bin = []
        self.schuetz_links = 0
        self.schuetz_rechts = 0
        self.schuetz_langsam = 0
        self.schuetz_schnell = 0
        self.schütz_res_1 = 0
        self.schütz_res_2 = 0
        self.schütz_res_3 = 0
        self.schütz_licht = 0

        # Start Merker
        self.Start_up = 0

        # Definition der verwendeten Widgets
        # Button fuer Rechtslauf
        schuss = QPushButton('Schuss', self)
        schuss.setFont(QFont('Arial', 60))
        schuss.move(50, 20)
        schuss.resize(400, 400)
        schuss.clicked.connect(self.scheibe_vorwearts)

        # Button fuer Linkslauf
        wertung = QPushButton('Wertung', self)
        wertung.setFont(QFont('Arial', 60))
        wertung.move(50, 470)
        wertung.resize(400, 400)
        wertung.clicked.connect(self.scheibe_rueckwearts)

        # Button fuer Licht an
        licht_an = QPushButton('Licht an', self)
        licht_an.setFont(QFont('Arial', 60))
        licht_an.move(750, 20)
        licht_an.resize(400, 400)
        licht_an.clicked.connect(self.lichtan)

        # Button fuer Licht aus
        licht_aus = QPushButton('Licht aus', self)
        licht_aus.setFont(QFont('Arial', 60))
        licht_aus.move(750, 470)
        licht_aus.resize(400, 400)
        licht_aus.clicked.connect(self.lichtaus)

        # Button zum anzeigen der I/O`s im Terminal
        I_O_test = QPushButton('Test_I/O', self)
        I_O_test.setFont(QFont('Arial', 60))
        I_O_test.move(1465, 20)
        I_O_test.resize(400, 400)
        I_O_test.clicked.connect(self.test)

        # Label zum anzeigen von Fehlern
        error = QLabel(self)
        error.setFont(QFont('Arial', 60))
        error.move(310, 900)
        error.setText(self.Status())

        error_anzeige = QLabel(self, text='Status:')
        error_anzeige.setFont(QFont('Arial', 60))
        error_anzeige.move(50, 900)

        # Button zum schliesen des Programms
        exit = QPushButton('Exit', self)
        exit.setFont(QFont('Arial', 60))
        exit.move(1465, 470)
        exit.resize(400, 400)
        exit.clicked.connect(QtCore.QCoreApplication.instance().quit)

        # Methode zum anzeigen des Fensters (Maximiert)
        self.showMaximized()

# Methoden Definitionen

    def relais_an(self):
        self.cmd[0] = 0x01   # Device address
        self.cmd[1] = 0x05   # command
        self.cmd[2] = 0      # freies bit 
        self.cmd[3] = self.variable_relais_kanal      # Relais nummer 0x00 - 0x07
        self.cmd[4] = 0xFF   # Relais an
        self.cmd[5] = 0      # freies bit 
        crc = pycrc.ModbusCRC(self.cmd[0:6])
        self.cmd[6] = crc & 0xFF
        self.cmd[7] = crc >> 8
        self.socket.send(bytearray(self.cmd))
        time.sleep(0.2)
        self.output = self.socket.recv(1024)
        
        self.output_bin = bin(int(hex(self.output[3]), 16))[2:].zfill(8)     # Umwandlung in bin
        
        # Aufteilung der bin und Einzelsignale
        self.schuetz_links = self.output_bin[7]
        self.schuetz_rechts = self.output_bin[6]
        self.schuetz_langsam = self.output_bin[5]
        self.schuetz_schnell = self.output_bin[4]
        self.schütz_res_1 = self.output_bin[3]
        self.schütz_res_2 = self.output_bin[2]
        self.schütz_res_3 = self.output_bin[1]
        self.schütz_licht = self.output_bin[0]

    def relais_aus(self):
        self.cmd[0] = 0x01   # Device address
        self.cmd[1] = 0x05   # command
        self.cmd[2] = 0      # freies bit 
        self.cmd[3] = self.variable_relais_kanal      # Relais nummer 0x00 - 0x07
        self.cmd[4] = 0      # Relais aus
        self.cmd[5] = 0      # freies bit 
        crc = pycrc.ModbusCRC(self.cmd[0:6])
        self.cmd[6] = crc & 0xFF
        self.cmd[7] = crc >> 8
        self.socket.send(bytearray(self.cmd))
        time.sleep(0.2)
        self.output = self.socket.recv(1024)

        self.output_bin = bin(int(hex(self.output[3]), 16))[2:].zfill(8)      # Umwandlung in Bits        
        
        self.schuetz_links = self.output_bin[7]
        self.schuetz_rechts = self.output_bin[6]
        self.schuetz_langsam = self.output_bin[5]
        self.schuetz_schnell = self.output_bin[4]
        self.schütz_res_1 = self.output_bin[3]
        self.schütz_res_2 = self.output_bin[2]
        self.schütz_res_3 = self.output_bin[1]
        self.schütz_licht = self.output_bin[0]

    def eingaegne_lesen(self):
        self.cmd[0] = 0x01  #Device address
        self.cmd[1] = 0x02  #command
        self.cmd[2] = 0
        self.cmd[3] = 0
        self.cmd[4] = 0
        self.cmd[5] = 8
        crc = pycrc.ModbusCRC(self.cmd[0:6])
        self.cmd[6] = crc & 0xFF
        self.cmd[7] = crc >> 8
        self.socket.send(bytearray(self.cmd))
        time.sleep(0.2)
        self.input = self.socket.recv(1024)
        
        self.input_bin = bin(int(hex(self.output[3]), 16))[2:].zfill(8)

        self.motorschutz = self.input_bin[7]
        self.endschalter = self.input_bin[6]
        self.relais_linkslauf = self.input_bin[5]
        self.relais_rechtlauf = self.input_bin[4]
        self.relais__langsam = self.input_bin[3]
        self.relais_schnfell = self.input_bin[2]
        self.res_1 = self.input_bin[1]
        self.res_2 = self.input_bin[0]

    # Methode fuer Linkslauf
    def scheibe_rueckwearts(self):
        self.eingaegne_lesen()       
        # Die ueberpruefung ob der Kartenhalter
        # hinten ist bei Spannungswiederkehr ?
        # Wenn nicht fuehre diese Schleife aus (bis Endschalter betaetigt)
        # Bedingung der Schleife -> Merker = 0 und Endschalter = 0
        while self.Start_up == 0 and  self.endschalter == 1:
            self.eingaegne_lesen()
            self.Status()               # Ueberpruefung auf Fehler
            self.variable_relais_kanal = 0x00        # Einschalten der Schuetz (Linkslauf)
            self.relais_an()
            time.sleep(self.time_Bremse)
            self.variable_relais_kanal = 0x02        # Einschalten der Schuetz (Langsam)
            self.relais_an()
        else:							  # Wenn der Endschalter erreicht wurde
            time.sleep(self.time_Anschlag)
            self.variable_relais_kanal = 0x02         # Ausschalten der Schuetz (Langsam)
            self.relais_aus()
            time.sleep(self.time_Bremse)
            self.variable_relais_kanal = 0x00         # Ausschalten der Schuetz (Linkslauf)
            self.relais_aus()
            self.Start_up = +1            # Setzen des Merkers auf 1
            self.Status()               # erneute Ueberpruefung auf Fehler

        # Kartenhalter war auf Startposition und ist auf Beschussposition
        if self.Start_up == 1 and self.endschalter == 1:
            self.Status()
            self.variable_relais_kanal = 0x00		  # Schuetz Einschalten (Linkslauf)
            self.relais_an()
            time.sleep(self.time_Bremse)
            self.variable_relais_kanal = 0x03         # Schuetz Einschalten (Schnell)
            self.relais_an()
            time.sleep(self.time_linkslauf_schnell)
            while self.endschalter == 0:
                self.eingaegne_lesen()
                self.variable_relais_kanal = 0x03      # Schuetz Ausschalten (Schnell)
                self.relais_aus()
                time.sleep(self.time_Umschaltpause)
                self.variable_relais_kanal = 0x02    # Einschalten Schuetz (Langsam)
                self.relais_an()
            else:
                time.sleep(self.time_Anschlag)
                self.variable_relais_kanal = 0x02     # Ausschalten Schuetz (Langsam)
                self.relais_aus()
                time.sleep(self.time_Bremse)
                self.variable_relais_kanal = 0x00     # Ausschalten Schuetz (Linkslauf)
                self.relais_aus()
                self.Status()

    # Methode fuer Rechtslauf
    def scheibe_vorwearts(self):
        self.eingaegne_lesen()
        self.Status()                      # wenn Zaehler = 0 dann ->
        if self.endschalter == 0 and self.Start_up == 0:
            self.Start_up == +1              # Zaehler +1
            self.variable_relais_kanal = 0x01           # Schuetz Einschalten (Rechtslauf)
            self.relais_an()
            time.sleep(self.time_Bremse)
            self.variable_relais_kanal = 0x03            # Schuetz Einschalten (Schnell)
            self.relais_an()
            time.sleep(self.time_rechtslauf_schnell)
            self.variable_relais_kanal = 0x03             # Schuetz Ausschalten (Schnell)
            self.relais_aus()
            self.variable_relais_kanal = 0x02           # Einschalten Schuetz (Langsam)
            self.relais_an()
            time.sleep(self.time_rechtslauf_langsam)
            self.variable_relais_kanal = 0x02            # Ausschalten Schuetz (Langsam)
            self.relais_aus()
            time.sleep(self.time_Bremse)
            self.variable_relais_kanal = 0x01            # Schuetz Ausschalten (Rechtslauf)
            self.relais_aus()
            self.Status()
        
        else:
            self.variable_relais_kanal = 0x01           # Schuetz Einschalten (Rechtslauf)
            self.relais_an()
            self.test()
            time.sleep(self.time_Bremse)
            self.variable_relais_kanal = 0x03            # Schuetz Einschalten (Schnell)
            self.relais_an()
            self.test()
            time.sleep(self.time_rechtslauf_schnell)
            self.variable_relais_kanal = 0x03             # Schuetz Ausschalten (Schnell)
            self.relais_aus()
            self.variable_relais_kanal = 0x02           # Einschalten Schuetz (Langsam)
            self.relais_an()
            self.test()
            time.sleep(self.time_rechtslauf_langsam)
            self.variable_relais_kanal = 0x02            # Ausschalten Schuetz (Langsam)
            self.relais_aus()
            self.test()
            time.sleep(self.time_Bremse)
            self.variable_relais_kanal = 0x01            # Schuetz Ausschalten (Rechtslauf)
            self.relais_aus()
            self.test()
            self.Status()

    # Methode fuer Licht an
    def lichtan(self):
        self.variable_relais_kanal = 0x07            # Licht an
        self.relais_an()

    # Methode fuer Licht aus
    def lichtaus(self):
        self.variable_relais_kanal = 0x07            # Licht aus
        self.relais_aus()

    # Methode zur Feststellung von Fehlern
    def Status(self):

        # Bedingung -> Eingang Motorschutz = 0
        if self.motorschutz == 0:
            self.stop()
            fehler = 'Motorschutz ausgeloest'
            return fehler

        # Bedingung -> Schuetze = 1
        elif self.output[3] == 0x00 and self.relais_rechtlauf == 1 or self.relais_linkslauf == 1 or self.relais_langsam == 1 or self.relais_schnell == 1:
            self.stop()
            fehler = 'Ein Schuetz klebt'
            return fehler

        # Bedingung -> Endschalter = 0 und Schuetze = 0
        elif self.endschalter == 0 and self.relais_rechtlauf == 0 and self.relais_linkslauf == 0 and self.relais_langsam == 0 and self.relais_schnell == 0:
            fehler = 'Auswertung'
            return fehler

        # Bedingung -> Endschalter = 1 und Schuetze = 0
        elif self.endschalter == 1 and self.relais_rechtlauf == 0 and self.relais_linkslauf == 0 and self.relais_langsam == 0 and self.relais_schnell == 0:
            fehler = 'Feuer frei'
            return fehler

        # Bedingung -> Endschalter = 1 und Schuetze rechts oder links = 1 und Schuetz schnell oder langsam = 1
        elif self.endschalter == 1 and self.relais_rechtlauf == 1 or self.relais_linkslauf == 1 and self.relais_langsam == 1 or self.relais_schnell == 1:
            fehler = 'Unterwegs'
            return fehler
        
        # Bedingung -> Schuetz schnell und langsam = 1
        elif self.relais_langsam == 1 and self.relais_schnell == 1:
            fehler = 'Fehler Schnell / Langsam'
            return fehler
        
        # Bedinung -> Schuetze rechts und links = 1
        elif self.relais_linkslauf == 1 and self.relais_rechtlauf == 1:
            fehler = 'Fehler Rechts- / Linkslauf'
            return fehler
        
        # Bedingung -> treffen die Bedingungen von
        # weiter oben nicht zu => Fehlerfrei
        else:
            fehler = 'Unbekanter Fehler'
            return fehler

    # Im Fehlerfall alle Motorschuetze abschalten
    def stop(self):
        self.variable_relais_kanal = 0xFF
        self.relais_aus()
        self.Start_up = 0

    # Bei Start alles Abschalten um ungewollte Bewegungen zu verhindern
    def start(self):
        self.variable_relais_kanal = 0xFF
        self.relais_aus()

    # Ausgabe aller Parameter zur ueberpruefung im Terminal
    def test(self):
        print("_________________")
        print("Eingänge")
        print("Endschalter: " + str(self.endschalter))
        print("Motorschutz: " + str(self.motorschutz))
        print("Rückmel. RL: " + str(self.relais_rechtlauf))
        print("Rückmel. LL: " + str(self.relais_linkslauf))
        print("Rückmel. Langsam: " + str(self.relais_langsam))
        print("Rückmel. Schnell: " + str(self.relais_schnell))
        print("_________________")
        print("Ausgänge")
        print("Linkslauf: " + str(self.schuetz_links))
        print("Rechtslauf: " + str(self.schuetz_rechts))
        print("Langsam: " + str(self.schuetz_langsam))
        print("Schnell: " + str(self.schuetz_schnell))
        print("_________________")




# Abschluss des Programmes / Fensters
app = QApplication(sys.argv)
F = Fenster()
sys.exit(app.exec_())

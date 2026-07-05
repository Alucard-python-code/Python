#!/usr/bin/python
# Importe der Module 
import sys
from PyQt5.QtWidgets import QApplication, QWidget, QLabel, QPushButton
from PyQt5.QtGui import QFont
from PyQt5 import QtCore
import RPi.GPIO as GPIO
import time

# Festlegung der Pinnummerirung der GPIO`s
GPIO.setmode(GPIO.BCM)

# Festlegung der Ausgaenge
# Schuetz_Schnell
GPIO.setup(6, GPIO.OUT)

# Schuetz_Langsam
GPIO.setup(13, GPIO.OUT)

# Schuetz_Rueckwaerts
GPIO.setup(19, GPIO.OUT)

# Schuetz_Vorearts
GPIO.setup(26, GPIO.OUT)

# Schuetz_Licht
GPIO.setup(23, GPIO.OUT)

# Festlegung der Eingaenge
# Endschalter
GPIO.setup(10, GPIO.IN)

# Schuetz_Scnell
GPIO.setup(12, GPIO.IN)

# Schuetz_Langsam
GPIO.setup(16, GPIO.IN)

# Schuetz_Motorschutz
GPIO.setup(18, GPIO.IN)

# Schuetz_Rueckwaerts
GPIO.setup(20, GPIO.IN)

# Schuetz_Vorwaerts
GPIO.setup(21, GPIO.IN)


# Initalisierung des Fensters
class Fenster(QWidget):
    def __init__(self):
        super().__init__()
        self.start()
        self.initMe()

# Definition / Erstelung des Fensters
    def initMe(self):

        # Definition der verwendeten Variablen
        # Timer fuer Fahrzeiten in sek.
        self.time_rechtslauf_schnell = 7
        self.time_rechtslauf_langsam = 2.5
        self.time_linkslauf_schnell = 6.5
        self.time_Bremse = 0.2
        self.time_Anschlag = 0.4
        self.time_Umschaltpause = 0.05

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
        error.setText(self.Stoerung())

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

    # Methode fuer Linkslauf
    def scheibe_rueckwearts(self):

        # Die ueberpruefung ob der Kartenhalter hinten
        # ist bei Spannungswiederkehr ?
        # Wenn nicht fuehre diese Schleife aus (bis Endschalter betaetigt)
        # Bedingung der Schleife -> Merker = 0 und Endschalter = 0
        while self.Start_up == 0 and GPIO.input(10) == 0:
            self.Stoerung()  # Ueberpruefung auf Fehler
            GPIO.output(19, False)  # Einschalten der Schuetz (Linkslauf)
            time.sleep(self.time_Bremse)
            GPIO.output(13, False)  # Einschalten der Schuetz (Langsam)
        else:			            # Wenn der Endschalter erreicht wurde
            time.sleep(self.time_Anschlag)
            GPIO.output(13, True)   # Ausschalten der Schuetz (Langsam)
            time.sleep(self.time_Bremse)
            GPIO.output(19, True)   # Ausschalten der Schuetz (Linkslauf)
            self.Start_up = +1      # Setzen des Merkers auf 1
            self.Stoerung()         # erneute Ueberpruefung auf Fehler

        # Kartenhalter war auf Startposition und ist auf Beschussposition
        if self.Start_up == 1 and GPIO.input(10) == 0:
            self.Stoerung()
            GPIO.output(19, False)  # Schuetz Einschalten (Linkslauf)
            time.sleep(self.time_Bremse)
            GPIO.output(6, False)  # Schuetz Einschalten (Schnell)
            time.sleep(self.time_linkslauf_schnell)
            while GPIO.input(10) == 0:
                GPIO.output(6, True)  # Schuetz Ausschalten (Schnell)
                time.sleep(self.time_Umschaltpause)
                GPIO.output(13, False)  # Einschalten Schuetz (Langsam)
            else:
                time.sleep(self.time_Anschlag)
                GPIO.output(13, True)  # Ausschalten Schuetz (Langsam)
                time.sleep(self.time_Bremse)
                GPIO.output(19, True)  # Ausschalten Schuetz (Linkslauf)
                self.Stoerung()

    # Methode fuer Rechtslauf
    def scheibe_vorwearts(self):
        self.Stoerung()                     # wenn Zaehler = 0 dann ->
        if GPIO.input(10) == 1 and self.Start_up == 0:
            self.Start_up == +1             # Zaehler +1
            GPIO.output(26, False)          # Schuetz Einschalten (Rechtslauf)
            time.sleep(self.time_Bremse)
            GPIO.output(6, False)           # Schuetz Einschalten (Schnell)
            time.sleep(self.time_rechtslauf_schnell)
            GPIO.output(6, True)            # Schuetz Ausschalten (Schnell)
            GPIO.output(13, False)          # Einschalten Schuetz (Langsam)
            time.sleep(self.time_rechtslauf_langsam)
            GPIO.output(13, True)           # Ausschalten Schuetz (Langsam)
            time.sleep(self.time_Bremse)
            GPIO.output(26, True)           # Schuetz Ausschalten (Rechtslauf)
            self.Stoerung()
        else:
            GPIO.output(26, False)          # Schuetz Einschalten (Rechtslauf)
            time.sleep(self.time_Bremse)
            GPIO.output(6, False)           # Schuetz Einschalten (Schnell)
            time.sleep(self.time_rechtslauf_schnell)
            GPIO.output(6, True)            # Schuetz Ausschalten (Schnell)
            GPIO.output(13, False)          # Einschalten Schuetz (Langsam)
            time.sleep(self.time_rechtslauf_langsam)
            GPIO.output(13, True)           # Ausschalten Schuetz (Langsam)
            time.sleep(self.time_Bremse)
            GPIO.output(26, True)           # Schuetz Ausschalten (Rechtslauf)
            self.Stoerung()

    # Methode fuer Licht an
    def lichtan(self):
        GPIO.output(23, False)

    # Methode fuer Licht aus
    def lichtaus(self):
        GPIO.output(23, True)

    # Methode zur Feststellung von Fehlern
    def Stoerung(self):

        # Bedingung -> Eingang Motorschutz =0
        if GPIO.input(18) == 0:
            self.stop()
            fehler = 'Motorschutz ausgeloest'
            return fehler

        # Bedingung -> Endschalter =1 und einer
        # der 4 Schuetze ist noch an -> Schuetz klebt
        elif (GPIO.input(18) == 1
              and GPIO.input(20) == 1
              or GPIO.input(21) == 1
              or GPIO.input(16) == 1
              or GPIO.input(12) == 1):
            self.stop()
            fehler = 'Ein Schuetz klebt'
            return fehler

        # Bedingung -> Mototrschutz und Endschalter =1
        elif GPIO.input(18) == 1 and GPIO.input(10) == 1:
            fehler = 'Auswertung'
            return fehler

        # Bedingung -> Endschalter und Schuetze =0 und Motorschutz =1S
        elif (GPIO.input(10) == 0
              and GPIO.input(20) == 0
              and GPIO.input(21) == 0
              and GPIO.input(16) == 0
              and GPIO.input(12) == 0
              and GPIO.input(18) == 1):
            fehler = 'Feuer frei'
            return fehler

        # Bedingung -> treffen die Bedingungen
        # von weiter oben nicht zu => Fehlerfrei
        else:
            fehler = 'OK'
            return fehler

    # Im Fehlerfall alle Motorschuetze abschalten
    def stop(self):
        GPIO.output(13, True),  # Schnell
        GPIO.output(6, True),  # Langsam
        time.sleep(self.time_Bremse)
        GPIO.output(19, True),  # Linkslauf
        GPIO.output(26, True)  # Rechtslauf
        self.Start_up = 0

    # Bei Start alles Abschalten um ungewollte Bewegungen zu verhindern
    def start(self):
        GPIO.output(13, True),  # Schnell
        GPIO.output(6, True),  # Langsam
        GPIO.output(19, True),  # Linkslauf
        GPIO.output(26, True)  # Rechtslauf
        GPIO.output(23, True)  # Licht

    # Ausgabe aller Parameter zur ueberpruefung im Terminal
    def test(self):
        print(' ')
        print('#_Ausgaenge')
        print(str(GPIO.input(6)) + ' _Schnell')
        print(str(GPIO.input(13)) + ' _Langsam')
        print(str(GPIO.input(19)) + ' _Linkslauf')
        print(str(GPIO.input(26)) + ' _Rechtslauf')
        print(str(GPIO.input(23)) + ' _Licht')
        print(' ')
        print('#_Eingaenge')
        print(str(GPIO.input(10)) + ' _Endschalter')
        print(str(GPIO.input(12)) + ' _Schnell')
        print(str(GPIO.input(16)) + ' _Langsam')
        print(str(GPIO.input(18)) + ' _Motorschutz')
        print(str(GPIO.input(20)) + ' _Linkslauf')
        print(str(GPIO.input(21)) + ' _Rechtslauf')
        print(str(self.Start_up) + ' _Startmerker')


# Abschluss des Programmes / Fensters
app = QApplication(sys.argv)
F = Fenster()
sys.exit(app.exec_())

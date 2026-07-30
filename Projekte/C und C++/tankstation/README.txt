================================================================================
           BETRIEBSANLEITUNG: AUTOMATISCHE MODELLBAUTANKSTATION
================================================================================

Diese mobile Tankstation dient dem sicheren Be- und Enttanken von Flugmodellen 
via sensorüberwachter Automatik oder präziser manueller Steuerung.

--------------------------------------------------------------------------------
1. SYSTEMSTART & PILOTENANZEIGE
--------------------------------------------------------------------------------
1. Schalten Sie die Hauptstromversorgung der Tankstation ein.
2. Das System führt einen Selbsttest durch und prüft die SD-Karte sowie die 
   Modulino-I2C-Module.
3. Splash-Screen (10 Sek.): Das Display zeigt die hinterlegten Pilotendaten 
   (Name, Anschrift) an.
   * Abkürzung: Ein kurzer Druck auf den Drehencoder überspringt die Anzeige 
     und öffnet sofort das Hauptmenü.

--------------------------------------------------------------------------------
2. DER AUTOMATIK-MODUS (Sicheres Betanken)
--------------------------------------------------------------------------------
Im Automatik-Modus steuert das System den Vorgang komplett eigenständig anhand 
der im Modellspeicher hinterlegten Limits.

Schritt-für-Schritt-Ablauf:
1. Wählen Sie im Hauptmenü "1. Automatik Modus".
2. Drehen Sie den Encoder, um das gewünschte Modell auszuwählen (Modell 1 bis 10). 
   Das Display zeigt Name, Tankvolumen (ml), Maximaldruck (mbar) und den Tanktyp.
3. Bestätigen Sie die Auswahl mit einem Klick auf den Encoder. Der Vorgang 
   startet sofort.

Automatische Phasen:
* Phase 1: Schlauch leeren (Einstellbare Sekunden): Die Pumpe läuft rückwärts, 
  um Luft oder Treibstoffreste aus dem Schlauchleitungssystem zu entfernen.
* Phase 2: Betanken: Die Pumpe schaltet um und fördert Treibstoff vorwärts in 
  das Modell. Das Display zeigt live den aktuellen Druck, die getankte Menge 
  in ml und den aktuellen Durchfluss an.

Automatische Sicherheitsabschaltung:
Das System stoppt die Pumpe und die Richtungsrelais augenblicklich, sobald:
* Das hinterlegte Tankvolumen (ml) exakt erreicht ist.
* Der Maximaldruck (mbar) des Tanks überschritten wird.
* Ein plötzlicher Druckanstieg (Druck-Peak) erkannt wird (z. B. Beutel-Tank 
  voll oder Knick im Schlauch).
* Schlauchplatzer-Schutz (Leckage-Alarm): Wenn Treibstoff fließt, aber für 
  mehr als die eingestellte Zeit (Standard: 2,5 Sek.) kein Gegendruck entsteht 
  (Schlauch abgerutscht), bricht das System ab und zeigt eine rote Warnmeldung.

*Nach erfolgreicher Beendigung kehrt das System nach 3 Sekunden automatisch 
ins Hauptmenü zurück.*

--------------------------------------------------------------------------------
3. DER MANUELLE MODUS (Manueller Gashebel)
--------------------------------------------------------------------------------
Für freies Pumpen ohne Modellauswahl und automatische Limits.

1. Wählen Sie im Hauptmenü "2. Manueller Modus".
2. Der Drehencoder fungiert nun als stufenloser Regler (Gashebel von -100% 
   bis +100%):
   * Rechtsdrehung (Positive %): Pumpe läuft vorwärts (TANKEN).
   * Linksdrehung (Negative %): Pumpe läuft rückwärts (ENTLEEREN).
   * Mittelstellung (0%): Pumpe steht im Leerlauf (STOPP).
3. Das Display zeigt den Live-Druck und das geförderte Gesamtvolumen an.
4. Beenden: Stellen Sie den Regler auf 0% (STOPP) und drücken Sie den Encoder. 
   Sie kehren ins Hauptmenü zurück.

--------------------------------------------------------------------------------
4. DIE SYSTEM-EINSTELLUNGEN (Geschützter Bereich)
--------------------------------------------------------------------------------
Hinweis: Der Zugang zu den Einstellungen ist über eine PIN-Abfrage geschützt.

1. Durchfluss-Kalibrierung (Flow)
   Falls sich die Viskosität des Treibstoffs ändert oder eine neue Pumpe 
   verbaut wird:
   * Stellen Sie einen präzisen Messzylinder (1 Liter / 1000 ml) bereit und 
     führen Sie den Tankschlauch hinein.
   * Wählen Sie den Punkt an. Halten Sie den Encoder-Knopf physisch gedrückt.
   * Die Pumpe läuft mit 50 % Leistung an. Lassen Sie den Knopf exakt in dem 
     Moment los, in dem der Treibstoffspiegel im Zylinder die 1-Liter-Marke 
     erreicht.
   * Die gezählten Sensor-Impulse werden automatisch als neue Referenz auf 
     der SD-Karte gespeichert.

2. Druck-Nullung
   Gleicht Umgebungsluftdruck-Schwankungen oder Sensor-Toleranzen aus.
   * Stellen Sie sicher, dass das Schlauchsystem absolut drucklos ist 
     (Pumpe aus, Schläuche offen).
   * Wählen Sie den Punkt an. Der Arduino liest die aktuelle Ruhespannung des 
     Drucksensors ein und deklariert diese als neuen Nullpunkt (0 mbar).

5. Timer & Leckage (Feinjustierung)
   Hier können Sie die Software-Sicherheitszeiten direkt am Flugplatz verändern:
   * Leeren Zeit: Dauer der anfänglichen Schlauch-Entleerung (einstellbar 
     von 1-30 Sekunden).
   * Leck-Alarm: Reaktionszeit des Schlauchplatzer-Schutzes (einstellbar 
     von 500-10.000 Millisekunden).
   * Klicken Sie sich nach unten auf SPEICHERN & EXIT, um die geänderten Zeiten 
     fest auf die SD-Karte zu schreiben.

--------------------------------------------------------------------------------
5. DER MODELLSPEICHER (Tabelle)
--------------------------------------------------------------------------------
1. Wählen Sie im Hauptmenü "4. Modellspeicher".
2. Das Display listet alle hinterlegten Modelle in einer übersichtlichen Tabelle 
   mit Name, Tankvolumen, maximal zulässigem Druck und Tank-Typ auf.
3. Ein einfacher Klick bringt Sie jederzeit zurück ins Hauptmenü.

--------------------------------------------------------------------------------
6. WICHTIGE HARDWARE- & SICHERHEITSHINWEISE
--------------------------------------------------------------------------------
* NOT-AUS-FUNKTION: Ein langer Druck (über 1,5 Sekunden) auf den Encoder bricht 
  jeden laufenden Tankvorgang in jedem Menü sofort ab, stoppt den Motor, 
  schaltet alle Relais aus und wirft Sie zurück ins Hauptmenü!
* SD-KARTEN-FORMAT: Die SD-Karte muss im Format FAT16 oder FAT32 formatiert 
  sein. Das modernere exFAT-Format wird nicht unterstützt.
* GEMEINSAME MASSE (GND): Achten Sie darauf, dass die Masse (GND) des Pumpen-Akkus 
  zwingend mit dem GND-Pin des Arduinos verbunden ist, da es andernfalls zu 
  gefährlichen Fehlmessungen des Drucksensors kommt.

--------------------------------------------------------------------------------
7. GEWÄHRLEISTUNG & GARANTIEBEDINGUNGEN
--------------------------------------------------------------------------------
Für die Tankstation gelten strenge Garantie- und Reparaturbedingungen. Bitte 
lesen Sie diese vor der Inbetriebnahme aufmerksam durch.

Garantiefrist und Umfang:
* Die Garantiezeit beträgt 1 Jahr ab Kaufdatum.
* Diese Garantie umfasst ausschließlich Material- und Fabrikationsfehler des 
  Hersteller bei bestimmungsgemäßem und sachgemäßem Betrieb laut dieser Anleitung.

ACHTUNG: Erlöschen der Garantie bei Siegelbruch (Box öffnen)
* Die Gehäusebox der Tankstation ist werkseitig versiegelt bzw. geschützt.
* Mit dem Öffnen der Gehäusebox erlischt jeglicher Garantieanspruch sofort 
  und unwiderruflich!
* Jegliche eigenmächtige Modifikation an der internen Verkabelung, den Modulino-
  Modulen, dem Display oder der Steuerungselektronik führt zum sofortigen 
  Verlust aller Garantieansprüche.

Kostenpflichtiger Reparaturservice nach Garantie-Erlöschen:
Sollte die Gehäusebox geöffnet worden sein oder die einjährige Garantiefrist 
abgelaufen sein, besteht kein Anspruch auf kostenlosen Ersatz oder kostenfreie 
Instandsetzung. In diesem Fall gilt:
* Ausschließlich Reparatur: Das Gerät wird im Schadensfall nicht umgetauscht, 
  sondern einer technischen Prüfung unterzogen und repariert.
* Voll kostenpflichtig: Alle anfallenden Arbeitszeiten sowie die benötigten 
  Ersatzteile (z. B. Display, Sensoren, Relais) werden dem Kunden voll in 
  Rechnung gestellt.
* Versand- und Transportkosten: Die Kosten für den versicherten Versand zur 
  Reparaturwerkstatt (Hinweg) sowie die Kosten für den Rückversand zum Kunden 
  (Rückweg) sind zu 100 % vom Kunden zu tragen. Unfreie Einsendungen werden 
  nicht angenommen.

================================================================================

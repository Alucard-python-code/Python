====================================================================
README: PILATUS PC-6 PORTER (24,9 KG TURBOPROP-PROJEKT) - ETAPPENPLAN
====================================================================

Dieses Dokument beschreibt die exakte, logische Reihenfolge zum Bau 
deines High-End-Großmodells. Alle Systeme sind auf maximalen Leichtbau,
Vibrationsschutz und höchste Ausfallsicherheit optimiert.

--------------------------------------------------------------------
ETAPPE 1: KOPPLUNG VON LASER & HOLZBAU (NACH ANSCHAFFUNG DES LASERS)
--------------------------------------------------------------------
1. CAD-Vorbereitung: Konstruiere den Rumpf-Gitterrahmen im CAD aus 
   10x10 mm Balsaleisten. Plane fast vollständig OHNE Zwischenspanten.
2. Hauptschotts lasern: Schneide die 4 lebenswichtigen Kraftknotenpunkte 
   aus 3-6 mm Birkensperrholz mit dem Laser (Motorspant, Fahrwerksspant, 
   Flächensteckung, Heckschott).
3. Helling-Aufbau: Baue das 10x10 mm Balsagitter absolut gerade auf 
   einer ebenen Bauhelling auf. Verklebe die gelaserten Hauptschotts.
4. Holz versiegeln: Streiche den fertigen Holzrahmen hauchdünn mit 
   Porenfüller/Schnellschliffgrund ein, damit das Balsa später kein 
   Klebeharz wie ein Schwamm aufsaugt.

--------------------------------------------------------------------
ETAPPE 2: COMPOSITE-AUSSENHAUT (FORMPRESSEN IM VAKUUMBEUTEL)
--------------------------------------------------------------------
1. Formen drucken: Drucke die Rumpf- und Flächen-Halbschalenformen in 
   Segmenten im 3D-Drucker (Infill min. 30%, 4-5 Wandlinien).
2. Faser-Setup Rumpf: Lege das Gewebe trocken in die Form (80g Glas + 
   120g Kohle im 45-Grad-Winkel + 80g Glas). Am Heck die Kohle weglassen 
   und nur mit 2x 80g Glas arbeiten (Gewicht sparen!).
3. Faser-Setup Fläche: Bereite die eckige I-Träger-Haupthülse im Flügel 
   vor. Der Holm besteht aus 3 mm Birkensperrholz, aufglegten UD-Kohlegurten 
   und wird mit 2-3 Lagen Kohleschlauch überzogen.
4. Envelope Infusion: Stecke die komplette Form nass oder trocken (Infusion) 
   in den Vakuumsack. Nutze Abreißgewebe als innerste Schicht für eine 
   perfekt raue, klebebereite GFK/CFK-Innenseite.
5. Rumpf-Hochzeit: Klebe die entformten Außenhäute über die überlappende 
   Klebelippentechnik (Schäftung) mit angedicktem Harz (Baumwollflocken) 
   punktuell auf den Balsarahmen auf.

--------------------------------------------------------------------
ETAPPE 3: ELEKTRONIK & DIGITALE RECHTECK-PLATINE (U-SHIELD)
--------------------------------------------------------------------
1. U-Platinen-Layout: Zeichne im CAD ein U-förmiges Platinenlayout, das 
   exakt außen um deinen SmoothFlite ARXL Controller herumpasst (Kühlfläche 
   bleibt komplett frei!).
2. Direktlöten: Verzichte im Rumpf auf Stecker. Löte alle ankommenden 
   Hauptkabelbündel der Flächen (6 Pins pro Seite) und des Hecks direkt 
   auf die Platine auf.
3. Verguss & Entlastung: Vergieße die Lötstellen hauchdünn mit elastischem 
   Vergusscharz gegen Vibrationen. Klebe 3D-gedruckte Zugentlastungen 
   direkt daneben auf den Rumpfboden.
4. Zwischenboden-Einbau: Platziere das gesamte Elektronikzentrum im 
   originalgetreuen Zwischenboden der PC-6, zugänglich über eine Klappe 
   von der Rumpfunterseite. Einschalten erfolgt unsichtbar per Magnetschalter.

--------------------------------------------------------------------
ETAPPE 4: TANK, COCKPIT & LIVE-GLASS-COCKPIT
--------------------------------------------------------------------
1. Kerosinwanne: Drucke eine absolut dichte Sicherheitswanne aus PETG/ABS. 
   Platziere darin den 5-Liter-Beuteltank exakt auf der Schwerpunktlinie.
2. Kistentarnung: Tarne die Wanne in der Kabine mit einer gelaserten 
   Frachtkisten-Attrappe. Integriere den mechanischen Peilstab für den 
   visuellen Hardware-Check am Boden.
3. Glass Cockpit: Schließe das 2,5" SPI-Display direkt an den 7g leichten 
   Arduino Nano ESP32 an. 
4. S.Bus2-Datenstrom: Verbinde den Pin D4 des Nano direkt mit der S.Bus2-
   Telemetrieleitung zwischen Empfänger und SmoothFlite ARXL. Der Code liest 
   die echten Fluglagen (Pitch/Roll) sowie die barometrische Höhe aus 
   und spiegelt sie im Garmin G1000 PFD wider.

====================================================================
Das Konzept garantiert: Minimale Fehlerquellen und maximale Festigkeit 
beim Abfluggewicht unter der magischen 24,9 kg Grenze. Gutes Gelingen!
====================================================================

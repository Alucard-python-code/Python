"""
pdf_generator.py – Gesamt-Auftrags-PDF beim Abschließen eines Auftrags (ReportLab).

Aufbau:
  Seite 1      Deckblatt: Kunde, Auftrag, Zeitraum, Prüfer, Management-Summary,
               Inhaltsverzeichnis aller TAGs mit Ergebnis und Seitenzahl
  je Gerät     genau 1 Seite: Stammdaten, Messbereich, 5-Punkt-Tabelle (Soll, HART-Ist,
               True-mA, Abweichungen), Beweisfoto mit SHA-256, Gesamtergebnis
  letzte Seite Kunden-Rückläufer: Übernahme-/Kenntnisnahmebestätigung mit Feldern für
               Name (Druckbuchstaben), Datum, Firmenstempel, Unterschrift

Seitenzahlen ("Seite x von y") und Inhaltsverzeichnis entstehen in zwei Durchläufen:
Im ersten wird gemessen, auf welcher Seite jedes Gerät landet, im zweiten eingetragen.
Eingabe ist Database.order_report(order_id).
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (BaseDocTemplate, Flowable, Frame, Image, KeepInFrame, PageBreak, PageTemplate,
                                Paragraph, Spacer, Table, TableStyle)

import config

log = logging.getLogger(__name__)
TZ = ZoneInfo(config.TIMEZONE)

# Druckfarben (dunkler als die UI-Farben -> auf weißem Papier gut lesbar)
C_PASS = colors.HexColor("#00873E")
C_FAIL = colors.HexColor("#C62828")
C_WARN = colors.HexColor("#E65100")
C_HEAD = colors.HexColor("#0D1117")
C_ACCENT = colors.HexColor("#00838F")
C_GRID = colors.HexColor("#B0B7C0")
C_ZEBRA = colors.HexColor("#F2F4F7")

PAGE_W, PAGE_H = A4
MARGIN = 18 * mm


# =============================================================================
# Schriften (DejaVu für Ω, ³, µ …; sonst Helvetica)
# =============================================================================
def _register_fonts() -> tuple[str, str]:
    base = Path(config.Printer.FONT_DIR)
    try:
        pdfmetrics.registerFont(TTFont("Body", str(base / "DejaVuSans.ttf")))
        pdfmetrics.registerFont(TTFont("Body-Bold", str(base / "DejaVuSans-Bold.ttf")))
        pdfmetrics.registerFontFamily("Body", normal="Body", bold="Body-Bold")
        return "Body", "Body-Bold"
    except Exception:
        log.warning("DejaVu-Schriften nicht gefunden – Helvetica (ohne Ω)")
        return "Helvetica", "Helvetica-Bold"


FONT, FONT_B = _register_fonts()


def _style(name, size=9, bold=False, color=colors.black, align=0, leading=None, space_after=0):
    return ParagraphStyle(name, fontName=FONT_B if bold else FONT, fontSize=size, textColor=color,
                          alignment=align, leading=leading or size * 1.25, spaceAfter=space_after)


S_TITLE = _style("title", 20, True, C_HEAD, leading=24, space_after=4)
S_SUB = _style("sub", 11, False, C_ACCENT, space_after=10)
S_H2 = _style("h2", 12, True, C_HEAD, leading=15, space_after=4)
S_BODY = _style("body", 9)
S_SMALL = _style("small", 7.5, color=colors.HexColor("#555555"))
S_CELL = _style("cell", 8)
S_CELL_B = _style("cellb", 8, True)
S_CELL_R = _style("cellr", 8, align=TA_RIGHT)
S_CENTER = _style("center", 9, align=TA_CENTER)


# =============================================================================
# Formatierung (deutsch)
# =============================================================================
def num(v: Optional[float], nd: int = 2, sign: bool = False) -> str:
    if v is None:
        return "–"
    s = f"{v:+.{nd}f}" if sign else f"{v:.{nd}f}"
    return s.replace(".", ",")


def dt(ts: Optional[float], with_time: bool = True) -> str:
    if not ts:
        return "–"
    d = datetime.fromtimestamp(ts, TZ)
    return d.strftime("%d.%m.%Y %H:%M") if with_time else d.strftime("%d.%m.%Y")


def duration(s: Optional[float]) -> str:
    if not s:
        return "–"
    m, sec = divmod(int(s), 60)
    return f"{m} min {sec:02d} s"


def esc(text) -> str:
    return (str(text) if text is not None else "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def result_color(result: str):
    return C_PASS if result == "BESTANDEN" else C_FAIL if result == "NICHT BESTANDEN" else C_WARN


# =============================================================================
# Hilfs-Flowables
# =============================================================================
class Anchor(Flowable):
    """Unsichtbar; merkt sich die Seitennummer, auf der es gezeichnet wird (Inhaltsverzeichnis)."""

    def __init__(self, key: str, registry: dict):
        super().__init__()
        self.key, self.registry = key, registry
        self.width = self.height = 0

    def draw(self):
        self.registry[self.key] = self.canv.getPageNumber()


class ResultBadge(Flowable):
    def __init__(self, text: str, color, width=60 * mm, height=10 * mm, size=12):
        super().__init__()
        self.text, self.color, self.width, self.height, self.size = text, color, width, height, size

    def draw(self):
        c = self.canv
        c.setFillColor(self.color)
        c.roundRect(0, 0, self.width, self.height, 2 * mm, stroke=0, fill=1)
        c.setFillColor(colors.white)
        c.setFont(FONT_B, self.size)
        c.drawCentredString(self.width / 2, (self.height - self.size * 0.7) / 2, self.text)


def kv_table(rows: list[tuple[str, str]], col1=42 * mm, col2=None, cols: int = 1) -> Table:
    """Schlüssel/Wert-Tabelle, optional zweispaltig."""
    avail = PAGE_W - 2 * MARGIN
    if cols == 2:
        half = (len(rows) + 1) // 2
        left, right = rows[:half], rows[half:] + [("", "")] * (2 * half - len(rows))
        data = [[Paragraph(esc(a), S_CELL_B), Paragraph(esc(b), S_CELL), Paragraph(esc(c), S_CELL_B),
                 Paragraph(esc(d), S_CELL)] for (a, b), (c, d) in zip(left, right)]
        w = (avail - 2 * col1) / 2
        t = Table(data, colWidths=[col1, w, col1, w])
    else:
        data = [[Paragraph(esc(a), S_CELL_B), Paragraph(esc(b), S_CELL)] for a, b in rows]
        t = Table(data, colWidths=[col1, col2 or avail - col1])
    t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
                           ("TOPPADDING", (0, 0), (-1, -1), 2), ("LINEBELOW", (0, 0), (-1, -1), 0.25, C_GRID)]))
    return t


def grid_style(header_rows: int = 1) -> list:
    return [("FONTNAME", (0, 0), (-1, -1), FONT), ("FONTNAME", (0, 0), (-1, header_rows - 1), FONT_B),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("BACKGROUND", (0, 0), (-1, header_rows - 1), C_HEAD),
            ("TEXTCOLOR", (0, 0), (-1, header_rows - 1), colors.white),
            ("GRID", (0, 0), (-1, -1), 0.4, C_GRID), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("ROWBACKGROUNDS", (0, header_rows), (-1, -1), [colors.white, C_ZEBRA]),
            ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]


# =============================================================================
# Bericht
# =============================================================================
class OrderReportPDF:
    def __init__(self, report: dict, *, generated_at: Optional[float] = None, app_version: str = "1.0"):
        self.r = report
        self.order = report["order"]
        self.customer = report["customer"]
        self.entries = report["entries"]
        self.summary = report["summary"]
        self.generated_at = generated_at or datetime.now(TZ).timestamp()
        self.app_version = app_version
        self.pages: dict[str, int] = {}
        self.total_pages = 0

    # ------------------------------------------------------------------ Kopf/Fußzeile
    def _decorate(self, canv, doc):
        canv.saveState()
        canv.setStrokeColor(C_ACCENT)
        canv.setLineWidth(1.2)
        canv.line(MARGIN, PAGE_H - 12 * mm, PAGE_W - MARGIN, PAGE_H - 12 * mm)
        canv.setFont(FONT_B, 8)
        canv.setFillColor(C_HEAD)
        canv.drawString(MARGIN, PAGE_H - 10.5 * mm, config.Company.NAME)
        canv.setFont(FONT, 8)
        canv.drawRightString(PAGE_W - MARGIN, PAGE_H - 10.5 * mm,
                             f"Prüfbericht Auftrag {self.order['order_no']} · {self.customer['name']}")
        canv.setStrokeColor(C_GRID)
        canv.setLineWidth(0.5)
        canv.line(MARGIN, 12 * mm, PAGE_W - MARGIN, 12 * mm)
        canv.setFont(FONT, 7)
        canv.setFillColor(colors.HexColor("#555555"))
        canv.drawString(MARGIN, 8.5 * mm, f"Erstellt {dt(self.generated_at)} · HART-Feldcommunicator v{self.app_version}")
        total = self.total_pages or "?"
        canv.drawRightString(PAGE_W - MARGIN, 8.5 * mm, f"Seite {doc.page} von {total}")
        canv.restoreState()

    # ------------------------------------------------------------------ Deckblatt
    def _cover(self) -> list:
        o, c, s = self.order, self.customer, self.summary
        story = [Spacer(1, 6 * mm), Paragraph("Kalibrier- und Prüfbericht", S_TITLE),
                 Paragraph(f"HART-Messstellen · Auftrag {esc(o['order_no'])}", S_SUB)]
        period = f"{dt(o['opened_at'])} – {dt(o['closed_at']) if o.get('closed_at') else 'offen'}"
        story.append(kv_table([
            ("Kunde", c["name"]), ("Kundennummer", c.get("customer_no") or "–"),
            ("Anschrift", c.get("address") or "–"), ("Auftragsnummer", o["order_no"]),
            ("Beschreibung", o.get("description") or "–"), ("Zeitraum", period),
            ("Prüfer", o["technician"]), ("Ausführender Betrieb", f"{config.Company.NAME}, {config.Company.ADDRESS}"),
        ]))
        story += [Spacer(1, 6 * mm), Paragraph("Zusammenfassung", S_H2)]
        kpis = [("Prüfungen", s["calibrations"], C_HEAD), ("Bestanden", s["passed"], C_PASS),
                ("Nicht bestanden", s["failed"], C_FAIL if s["failed"] else C_HEAD),
                ("Gerätetausche", s["swaps"], C_WARN if s["swaps"] else C_HEAD),
                ("Neuaufnahmen", s["new_devices"], C_HEAD), ("Nachkalibrierungen", s["recalibrations"], C_HEAD)]
        big = [Paragraph(f'<font color="{col.hexval().replace("0x", "#")}" size="18"><b>{v}</b></font>', S_CENTER)
               for _, v, col in kpis]
        lbl = [Paragraph(esc(k), _style("kl", 6.8, align=TA_CENTER)) for k, _, _ in kpis]
        kt = Table([big, lbl], colWidths=[(PAGE_W - 2 * MARGIN) / 6] * 6, rowHeights=[11 * mm, 6 * mm])
        kt.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 0.6, C_GRID), ("INNERGRID", (0, 0), (-1, -1), 0.3, C_GRID),
                                ("VALIGN", (0, 0), (-1, -1), "MIDDLE")]))
        story.append(kt)
        if s["calibrations"]:
            rate = s["passed"] / s["calibrations"] * 100
            txt = (f"Von {s['calibrations']} geprüften Messstellen haben {s['passed']} die Prüfung bestanden "
                   f"({num(rate, 0)} %).")
            if s["failed"]:
                failed = ", ".join(e["device"]["tag"] for e in self.entries
                                   if e["calibration"]["result"] == "NICHT BESTANDEN")
                txt += f" <b>Handlungsbedarf</b> bei: {esc(failed)}."
            story += [Spacer(1, 3 * mm), Paragraph(txt, S_BODY)]

        story += [Spacer(1, 6 * mm), Paragraph("Inhaltsverzeichnis", S_H2)]
        rows = [["Nr.", "TAG", "Gerät", "Prüfart", "Ergebnis", "Seite"]]
        for i, e in enumerate(self.entries, 1):
            cal, dev = e["calibration"], e["device"]
            rows.append([str(i), Paragraph(f"<b>{esc(dev['tag'])}</b>", S_CELL),
                         Paragraph(esc(dev.get("display_name") or "–"), S_CELL), cal["case_type"].title()
                         .replace("Geraetetausch", "Gerätetausch"),
                         Paragraph(f'<font color="{result_color(cal["result"]).hexval().replace("0x", "#")}">'
                                   f'<b>{esc(cal["result"])}</b></font>', S_CELL),
                         str(self.pages.get(f"dev{i}", "–"))])
        rows.append(["", "", "Kunden-Rückläufer", "", "", str(self.pages.get("return", "–"))])
        avail = PAGE_W - 2 * MARGIN
        t = Table(rows, colWidths=[9 * mm, 32 * mm, avail - 9 * mm - 32 * mm - 34 * mm - 32 * mm - 14 * mm,
                                   34 * mm, 32 * mm, 14 * mm], repeatRows=1)
        t.setStyle(TableStyle(grid_style() + [("ALIGN", (-1, 0), (-1, -1), "RIGHT")]))
        story += [t, PageBreak()]
        return story

    # ------------------------------------------------------------------ Geräteseite
    def _device_page(self, idx: int, e: dict) -> list:
        cal, dev, pts = e["calibration"], e["device"], e["points"]
        unit = cal.get("unit") or dev.get("unit") or ""
        meter = json.loads(cal["meter_info"]) if cal.get("meter_info") else {}
        head = Table([[Paragraph(f"{idx}. {esc(dev['tag'])}", _style("t", 16, True, C_HEAD, leading=19)),
                       ResultBadge(cal["result"], result_color(cal["result"]))]],
                     colWidths=[PAGE_W - 2 * MARGIN - 62 * mm, 62 * mm])
        head.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("ALIGN", (1, 0), (1, 0), "RIGHT")]))
        story = [head, Paragraph(esc(dev.get("descriptor") or ""), S_SUB)]

        mfr = f"0x{dev['manufacturer_id']:04X}" if dev.get("manufacturer_id") is not None else "–"
        dtype = f"0x{dev['device_type']:04X}" if dev.get("device_type") is not None else "–"
        rows = [("Gerät", dev.get("display_name") or "–"), ("Geräteklasse", dev.get("device_class") or "–"),
                ("HART Unique-ID", dev["hart_unique_id"]), ("Hersteller / Typ", f"{mfr} / {dtype}"),
                ("HART-Revision", str(dev.get("universal_rev") or "–")), ("Einbauort", dev.get("location") or "–"),
                ("Messbereich", f"{num(cal['lrv'], 3)} … {num(cal['urv'], 3)} {unit}"),
                ("Toleranz", f"± {num(cal['tolerance_pct'])} % der Spanne"),
                ("Prüfart", cal["case_type"].title().replace("Geraetetausch", "Gerätetausch")),
                ("Prüfer", cal["technician"]), ("Prüfbeginn", dt(cal["started_at"])),
                ("Dauer", duration(cal.get("duration_s"))), ("Zeitquelle", cal.get("time_source") or "–"),
                ("Versuche im Auftrag", str(e.get("attempts", 1)))]
        if meter:
            rows.append(("Messmittel mA", f"{meter.get('name', 'INA226 True-mA')}, kalibriert "
                                          f"{(meter.get('calibrated_at') or '–')[:10]}"))
        story += [kv_table(rows, col1=30 * mm, cols=2), Spacer(1, 3 * mm)]

        if e.get("replaced_device"):
            old = e["replaced_device"]
            story.append(Paragraph(
                f'<font color="#E65100"><b>Gerätetausch:</b></font> Ersetzt das Gerät mit Unique-ID '
                f'<b>{esc(old["hart_unique_id"])}</b> (außer Betrieb seit {dt(old.get("replaced_at"))}). '
                f'Messbereich und Toleranz wurden übernommen, die Historie des Altgeräts bleibt erhalten.', S_BODY))
            story.append(Spacer(1, 3 * mm))

        story.append(Paragraph("5-Punkt-Prüfung", S_H2))
        hdr = ["Punkt", f"Soll\n[{unit}]", "Soll\n[mA]", f"HART-Ist\n[{unit}]", "HART\n[mA]", "True-mA\n[mA]",
               "Abw. PV\n[%]", "Abw. mA\n[%]", "D/A\n[%]", ""]
        data = [hdr]
        style = grid_style()
        for r, p in enumerate(pts, 1):
            data.append([f"{num(p['point_pct'], 0)} %", num(p["setpoint_value"], 3), num(p["setpoint_ma"], 3),
                         num(p["hart_pv"], 3), num(p["hart_ma"], 3), num(p["true_ma"], 3),
                         num(p["error_pv_pct"], 3, True), num(p["error_ma_pct"], 3, True),
                         num(p["da_mismatch_pct"], 3, True), "OK" if p["passed"] else "FEHLER"])
            style.append(("TEXTCOLOR", (-1, r), (-1, r), C_PASS if p["passed"] else C_FAIL))
            style.append(("FONTNAME", (-1, r), (-1, r), FONT_B))
            for c_idx, key in ((6, "error_pv_pct"), (7, "error_ma_pct")):
                if p[key] is not None and abs(p[key]) > cal["tolerance_pct"]:
                    style.append(("TEXTCOLOR", (c_idx, r), (c_idx, r), C_FAIL))
        style += [("ALIGN", (0, 0), (-1, -1), "CENTER")]
        avail = PAGE_W - 2 * MARGIN
        t = Table(data, colWidths=[14 * mm] + [(avail - 30 * mm) / 8] * 8 + [16 * mm])
        t.setStyle(TableStyle(style))
        story += [t, Paragraph("Abweichungen in % der Spanne. PV = digitaler HART-Messwert, "
                               "mA = gemessener Schleifenstrom (True-mA), D/A = True-mA gegenüber dem vom Gerät "
                               "gemeldeten Strom.", S_SMALL), Spacer(1, 4 * mm)]

        story += self._photo_block(e["photos"])
        verdict = (f"Größte Abweichung {num(cal.get('max_error_pct'), 3)} % der Spanne bei einer zulässigen Toleranz "
                   f"von ± {num(cal['tolerance_pct'])} %.")
        if cal["result"] == "NICHT BESTANDEN":
            verdict += " Die Messstelle erfüllt die Anforderungen NICHT – Instandsetzung oder Austausch erforderlich."
        if cal.get("notes"):
            verdict += f"<br/>Bemerkung: {esc(cal['notes'])}"
        box = Table([[Paragraph(f"<b>Gesamtergebnis: {esc(cal['result'])}</b><br/>{verdict}",
                                _style("v", 9.5, color=colors.black))]], colWidths=[avail])
        box.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 1.5, result_color(cal["result"])),
                                 ("LEFTPADDING", (0, 0), (-1, -1), 6), ("TOPPADDING", (0, 0), (-1, -1), 5),
                                 ("BOTTOMPADDING", (0, 0), (-1, -1), 6)]))
        story += [Spacer(1, 3 * mm), box]
        frame_h = PAGE_H - 2 * MARGIN - 6 * mm
        # Seitenmarke AUSSERHALB von KeepInFrame, sonst wird sie nicht registriert
        return [Anchor(f"dev{idx}", self.pages), KeepInFrame(avail, frame_h, story, mode="shrink"), PageBreak()]

    def _photo_block(self, photos: list[dict]) -> list:
        if not photos:
            return []
        out = [Paragraph("Beweisfoto" + ("s" if len(photos) > 1 else ""), S_H2)]
        cells = []
        for ph in photos[:2]:
            src = ph.get("thumbnail") or ph["path"]
            label = (f"{'Punkt ' + num(ph['point_pct'], 0) + ' %' if ph.get('point_pct') is not None else 'Gerät'}"
                     f" · {dt(ph.get('captured_at'))}<br/>SHA-256: {esc(ph['sha256'][:24])}…")
            if src and Path(src).exists():
                img = Image(src)
                ratio = img.imageHeight / float(img.imageWidth or 1)
                w = 78 * mm
                img.drawWidth, img.drawHeight = w, min(w * ratio, 58 * mm)
                if w * ratio > 58 * mm:
                    img.drawWidth = 58 * mm / ratio
                cells.append([img, Paragraph(label, S_SMALL)])
            else:
                cells.append([Paragraph("Foto nicht verfügbar", S_SMALL), Paragraph(label, S_SMALL)])
        t = Table([[c[0] for c in cells], [c[1] for c in cells]],
                  colWidths=[(PAGE_W - 2 * MARGIN) / 2] * len(cells))
        t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0)]))
        return out + [t]

    # ------------------------------------------------------------------ Rückläufer
    def _return_page(self) -> list:
        o, c, s = self.order, self.customer, self.summary
        failed = [e["device"]["tag"] for e in self.entries if e["calibration"]["result"] == "NICHT BESTANDEN"]
        story = [Anchor("return", self.pages), Spacer(1, 4 * mm),
                 Paragraph("Kunden-Rückläufer", S_TITLE),
                 Paragraph("Übernahme- und Kenntnisnahmebestätigung", S_SUB),
                 Paragraph(f"<b>Rücksendung an:</b> {esc(config.Company.NAME)}, {esc(config.Company.ADDRESS)}"
                           f"<br/>{esc(config.Company.CONTACT)}", S_BODY), Spacer(1, 6 * mm),
                 kv_table([("Kunde", c["name"]), ("Kundennummer", c.get("customer_no") or "–"),
                           ("Auftragsnummer", o["order_no"]),
                           ("Prüfzeitraum", f"{dt(o['opened_at'], False)} – {dt(o.get('closed_at'), False)}"),
                           ("Prüfer", o["technician"])]), Spacer(1, 6 * mm)]
        text = (f"Hiermit bestätigen wir den Erhalt des Prüfberichts zum Auftrag <b>{esc(o['order_no'])}</b> "
                f"über <b>{s['calibrations']}</b> geprüfte HART-Messstellen (davon {s['passed']} bestanden, "
                f"{s['failed']} nicht bestanden, {s['swaps']} Gerätetausch(e), {s['new_devices']} Neuaufnahme(n)). "
                "Die Ergebnisse wurden zur Kenntnis genommen; die geprüften Messstellen wurden in den "
                "dokumentierten Zustand übernommen.")
        story.append(Paragraph(text, _style("rt", 10, leading=14)))
        if failed:
            story += [Spacer(1, 3 * mm), Paragraph(
                f"Uns ist bekannt, dass folgende Messstellen die Prüfung <b>nicht bestanden</b> haben und "
                f"instand gesetzt oder ausgetauscht werden müssen: <b>{esc(', '.join(failed))}</b>.",
                _style("rf", 10, leading=14))]
        story.append(Spacer(1, 14 * mm))

        line = lambda label, w: Table([[""], [Paragraph(label, S_SMALL)]], colWidths=[w], rowHeights=[12 * mm, 5 * mm],
                                      style=[("LINEBELOW", (0, 0), (0, 0), 0.8, colors.black)])
        avail = PAGE_W - 2 * MARGIN
        story.append(Table([[line("Name in Druckbuchstaben", avail * 0.6), line("Datum", avail * 0.35)]],
                           colWidths=[avail * 0.62, avail * 0.38]))
        story.append(Spacer(1, 10 * mm))
        stamp = Table([[Paragraph("Firmenstempel", S_SMALL)]], colWidths=[avail * 0.45], rowHeights=[45 * mm],
                      style=[("BOX", (0, 0), (-1, -1), 0.8, colors.black), ("VALIGN", (0, 0), (-1, -1), "BOTTOM")])
        story.append(Table([[stamp, line("Unterschrift", avail * 0.45)]], colWidths=[avail * 0.5, avail * 0.5],
                           style=[("VALIGN", (0, 0), (-1, -1), "BOTTOM")]))
        story += [Spacer(1, 10 * mm),
                  Paragraph("Bitte unterschrieben und gestempelt zurücksenden (Post, Fax oder eingescannt per E-Mail).",
                            S_SMALL)]
        return story

    # ------------------------------------------------------------------ Erzeugen
    def _story(self) -> list:
        story = self._cover()
        for i, e in enumerate(self.entries, 1):
            story += self._device_page(i, e)
        return story + self._return_page()

    def _build_once(self, path: Path) -> int:
        counter = {"pages": 0}

        def on_page(canv, doc):
            counter["pages"] = doc.page
            self._decorate(canv, doc)
        doc = BaseDocTemplate(str(path), pagesize=A4, leftMargin=MARGIN, rightMargin=MARGIN,
                              topMargin=MARGIN, bottomMargin=MARGIN,
                              title=f"Prüfbericht {self.order['order_no']}", author=self.order["technician"],
                              subject=f"Kalibrierbericht {self.customer['name']}", creator="HART-Feldcommunicator")
        frame = Frame(MARGIN, MARGIN, PAGE_W - 2 * MARGIN, PAGE_H - 2 * MARGIN - 4 * mm, id="main")
        doc.addPageTemplates([PageTemplate(id="page", frames=[frame], onPage=on_page)])
        doc.build(self._story())
        return counter["pages"]

    def build(self, path: Path | str) -> dict:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.total_pages = self._build_once(path)         # Durchlauf 1: Seiten zählen/zuordnen
        self.total_pages = self._build_once(path)         # Durchlauf 2: mit Seitenzahlen
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        log.info("Prüfbericht erstellt: %s (%d Seiten)", path, self.total_pages)
        return {"path": str(path), "pages": self.total_pages, "sha256": digest,
                "device_pages": {k: v for k, v in self.pages.items() if k.startswith("dev")}}


def report_filename(report: dict) -> str:
    o, c = report["order"], report["customer"]
    safe = lambda s: re.sub(r"[^A-Za-z0-9_.-]+", "_", str(s)).strip("_")[:40]
    return f"Pruefbericht_{safe(o['order_no'])}_{safe(c['name'])}.pdf"


def generate_order_pdf(report: dict, out_dir: Path | str = config.REPORT_DIR) -> dict:
    return OrderReportPDF(report).build(Path(out_dir) / report_filename(report))


if __name__ == "__main__":
    import os
    os.environ.setdefault("HART_SIM", "1")
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    from demo_data import build_demo_order
    db, oid = build_demo_order(config.DATA_DIR / "demo")
    print(generate_order_pdf(db.order_report(oid), config.DATA_DIR / "demo" / "reports"))

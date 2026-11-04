import os
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors

def generate_anlage_pdf(pdf_name, kunde, standort, anlage, sig_path):
    doc = SimpleDocTemplate(pdf_name, pagesize=letter, rightMargin=30, leftMargin=30, topMargin=30, bottomMargin=30)
    story = []
    
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle('T1', parent=styles['Heading1'], fontSize=16, spaceAfter=15)
    section_style = ParagraphStyle('T2', parent=styles['Heading2'], fontSize=12, spaceBefore=10, spaceAfter=5)
    text_style = styles['Normal']
    
    # Kopfzeilen des PDF
    story.append(Paragraph(f"<b>PRÜFBERICHT: {anlage['typ'].upper()}</b>", title_style))
    story.append(Paragraph(f"<b>Anlage-ID / Ort:</b> {anlage['bezeichnung']}", section_style))
    story.append(Spacer(1, 10))
    
    # Stammdaten-Tabelle
    stammdaten = [
        [Paragraph("<b>Kunde / Betreiber:</b>", text_style), Paragraph(kunde, text_style)],
        [Paragraph("<b>Standort / Werk:</b>", text_style), Paragraph(standort, text_style)],
        [Paragraph("<b>Hersteller / Modell:</b>", text_style), Paragraph(anlage['hersteller'], text_style)]
    ]
    t_stamm = Table(stammdaten, colWidths=[130, 370])
    t_stamm.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), colors.lightgrey),
        ('GRID', (0,0), (-1,-1), 0.5, colors.white),
        ('PADDING', (0,0), (-1,-1), 5),
    ]))
    story.append(t_stamm)
    story.append(Spacer(1, 15))
    
    # Befunde
    story.append(Paragraph("<b>Prüfergebnisse Komponenten:</b>", section_style))
    story.append(Paragraph(f"• Antrieb & Mechanik: {'[X] i.O.' if anlage['antrieb_io'] else '[ ] n.i.O.'}", text_style))
    story.append(Paragraph(f"• Notentriegelung & Sicherheit: {'[X] i.O.' if anlage['notaus_io'] else '[ ] n.i.O.'}", text_style))
    story.append(Paragraph(f"• Gehäuse & Beschilderung: {'[X] i.O.' if anlage['allgemein_io'] else '[ ] n.i.O.'}", text_style))
    story.append(Spacer(1, 15))
    
    # Unterschrift einbinden
    story.append(Paragraph("<b>Rechtlicher Abschluss & Unterschrift:</b>", section_style))
    if os.path.exists(sig_path):
        try:
            img_sig = Image(sig_path, width=180, height=65)
            img_sig.hAlign = 'LEFT'
            story.append(img_sig)
        except:
            pass
            
    story.append(Spacer(1, 15))
    
    # Bilder einbetten
    if anlage['fotos']:
        story.append(Paragraph("<b>Zugehörige Mängelfotos dieser Anlage:</b>", section_style))
        for img_file in anlage['fotos']:
            if os.path.exists(img_file):
                try:
                    pdf_img = Image(img_file, width=220, height=150)
                    pdf_img.hAlign = 'LEFT'
                    story.append(pdf_img)
                    story.append(Spacer(1, 10))
                except:
                    pass
        
    doc.build(story)

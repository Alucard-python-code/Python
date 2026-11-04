from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from datetime import datetime, timedelta

class PDFGenerator:
    @staticmethod
    def create_pdf(filename, customer, exam_results, signature_path, months=12):
        doc = SimpleDocTemplate(filename, pagesize=letter, rightMargin=40, leftMargin=40, topMargin=40, bottomMargin=40)
        story = []
        styles = getSampleStyleSheet()

        story.append(Paragraph(f"<b>UVV-PRÜFPROTOKOLL NACH GESETZLICHEN VORGABEN</b>", styles['Title']))
        story.append(Spacer(1, 15))
        
        now = datetime.now()
        # Gleiche mathematische Annäherung wie in der Datenbank
        due_date = now + timedelta(days=months * 30)
        
        meta_text = f"<b>Prüfdatum:</b> {now.strftime('%d.%m.%Y %H:%M')}<br/>" \
                    f"<b>Nächste Prüfung fällig am:</b> <font color='red'><b>{due_date.strftime('%d.%m.%Y')}</b></font> (Intervall: {months} Monate)<br/>" \
                    f"<b>Firma:</b> {customer}<br/>" \
                    f"<b>Ansprechpartner:</b> {customer}<br/>" \
                    f"<b>Kunden-E-Mail:</b> {customer}"
        story.append(Paragraph(meta_text, styles['Normal']))
        story.append(Spacer(1, 20))

        for exam_type, results in exam_results.items():
            from checklist_data import CHECKLISTS
            info = CHECKLISTS[exam_type]
            
            story.append(Paragraph(f"<b>Prüfgegenstand: {info['title']}</b>", styles['Heading2']))
            story.append(Paragraph(f"<i>Norm-Grundlage: {info['norm']}</i>", styles['Italic']))
            story.append(Spacer(1, 5))

            table_data = [["Prüfkriterium / Vorgabe", "Status", "Bemerkung / Mängel"]]
            for res in results:
                table_data.append([res['frage'], res['status'], res['bemerkung']])

            t = Table (table_data, colWidths=[250, 100, 200])
            t.setStyle(TableStyle([
                ('BACKGROUND', (0,0), (-1,0), colors.grey),
                ('TEXTCOLOR', (0,0), (-1,0), colors.whitesmoke),
                ('ALIGN', (0,0), (-1,-1), 'LEFT'),
                ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
                ('BOTTOMPADDING', (0,0), (-1,0), 6),
                ('GRID', (0,0), (-1,-1), 0.5, colors.black),
                ('VALIGN', (0,0), (-1,-1), 'TOP'),
            ]))
            story.append(t)
            story.append(Spacer(1, 15))

        story.append(Spacer(1, 10))
        story.append(Paragraph("<b>Rechtsverbindliche Abnahme-Unterschrift Kunde:</b>", styles['Heading3']))
        story.append(Spacer(1, 5))
        try:
            story.append(Image(signature_path, width=200, height=100))
        except:
            story.append(Paragraph("[Handzeichen Grafikfehler]", styles['Normal']))
        
        story.append(Spacer(1, 30))
        disclaimer_style = ParagraphStyle('Disclaimer', parent=styles['Normal'], fontSize=7, textColor=colors.gray)
        disclaimer_text = "This is for informational purposes only. For medical advice or diagnosis, consult a professional. AI responses may include mistakes. " \
                          "Hinweis: Dieses Dokument ersetzt im Schadensfall nicht die behördliche Überprüfung der Originalkomponenten durch zertifizierte Sachverständige."
        story.append(Paragraph(disclaimer_text, disclaimer_style))

        doc.build(story)

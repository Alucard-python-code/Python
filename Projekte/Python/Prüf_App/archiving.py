import os
import zipfile
from datetime import datetime
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders

class ArchiveManager:
    def generate_archive_and_email(self, customer, pdf_path, signature_path):
        cust_id, name, company, email = customer
        date_str = datetime.now().strftime("%Y-%m-%d_%H-%M")
        
        zip_filename = f"UVV_Archiv_{company.replace(' ', '_')}_{date_str}.zip"
        
        # ZIP-Archiv schreiben
        with zipfile.ZipFile(zip_filename, 'w') as zipf:
            if os.path.exists(pdf_path):
                zipf.write(pdf_path, arcname=f"Pruefbericht_{date_str}.pdf")
            if os.path.exists(signature_path):
                zipf.write(signature_path, arcname=f"Kundenunterschrift_{date_str}.png")
        
        mail_success = self.send_email(email, zip_filename, name)
        return zip_filename, mail_success

    def send_email(self, recipient_email, attachment_path, customer_name):
        # ⚠️ Echte Zugangsdaten zum scharf Schalten eintragen
        smtp_server = "smtp.ihranbieter.de"
        smtp_port = 587
        sender_email = "ihre-pruef-app@domain.de"
        sender_password = "IhrPasswort"

        msg = MIMEMultipart()
        msg['From'] = sender_email
        msg['To'] = recipient_email
        msg['Subject'] = f"Ihr gesetzliches UVV-Prüfprotokoll"

        body = f"Hallo {customer_name},\n\nanbei erhalten Sie das digital archivierte Prüfprotokoll als ZIP-Datei.\n\nMit freundlichen Grüßen,\nIhr Prüfbetrieb"
        msg.attach(MIMEText(body, 'plain'))

        try:
            with open(attachment_path, "rb") as attachment:
                part = MIMEBase("application", "octet-stream")
                part.set_payload(attachment.read())
            encoders.encode_base64(part)
            part.add_header("Content-Disposition", f"attachment; filename={os.path.basename(attachment_path)}")
            msg.attach(part)

            # Entferne das '#' vor den nächsten 5 Zeilen um den Versand sofort aktiv zu schalten:
            # server = smtplib.SMTP(smtp_server, smtp_port)
            # server.starttls()
            # server.login(sender_email, sender_password)
            # server.send_message(msg)
            # server.quit()
            return True
        except Exception as e:
            print("Mail-Übertragungsfehler:", e)
            return False

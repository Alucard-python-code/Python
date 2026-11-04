from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QListWidget, QListWidgetItem, QMessageBox

class CustomerScreen(QWidget):
    def __init__(self, main_app):
        super().__init__()
        self.main_app = main_app
        layout = QVBoxLayout()

        layout.addWidget(QLabel("<h2>Kundenverwaltung & Dashboard</h2>"))
        
        # NEU: Live-Suchfeld für Kunden
        search_layout = QHBoxLayout()
        search_layout.addWidget(QLabel("🔍 Schnellsuche:"))
        self.txt_search = QLineEdit(placeholderText="Firma, Name oder E-Mail eingeben...")
        self.txt_search.textChanged.connect(self.filter_customers)
        search_layout.addWidget(self.txt_search)
        layout.addLayout(search_layout)
        
        self.customer_list = QListWidget()
        layout.addWidget(self.customer_list)
        
        btn_layout_top = QHBoxLayout()
        btn_select = QPushButton("Ausgewählten Kunden prüfen")
        btn_select.clicked.connect(self.select_customer)
        btn_history = QPushButton("📜 Prüfungs-Historie (Archiv) anzeigen")
        btn_history.clicked.connect(self.main_app.show_history_screen)
        
        btn_layout_top.addWidget(btn_select)
        btn_layout_top.addWidget(btn_history)
        layout.addLayout(btn_layout_top)

        layout.addWidget(QLabel("<h3>Neuen Kunden anlegen</h3>"))
        form_layout = QHBoxLayout()
        self.txt_name = QLineEdit(placeholderText="Name Ansprechpartner")
        self.txt_company = QLineEdit(placeholderText="Firmenname")
        self.txt_email = QLineEdit(placeholderText="Kunden-E-Mail")
        form_layout.addWidget(self.txt_name)
        form_layout.addWidget(self.txt_company)
        form_layout.addWidget(self.txt_email)
        layout.addLayout(form_layout)

        btn_add = QPushButton("Kunde speichern & Prüfung starten")
        btn_add.clicked.connect(self.add_customer)
        layout.addWidget(btn_add)

        self.setLayout(layout)

    def refresh_customers(self):
        self.customer_list.clear()
        self.all_customers = self.main_app.db.get_all_customers()
        for cust in self.all_customers:
            item = QListWidgetItem(f"Firma: {cust[2]} | Kontakt: {cust[1]} ({cust[3]})")
            item.setData(100, cust[0])
            self.customer_list.addItem(item)
        self.filter_customers()

    def filter_customers(self):
        search_text = self.txt_search.text().lower()
        for i in range(self.customer_list.count()):
            item = self.customer_list.item(i)
            item.setHidden(search_text not in item.text().lower())

    def select_customer(self):
        current_item = self.customer_list.currentItem()
        if current_item and not current_item.isHidden():
            customer_id = current_item.data(100)
            self.main_app.show_select_screen(customer_id)
        else:
            QMessageBox.warning(self, "Fehler", "Bitte wählen Sie einen sichtbaren Kunden aus.")

    def add_customer(self):
        name = self.txt_name.text().strip()
        company = self.txt_company.text().strip()
        email = self.txt_email.text().strip()
        if not name or not company or not email:
            QMessageBox.warning(self, "Fehler", "Alle Felder sind Pflichtfelder.")
            return
        
        cust_id = self.main_app.db.add_customer(name, company, email)
        self.txt_name.clear()
        self.txt_company.clear()
        self.txt_email.clear()
        self.txt_search.clear()
        self.main_app.show_select_screen(cust_id)

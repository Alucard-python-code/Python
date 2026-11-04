from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel, QScrollArea, QRadioButton, QButtonGroup, QHBoxLayout, QPushButton, QLineEdit
from checklist_data import CHECKLISTS

class ExamFormScreen(QWidget):
    def __init__(self, main_app):
        super().__init__()
        self.main_app = main_app
        self.current_type = None
        self.radio_groups = []
        self.comment_inputs = []

        self.layout = QVBoxLayout()
        self.title_label = QLabel()
        self.layout.addWidget(self.title_label)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll_content = QWidget()
        self.scroll_layout = QVBoxLayout(self.scroll_content)
        self.scroll.setWidget(self.scroll_content)
        self.layout.addWidget(self.scroll)

        btn_layout = QHBoxLayout()
        btn_next = QPushButton("Prüfung speichern & Weiter")
        btn_next.clicked.connect(self.save_and_continue)
        btn_layout.addWidget(btn_next)
        self.layout.addLayout(btn_layout)

        self.setLayout(self.layout)

    def load_exam_type(self, exam_type):
        self.current_type = exam_type
        for i in reversed(range(self.scroll_layout.count())): 
            self.scroll_layout.itemAt(i).widget().setParent(None)
        
        self.radio_groups.clear()
        self.comment_inputs.clear()

        data = CHECKLISTS[exam_type]
        self.title_label.setText(f"<h2>Prüfung: {data['title']}</h2><p><b>Norm-Grundlage:</b> {data['norm']}</p>")

        for item_text in data["items"]:
            item_widget = QWidget()
            item_box = QVBoxLayout(item_widget)
            item_box.addWidget(QLabel(f"👉 {item_text}"))

            rb_layout = QHBoxLayout()
            bg = QButtonGroup(item_widget)
            
            rb_ok = QRadioButton("Mängelfrei (OK)")
            rb_nok = QRadioButton("Mangel (NOK)")
            rb_na = QRadioButton("Nicht relevant")
            rb_ok.setChecked(True)

            bg.addButton(rb_ok, 1)
            bg.addButton(rb_nok, 2)
            bg.addButton(rb_na, 3)

            rb_layout.addWidget(rb_ok)
            rb_layout.addWidget(rb_nok)
            rb_layout.addWidget(rb_na)
            item_box.addLayout(rb_layout)

            comment = QLineEdit(placeholderText="Mangelbeschreibung / Maße / Bemerkung eingeben...")
            item_box.addWidget(comment)

            self.radio_groups.append(bg)
            self.comment_inputs.append(comment)
            self.scroll_layout.addWidget(item_widget)

    def save_and_continue(self):
        results = []
        data = CHECKLISTS[self.current_type]
        for idx, bg in enumerate(self.radio_groups):
            status_id = bg.checkedId()
            status_text = "OK" if status_id == 1 else ("Mangel" if status_id == 2 else "Entfällt")
            results.append({
                "frage": data["items"][idx],
                "status": status_text,
                "bemerkung": self.comment_inputs[idx].text().strip()
            })
        self.main_app.save_current_exam_result(results)

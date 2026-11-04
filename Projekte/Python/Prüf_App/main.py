import sys
from PyQt6.QtWidgets import QApplication, QMainWindow, QStackedWidget, QMessageBox
from database import Database
from gui_customer import CustomerScreen
from gui_select_exam import ExamSelectScreen
from gui_exam_form import ExamFormScreen
from gui_signature import SignatureScreen
from gui_history import HistoryScreen

class MainApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("UVV Prüfungs-Assistent PRO (Qt6)")
        self.resize(1000, 750)
        
        self.db = Database()
        self.current_customer_id = None
        self.selected_exams = []
        self.current_exam_index = 0
        self.exam_results = {}

        self.stacked_widget = QStackedWidget()
        self.setCentralWidget(self.stacked_widget)
        
        self.init_screens()
        self.show_customer_screen()

    def init_screens(self):
        self.customer_screen = CustomerScreen(self)
        self.select_screen = ExamSelectScreen(self)
        self.exam_form_screen = ExamFormScreen(self)
        self.signature_screen = SignatureScreen(self)
        self.history_screen = HistoryScreen(self)
        
        self.stacked_widget.addWidget(self.customer_screen)
        self.stacked_widget.addWidget(self.select_screen)
        self.stacked_widget.addWidget(self.exam_form_screen)
        self.stacked_widget.addWidget(self.signature_screen)
        self.stacked_widget.addWidget(self.history_screen)

    def show_customer_screen(self):
        self.customer_screen.refresh_customers()
        self.stacked_widget.setCurrentWidget(self.customer_screen)

    def show_select_screen(self, customer_id):
        self.current_customer_id = customer_id
        self.selected_exams = []
        self.current_exam_index = 0
        self.exam_results = {}
        self.stacked_widget.setCurrentWidget(self.select_screen)

    def show_history_screen(self):
        self.history_screen.refresh_history()
        self.stacked_widget.setCurrentWidget(self.history_screen)

    def start_exams(self, selected_types):
        if not selected_types:
            QMessageBox.warning(self, "Fehler", "Bitte wählen Sie mindestens eine Prüfungsart.")
            return
        self.selected_exams = selected_types
        self.current_exam_index = 0
        self.show_next_exam()

    def show_next_exam(self):
        if self.current_exam_index < len(self.selected_exams):
            exam_type = self.selected_exams[self.current_exam_index]
            self.exam_form_screen.load_exam_type(exam_type)
            self.stacked_widget.setCurrentWidget(self.exam_form_screen)
        else:
            self.stacked_widget.setCurrentWidget(self.signature_screen)

    def save_current_exam_result(self, results):
        exam_type = self.selected_exams[self.current_exam_index]
        self.exam_results[exam_type] = results
        self.current_exam_index += 1
        self.show_next_exam()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainApp()
    window.show()
    sys.exit(app.exec())

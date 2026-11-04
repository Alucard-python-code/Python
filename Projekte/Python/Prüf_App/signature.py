from PySide6.QtWidgets import QWidget
from PySide6.QtGui import QPainter, QPen, QImage
from PySide6.QtCore import Qt, QPoint

class SignaturePad(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(400, 150)
        self.image = QImage(self.size(), QImage.Format_RGB32)
        self.clear_canvas()
        self.last_point = QPoint()
        self.drawing = False

    def clear_canvas(self):
        self.image.fill(Qt.white)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.drawImage(0, 0, self.image)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.last_point = event.position().toPoint()
            self.drawing = True

    def mouseMoveEvent(self, event):
        if (event.buttons() & Qt.LeftButton) and self.drawing:
            painter = QPainter(self.image)
            painter.setPen(QPen(Qt.black, 3, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            painter.drawLine(self.last_point, event.position().toPoint())
            self.last_point = event.position().toPoint()
            self.update()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.drawing = False

    def save_signature(self, filename):
        self.image.save(filename, "PNG")

from PIL import ImageOps
from PySide6.QtCore import Qt, QRectF, Signal
from PySide6.QtGui import QPainter, QPixmap, QImage, QColor, QPen
from PySide6.QtWidgets import QWidget
from .widgets import png_bytes


class CropView(QWidget):
    positionChanged = Signal(float, float)

    def __init__(self):
        super().__init__()
        self.setMinimumHeight(180)
        self.setMaximumHeight(240)
        self.image = self.pixmap = None
        self.position, self.zoom, self.fit = (.5, .5), 1., "cover"
        self.area = QRectF()
        self.setCursor(Qt.CursorShape.CrossCursor)

    def set_image(self, image):
        self.image = image
        small = ImageOps.contain(image, (900, 400))
        self.pixmap = QPixmap.fromImage(QImage.fromData(png_bytes(small)))
        self.update()

    def crop_size(self):
        scale = max(640 / self.image.width, 128 / self.image.height) * self.zoom
        return 640 / scale, 128 / scale

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#080f19"))
        if self.pixmap is None:
            painter.end(); return
        factor = min(self.width()/self.image.width, self.height()/self.image.height)
        w, h = self.image.width * factor, self.image.height * factor
        self.area = QRectF((self.width()-w)/2, (self.height()-h)/2, w, h)
        painter.drawPixmap(self.area, self.pixmap, QRectF(self.pixmap.rect()))
        if self.fit == "cover":
            cw, ch = self.crop_size()
            x = self.area.x() + (self.image.width-cw) * self.position[0] * factor
            y = self.area.y() + (self.image.height-ch) * self.position[1] * factor
            crop = QRectF(x, y, cw*factor, ch*factor)
            dim = QColor(0, 0, 0, 150)
            painter.fillRect(QRectF(self.area.x(), self.area.y(), w, y-self.area.y()), dim)
            painter.fillRect(QRectF(self.area.x(), crop.bottom(), w, self.area.bottom()-crop.bottom()), dim)
            painter.fillRect(QRectF(self.area.x(), y, x-self.area.x(), crop.height()), dim)
            painter.fillRect(QRectF(crop.right(), y, self.area.right()-crop.right(), crop.height()), dim)
            painter.setPen(QPen(QColor("#64e6ca"), 2)); painter.drawRect(crop)
            for i in range(1, 5):
                xx = crop.x() + crop.width()*i/5
                painter.drawLine(int(xx), int(crop.top()), int(xx), int(crop.bottom()))
        painter.end()

    def point(self, event):
        if self.image is None or self.fit != "cover" or self.area.width() <= 0:
            return
        factor = self.area.width()/self.image.width
        cw, ch = self.crop_size()
        px = (event.position().x()-self.area.x())/factor
        py = (event.position().y()-self.area.y())/factor
        x = (px-cw/2)/max(.001, self.image.width-cw)
        y = (py-ch/2)/max(.001, self.image.height-ch)
        self.positionChanged.emit(max(0, min(1, x)), max(0, min(1, y)))

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.point(event)

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.MouseButton.LeftButton:
            self.point(event)

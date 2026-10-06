from __future__ import annotations

import copy
from .color_ui import ColorButton

from PIL import Image, ImageColor
from PySide6.QtCore import Qt, Signal, QRectF
from PySide6.QtGui import QPainter, QColor, QPixmap, QImage, QPen
from PySide6.QtWidgets import (QWidget, QDialog, QHBoxLayout, QVBoxLayout, QFormLayout, QLabel,
    QListWidget, QComboBox, QLineEdit, QSpinBox, QDoubleSpinBox, QPushButton, QFileDialog,
    QDialogButtonBox, QMessageBox)

from .extensions import METRICS, custom_image, validate_content
from .widgets import png_bytes


class DesignCanvas(QWidget):
    changed = Signal()
    selected = Signal(int)

    def __init__(self, screen):
        super().__init__()
        self.screen = screen
        self.index, self.anchor = -1, None
        self.setFixedSize(384, 384)
        self.values = {"cpu": 32, "ram": 61, "gpu": 48, "disk": 42, "cpu_temp": 53, "gpu_temp": 46, "download": 2500, "upload": 400}

    def paintEvent(self, event):
        p = QPainter(self)
        try:
            image = custom_image(self.screen, self.values)
            p.drawPixmap(self.rect(), QPixmap.fromImage(QImage.fromData(png_bytes(image))))
        except (ValueError, OSError):
            p.fillRect(self.rect(), QColor("#101b2b"))
        if 0 <= self.index < len(self.screen["elements"]):
            e = self.screen["elements"][self.index]
            p.setPen(QPen(QColor("#ffc879"), 2, Qt.PenStyle.DashLine))
            p.drawRect(QRectF(e["x"] * 3, e["y"] * 3, e["width"] * 3, e["height"] * 3))
        p.end()

    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            return
        x, y = event.position().x() / 3, event.position().y() / 3
        for i in range(len(self.screen["elements"])-1, -1, -1):
            e = self.screen["elements"][i]
            if e["x"] <= x < e["x"] + e["width"] and e["y"] <= y < e["y"] + e["height"]:
                self.index, self.anchor = i, (x-e["x"], y-e["y"])
                self.selected.emit(i)
                self.update()
                return

    def mouseMoveEvent(self, event):
        if self.anchor is not None and event.buttons() & Qt.MouseButton.LeftButton:
            e = self.screen["elements"][self.index]
            e["x"] = max(0, min(127, round(event.position().x()/3 - self.anchor[0])))
            e["y"] = max(0, min(127, round(event.position().y()/3 - self.anchor[1])))
            self.changed.emit()
            self.update()

    def mouseReleaseEvent(self, event):
        self.anchor = None


class DesignerDialog(QDialog):
    def __init__(self, parent, screen):
        super().__init__(parent)
        self.t = parent.t
        self.screen = copy.deepcopy(screen)
        self.screen.setdefault("elements", [])
        self.loading = False
        self.setWindowTitle(self.t("Diseñador de widgets", "Widget designer"))
        layout = QVBoxLayout(self)
        hint = QLabel(self.t("Arrastra los elementos para colocarlos. Vista de 128 × 128 ampliada; métricas de ejemplo.",
                            "Drag elements to position them. Enlarged 128 × 128 preview; sample metrics."))
        hint.setWordWrap(True)
        layout.addWidget(hint)
        row = QHBoxLayout()
        self.canvas = DesignCanvas(self.screen)
        self.canvas.selected.connect(self.select_canvas)
        self.canvas.changed.connect(self.load_element)
        row.addWidget(self.canvas, alignment=Qt.AlignmentFlag.AlignTop)
        column = QVBoxLayout()
        self.list = QListWidget()
        self.list.setMaximumHeight(100)
        self.list.currentRowChanged.connect(self.select)
        column.addWidget(self.list)
        buttons = QHBoxLayout()
        for text, kind in [("Text", "text"), ("Bar", "bar"), ("Image", "image")]:
            b = QPushButton(text)
            b.clicked.connect(lambda checked=False, k=kind: self.add(k))
            buttons.addWidget(b)
        column.addLayout(buttons)
        form = QFormLayout()
        self.fields = {}
        for key, label, low, high in [("x", "X", 0, 127), ("y", "Y", 0, 127), ("width", "Width", 1, 128), ("height", "Height", 1, 128), ("size", "Font size", 6, 64)]:
            w = QSpinBox(); w.setRange(low, high); w.valueChanged.connect(self.change)
            form.addRow(label, w); self.fields[key] = w
        self.text = QLineEdit(); self.text.textChanged.connect(self.change)
        self.color = ColorButton(t=self.t); self.color.textChanged.connect(self.change)
        self.metric_combo = QComboBox()
        for key, label in METRICS:
            self.metric_combo.addItem(label, key)
        self.metric_combo.currentIndexChanged.connect(self.change)
        self.maximum = QDoubleSpinBox(); self.maximum.setRange(.1, 1e12); self.maximum.valueChanged.connect(self.change)
        form.addRow("Text", self.text); form.addRow("Color", self.color); form.addRow("Bar metric", self.metric_combo); form.addRow("Bar maximum", self.maximum)
        column.addLayout(form)
        hint = QLabel("Dynamic text: {cpu}, {ram}, {gpu}, {disk}, {cpu_temp}, {gpu_temp}, {time}, {date}")
        hint.setWordWrap(True); hint.setMaximumWidth(310); column.addWidget(hint)
        row2 = QHBoxLayout()
        for text, callback in [("↑", lambda: self.move(-1)), ("↓", lambda: self.move(1)), ("Delete", self.remove), ("Choose image…", self.choose_image)]:
            b = QPushButton(text); b.clicked.connect(callback); row2.addWidget(b)
        column.addLayout(row2)
        row.addLayout(column)
        layout.addLayout(row)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText(self.t("Guardar diseño", "Save design"))
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(self.t("Cancelar", "Cancel"))
        buttons.accepted.connect(self.accept); buttons.rejected.connect(self.reject); layout.addWidget(buttons)
        self.refresh()

    def refresh(self, index=0):
        self.list.blockSignals(True); self.list.clear()
        for i, e in enumerate(self.screen["elements"]):
            self.list.addItem(f"{i+1} · {e['type']} · {e.get('text') or e.get('metric') or 'Image'}")
        self.list.blockSignals(False)
        self.list.setCurrentRow(min(index, len(self.screen["elements"])-1))
        self.canvas.update()

    def select_canvas(self, index):
        self.list.setCurrentRow(index)

    def select(self, index):
        self.canvas.index = index
        self.load_element()
        self.canvas.update()

    def load_element(self):
        i = self.canvas.index
        if not 0 <= i < len(self.screen["elements"]):
            return
        self.loading = True
        e = self.screen["elements"][i]
        for key, w in self.fields.items():
            w.setValue(e.get(key, 16))
        self.text.setText(e.get("text", "")); self.color.setText(e.get("color", "#64e6ca"))
        self.metric_combo.setCurrentIndex(self.metric_combo.findData(e.get("metric", "cpu")))
        self.maximum.setValue(e.get("maximum", 100))
        self.loading = False

    def change(self, *_):
        i = self.canvas.index
        if self.loading or not 0 <= i < len(self.screen["elements"]):
            return
        e = self.screen["elements"][i]
        e.update({key: w.value() for key, w in self.fields.items()})
        e.update(text=self.text.text(), metric=self.metric_combo.currentData(), maximum=self.maximum.value())
        try:
            ImageColor.getrgb(self.color.text())
            e["color"] = self.color.text()
        except ValueError:
            pass
        self.canvas.update()

    def add(self, kind):
        if len(self.screen["elements"]) >= 20:
            return
        self.screen["elements"].append({"type": kind, "x": 8, "y": 8, "width": 112, "height": 24,
            "size": 16, "color": "#64e6ca", "text": "CPU {cpu}%" if kind == "text" else "", "metric": "cpu", "maximum": 100, "path": ""})
        self.refresh(len(self.screen["elements"])-1)
        if kind == "image":
            self.choose_image()

    def choose_image(self):
        i = self.canvas.index
        if i < 0 or self.screen["elements"][i]["type"] != "image":
            return
        path, _ = QFileDialog.getOpenFileName(self, "Image", "", "Images (*.png *.jpg *.jpeg *.webp *.bmp)")
        if path:
            try:
                with Image.open(path) as image:
                    image.verify()
                self.screen["elements"][i]["path"] = path
                self.canvas.update()
            except Exception as error:
                QMessageBox.warning(self, "Image", str(error))

    def remove(self):
        i = self.canvas.index
        if i >= 0:
            self.screen["elements"].pop(i); self.refresh(max(0, i-1))

    def move(self, offset):
        i = self.canvas.index; j = i + offset
        if 0 <= i < len(self.screen["elements"]) and 0 <= j < len(self.screen["elements"]):
            items = self.screen["elements"]; items[i], items[j] = items[j], items[i]; self.refresh(j)

    def accept(self):
        try:
            validate_content(self.screen)
            super().accept()
        except Exception as error:
            QMessageBox.warning(self, self.windowTitle(), str(error))

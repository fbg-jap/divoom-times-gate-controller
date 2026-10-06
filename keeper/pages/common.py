from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QPushButton, QSpinBox

from ..content import EXTRA_KINDS


KINDS = [
    ("empty", "Sin gestionar", "Unmanaged"), ("media", "Imagen / GIF", "Image / GIF"),
    ("text", "Texto", "Text"), ("clock", "Reloj", "Clock"), ("pc", "Estadísticas del PC", "PC metrics"),
    ("weather", "Tiempo", "Weather"), ("countdown", "Cuenta atrás", "Countdown"),
    ("calendar", "Calendario ICS", "ICS calendar"), ("service", "Estado de servicio", "Service health"),
    ("native", "Mantener modo nativo", "Keep native mode"), ("pc_native", "Monitor PC nativo · experimental", "Native PC monitor · experimental"),
] + EXTRA_KINDS

def box():
    frame = QFrame()
    frame.setObjectName("card")
    return frame


def button(text, callback, primary=False):
    btn = QPushButton(text)
    btn.setCursor(Qt.CursorShape.PointingHandCursor)
    if primary:
        btn.setObjectName("primary")
    btn.clicked.connect(callback)
    return btn


def integer(low, high, value=0):
    control = QSpinBox()
    control.setRange(low, high)
    control.setValue(value)
    return control

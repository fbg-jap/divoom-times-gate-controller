"""Visual color selection shared by desktop editors and ambient lighting."""
from PIL import ImageColor
from PySide6.QtCore import Qt, Signal, QRectF, QSize
from PySide6.QtGui import QColor, QPainter, QPen, QLinearGradient, QPixmap, QIcon
from PySide6.QtWidgets import (QWidget, QPushButton, QDialog, QDialogButtonBox, QLabel,
    QVBoxLayout, QHBoxLayout, QGridLayout, QSlider, QComboBox, QCheckBox, QButtonGroup)
from .lighting import PALETTE, PRESETS, defaults


def color_name(color, t):
    return next((t(es, en) for es, en, code in PALETTE if code == color.name()), t('Personalizado', 'Custom'))


def swatch_icon(color, size=24):
    image = QPixmap(size, size); image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image); painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(QPen(QColor('#8090a0'), 1)); painter.setBrush(color)
    painter.drawRoundedRect(QRectF(1, 1, size-2, size-2), 5, 5); painter.end()
    return QIcon(image)


class ColorPlane(QWidget):
    changed = Signal(QColor)
    def __init__(self, color):
        super().__init__(); self.setMinimumSize(260, 180); self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAccessibleName('Saturación y luminosidad: arrastra o usa las flechas')
        self.set_color(color)

    def set_color(self, color):
        self.hue = max(0, color.hsvHueF()); self.saturation = color.hsvSaturationF(); self.value = color.valueF(); self.update()

    def selected(self):
        return QColor.fromHsvF(self.hue, self.saturation, self.value)

    def paintEvent(self, event):
        p = QPainter(self); r = self.rect()
        g = QLinearGradient(0, 0, r.width(), 0); g.setColorAt(0, QColor('white')); g.setColorAt(1, QColor.fromHsvF(self.hue, 1, 1)); p.fillRect(r, g)
        g = QLinearGradient(0, 0, 0, r.height()); g.setColorAt(0, QColor(0, 0, 0, 0)); g.setColorAt(1, QColor('black')); p.fillRect(r, g)
        x, y = self.saturation*(r.width()-1), (1-self.value)*(r.height()-1)
        p.setBrush(Qt.BrushStyle.NoBrush); p.setPen(QPen(QColor('black'), 4)); p.drawEllipse(QRectF(x-6, y-6, 12, 12))
        p.setPen(QPen(QColor('white'), 2)); p.drawEllipse(QRectF(x-6, y-6, 12, 12))

    def pick(self, position):
        self.saturation = max(0, min(1, position.x()/max(1, self.width()-1)))
        self.value = max(0, min(1, 1-position.y()/max(1, self.height()-1)))
        self.changed.emit(self.selected()); self.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton: self.setFocus(); self.pick(event.position())

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.MouseButton.LeftButton: self.pick(event.position())

    def keyPressEvent(self, event):
        direction = {Qt.Key.Key_Left: (-.02, 0), Qt.Key.Key_Right: (.02, 0), Qt.Key.Key_Up: (0, .02), Qt.Key.Key_Down: (0, -.02)}.get(event.key())
        if direction:
            self.saturation = max(0, min(1, self.saturation+direction[0])); self.value = max(0, min(1, self.value+direction[1]))
            self.changed.emit(self.selected()); self.update()
        else: super().keyPressEvent(event)


class ColorDialog(QDialog):
    recent = []
    def __init__(self, color, parent=None, t=lambda es, en: es):
        super().__init__(parent); self.t = t; self.color = QColor(color)
        self.setWindowTitle(t('Elige un color', 'Choose a color')); self.setMinimumWidth(360)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(t('Arrastra para elegir el tono y su intensidad', 'Drag to choose a shade and its intensity')))
        self.plane = ColorPlane(color); layout.addWidget(self.plane)
        self.hue = QSlider(Qt.Orientation.Horizontal); self.hue.setRange(0, 359); self.hue.setValue(max(0, color.hsvHue()))
        self.hue.setAccessibleName(t('Tono', 'Hue'))
        self.hue.setStyleSheet('QSlider::groove:horizontal {height:14px;border-radius:7px;background:qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 red,stop:0.167 yellow,stop:0.333 lime,stop:0.5 cyan,stop:0.667 blue,stop:0.833 magenta,stop:1 red);} QSlider::handle:horizontal {background:white;border:2px solid #293447;width:16px;margin:-4px 0;border-radius:7px;}')
        layout.addWidget(self.hue); self.sample = QLabel(); self.sample.setMinimumHeight(48); layout.addWidget(self.sample)
        grid = QGridLayout()
        for i, (es, en, code) in enumerate(PALETTE):
            b = QPushButton(); b.setIcon(swatch_icon(QColor(code), 28)); b.setIconSize(QSize(28, 28)); b.setToolTip(t(es, en)); b.setAccessibleName(t(es, en)); b.setMinimumSize(42, 38)
            b.clicked.connect(lambda checked=False, value=code: self.choose(QColor(value))); grid.addWidget(b, i//8, i%8)
        layout.addLayout(grid)
        if self.recent:
            layout.addWidget(QLabel(t('Colores recientes', 'Recent colors'))); row = QHBoxLayout()
            for code in self.recent:
                b = QPushButton(); b.setIcon(swatch_icon(QColor(code))); b.setAccessibleName(t('Color reciente', 'Recent color')); b.clicked.connect(lambda checked=False, value=code: self.choose(QColor(value))); row.addWidget(b)
            layout.addLayout(row)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText(t('Usar color', 'Use color')); buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(t('Cancelar', 'Cancel'))
        buttons.accepted.connect(self.accept); buttons.rejected.connect(self.reject); layout.addWidget(buttons)
        self.plane.changed.connect(self.update_sample); self.hue.valueChanged.connect(self.change_hue); self.update_sample(color)

    def change_hue(self, hue):
        self.plane.hue = hue/360; self.plane.update(); self.update_sample(self.plane.selected())

    def choose(self, color):
        self.plane.set_color(color); self.hue.blockSignals(True); self.hue.setValue(max(0, color.hsvHue())); self.hue.blockSignals(False); self.update_sample(color)

    def update_sample(self, color):
        self.color = QColor(color)
        foreground = '#101720' if color.lightnessF() > .55 else '#ffffff'
        self.sample.setText(color_name(color, self.t)); self.sample.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.sample.setStyleSheet(f'background:{color.name()};color:{foreground};border:1px solid #8090a0;border-radius:8px;padding:8px;')

    def accept(self):
        ColorDialog.recent = [self.color.name(), *[c for c in self.recent if c != self.color.name()]][:8]
        super().accept()


class ColorButton(QPushButton):
    textChanged = Signal(str)
    def __init__(self, value='#64e6ca', parent=None, t=lambda es, en: es):
        super().__init__(parent); self.t = t; self._color = None; self.setMinimumWidth(138); self.setIconSize(QSize(24, 24)); self.setText(value)
        self.clicked.connect(self.choose)

    def text(self):
        return self._color.name()

    def setText(self, value):
        color = QColor(*ImageColor.getrgb(value)[:3])
        changed = self._color != color; self._color = color
        super().setText(color_name(color, self.t)); self.setIcon(swatch_icon(color)); self.setToolTip(self.t('Elegir color…', 'Choose color…')); self.setAccessibleName(self.t('Elegir color: ', 'Choose color: ')+color_name(color, self.t))
        if changed: self.textChanged.emit(color.name())

    def choose(self):
        dialog = ColorDialog(self._color, self, self.t)
        if dialog.exec() == QDialog.DialogCode.Accepted: self.setText(dialog.color.name())


class LightingPreview(QWidget):
    def __init__(self, read):
        super().__init__(); self.read = read; self.setMinimumHeight(142); self.setAccessibleName('Vista de color y zonas del Times Gate')

    def paintEvent(self, event):
        s = self.read(); p = QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        width = self.width(); color = QColor(s['color']); color.setAlphaF(s['brightness']/100 if s['on'] else 0)
        gradient = QLinearGradient(15, 0, width-15, 0)
        for stop, code in [(0, '#ff5263'), (.25, '#ffc879'), (.5, '#64e6ca'), (.75, '#5295ff'), (1, '#ff70bd')]:
            c = QColor(code); c.setAlphaF(color.alphaF()); gradient.setColorAt(stop, c)
        brush = gradient if s['cycle'] else color
        p.setPen(Qt.PenStyle.NoPen); p.setBrush(QColor('#0b1119')); p.drawRoundedRect(QRectF(6, 8, width-12, 122), 18, 18)
        if s['zone'] in (0, 2): p.setBrush(brush); p.drawRoundedRect(QRectF(19, 100, width-38, 17), 7, 7)
        tile = (width-46)/5
        for i in range(5):
            x = 16+i*(tile+3)
            p.setPen(QPen(brush if s['zone'] in (0, 1) else QColor('#344056'), 4)); p.setBrush(QColor('#172335')); p.drawRoundedRect(QRectF(x, 24, tile-5, 64), 9, 9)
            p.setPen(QColor('#91a5bc')); p.drawText(QRectF(x, 24, tile-5, 64), Qt.AlignmentFlag.AlignCenter, str(i+1))
        p.setPen(Qt.PenStyle.NoPen); p.setBrush(QColor('#e8f3ff') if s['keys'] else QColor('#344056')); p.drawRoundedRect(QRectF(width/2-12, 121, 24, 3), 1, 1)


class LightingPanel(QWidget):
    applyRequested = Signal()
    def __init__(self, parent=None, t=lambda es, en: es):
        super().__init__(parent); self.t = t
        layout = QVBoxLayout(self); layout.addWidget(QLabel(t('Iluminación RGB', 'RGB lighting')))
        self.color = ColorButton(t=t); self.brightness = QSlider(Qt.Orientation.Horizontal); self.brightness.setRange(0, 100); self.brightness.setValue(50); self.brightness.setAccessibleName(t('Brillo RGB', 'RGB brightness'))
        self.zone = QComboBox(); self.zone.addItems([t('Todas las zonas', 'All zones'), t('Bordes', 'Edges'), t('Luz trasera', 'Backlight')])
        self.on = QCheckBox(t('Iluminación encendida', 'Lighting on')); self.on.setChecked(True)
        self.cycle = QCheckBox(t('Ciclo multicolor', 'Color cycle')); self.keys = QCheckBox(t('Luz de teclas', 'Key light')); self.keys.setChecked(True)
        self.effects = QButtonGroup(self); self.effects.setExclusive(True)
        self.preview = LightingPreview(self.settings); layout.addWidget(self.preview)
        row = QHBoxLayout(); row.addWidget(self.color); row.addWidget(self.zone); row.addStretch(); row.addWidget(self.on); layout.addLayout(row)
        row = QHBoxLayout(); row.addWidget(QLabel(t('Brillo', 'Brightness'))); row.addWidget(self.brightness); self.percent = QLabel('50%'); row.addWidget(self.percent); layout.addLayout(row)
        presets = QGridLayout()
        for i, (es, en, color, brightness, cycle) in enumerate(PRESETS):
            b = QPushButton(t(es, en)); b.setIcon(swatch_icon(QColor(color))); b.clicked.connect(lambda checked=False, n=i: self.preset(n)); presets.addWidget(b, i//3, i%3)
        layout.addLayout(presets); layout.addWidget(QLabel(t('Efecto del dispositivo', 'Device effect')))
        grid = QGridLayout()
        for i in range(12):
            b = QPushButton(t(f'Efecto {i+1}', f'Effect {i+1}')); b.setCheckable(True); b.setMinimumHeight(40); self.effects.addButton(b, i); grid.addWidget(b, i//6, i%6)
            b.setStyleSheet('QPushButton:checked {background:#24524c;color:#aaffdf;border:2px solid #64e6ca;}')
        self.effects.button(0).setChecked(True); layout.addLayout(grid)
        row = QHBoxLayout(); row.addWidget(self.cycle); row.addWidget(self.keys); row.addStretch(); layout.addLayout(row)
        note = QLabel(t('Vista de color, brillo y zonas. La animación de cada efecto depende del firmware; aplícalo para verlo en el dispositivo.', 'Color, brightness and zone preview. Each effect animation depends on firmware; apply it to see it on the device.')); note.setWordWrap(True); layout.addWidget(note)
        apply = QPushButton(t('Aplicar iluminación', 'Apply lighting')); apply.setObjectName('primary'); apply.clicked.connect(self.applyRequested); layout.addWidget(apply)
        self.color.textChanged.connect(self.refresh); self.brightness.valueChanged.connect(self.refresh); self.zone.currentIndexChanged.connect(self.refresh)
        for b in [self.on, self.cycle, self.keys]: b.toggled.connect(self.refresh)

    def settings(self):
        return dict(color=self.color.text(), brightness=self.brightness.value(), effect=max(0, self.effects.checkedId()), zone=self.zone.currentIndex(), on=self.on.isChecked(), cycle=self.cycle.isChecked(), keys=self.keys.isChecked())

    def set_settings(self, value):
        s = {**defaults(), **value}; self.color.setText(s['color']); self.brightness.setValue(s['brightness']); self.zone.setCurrentIndex(s['zone']); self.effects.button(s['effect']).setChecked(True)
        self.on.setChecked(s['on']); self.cycle.setChecked(s['cycle']); self.keys.setChecked(s['keys']); self.refresh()

    def preset(self, index):
        _, _, color, brightness, cycle = PRESETS[index]; self.color.setText(color); self.brightness.setValue(brightness); self.cycle.setChecked(cycle); self.on.setChecked(True)

    def refresh(self, *_):
        self.percent.setText(f'{self.brightness.value()}%'); self.preview.update()

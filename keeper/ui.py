from __future__ import annotations

import copy
from datetime import datetime, timedelta
import json
import os
from pathlib import Path
import queue
import sys

from PySide6.QtCore import Qt, QTimer, QDateTime, QTime, QSize, QUrl
from PySide6.QtGui import QColor, QDesktopServices, QIcon, QImage, QMovie, QPainter, QPixmap
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDateTimeEdit, QDialog, QDialogButtonBox,
    QDoubleSpinBox, QFileDialog, QFormLayout, QFrame, QGridLayout, QHBoxLayout,
    QInputDialog, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMainWindow,
    QMenu, QMessageBox, QPlainTextEdit, QPushButton, QScrollArea, QSlider,
    QSpinBox, QStackedWidget, QSystemTrayIcon, QTableWidget, QTableWidgetItem,
    QTextEdit, QTimeEdit, QVBoxLayout, QWidget,
)

from .color_ui import ColorButton, LightingPanel
from .lighting import payload as lighting_payload
from .config import device, slot, uid
from .content import PC_VIEWS, EXTRA_KINDS, assets, composition, empty_playlists
from . import __version__
from .protocol import valid_ip


KINDS = [
    ("empty", "Sin gestionar", "Unmanaged"), ("media", "Imagen / GIF", "Image / GIF"),
    ("text", "Texto", "Text"), ("clock", "Reloj", "Clock"), ("pc", "Estadísticas del PC", "PC metrics"),
    ("weather", "Tiempo", "Weather"), ("countdown", "Cuenta atrás", "Countdown"),
    ("calendar", "Calendario ICS", "ICS calendar"), ("service", "Estado de servicio", "Service health"),
    ("native", "Mantener modo nativo", "Keep native mode"), ("pc_native", "Monitor PC nativo · experimental", "Native PC monitor · experimental"),
] + EXTRA_KINDS


def application_icon():
    pixmap = QPixmap(64, 64)
    pixmap.fill(QColor("#101827"))
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    for i, height in enumerate([21, 32, 43, 32, 21]):
        painter.setBrush(QColor("#68e6c4" if i == 2 else "#7199f5"))
        painter.drawRoundedRect(7 + i * 11, (64 - height) // 2, 7, height, 3, 3)
    painter.end()
    return QIcon(pixmap)


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


class Window(QMainWindow):
    def __init__(self, store, engine, demo=False, tray=True):
        super().__init__()
        self.store, self.engine, self.demo = store, engine, demo
        self.lang = store.snapshot().get("language", "es")
        self.selected = 0
        self.extra_drafts = {}
        self.loading = False
        self.dirty = False
        self.movies = []
        self.tray = None
        self.quitting = False
        self.statuses = {}
        self.health_states = {}
        self.setWindowTitle("Divoom Keeper Studio" + (" · DEMO" if demo else ""))
        self.setWindowIcon(application_icon())
        self.resize(1440, 940)
        self.setMinimumSize(1120, 760)
        self.build()
        self.apply_theme()
        self.load_devices()
        self.refresh_lists()
        if tray and QSystemTrayIcon.isSystemTrayAvailable():
            self.tray = QSystemTrayIcon(self.windowIcon(), self)
            self.tray.setToolTip("Divoom Keeper Studio")
            menu = QMenu()
            menu.addAction(self.t("Abrir Studio", "Open Studio"), self.reveal)
            menu.addAction(self.t("Enviar composición", "Send layout"), self.send_all)
            menu.addAction(self.t("Restaurar composición", "Restore layout"), lambda: self.job("resume"))
            menu.addSeparator()
            menu.addAction(self.t("Salir", "Quit"), self.quit_app)
            self.tray.setContextMenu(menu)
            self.tray.activated.connect(lambda reason: self.reveal() if reason == QSystemTrayIcon.ActivationReason.DoubleClick else None)
            self.tray.show()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.poll)
        self.timer.start(150)
        if os.name == "nt" and not demo:
            import ctypes
            from ctypes import wintypes
            register = ctypes.windll.wtsapi32.WTSRegisterSessionNotification
            register.argtypes = [wintypes.HWND, wintypes.DWORD]
            register.restype = wintypes.BOOL
            register(int(self.winId()), 0)
        if store.migration_note:
            self.toast(store.migration_note)

    def nativeEvent(self, event_type, message):
        if os.name == "nt" and not self.demo:
            import ctypes
            from ctypes import wintypes
            msg = ctypes.cast(int(message), ctypes.POINTER(wintypes.MSG)).contents
            if msg.message == 0x02B1 and msg.wParam in (7, 8):
                self.engine.submit("session_lock", locked=msg.wParam == 7)
        return super().nativeEvent(event_type, message)

    def t(self, es, en):
        return en if self.lang == "en" else es

    def job(self, action, **kwargs):
        self.engine.submit(action, self.store.snapshot()["active_device"], **kwargs)

    def toast(self, text):
        self.statusBar().showMessage(text, 12000)

    def hint(self, text):
        label = QLabel(text)
        label.setWordWrap(True)
        label.setObjectName("muted")
        label.setTextFormat(Qt.TextFormat.PlainText)
        return label

    def page(self, title, subtitle):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(28, 24, 28, 20)
        layout.setSpacing(18)
        heading = QLabel(title)
        heading.setObjectName("heading")
        layout.addWidget(heading)
        layout.addWidget(self.hint(subtitle))
        scroller = QScrollArea()
        scroller.setWidgetResizable(True)
        scroller.setFrameShape(QFrame.Shape.NoFrame)
        scroller.setWidget(page)
        self.pages.addWidget(scroller)
        return layout

    def build(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(206)
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(20, 28, 20, 20)
        brand = QLabel("KEEPER")
        brand.setObjectName("brand")
        side.addWidget(brand)
        side.addWidget(self.hint("S T U D I O   /   " + __version__))
        side.addSpacing(32)
        self.nav = QListWidget()
        self.nav.setObjectName("navigation")
        for label in [self.t("Pantallas", "Screens"), self.t("Escenas", "Scenes"), self.t("Dispositivo", "Device"),
                      self.t("Herramientas", "Tools"), self.t("Horarios", "Schedules"), self.t("Actividad", "Activity"),
                      self.t("Ajustes", "Settings"), self.t("Automatizaciones", "Automations"), self.t("Integraciones", "Integrations")]:
            item = QListWidgetItem(label)
            item.setSizeHint(QSize(160, 42))
            self.nav.addItem(item)
        side.addWidget(self.nav)
        side.addWidget(self.hint(self.t("Cinco pantallas.\nTu propio espacio.", "Five screens.\nYour own space.")))
        side.addSpacing(12)
        side.addWidget(self.hint("DEMO · OFFLINE" if self.demo else "DIVOOM TIMES GATE"))
        root.addWidget(sidebar)
        workspace = QVBoxLayout()
        workspace.setSpacing(0)
        top = QFrame()
        top.setObjectName("topbar")
        top_layout = QHBoxLayout(top)
        top_layout.setContentsMargins(28, 16, 28, 16)
        top_layout.addWidget(self.hint(self.t("ESPACIO DE TRABAJO", "WORKSPACE")))
        top_layout.addStretch()
        self.health_label = QLabel(self.t("●  Sin comprobar", "●  Not checked"))
        self.health_label.setObjectName("badge")
        top_layout.addWidget(self.health_label)
        self.device_picker = QComboBox()
        self.device_picker.setMinimumWidth(230)
        self.device_picker.currentIndexChanged.connect(self.device_changed)
        top_layout.addWidget(self.device_picker)
        workspace.addWidget(top)
        self.pages = QStackedWidget()
        workspace.addWidget(self.pages)
        root.addLayout(workspace, 1)
        self.build_screens()
        self.build_scenes()
        self.build_device()
        self.build_tools()
        self.build_schedules()
        self.build_activity()
        self.build_settings()
        from .extra_ui import AutomationPanel, IntegrationPanel
        auto_layout = self.page(self.t("Automatizaciones", "Automations"), self.t("Trabajo, avisos y escenas que responden a tu PC.", "Focus sessions, notifications and scenes that react to your PC."))
        self.automation_panel = AutomationPanel(self); auto_layout.addWidget(self.automation_panel)
        integration_layout = self.page(self.t("Integraciones", "Integrations"), self.t("Conecta tus herramientas y fuentes de datos.", "Connect your tools and data sources."))
        self.integration_panel = IntegrationPanel(self); integration_layout.addWidget(self.integration_panel)
        self.nav.currentRowChanged.connect(self.pages.setCurrentIndex)
        self.nav.setCurrentRow(0)
        self.statusBar().setSizeGripEnabled(False)

    def build_screens(self):
        layout = self.page(self.t("Tu composición", "Your layout"), self.t(
            "Combina imágenes, animaciones y datos en las cinco pantallas. Selecciona una para editarla.",
            "Mix images, animations and live data across five screens. Select a screen to edit it."))
        actions = QHBoxLayout()
        self.auto = QCheckBox(self.t("Actualización automática", "Automatic updates"))
        self.auto.toggled.connect(self.toggle_auto)
        actions.addWidget(self.auto)
        self.delivery = self.hint(self.t("Listo para configurar", "Ready to configure"))
        actions.addWidget(self.delivery, 1)
        actions.addWidget(button(self.t("Panorámica…", "Panorama…"), self.open_panorama))
        actions.addWidget(button(self.t("Restaurar composición", "Restore layout"), lambda: self.job("resume")))
        actions.addWidget(button(self.t("Enviar todo", "Send all"), self.send_all, True))
        layout.addLayout(actions)
        cards = QHBoxLayout()
        cards.setSpacing(12)
        self.panel_buttons, self.panel_images, self.panel_titles = [], [], []
        for i in range(5):
            card = box()
            card.setMinimumWidth(150)
            vertical = QVBoxLayout(card)
            vertical.setContentsMargins(12, 14, 12, 14)
            header = button(f"0{i + 1}   ·   " + self.t("PANTALLA", "SCREEN"), lambda checked=False, index=i: self.select_panel(index))
            header.setObjectName("panelHeader")
            vertical.addWidget(header)
            image = QLabel()
            image.setFixedSize(140, 140)
            image.setAlignment(Qt.AlignmentFlag.AlignCenter)
            image.setObjectName("preview")
            vertical.addWidget(image, alignment=Qt.AlignmentFlag.AlignHCenter)
            title = self.hint("—")
            title.setAlignment(Qt.AlignmentFlag.AlignCenter)
            vertical.addWidget(title)
            vertical.addWidget(button(self.t("Editar", "Edit"), lambda checked=False, index=i: self.select_panel(index)))
            cards.addWidget(card, 1)
            self.panel_buttons.append(header)
            self.panel_images.append(image)
            self.panel_titles.append(title)
        layout.addLayout(cards)
        editor = box()
        edit = QVBoxLayout(editor)
        edit.setContentsMargins(22, 18, 22, 18)
        self.editor_title = QLabel()
        self.editor_title.setObjectName("section")
        editor_heading = QHBoxLayout()
        editor_heading.addWidget(self.editor_title)
        editor_heading.addStretch()
        editor_heading.addWidget(button(self.t("Lista de reproducción…", "Playlist…"), self.open_playlist))
        edit.addLayout(editor_heading)
        self.playlist_hint = self.hint("")
        edit.addWidget(self.playlist_hint)
        common = QGridLayout()
        self.kind = QComboBox()
        for key, es, en in KINDS:
            self.kind.addItem(self.t(es, en), key)
        self.kind.currentIndexChanged.connect(self.kind_changed)
        self.slot_title = QLineEdit()
        self.slot_title.setPlaceholderText(self.t("Título opcional", "Optional title"))
        self.refresh = integer(5, 86400, 30)
        self.refresh.setSuffix(" s")
        common.addWidget(self.kind, 0, 0)
        common.addWidget(self.slot_title, 0, 1)
        common.addWidget(self.hint(self.t("Actualizar cada", "Refresh every")), 0, 2)
        common.addWidget(self.refresh, 0, 3)
        edit.addLayout(common)
        self.fields = QStackedWidget()
        self.fields.setObjectName("slotFields")
        self.fields.setMinimumHeight(135)
        self.kind_pages = {}
        for key, _, _ in KINDS:
            p = QWidget()
            f = QFormLayout(p)
            f.setContentsMargins(0, 12, 0, 4)
            f.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
            self.kind_pages[key] = self.fields.addWidget(p)
            if key in {"empty", "native"}:
                f.addRow(self.hint(self.t("Esta pantalla no recibe contenido automático. Conserva lo que muestre el dispositivo.",
                                         "This screen receives no automatic uploads. Its existing device content is preserved.")))
            elif key == "media":
                self.media_path = QLineEdit()
                self.media_path.setPlaceholderText(self.t("Selecciona una imagen o GIF", "Choose an image or GIF"))
                row = QHBoxLayout()
                row.addWidget(self.media_path, 1)
                row.addWidget(button(self.t("Elegir archivo…", "Choose file…"), self.choose_media))
                f.addRow(self.t("Archivo", "File"), row)
                self.fit = QComboBox()
                for es, en, value in [("Encajar", "Fit", "contain"), ("Recortar", "Crop", "cover"), ("Estirar · original", "Stretch · legacy", "stretch")]:
                    self.fit.addItem(self.t(es, en), value)
                self.frame_step = integer(1, 100, 1)
                row = QHBoxLayout()
                row.addWidget(self.fit)
                row.addWidget(self.hint(self.t("Usar 1 de cada N fotogramas", "Use 1 in every N frames")))
                row.addWidget(self.frame_step)
                f.addRow(self.t("Ajuste", "Sizing"), row)
                f.addRow(self.hint(self.t("Los archivos se copian a tu biblioteca al guardar. Los clips panorámicos conservan su velocidad y encuadre propios.",
                                         "Files are copied into your library on save. Up to 600 frames per upload.")))
            elif key == "text":
                self.text_content = QPlainTextEdit()
                self.text_content.setMaximumHeight(90)
                self.font_size = integer(10, 40, 24)
                f.addRow(self.t("Mensaje", "Message"), self.text_content)
                f.addRow(self.t("Tamaño", "Size"), self.font_size)
            elif key == "clock":
                self.timezone = QLineEdit("Europe/Madrid")
                f.addRow(self.t("Zona IANA", "IANA timezone"), self.timezone)
                f.addRow(self.hint("Europe/Madrid · Europe/London · America/New_York · Asia/Tokyo"))
            elif key == "pc":
                self.pc_view = QComboBox()
                for view_key, es, en in PC_VIEWS:
                    self.pc_view.addItem(self.t(es, en), view_key)
                f.addRow(self.t("Vista", "View"), self.pc_view)
                self.pc_disk = QComboBox()
                self.pc_disk.setEditable(True)
                self.pc_disk.addItem(self.t("Disco del sistema", "System disk"), "")
                import psutil
                try:
                    for path in sorted({p.mountpoint for p in psutil.disk_partitions() if "cdrom" not in p.opts}):
                        self.pc_disk.addItem(path, path)
                except OSError:
                    pass
                f.addRow(self.t("Disco (vista de almacenamiento)", "Disk (storage view)"), self.pc_disk)
                f.addRow(self.hint(self.t("Gráficas: últimas 60 lecturas. Red: tráfico total del PC; la primera lectura necesita dos muestras. Actualiza cada 5 s para mayor detalle.",
                                         "Graphs: last 60 samples. Network: total PC traffic; the first rate needs two samples. Refresh every 5 s for more detail.")))
                f.addRow(self.hint(self.t("CPU y RAM mediante psutil; GPU NVIDIA mediante nvidia-smi, si está instalado. Los sensores no disponibles muestran N/D.",
                                         "CPU and RAM via psutil; NVIDIA GPU via nvidia-smi if installed. Unavailable sensors display N/A.")))
            elif key == "weather":
                self.latitude, self.longitude = QDoubleSpinBox(), QDoubleSpinBox()
                self.latitude.setRange(-90, 90)
                self.longitude.setRange(-180, 180)
                for control in [self.latitude, self.longitude]:
                    control.setDecimals(4)
                row = QHBoxLayout()
                row.addWidget(self.latitude)
                row.addWidget(self.longitude)
                f.addRow(self.t("Latitud / longitud", "Latitude / longitude"), row)
                f.addRow(self.hint(self.t("Datos de Open-Meteo · sin clave · caché de 10 minutos · requiere Internet.",
                                         "Weather data by Open-Meteo · no key · 10-minute cache · requires Internet.")))
            elif key == "countdown":
                self.target = QDateTimeEdit()
                self.target.setCalendarPopup(True)
                self.target.setDisplayFormat("dd/MM/yyyy HH:mm:ss")
                f.addRow(self.t("Fecha y hora local", "Local date and time"), self.target)
            elif key == "service":
                self.service_url = QLineEdit()
                self.service_url.setPlaceholderText("https://example.com/health")
                f.addRow("URL", self.service_url)
                f.addRow(self.hint(self.t("ONLINE si responde con HTTP < 400; tiempo de espera de 4 segundos.",
                                         "ONLINE when HTTP status is below 400; 4-second timeout.")))
            elif key == "calendar":
                self.calendar_url = QLineEdit()
                self.calendar_path = QLineEdit()
                self.calendar_url.setPlaceholderText("https://…/calendar.ics")
                row = QHBoxLayout()
                row.addWidget(self.calendar_path)
                row.addWidget(button(self.t("Archivo ICS…", "ICS file…"), self.choose_calendar))
                f.addRow("URL ICS", self.calendar_url)
                f.addRow(self.t("O archivo local", "Or local file"), row)
            elif key in {k for k, _, _ in EXTRA_KINDS}:
                f.addRow(button(self.t("Configurar widget…", "Configure widget…"), self.configure_extra))
                f.addRow(self.hint(self.t("Música, RSS, sensores y diseños propios se configuran aquí. Los controles de Pomodoro están en Automatizaciones.",
                                         "Configure media, RSS, sensors and custom designs here. Pomodoro controls are under Automations.")))
            elif key == "pc_native":
                self.pc_native_mode = QComboBox()
                self.pc_native_mode.addItem(self.t("Enviar datos al monitor ya elegido", "Send data to the selected monitor"), "existing")
                self.pc_native_mode.addItem(self.t("Intentar activar el reloj 625", "Try activating clock 625"), "activate")
                f.addRow(self.t("Modo", "Mode"), self.pc_native_mode)
                self.pc_independence = integer(0, 2147483647)
                f.addRow(self.t("Grupo nativo (solo activación)", "Native group (activation only)"), self.pc_independence)
                f.addRow(self.hint(self.t("Selecciona PC Monitor en esa pantalla desde la app Divoom y envía los datos aquí. No necesita IDs de la nube. La activación del reloj desde Studio es experimental. Activa Actualización automática para mantener los valores al día.",
                                         "Select PC Monitor on this screen in the Divoom app, then send data here. No cloud IDs needed. Clock activation from Studio is experimental. Enable Automatic updates to keep values current.")))
        edit.addWidget(self.fields)
        bottom = QHBoxLayout()
        self.accent = ColorButton("#64e6ca", t=self.t)
        self.background = ColorButton("#101b2b", t=self.t)
        bottom.addWidget(self.hint(self.t("Color", "Color")))
        bottom.addWidget(self.accent)
        bottom.addWidget(self.hint(self.t("Fondo", "Background")))
        bottom.addWidget(self.background)
        bottom.addStretch()
        bottom.addWidget(button(self.t("Guardar pantalla", "Save screen"), self.save_editor))
        bottom.addWidget(button(self.t("Guardar y enviar", "Save and send"), self.save_send, True))
        edit.addLayout(bottom)
        layout.addWidget(editor)
        layout.addWidget(self.hint(self.t("Las vistas previas muestran el contenido generado por Studio, no una captura del dispositivo.",
                                         "Previews show content generated by Studio, not a screenshot of the device.")))
        layout.addStretch()
        for control in [self.slot_title, self.media_path, self.timezone, self.service_url, self.calendar_url,
                        self.calendar_path, self.accent, self.background]:
            control.textChanged.connect(self.mark_dirty)
        for control in [self.refresh, self.frame_step, self.font_size, self.latitude, self.longitude, self.pc_independence]:
            control.valueChanged.connect(self.mark_dirty)
        self.text_content.textChanged.connect(self.mark_dirty)
        self.fit.currentIndexChanged.connect(self.mark_dirty)
        self.pc_view.currentIndexChanged.connect(self.mark_dirty)
        self.pc_disk.currentTextChanged.connect(self.mark_dirty)
        self.pc_native_mode.currentIndexChanged.connect(self.mark_dirty)
        self.target.dateTimeChanged.connect(self.mark_dirty)

    def build_scenes(self):
        layout = self.page(self.t("Escenas", "Scenes"), self.t("Guarda composiciones completas y cambia de ambiente con un clic.",
                                                                 "Save complete layouts and change the mood with one click."))
        card = box()
        row = QHBoxLayout(card)
        self.scene_list = QListWidget()
        self.scene_list.setMinimumHeight(250)
        row.addWidget(self.scene_list, 2)
        actions = QVBoxLayout()
        actions.addWidget(button(self.t("Guardar composición actual…", "Save current layout…"), self.new_scene, True))
        actions.addWidget(button(self.t("Aplicar escena", "Apply scene"), self.apply_scene))
        actions.addWidget(button(self.t("Renombrar", "Rename"), self.rename_scene))
        actions.addWidget(button(self.t("Eliminar", "Delete"), self.delete_scene))
        actions.addStretch()
        row.addLayout(actions, 1)
        layout.addWidget(card)
        rotation = box()
        form = QFormLayout(rotation)
        self.rotation_enabled = QCheckBox(self.t("Rotar las escenas marcadas", "Rotate checked scenes"))
        self.rotation_seconds = integer(30, 86400, 300)
        self.rotation_seconds.setSuffix(" s")
        form.addRow(self.rotation_enabled)
        form.addRow(self.t("Cambiar cada", "Switch every"), self.rotation_seconds)
        form.addRow(self.hint(self.t("Marca escenas en la lista. La rotación sigue su orden y necesita la actualización automática activada.",
                                    "Check scenes in the list. Rotation follows list order and requires automatic updates.")))
        form.addRow(button(self.t("Guardar rotación", "Save rotation"), self.save_rotation))
        layout.addWidget(rotation)
        layout.addStretch()

    def build_device(self):
        layout = self.page(self.t("Tu dispositivo", "Your device"), self.t("Conexión local, controles de pantalla e iluminación ambiental.",
                                                                           "Local connection, display controls and ambient lighting."))
        card = box()
        form = QFormLayout(card)
        self.device_name, self.device_ip, self.device_mac = QLineEdit(), QLineEdit(), QLineEdit()
        self.device_id = QLineEdit()
        form.addRow(self.t("Nombre", "Name"), self.device_name)
        form.addRow("IP", self.device_ip)
        form.addRow("MAC", self.device_mac)
        form.addRow("DeviceId", self.device_id)
        row = QHBoxLayout()
        row.addWidget(button(self.t("Guardar conexión", "Save connection"), self.save_device, True))
        row.addWidget(button(self.t("Añadir dispositivo…", "Add device…"), self.add_device))
        row.addWidget(button(self.t("Buscar en LAN", "Scan LAN"), lambda: self.scan(False)))
        row.addWidget(button(self.t("Buscar vía Divoom", "Discover via Divoom"), lambda: self.scan(True)))
        row.addWidget(button(self.t("Comprobar", "Check"), lambda: self.job("health")))
        form.addRow(row)
        layout.addWidget(card)
        controls = QHBoxLayout()
        display = box()
        f = QFormLayout(display)
        self.brightness = QSlider(Qt.Orientation.Horizontal)
        self.brightness.setRange(0, 100)
        self.brightness.setValue(60)
        self.brightness_label = QLabel("60%")
        self.brightness.valueChanged.connect(lambda n: self.brightness_label.setText(f"{n}%"))
        row = QHBoxLayout()
        row.addWidget(self.brightness)
        row.addWidget(self.brightness_label)
        f.addRow(self.t("Brillo de pantallas", "Display brightness"), row)
        f.addRow(button(self.t("Aplicar brillo", "Apply brightness"), lambda: self.command("Channel/SetBrightness", Brightness=self.brightness.value())))
        row = QHBoxLayout()
        row.addWidget(button(self.t("Encender", "Turn on"), lambda: self.command("Channel/OnOffScreen", OnOff=1)))
        row.addWidget(button(self.t("Apagar", "Turn off"), lambda: self.command("Channel/OnOffScreen", OnOff=0)))
        f.addRow(row)
        self.hour24 = QCheckBox(self.t("Formato 24 horas", "24-hour format"))
        self.hour24.setChecked(True)
        self.celsius = QCheckBox(self.t("Temperatura en °C", "Temperature in °C"))
        self.celsius.setChecked(True)
        self.mirror = QCheckBox(self.t("Modo espejo", "Mirror mode"))
        f.addRow(self.hour24)
        f.addRow(self.celsius)
        f.addRow(self.mirror)
        f.addRow(button(self.t("Aplicar preferencias", "Apply preferences"), self.apply_preferences))
        f.addRow(button(self.t("Sincronizar hora del PC", "Sync computer time"), self.sync_time))
        controls.addWidget(display)
        layout.addLayout(controls)
        rgb = box()
        rgb_layout = QVBoxLayout(rgb)
        self.lighting = LightingPanel(t=self.t)
        self.lighting.applyRequested.connect(self.apply_rgb)
        rgb_layout.addWidget(self.lighting)
        layout.addWidget(rgb)
        layout.addStretch()

    def build_tools(self):
        layout = self.page(self.t("Herramientas y avisos", "Tools and notifications"), self.t(
            "Las herramientas nativas pausan el reenvío de este dispositivo. Restaura la composición al terminar.",
            "Native tools pause this device's automatic uploads. Restore your layout when finished."))
        tabs = QHBoxLayout()
        card = box()
        form = QFormLayout(card)
        self.tool_panel = QComboBox()
        self.tool_panel.addItem(self.t("Global · compatible", "Global · compatible"), None)
        for i in range(5):
            self.tool_panel.addItem(self.t(f"Pantalla {i+1} · experimental", f"Screen {i+1} · experimental"), i + 1)
        form.addRow(self.t("Destino herramientas", "Tool target"), self.tool_panel)
        self.timer_minutes = integer(0, 999, 25)
        self.timer_seconds = integer(0, 59)
        row = QHBoxLayout()
        row.addWidget(self.timer_minutes)
        row.addWidget(QLabel("min"))
        row.addWidget(self.timer_seconds)
        row.addWidget(QLabel("s"))
        form.addRow(self.t("Cuenta atrás", "Timer"), row)
        row = QHBoxLayout()
        row.addWidget(button(self.t("Iniciar", "Start"), lambda: self.native_tool("Tools/SetTimer", Minute=self.timer_minutes.value(), Second=self.timer_seconds.value(), Status=1)))
        row.addWidget(button(self.t("Detener", "Stop"), lambda: self.native_tool("Tools/SetTimer", Minute=0, Second=0, Status=0)))
        form.addRow(row)
        row = QHBoxLayout()
        for es, en, status in [("Iniciar", "Start", 1), ("Parar", "Stop", 0), ("Reiniciar", "Reset", 2)]:
            row.addWidget(button(self.t(es, en), lambda checked=False, value=status: self.native_tool("Tools/SetStopWatch", Status=value)))
        form.addRow(self.t("Cronómetro", "Stopwatch"), row)
        self.red_score, self.blue_score = integer(0, 999), integer(0, 999)
        row = QHBoxLayout()
        row.addWidget(self.red_score)
        row.addWidget(self.blue_score)
        form.addRow(self.t("Marcador rojo / azul", "Red / blue score"), row)
        form.addRow(button(self.t("Mostrar marcador", "Show scoreboard"), lambda: self.native_tool("Tools/SetScoreBoard", RedScore=self.red_score.value(), BlueScore=self.blue_score.value())))
        row = QHBoxLayout()
        row.addWidget(button(self.t("Medidor de sonido", "Noise meter"), lambda: self.native_tool("Tools/SetNoiseStatus", NoiseStatus=1)))
        row.addWidget(button(self.t("Parar medidor", "Stop meter"), lambda: self.native_tool("Tools/SetNoiseStatus", NoiseStatus=0)))
        form.addRow(row)
        form.addRow(button(self.t("Restaurar composición", "Restore layout"), lambda: self.job("resume"), True))
        tabs.addWidget(card, 1)
        notices = box()
        form = QFormLayout(notices)
        self.notice_text = QPlainTextEdit()
        self.notice_text.setMaximumHeight(90)
        self.notice_text.setPlaceholderText(self.t("Tu mensaje…", "Your message…"))
        self.notice_panel = integer(1, 5, 1)
        self.notice_seconds = integer(5, 3600, 15)
        self.notice_buzzer = QCheckBox(self.t("Aviso sonoro", "Sound alert"))
        form.addRow(self.t("Mensaje temporal", "Temporary message"), self.notice_text)
        form.addRow(self.t("Pantalla", "Screen"), self.notice_panel)
        form.addRow(self.t("Duración (s)", "Duration (s)"), self.notice_seconds)
        form.addRow(self.notice_buzzer)
        form.addRow(button(self.t("Enviar aviso", "Send notification"), self.send_notice, True))
        form.addRow(button(self.t("Probar pitido", "Test buzzer"), lambda: self.command("Device/PlayBuzzer", ActiveTimeInCycle=150, OffTimeInCycle=150, PlayTotalTime=600)))
        form.addRow(self.hint(self.t("El aviso restaura después la imagen o widget anterior. Elige una pantalla gestionada por Studio.",
                                    "The notification restores the previous image or widget afterward. Choose a screen managed by Studio.")))
        tabs.addWidget(notices, 1)
        layout.addLayout(tabs)
        native = box()
        f = QFormLayout(native)
        self.clock_id = integer(0, 2147483647, 625)
        self.independence = integer(0, 2147483647)
        self.native_panel = integer(1, 5, 1)
        f.addRow(QLabel(self.t("Relojes nativos · experimental", "Native clocks · experimental")))
        f.addRow("ClockId", self.clock_id)
        f.addRow("LcdIndependence", self.independence)
        f.addRow(self.t("Pantalla", "Screen"), self.native_panel)
        row = QHBoxLayout()
        row.addWidget(button(self.t("Consultar catálogo / IDs", "Read catalog / IDs"), lambda: self.job("catalog")))
        row.addWidget(button(self.t("Aplicar reloj individual", "Apply individual clock"), self.set_native_clock))
        row.addWidget(button(self.t("Aplicar reloj completo", "Apply whole clock"), lambda: self.command("Channel/Set5LcdWholeClockId", pause=True, ClockId=self.clock_id.value())))
        f.addRow(row)
        f.addRow(self.hint(self.t("La consulta usa la nube Divoom y necesita DeviceId. La respuesta aparece en Actividad. No todos los relojes funcionan en todos los firmwares.",
                                 "The query uses Divoom cloud and requires DeviceId. Results appear in Activity. Clock compatibility depends on firmware.")))
        layout.addWidget(native)
        layout.addStretch()

    def build_schedules(self):
        layout = self.page(self.t("Horarios", "Schedules"), self.t("Programa escenas, brillo y descanso de las pantallas. Se usa la hora local del PC.",
                                                                   "Schedule scenes, brightness and display sleep using your computer's local time."))
        self.schedule_table = QTableWidget(0, 6)
        self.schedule_table.setHorizontalHeaderLabels([self.t("Hora", "Time"), self.t("Días", "Days"), self.t("Dispositivo", "Device"), self.t("Acción", "Action"), self.t("Valor", "Value"), self.t("Activo", "Enabled")])
        self.schedule_table.horizontalHeader().setStretchLastSection(True)
        self.schedule_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.schedule_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.schedule_table.setMinimumHeight(230)
        layout.addWidget(self.schedule_table)
        card = box()
        f = QFormLayout(card)
        self.schedule_time = QTimeEdit(QTime(22, 0))
        self.schedule_time.setDisplayFormat("HH:mm")
        self.schedule_days = QComboBox()
        self.schedule_days.addItem(self.t("Todos los días", "Every day"), list(range(7)))
        self.schedule_days.addItem(self.t("Lunes a viernes", "Weekdays"), list(range(5)))
        self.schedule_days.addItem(self.t("Sábado y domingo", "Weekends"), [5, 6])
        self.schedule_action = QComboBox()
        for es, en, key in [("Aplicar escena", "Apply scene", "scene"), ("Brillo", "Brightness", "brightness"), ("Apagar pantallas", "Displays off", "off"), ("Encender pantallas", "Displays on", "on")]:
            self.schedule_action.addItem(self.t(es, en), key)
        self.schedule_scene = QComboBox()
        self.schedule_brightness = integer(0, 100, 20)
        f.addRow(self.t("Hora", "Time"), self.schedule_time)
        f.addRow(self.t("Días", "Days"), self.schedule_days)
        f.addRow(self.t("Acción", "Action"), self.schedule_action)
        f.addRow(self.t("Escena (si corresponde)", "Scene (when applicable)"), self.schedule_scene)
        f.addRow(self.t("Brillo (si corresponde)", "Brightness (when applicable)"), self.schedule_brightness)
        row = QHBoxLayout()
        row.addWidget(button(self.t("Añadir al dispositivo seleccionado", "Add for selected device"), self.add_schedule, True))
        row.addWidget(button(self.t("Activar / desactivar seleccionado", "Toggle selected"), self.toggle_schedule))
        row.addWidget(button(self.t("Eliminar seleccionado", "Delete selected"), self.delete_schedule))
        f.addRow(row)
        layout.addWidget(card)
        layout.addWidget(self.hint(self.t("Studio debe estar abierto y la actualización automática activa. Los horarios no ejecutados mientras el PC estaba apagado no se recuperan.",
                                         "Studio must be running with automatic updates enabled. Schedules missed while the computer was off are not replayed.")))
        layout.addStretch()

    def build_activity(self):
        layout = self.page(self.t("Actividad", "Activity"), self.t("Respuestas del dispositivo, envíos y errores. Un comando aceptado aún requiere comprobar el efecto en pantalla.",
                                                                   "Device responses, uploads and errors. Accepted commands still need visual verification on the device."))
        self.activity = QPlainTextEdit()
        self.activity.setReadOnly(True)
        self.activity.document().setMaximumBlockCount(1500)
        self.activity.setMinimumHeight(450)
        layout.addWidget(self.activity, 1)
        row = QGridLayout()
        row.addWidget(button(self.t("Consultar ajustes", "Read settings"), lambda: self.command("Channel/GetAllConf")), 0, 0)
        row.addWidget(button(self.t("Consultar canales", "Read channels"), lambda: self.command("Channel/GetIndex")), 0, 1)
        row.addWidget(button(self.t("Abrir carpeta de datos", "Open data folder"), lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.store.root)))), 0, 2)
        row.addWidget(button(self.t("Limpiar vista", "Clear view"), self.activity.clear), 1, 0)
        row.addWidget(button(self.t("Reiniciar dispositivo…", "Reboot device…"), self.reboot), 1, 1)
        layout.addLayout(row)

    def build_settings(self):
        layout = self.page(self.t("Ajustes de Studio", "Studio settings"), self.t("Tu biblioteca y preferencias se guardan separadas de Divoom Keeper original.",
                                                                                "Your library and preferences are stored separately from the original Divoom Keeper."))
        card = box()
        f = QFormLayout(card)
        self.language = QComboBox()
        self.language.addItem("Español", "es")
        self.language.addItem("English", "en")
        self.theme = QComboBox()
        self.theme.addItem(self.t("Oscuro", "Dark"), "dark")
        self.theme.addItem(self.t("Claro", "Light"), "light")
        self.startup = QCheckBox(self.t("Iniciar Studio al iniciar sesión", "Start Studio at login"))
        self.resend = QCheckBox(self.t("Restaurar al iniciar (dispositivos automáticos)", "Restore on startup (automatic devices)"))
        self.interval = integer(1, 10080, 60)
        self.interval.setSuffix(" min")
        self.quality = integer(30, 100, 85)
        self.speed = integer(1, 10000, 100)
        self.speed.setSuffix(" ms")
        data = self.store.snapshot()
        self.language.setCurrentIndex(self.language.findData(data["language"]))
        self.theme.setCurrentIndex(self.theme.findData(data["theme"]))
        self.startup.setChecked(data["startup"])
        self.resend.setChecked(data["resend_on_startup"])
        f.addRow(self.t("Idioma · al reiniciar", "Language · after restart"), self.language)
        f.addRow(self.t("Apariencia", "Appearance"), self.theme)
        f.addRow(self.startup)
        f.addRow(self.resend)
        f.addRow(self.t("Reenvío de seguridad", "Recovery resend interval"), self.interval)
        f.addRow(self.t("Calidad JPEG", "JPEG quality"), self.quality)
        f.addRow(self.t("Duración por fotograma GIF", "GIF frame duration"), self.speed)
        f.addRow(button(self.t("Guardar ajustes", "Save settings"), self.save_settings, True))
        f.addRow(self.hint(self.t("Intervalo, calidad y velocidad corresponden al dispositivo seleccionado. Los widgets tienen su propio intervalo de actualización.",
                                 "Interval, quality and speed apply to the selected device. Widgets have individual refresh intervals.")))
        layout.addWidget(card)
        copies = box()
        v = QVBoxLayout(copies)
        v.addWidget(QLabel(self.t("Biblioteca y copias de seguridad", "Library and backups")))
        v.addWidget(self.hint(str(self.store.root)))
        row = QHBoxLayout()
        row.addWidget(button(self.t("Exportar copia portátil…", "Export portable backup…"), self.export_bundle))
        row.addWidget(button(self.t("Importar copia…", "Import backup…"), self.import_bundle))
        row.addWidget(button(self.t("Abrir biblioteca", "Open library"), lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.store.media_dir)))))
        v.addLayout(row)
        v.addWidget(self.hint(self.t("La copia incluye perfiles, escenas, horarios y archivos locales. Puede contener direcciones de calendarios privados.",
                                    "Backups include profiles, scenes, schedules and local files. They may contain private calendar URLs.")))
        layout.addWidget(copies)
        layout.addStretch()

    def apply_theme(self):
        dark = self.store.snapshot()["theme"] == "dark"
        bg, panel, sidebar, fg, muted, border, field = (("#0c1320", "#151f30", "#101827", "#edf3ff", "#90a2bd", "#29374d", "#101a2a") if dark else
                                                     ("#eef2f8", "#ffffff", "#e3eaf4", "#17263b", "#576b85", "#ced8e6", "#f4f7fc"))
        self.setStyleSheet(f"""
            QMainWindow, QWidget {{ background: {bg}; color: {fg}; font-family: 'Segoe UI'; font-size: 13px; }}
            QFrame#sidebar {{ background: {sidebar}; border-right: 1px solid {border}; }}
            QFrame#topbar {{ background: {bg}; border-bottom: 1px solid {border}; }}
            QFrame#card {{ background: {panel}; border: 1px solid {border}; border-radius: 14px; }}
            QFrame#card QLabel, QFrame#card QCheckBox {{ background: transparent; }}
            QStackedWidget#slotFields, QStackedWidget#slotFields > QWidget {{ background: {panel}; }}
            QLabel#brand {{ font-size: 23px; font-weight: 800; color: {'#68e6c4' if dark else '#087d66'}; background: transparent; }}
            QLabel#heading {{ font-size: 29px; font-weight: 700; }}
            QLabel#section {{ font-size: 17px; font-weight: 600; }}
            QLabel#muted {{ color: {muted}; font-size: 12px; background: transparent; }}
            QLabel#badge {{ color: {'#68e6c4' if dark else '#087d66'}; padding: 8px 12px; background: {panel}; border-radius: 8px; }}
            QLabel#preview {{ background: #080f1b; border-radius: 10px; }}
            QPushButton {{ background: {field}; border: 1px solid {border}; border-radius: 7px; padding: 9px 13px; font-weight: 600; }}
            QPushButton:hover {{ border-color: #7199f5; background: {'#23334c' if dark else '#e6edfb'}; }}
            QPushButton:pressed {{ background: {'#304360' if dark else '#d7e2f5'}; }}
            QPushButton#primary {{ background: #68e6c4; color: #102b29; border: 0; }}
            QPushButton#primary:hover {{ background: #91f2d8; }}
            QPushButton#panelHeader {{ background: transparent; border: 0; color: {muted}; padding: 2px; font-size: 11px; }}
            QPushButton#panelHeader[selected='true'] {{ color: {'#68e6c4' if dark else '#087d66'}; }}
            QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QDateTimeEdit, QTimeEdit, QPlainTextEdit, QTextEdit {{
                background: {field}; border: 1px solid {border}; border-radius: 6px; padding: 7px; selection-background-color: #3b659a; }}
            QLineEdit:focus, QPlainTextEdit:focus {{ border-color: #7199f5; }}
            QComboBox QAbstractItemView {{ background: {panel}; selection-background-color: #3b659a; color: {fg}; }}
            QListWidget, QTableWidget {{ background: {panel}; border: 1px solid {border}; border-radius: 8px; padding: 5px; }}
            QListWidget#navigation {{ background: transparent; border: 0; padding: 0; }}
            QListWidget::item {{ padding: 8px; border-radius: 7px; }}
            QListWidget::item:selected {{ background: {'#263a52' if dark else '#cadbef'}; color: {'#68e6c4' if dark else '#087d66'}; }}
            QHeaderView::section {{ background: {sidebar}; color: {muted}; border: 0; padding: 10px; }}
            QCheckBox {{ spacing: 9px; }}
            QCheckBox::indicator {{ width: 17px; height: 17px; border: 1px solid {muted}; border-radius: 4px; background: {field}; }}
            QCheckBox::indicator:checked {{ background: #37af92; border-color: #68e6c4; }}
            QScrollArea {{ border: 0; }}
            QScrollBar:vertical {{ background: {bg}; width: 10px; }}
            QScrollBar::handle:vertical {{ background: {border}; border-radius: 5px; min-height: 30px; }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
            QSlider::groove:horizontal {{ height: 5px; background: {border}; border-radius: 2px; }}
            QSlider::handle:horizontal {{ background: #68e6c4; width: 15px; margin: -5px 0; border-radius: 7px; }}
            QStatusBar {{ background: {sidebar}; color: {muted}; padding: 3px; }}
            QMenu {{ background: {panel}; border: 1px solid {border}; padding: 5px; }}
            QMenu::item {{ padding: 8px 20px; }}
            QMenu::item:selected {{ background: #3b659a; }}
        """)

    def mark_dirty(self, *_):
        if not self.loading:
            self.dirty = True

    def kind_changed(self):
        key = self.kind.currentData()
        if hasattr(self, "kind_pages") and key in self.kind_pages:
            self.fields.setCurrentIndex(self.kind_pages[key])
        self.mark_dirty()

    def flush_editor(self):
        if self.dirty:
            return self.save_editor()
        return True

    def load_devices(self):
        self.loading = True
        self.device_picker.blockSignals(True)
        self.device_picker.clear()
        data = self.store.snapshot()
        for d in data["devices"]:
            self.device_picker.addItem(d["name"], d["id"])
        index = self.device_picker.findData(data["active_device"])
        self.device_picker.setCurrentIndex(max(0, index))
        self.device_picker.blockSignals(False)
        self.loading = False
        self.load_device()

    def device_changed(self):
        if self.loading or self.device_picker.currentData() is None:
            return
        previous = self.store.snapshot()["active_device"]
        if not self.flush_editor():
            self.device_picker.blockSignals(True)
            self.device_picker.setCurrentIndex(self.device_picker.findData(previous))
            self.device_picker.blockSignals(False)
            return
        self.store.change(lambda data: data.update(active_device=self.device_picker.currentData()))
        self.load_device()
        self.refresh_lists()

    def load_device(self):
        self.loading = True
        d = self.store.get_device()
        self.auto.setChecked(d["enabled"])
        self.device_name.setText(d["name"])
        self.lighting.set_settings(d.get('lighting', {}))
        self.device_ip.setText(d["ip"])
        self.device_mac.setText(d.get("mac", ""))
        self.device_id.setText(str(d.get("device_id", 0)))
        self.interval.setValue(d["interval_minutes"])
        self.quality.setValue(d["quality"])
        self.speed.setValue(d["speed"])
        self.rotation_enabled.setChecked(bool(d.get("rotation")))
        self.rotation_seconds.setValue(d.get("rotation_seconds", 300))
        self.delivery.setText(self.statuses.get(d["id"], self.t("Listo", "Ready")))
        state = self.health_states.get(d["id"])
        self.health_label.setText("●  " + ("ONLINE" if state is True else "OFFLINE" if state is False else self.t("Sin comprobar", "Not checked")))
        self.loading = False
        self.dirty = False
        self.load_editor()
        self.refresh_previews()

    def select_panel(self, index):
        if not self.flush_editor():
            return
        self.selected = index
        self.load_editor()

    def load_editor(self):
        self.loading = True
        s = {**slot(), **self.store.get_device()["screens"][self.selected]}
        self.extra_drafts = {s["kind"]: copy.deepcopy(s)}
        self.editor_title.setText(self.t(f"Pantalla 0{self.selected + 1}", f"Screen 0{self.selected + 1}"))
        playlist = self.store.get_device().get("playlists", empty_playlists())[self.selected]
        self.playlist_hint.setText(self.t("Lista activa: este editor conserva el contenido de reserva. Edita los elementos desde Lista de reproducción.",
                                         "Playlist active: this editor keeps the fallback content. Edit items from Playlist.") if playlist["enabled"] else "")
        self.playlist_hint.setVisible(playlist["enabled"])
        self.kind.setCurrentIndex(self.kind.findData(s["kind"]))
        self.fields.setCurrentIndex(self.kind_pages[s["kind"]])
        self.slot_title.setText(s["title"])
        self.refresh.setValue(s["refresh"])
        self.media_path.setText(s["path"])
        self.fit.setCurrentIndex(self.fit.findData(s["fit"]))
        self.frame_step.setValue(s["frame_step"])
        self.text_content.setPlainText(s["text"])
        self.font_size.setValue(s["font_size"])
        self.timezone.setText(s["timezone"])
        self.latitude.setValue(float(s["latitude"]))
        self.longitude.setValue(float(s["longitude"]))
        target = QDateTime.fromString(s["target"], Qt.DateFormat.ISODate)
        self.target.setDateTime(target if target.isValid() else QDateTime.currentDateTime().addSecs(1500))
        self.service_url.setText(s["url"])
        self.calendar_url.setText(s["url"])
        self.calendar_path.setText(s["path"])
        self.accent.setText(s["color"])
        self.background.setText(s["background"])
        self.pc_independence.setValue(int(s["independence"]))
        self.pc_native_mode.setCurrentIndex(self.pc_native_mode.findData(s.get(
            "native_pc_mode", "activate" if s["kind"] == "pc_native" else "existing")))
        self.pc_view.setCurrentIndex(self.pc_view.findData(s["pc_view"]))
        drive = s.get("pc_disk", "")
        disk_index = self.pc_disk.findData(drive)
        if disk_index >= 0:
            self.pc_disk.setCurrentIndex(disk_index)
        else:
            self.pc_disk.setEditText(drive)
        for i, btn in enumerate(self.panel_buttons):
            btn.setProperty("selected", i == self.selected)
            btn.style().unpolish(btn)
            btn.style().polish(btn)
        self.loading = False
        self.dirty = False

    def save_editor(self):
        try:
            from PIL import Image, ImageColor
            from zoneinfo import ZoneInfo
            from .widgets import http_url
            kind = self.kind.currentData()
            s = slot(kind, title=self.slot_title.text().strip(), refresh=self.refresh.value(),
                     color=self.accent.text().strip(), background=self.background.text().strip())
            ImageColor.getrgb(s["color"])
            ImageColor.getrgb(s["background"])
            if kind == "media":
                path = self.media_path.text().strip()
                with Image.open(path) as img:
                    img.verify()
                s.update(path=self.store.import_media(path), fit=self.fit.currentData(), frame_step=self.frame_step.value())
                original = self.store.get_device()["screens"][self.selected]
                if original.get("panorama_speed") and original.get("path") == s["path"]:
                    s.update(panorama_speed=original["panorama_speed"], fit="stretch", frame_step=1)
            elif kind == "text":
                s.update(text=self.text_content.toPlainText(), font_size=self.font_size.value())
            elif kind == "clock":
                ZoneInfo(self.timezone.text().strip())
                s["timezone"] = self.timezone.text().strip()
            elif kind == "pc":
                s["pc_view"] = self.pc_view.currentData()
                drive_text = self.pc_disk.currentText().strip()
                s["pc_disk"] = "" if drive_text == self.pc_disk.itemText(0) else drive_text
            elif kind == "weather":
                s.update(latitude=self.latitude.value(), longitude=self.longitude.value())
            elif kind == "countdown":
                s["target"] = self.target.dateTime().toPython().astimezone().isoformat()
            elif kind == "service":
                s["url"] = http_url(self.service_url.text().strip())
            elif kind == "calendar":
                url, path = self.calendar_url.text().strip(), self.calendar_path.text().strip()
                if url:
                    s["url"] = http_url(url)
                elif path:
                    from icalendar import Calendar
                    Calendar.from_ical(Path(path).read_bytes())
                    s["path"] = self.store.import_media(path)
                else:
                    raise ValueError(self.t("Selecciona una URL o archivo ICS", "Choose an ICS URL or file"))
            elif kind == "pc_native":
                if self.pc_native_mode.currentData() == "activate" and not self.pc_independence.value():
                    raise ValueError(self.t("Para activar desde Studio necesitas un grupo nativo válido. "
                        "Selecciona PC Monitor desde la app Divoom y usa 'Enviar datos al monitor ya elegido'.",
                        "Activation from Studio needs a valid native group. "
                        "Select PC Monitor in the Divoom app and use 'Send data to the selected monitor'."))
                s["independence"] = self.pc_independence.value()
                s["native_pc_mode"] = self.pc_native_mode.currentData()
            if kind in {k for k, _, _ in EXTRA_KINDS}:
                s = {**s, **copy.deepcopy(self.extra_drafts.get(kind, {})), "kind": kind,
                     "title": self.slot_title.text().strip(), "refresh": self.refresh.value(),
                     "color": self.accent.text().strip(), "background": self.background.text().strip()}
                from .extensions import validate_content
                validate_content(s)
                for asset in assets(s):
                    if asset.get("path"):
                        asset["path"] = self.store.import_media(asset["path"])
            d = self.store.get_device()
            self.store.update_screen(d["id"], self.selected, s)
            self.dirty = False
            self.job("invalidate", panel=self.selected)
            self.refresh_previews()
            self.toast(self.t("Pantalla guardada", "Screen saved"))
            return True
        except Exception as error:
            QMessageBox.warning(self, "Divoom Keeper Studio", str(error))
            return False

    def configure_extra(self):
        from .dialogs import ItemEditor
        kind = self.kind.currentData()
        screen = {**slot(kind), **copy.deepcopy(self.extra_drafts.get(kind, {})), "kind": kind,
                  "title": self.slot_title.text(), "color": self.accent.text(), "background": self.background.text(), "refresh": self.refresh.value()}
        dialog = ItemEditor(self, screen)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.extra_drafts[kind] = dialog.screen
            self.slot_title.setText(dialog.screen["title"])
            self.accent.setText(dialog.screen["color"]); self.background.setText(dialog.screen["background"])
            self.refresh.setValue(dialog.screen["refresh"])
            self.mark_dirty()

    def save_send(self):
        if self.save_editor():
            self.job("send", panel=self.selected)

    def send_all(self):
        if self.flush_editor():
            self.job("send")

    def choose_media(self):
        path, _ = QFileDialog.getOpenFileName(self, self.t("Imagen o animación", "Image or animation"), "", "Images (*.png *.jpg *.jpeg *.gif *.bmp *.webp)")
        if path:
            self.media_path.setText(path)

    def open_playlist(self):
        if not self.flush_editor():
            return
        from .dialogs import PlaylistDialog
        dialog = PlaylistDialog(self, self.store, self.selected)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            d = self.store.get_device()
            lists = d.get("playlists", empty_playlists())
            lists[self.selected] = dialog.playlist
            self.store.update_fields(d["id"], playlists=lists)
            self.job("invalidate", panel=self.selected)
            self.load_editor()
            self.refresh_previews()
            self.job("send", panel=self.selected)
            self.toast(self.t("Lista guardada. Activa Automático para reproducirla.", "Playlist saved. Enable Automatic updates to play it."))

    def open_panorama(self):
        if not self.flush_editor():
            return
        from .dialogs import PanoramaDialog
        dialog = PanoramaDialog(self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            try:
                if dialog.animation_blobs:
                    self.store.apply_panorama_animation(dialog.animation_blobs, dialog.animation_speed, Path(dialog.path.text()).stem)
                else:
                    self.store.apply_panorama(dialog.images, Path(dialog.path.text()).stem)
                self.job("invalidate")
                self.load_device()
                self.refresh_lists()
                self.job("send")
                self.toast(self.t("Panorámica aplicada. Puedes recuperar la composición anterior desde Escenas.",
                                  "Panorama applied. Restore the previous layout from Scenes."))
            except Exception as error:
                QMessageBox.warning(self, dialog.windowTitle(), str(error))
        dialog.deleteLater()

    def choose_calendar(self):
        path, _ = QFileDialog.getOpenFileName(self, "ICS", "", "Calendar (*.ics)")
        if path:
            self.calendar_path.setText(path)
            self.calendar_url.clear()

    def release_movies(self):
        for movie in self.movies:
            movie.stop()
            movie.setFileName("")
            movie.deleteLater()
        self.movies = []

    def refresh_previews(self):
        self.release_movies()
        d = self.store.get_device()
        for i, s in enumerate(d["screens"]):
            self.panel_images[i].clear()
            self.panel_images[i].setText("· · ·")
            playlist = d.get("playlists", empty_playlists())[i]
            if playlist["enabled"]:
                self.panel_titles[i].setText(self.t(f"Lista · {len(playlist['items'])} elementos", f"Playlist · {len(playlist['items'])} items"))
                self.job("preview", panel=i)
                continue
            kind_label = next(self.t(es, en) for key, es, en in KINDS if key == s["kind"])
            self.panel_titles[i].setText(s.get("title") or kind_label)
            if s["kind"] == "media" and Path(s.get("path", "")).suffix.lower() == ".gif":
                movie = QMovie(s["path"])
                movie.setScaledSize(QSize(128, 128))
                if movie.isValid():
                    self.panel_images[i].setMovie(movie)
                    movie.start()
                    self.movies.append(movie)
                    continue
            self.job("preview", panel=i)

    def toggle_auto(self, checked):
        if self.loading:
            return
        if checked and not self.flush_editor():
            self.auto.blockSignals(True)
            self.auto.setChecked(False)
            self.auto.blockSignals(False)
            return
        d = self.store.get_device()
        if checked:
            try:
                valid_ip(d["ip"])
            except ValueError as error:
                self.auto.blockSignals(True)
                self.auto.setChecked(False)
                self.auto.blockSignals(False)
                QMessageBox.warning(self, "IP", str(error))
                return
        self.store.update_fields(d["id"], enabled=checked)
        if checked:
            self.job("invalidate")
        self.toast(self.t("Automático activado" if checked else "Automático desactivado", "Automatic updates enabled" if checked else "Automatic updates disabled"))

    def save_device(self):
        try:
            d = self.store.get_device()
            self.store.update_fields(d["id"], name=self.device_name.text().strip() or "Times Gate", ip=valid_ip(self.device_ip.text()),
                                     mac=self.device_mac.text().strip(), device_id=int(self.device_id.text() or 0))
            self.job("invalidate")
            self.load_devices()
            self.toast(self.t("Conexión guardada", "Connection saved"))
        except Exception as error:
            QMessageBox.warning(self, "Conexión", str(error))

    def add_device(self):
        ip, ok = QInputDialog.getText(self, self.t("Añadir dispositivo", "Add device"), "IPv4")
        if ok:
            try:
                self.add_discovered({"ip": valid_ip(ip), "name": f"Times Gate · {ip}"})
            except Exception as error:
                QMessageBox.warning(self, "IP", str(error))

    def add_discovered(self, info):
        if not self.flush_editor():
            return
        def change(data):
            d = next((d for d in data["devices"] if d["ip"] == info["ip"] or
                      (info.get("mac") and d.get("mac") == info["mac"])), None)
            if d is None:
                d = device(**{key: value for key, value in info.items() if key in {"ip", "name", "mac", "device_id"}})
                data["devices"].append(d)
            else:
                d.update({key: value for key, value in info.items() if key in {"ip", "mac", "device_id"}})
            data["active_device"] = d["id"]
        self.store.change(change)
        self.load_devices()
        self.refresh_lists()

    def scan(self, cloud):
        self.toast(self.t("Buscando dispositivos…", "Discovering devices…"))
        self.engine.submit("discover", seed=self.device_ip.text().strip(), cloud=cloud)

    def command(self, command, pause=False, **kwargs):
        self.job("command", payload={"Command": command, **kwargs}, pause=pause)

    def native_tool(self, command, **kwargs):
        # Per-panel addressing is only evidenced for timer and scoreboard.
        panel = self.tool_panel.currentData()
        if panel is not None and command in {"Tools/SetTimer", "Tools/SetScoreBoard"}:
            kwargs["LcdId"] = panel
        self.command(command, pause=True, **kwargs)

    def apply_preferences(self):
        self.command("Device/SetTime24Flag", Mode=int(self.hour24.isChecked()))
        self.command("Device/SetDisTempMode", Mode=0 if self.celsius.isChecked() else 1)
        self.command("Device/SetMirrorMode", Mode=int(self.mirror.isChecked()))

    def sync_time(self):
        import time
        offset = datetime.now().astimezone().utcoffset().total_seconds() / 3600
        self.command("Device/SetUTC", Utc=int(time.time()))
        self.command("Sys/TimeZone", TimeZoneValue=f"GMT{offset:+g}")

    def apply_rgb(self):
        settings = self.lighting.settings()
        body = lighting_payload(settings)
        self.command(body.pop("Command"), **body)

    def send_notice(self):
        text = self.notice_text.toPlainText().strip()
        if text:
            self.job("notification", panel=self.notice_panel.value()-1, text=text,
                     seconds=self.notice_seconds.value(), buzzer=self.notice_buzzer.isChecked())

    def set_native_clock(self):
        if not self.independence.value():
            QMessageBox.warning(self, "Divoom Keeper Studio", self.t(
                "Necesitas un grupo LcdIndependence válido del catálogo. El grupo 0 puede vaciar otras pantallas.",
                "A valid catalog LcdIndependence group is required. Group 0 can clear other screens."))
            return
        self.command("Channel/Set5LcdChannelType", pause=True, ChannelType=1, LcdIndependence=self.independence.value())
        self.command("Channel/SetClockSelectId", pause=True, ClockId=self.clock_id.value(),
                     LcdIndependence=self.independence.value(), LcdIndex=self.native_panel.value()-1,
                     DeviceId=self.store.get_device().get("device_id", 0))

    def new_scene(self):
        if not self.flush_editor():
            return
        name, ok = QInputDialog.getText(self, self.t("Guardar escena", "Save scene"), self.t("Nombre", "Name"))
        if ok and name.strip():
            scene = {"id": uid(), "name": name.strip(), **composition(self.store.get_device())}
            self.store.change(lambda data: data["scenes"].append(scene))
            self.refresh_lists()

    def scene_id(self):
        item = self.scene_list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def apply_scene(self):
        scene_id = self.scene_id()
        if scene_id and self.flush_editor():
            self.job("scene", scene_id=scene_id)

    def rename_scene(self):
        scene_id = self.scene_id()
        if not scene_id:
            return
        name, ok = QInputDialog.getText(self, self.t("Renombrar escena", "Rename scene"), self.t("Nombre", "Name"))
        if ok and name.strip():
            self.store.change(lambda data: next(s for s in data["scenes"] if s["id"] == scene_id).update(name=name.strip()))
            self.refresh_lists()

    def delete_scene(self):
        scene_id = self.scene_id()
        if not scene_id:
            return
        if QMessageBox.question(self, self.t("Eliminar escena", "Delete scene"), self.t("También se eliminarán sus horarios y referencias de rotación. ¿Continuar?", "Related schedules and rotation references will also be removed. Continue?")) != QMessageBox.StandardButton.Yes:
            return
        def remove(data):
            data["scenes"] = [s for s in data["scenes"] if s["id"] != scene_id]
            data["profiles"] = [r for r in data.get("profiles", []) if r["scene_id"] != scene_id]
            data["schedules"] = [s for s in data["schedules"] if not (s["action"] == "scene" and s["value"] == scene_id)]
            for d in data["devices"]:
                d["rotation"] = [s for s in d.get("rotation", []) if s != scene_id]
        self.store.change(remove)
        self.refresh_lists()

    def save_rotation(self):
        d = self.store.get_device()
        selected = [self.scene_list.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.scene_list.count())
                    if self.scene_list.item(i).checkState() == Qt.CheckState.Checked]
        if self.rotation_enabled.isChecked() and not selected:
            QMessageBox.warning(self, "Escenas", self.t("Marca al menos una escena", "Check at least one scene"))
            return
        d["rotation"] = selected if self.rotation_enabled.isChecked() else []
        d["rotation_seconds"] = self.rotation_seconds.value()
        self.store.update_fields(d["id"], rotation=d["rotation"], rotation_seconds=d["rotation_seconds"])
        self.toast(self.t("Rotación guardada", "Rotation saved"))

    def refresh_lists(self):
        if hasattr(self, "automation_panel"):
            for panel in self.automation_panel.panels:
                panel.refresh()
        data = self.store.snapshot()
        d = self.store.get_device()
        self.scene_list.clear()
        self.schedule_scene.clear()
        for scene in data["scenes"]:
            item = QListWidgetItem(scene["name"])
            item.setData(Qt.ItemDataRole.UserRole, scene["id"])
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if scene["id"] in d.get("rotation", []) else Qt.CheckState.Unchecked)
            self.scene_list.addItem(item)
            self.schedule_scene.addItem(scene["name"], scene["id"])
        self.schedule_table.setRowCount(len(data["schedules"]))
        names = {d["id"]: d["name"] for d in data["devices"]}
        scenes = {s["id"]: s["name"] for s in data["scenes"]}
        days = self.t("L M X J V S D", "M T W T F S S").split()
        for i, rule in enumerate(data["schedules"]):
            values = [rule["time"], " ".join(days[n] for n in rule["days"]), names.get(rule["device_id"], "—"),
                      rule["action"], scenes.get(rule["value"], str(rule["value"])) if rule["action"] == "scene" else str(rule["value"]),
                      "ON" if rule.get("enabled", True) else "OFF"]
            for j, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(Qt.ItemDataRole.UserRole, rule["id"])
                self.schedule_table.setItem(i, j, item)
        self.schedule_table.resizeColumnsToContents()

    def add_schedule(self):
        action = self.schedule_action.currentData()
        value = self.schedule_scene.currentData() if action == "scene" else self.schedule_brightness.value() if action == "brightness" else ""
        if action == "scene" and not value:
            QMessageBox.warning(self, "Escenas", self.t("Guarda primero una escena", "Save a scene first"))
            return
        rule = {"id": uid(), "device_id": self.store.snapshot()["active_device"], "time": self.schedule_time.time().toString("HH:mm"),
                "days": self.schedule_days.currentData(), "action": action, "value": value, "enabled": True}
        self.store.change(lambda data: data["schedules"].append(rule))
        self.refresh_lists()

    def selected_rule(self):
        row = self.schedule_table.currentRow()
        return self.schedule_table.item(row, 0).data(Qt.ItemDataRole.UserRole) if row >= 0 else None

    def toggle_schedule(self):
        rid = self.selected_rule()
        if rid:
            def change(data):
                rule = next(r for r in data["schedules"] if r["id"] == rid)
                rule["enabled"] = not rule.get("enabled", True)
            self.store.change(change)
            self.refresh_lists()

    def delete_schedule(self):
        rid = self.selected_rule()
        if rid:
            self.store.change(lambda data: data.update(schedules=[r for r in data["schedules"] if r["id"] != rid]))
            self.refresh_lists()

    def save_settings(self):
        try:
            from .startup import set_startup
            if not self.demo:
                set_startup(self.startup.isChecked(), self.store.root)
            self.store.change(lambda data: data.update(language=self.language.currentData(), theme=self.theme.currentData(),
                                                       startup=self.startup.isChecked(), resend_on_startup=self.resend.isChecked()))
            d = self.store.get_device()
            self.store.update_fields(d["id"], interval_minutes=self.interval.value(), quality=self.quality.value(), speed=self.speed.value())
            self.apply_theme()
            self.toast(self.t("Ajustes guardados. El idioma y el reenvío al iniciar se aplicarán en el próximo arranque.",
                              "Settings saved. Language and startup resend apply on the next launch."))
        except Exception as error:
            QMessageBox.warning(self, "Studio", str(error))

    def export_bundle(self):
        if not self.flush_editor():
            return
        path, _ = QFileDialog.getSaveFileName(self, "Export", "DivoomKeeperStudio-backup.zip", "ZIP (*.zip)")
        if path:
            try:
                self.store.export(path)
                self.toast(self.t("Copia exportada", "Backup exported"))
            except Exception as error:
                QMessageBox.warning(self, "Export", str(error))

    def import_bundle(self):
        path, _ = QFileDialog.getOpenFileName(self, "Import", "", "ZIP (*.zip)")
        if not path:
            return
        if QMessageBox.question(self, "Import", self.t("Se sustituirá la configuración de Studio y se guardará una copia de la actual. ¿Continuar?", "Studio settings will be replaced and the current settings backed up. Continue?")) != QMessageBox.StandardButton.Yes:
            return
        try:
            self.store.import_bundle(path)
            self.integration_panel.reload()
            self.engine.submit("reset_runtime")
            self.dirty = False
            self.load_devices()
            self.refresh_lists()
            self.apply_theme()
            self.toast(self.t("Copia importada. Automático desactivado para revisar los dispositivos.", "Backup imported. Automatic updates disabled so you can review devices."))
        except Exception as error:
            QMessageBox.warning(self, "Import", str(error))

    def reboot(self):
        if QMessageBox.question(self, "Divoom", self.t("¿Reiniciar el dispositivo seleccionado? Sus pantallas se interrumpirán temporalmente.", "Reboot the selected device? Its displays will be interrupted temporarily.")) == QMessageBox.StandardButton.Yes:
            self.command("Device/SysReboot")

    def poll(self):
        for _ in range(60):
            try:
                event = self.engine.events.get_nowait()
            except queue.Empty:
                return
            kind = event["event"]
            current = event.get("device_id") == self.store.snapshot()["active_device"]
            if kind == "preview" and current:
                label = self.panel_images[event["panel"]]
                if label.movie() is None:
                    label.setPixmap(QPixmap.fromImage(QImage.fromData(event["png"])).scaled(128, 128, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
            elif kind == "playing" and current:
                self.panel_titles[event["panel"]].setText(self.t("Lista", "Playlist") + f" · {event['index'] + 1}/{event['count']}")
            elif kind == "log":
                self.activity.appendPlainText(datetime.now().strftime("%H:%M:%S") + "  " + event["message"])
            elif kind == "status":
                self.statuses[event["device_id"]] = event["text"]
                if current:
                    self.delivery.setText(event["text"])
            elif kind == "health":
                self.health_states[event["device_id"]] = event["online"]
                if current:
                    self.health_label.setText("●  " + ("ONLINE" if event["online"] else "OFFLINE"))
                    body = event["body"]
                    if isinstance(body.get("Brightness"), (int, float)):
                        self.brightness.setValue(int(body["Brightness"]))
            elif kind == "response":
                self.activity.appendPlainText(event["command"] + "\n" + json.dumps(event["body"], ensure_ascii=False, indent=2))
                self.toast(event["command"] + self.t(" · respuesta en Actividad", " · response in Activity"))
            elif kind == "failure":
                self.toast(event["message"])
            elif kind == "config":
                if not self.dirty:
                    self.load_device()
                self.refresh_lists()
            elif kind == "discovery":
                devices = event["devices"]
                if not devices:
                    self.toast(self.t("No se encontraron dispositivos", "No devices found"))
                    continue
                labels = [f"{d['name']} · {d['ip']}" for d in devices]
                chosen, ok = QInputDialog.getItem(self, self.t("Dispositivos encontrados", "Devices found"), self.t("Añadir o seleccionar", "Add or select"), labels, editable=False)
                if ok:
                    self.add_discovered(devices[labels.index(chosen)])

    def reveal(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def closeEvent(self, event):
        if not self.quitting and not self.flush_editor():
            event.ignore()
            return
        if self.tray and not self.quitting:
            event.ignore()
            self.hide()
            self.tray.showMessage("Divoom Keeper Studio", self.t("Sigue funcionando en la bandeja.", "Still running in the system tray."), QSystemTrayIcon.MessageIcon.Information, 2500)
        else:
            self.release_movies()
            self.engine.stop()
            event.accept()

    def quit_app(self):
        if not self.flush_editor():
            return
        self.quitting = True
        self.engine.stop()
        if self.tray:
            self.tray.hide()
        self.close()
        QApplication.quit()

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QCheckBox, QComboBox, QDateTimeEdit, QDoubleSpinBox, QFormLayout, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit, QStackedWidget, QVBoxLayout, QWidget

from ..color_ui import ColorButton
from ..config import device
from ..content import PC_VIEWS, EXTRA_KINDS
from .common import KINDS, box, button, integer


class ScreensPage:
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
                self.pc_disk.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon); self.pc_disk.setMinimumContentsLength(16)  # long mount paths must not widen the page
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

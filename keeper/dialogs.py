from __future__ import annotations

import copy
import queue
import threading
from pathlib import Path
from zoneinfo import ZoneInfo

from PIL import Image, ImageColor, ImageOps
from PySide6.QtCore import Qt, QDateTime, QTimer
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDateTimeEdit, QDialog, QDialogButtonBox,
    QDoubleSpinBox, QFileDialog, QFormLayout, QHBoxLayout, QInputDialog, QLabel, QLineEdit,
    QListWidget, QMenu, QMessageBox, QPlainTextEdit, QPushButton, QSpinBox, QVBoxLayout, QSlider, QWidget)

from .config import slot, uid
from .color_ui import ColorButton
from .content import PC_VIEWS, PLAYABLE, EXTRA_KINDS, assets, empty_playlists, split_panorama, panorama_canvas, validate_playlists
from .widgets import http_url, png_bytes


def spin(low, high, value):
    widget = QSpinBox()
    widget.setRange(low, high)
    widget.setValue(value)
    return widget


def action(text, callback):
    button = QPushButton(text)
    button.clicked.connect(callback)
    return button


class ItemEditor(QDialog):
    """Edit one independent playlist item without changing the base screen."""
    def __init__(self, parent, screen):
        super().__init__(parent)
        self.t = parent.t
        self.screen = {**slot(), **copy.deepcopy(screen)}
        self.setWindowTitle(self.t("Contenido de la lista", "Playlist content"))
        self.setMinimumWidth(520)
        form = QFormLayout(self)
        self.title = QLineEdit(self.screen["title"])
        self.color = ColorButton(self.screen["color"], t=self.t)
        self.background = ColorButton(self.screen["background"], t=self.t)
        self.refresh = spin(5, 86400, self.screen["refresh"])
        form.addRow(self.t("Título", "Title"), self.title)
        form.addRow(self.t("Color", "Color"), self.color)
        form.addRow(self.t("Fondo", "Background"), self.background)
        form.addRow(self.t("Actualizar cada (s)", "Refresh every (s)"), self.refresh)
        kind = self.screen["kind"]
        if kind in {"media", "calendar"}:
            self.path = QLineEdit(self.screen["path"])
            row = QHBoxLayout()
            row.addWidget(self.path)
            row.addWidget(action(self.t("Archivo…", "File…"), self.choose_file))
            form.addRow(self.t("Archivo", "File"), row)
        if kind == "media":
            self.fit = QComboBox()
            for value, es, en in [("contain", "Encajar", "Fit"), ("cover", "Recortar", "Crop"), ("stretch", "Estirar", "Stretch")]:
                self.fit.addItem(self.t(es, en), value)
            self.fit.setCurrentIndex(self.fit.findData(self.screen["fit"]))
            self.step = spin(1, 100, self.screen["frame_step"])
            form.addRow(self.t("Ajuste", "Sizing"), self.fit)
            form.addRow(self.t("Salto de fotogramas", "Frame step"), self.step)
        elif kind == "text":
            self.text = QPlainTextEdit(self.screen["text"])
            self.size = spin(10, 40, self.screen["font_size"])
            form.addRow(self.t("Texto", "Text"), self.text)
            form.addRow(self.t("Tamaño", "Size"), self.size)
        elif kind == "clock":
            self.timezone = QLineEdit(self.screen["timezone"])
            form.addRow(self.t("Zona horaria", "Time zone"), self.timezone)
        elif kind == "pc":
            self.view = QComboBox()
            for key, es, en in PC_VIEWS:
                self.view.addItem(self.t(es, en), key)
            self.view.setCurrentIndex(self.view.findData(self.screen["pc_view"]))
            self.disk = QLineEdit(self.screen["pc_disk"])
            self.disk.setPlaceholderText(self.t("Vacío: disco del sistema", "Empty: system disk"))
            form.addRow(self.t("Vista", "View"), self.view)
            form.addRow(self.t("Disco", "Disk"), self.disk)
        elif kind == "weather":
            self.lat, self.lon = QDoubleSpinBox(), QDoubleSpinBox()
            for control, low, high, value in [(self.lat, -90, 90, self.screen["latitude"]), (self.lon, -180, 180, self.screen["longitude"])]:
                control.setRange(low, high)
                control.setDecimals(4)
                control.setValue(value)
            form.addRow(self.t("Latitud", "Latitude"), self.lat)
            form.addRow(self.t("Longitud", "Longitude"), self.lon)
        elif kind == "countdown":
            self.target = QDateTimeEdit()
            self.target.setDisplayFormat("dd/MM/yyyy HH:mm:ss")
            self.target.setCalendarPopup(True)
            date = QDateTime.fromString(self.screen["target"], Qt.DateFormat.ISODate)
            self.target.setDateTime(date if date.isValid() else QDateTime.currentDateTime().addSecs(1500))
            form.addRow(self.t("Fecha límite", "Target date"), self.target)
        if kind in {"calendar", "service"}:
            self.url = QLineEdit(self.screen["url"])
            form.addRow("URL", self.url)
        if kind in {k for k, _, _ in EXTRA_KINDS}:
            from .extra_ui import ContentFields
            self.extra_fields = ContentFields(self, form, self.screen)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText(self.t("Guardar", "Save"))
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(self.t("Cancelar", "Cancel"))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def choose_file(self):
        filters = "Calendar (*.ics)" if self.screen["kind"] == "calendar" else "Images (*.png *.jpg *.jpeg *.gif *.bmp *.webp)"
        path, _ = QFileDialog.getOpenFileName(self, self.t("Elegir archivo", "Choose file"), "", filters)
        if path:
            self.path.setText(path)

    def accept(self):
        try:
            s = copy.deepcopy(self.screen)
            s.update(title=self.title.text().strip(), color=self.color.text().strip(),
                     background=self.background.text().strip(), refresh=self.refresh.value())
            ImageColor.getrgb(s["color"])
            ImageColor.getrgb(s["background"])
            kind = s["kind"]
            if kind == "media":
                s.update(path=self.path.text().strip(), fit=self.fit.currentData(), frame_step=self.step.value())
                with Image.open(s["path"]) as image:
                    image.verify()
            elif kind == "text":
                s.update(text=self.text.toPlainText(), font_size=self.size.value())
            elif kind == "clock":
                s["timezone"] = self.timezone.text().strip()
                ZoneInfo(s["timezone"])
            elif kind == "pc":
                s.update(pc_view=self.view.currentData(), pc_disk=self.disk.text().strip())
            elif kind == "weather":
                s.update(latitude=self.lat.value(), longitude=self.lon.value())
            elif kind == "countdown":
                s["target"] = self.target.dateTime().toPython().astimezone().isoformat()
            elif kind == "service":
                s["url"] = http_url(self.url.text().strip())
            elif kind == "calendar":
                s.update(path=self.path.text().strip(), url=self.url.text().strip())
                if s["url"]:
                    http_url(s["url"])
                else:
                    from icalendar import Calendar
                    Calendar.from_ical(Path(s["path"]).read_bytes())
            if hasattr(self, "extra_fields"):
                self.extra_fields.apply(s)
            self.screen = s
            super().accept()
        except Exception as error:
            QMessageBox.warning(self, self.windowTitle(), str(error))


class PlaylistDialog(QDialog):
    def __init__(self, parent, store, panel):
        super().__init__(parent)
        self.t, self.store, self.panel = parent.t, store, panel
        self.device = store.get_device()
        self.playlist = copy.deepcopy(self.device.get("playlists", empty_playlists())[panel])
        self.items = self.playlist["items"]
        self.setWindowTitle(self.t(f"Lista · pantalla {panel + 1}", f"Playlist · screen {panel + 1}"))
        self.resize(680, 510)
        layout = QVBoxLayout(self)
        self.enabled = QCheckBox(self.t("Usar esta lista en la pantalla", "Use this playlist on the screen"))
        self.enabled.setChecked(self.playlist["enabled"])
        layout.addWidget(self.enabled)
        hint = QLabel(self.t("La lista se repite en orden. Activa Actualización automática en Studio para avanzar. "
            "El tiempo cuenta desde que termina cada envío; los GIF grandes pueden retrasar los cambios.",
            "The list loops in order. Enable Automatic updates in Studio to advance. "
            "Each duration starts after the upload finishes; large GIFs may delay transitions."))
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.list = QListWidget()
        self.list.currentRowChanged.connect(self.select)
        self.list.itemDoubleClicked.connect(self.edit_item)
        layout.addWidget(self.list, 1)
        row = QHBoxLayout()
        row.addWidget(action(self.t("Imágenes / GIF…", "Images / GIF…"), self.add_media))
        widget_button = QPushButton(self.t("Añadir widget", "Add widget"))
        menu = QMenu(widget_button)
        for key, es, en in [("text", "Texto", "Text"), ("clock", "Reloj", "Clock"), ("pc", "PC", "PC"),
                            ("weather", "Tiempo", "Weather"), ("countdown", "Cuenta atrás", "Countdown"),
                            ("calendar", "Calendario", "Calendar"), ("service", "Servicio", "Service")] + EXTRA_KINDS:
            menu.addAction(self.t(es, en), lambda checked=False, kind=key: self.add_widget(kind))
        widget_button.setMenu(menu)
        row.addWidget(widget_button)
        row.addWidget(action(self.t("Copiar pantalla…", "Copy screen…"), self.copy_screen))
        layout.addLayout(row)
        row = QHBoxLayout()
        row.addWidget(action(self.t("Editar", "Edit"), self.edit_item))
        row.addWidget(action(self.t("Subir", "Move up"), lambda: self.move(-1)))
        row.addWidget(action(self.t("Bajar", "Move down"), lambda: self.move(1)))
        row.addWidget(action(self.t("Eliminar", "Remove"), self.remove))
        row.addStretch()
        row.addWidget(QLabel(self.t("Duración", "Duration")))
        self.seconds = spin(5, 86400, 30)
        self.seconds.setSuffix(" s")
        self.seconds.valueChanged.connect(self.set_seconds)
        row.addWidget(self.seconds)
        layout.addLayout(row)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText(self.t("Guardar", "Save"))
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(self.t("Cancelar", "Cancel"))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.refresh_list(0)

    def refresh_list(self, selected=0):
        self.list.blockSignals(True)
        self.list.clear()
        for i, item in enumerate(self.items):
            s = item["screen"]
            name = s.get("title") or (Path(s.get("path", "")).name if s["kind"] == "media" else s["kind"])
            self.list.addItem(f"{i + 1:02}  ·  {name}   —   {item['seconds']} s")
        self.list.setCurrentRow(min(selected, len(self.items) - 1))
        self.list.blockSignals(False)
        self.select(self.list.currentRow())

    def select(self, index):
        self.seconds.blockSignals(True)
        self.seconds.setEnabled(index >= 0)
        if index >= 0:
            self.seconds.setValue(int(self.items[index]["seconds"]))
        self.seconds.blockSignals(False)

    def set_seconds(self, value):
        index = self.list.currentRow()
        if index >= 0:
            self.items[index]["seconds"] = value
            self.refresh_list(index)

    def append(self, screen):
        if len(self.items) >= 50:
            raise ValueError(self.t("Máximo 50 elementos por lista", "Up to 50 items per playlist"))
        self.items.append({"id": uid(), "seconds": 30, "screen": copy.deepcopy(screen)})
        self.refresh_list(len(self.items) - 1)

    def add_media(self):
        paths, _ = QFileDialog.getOpenFileNames(self, self.t("Añadir imágenes / GIF", "Add images / GIF"), "",
                                               "Images (*.png *.jpg *.jpeg *.gif *.bmp *.webp)")
        try:
            for path in paths:
                with Image.open(path) as source:
                    source.verify()
                self.append(slot("media", path=path))
        except Exception as error:
            QMessageBox.warning(self, self.windowTitle(), str(error))

    def add_widget(self, kind):
        editor = ItemEditor(self, slot(kind, refresh=5 if kind == "pc" else 30))
        if editor.exec() == QDialog.DialogCode.Accepted:
            try:
                self.append(editor.screen)
            except ValueError as error:
                QMessageBox.warning(self, self.windowTitle(), str(error))

    def copy_screen(self):
        choices = [(i, s) for i, s in enumerate(self.device["screens"]) if s["kind"] in PLAYABLE]
        if not choices:
            return
        labels = [f"{i + 1} · {s.get('title') or s['kind']}" for i, s in choices]
        text, ok = QInputDialog.getItem(self, self.t("Copiar pantalla", "Copy screen"), self.t("Contenido", "Content"), labels, editable=False)
        if ok:
            try:
                self.append(choices[labels.index(text)][1])
            except ValueError as error:
                QMessageBox.warning(self, self.windowTitle(), str(error))

    def edit_item(self, *args):
        index = self.list.currentRow()
        if index < 0:
            return
        editor = ItemEditor(self, self.items[index]["screen"])
        if editor.exec() == QDialog.DialogCode.Accepted:
            self.items[index]["screen"] = editor.screen
            self.refresh_list(index)

    def move(self, offset):
        index = self.list.currentRow()
        target = index + offset
        if 0 <= index < len(self.items) and 0 <= target < len(self.items):
            self.items[index], self.items[target] = self.items[target], self.items[index]
            self.refresh_list(target)

    def remove(self):
        index = self.list.currentRow()
        if index >= 0:
            self.items.pop(index)
            self.refresh_list(max(0, index - 1))

    def accept(self):
        try:
            playlist = {"enabled": self.enabled.isChecked(), "items": copy.deepcopy(self.items)}
            lists = empty_playlists()
            lists[self.panel] = playlist
            validate_playlists(lists)
            for item in playlist["items"]:
                for s in assets(item["screen"]):
                    if s.get("path"):
                        s["path"] = self.store.import_media(s["path"])
            self.playlist = playlist
            super().accept()
        except Exception as error:
            QMessageBox.warning(self, self.windowTitle(), str(error))


class PanoramaDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.t = parent.t
        self.images = []
        self.source = None
        self.source_path = ""
        self.is_animation = False
        self.animation_blobs, self.animation_frames = [], []
        self.animation_speed, self.frame_index, self.generation = 200, 0, 0
        self.cancel_conversion = threading.Event()
        self.results = queue.Queue()
        self.convert_timer = QTimer(self); self.convert_timer.setSingleShot(True)
        self.convert_timer.timeout.connect(self.start_clip)
        self.result_timer = QTimer(self); self.result_timer.timeout.connect(self.poll_clip); self.result_timer.start(80)
        self.movie_timer = QTimer(self); self.movie_timer.timeout.connect(self.next_frame)
        self.setWindowTitle(self.t("Panorámica · imagen, GIF o vídeo", "Panorama · image, GIF or video"))
        self.setMinimumWidth(740)
        layout = QVBoxLayout(self)
        label = QLabel(self.t("Contenido repartido entre las cinco pantallas, de izquierda a derecha. "
            "La composición anterior se guardará como escena. Las listas quedarán desactivadas.",
            "Content across all five screens, from left to right. "
            "The previous layout will be saved as a scene. Playlists will be disabled."))
        label.setWordWrap(True)
        layout.addWidget(label)
        row = QHBoxLayout()
        self.path = QLineEdit()
        self.path.editingFinished.connect(self.refresh_preview)
        row.addWidget(self.path, 1)
        row.addWidget(action(self.t("Elegir archivo…", "Choose file…"), self.choose))
        self.fit = QComboBox()
        for key, es, en in [("cover", "Recortar", "Crop"), ("contain", "Encajar", "Fit"), ("stretch", "Estirar", "Stretch")]:
            self.fit.addItem(self.t(es, en), key)
        self.fit.currentIndexChanged.connect(self.refresh_preview)
        row.addWidget(self.fit)
        layout.addLayout(row)
        self.clip_controls = QWidget()
        clip_row = QHBoxLayout(self.clip_controls); clip_row.setContentsMargins(0, 0, 0, 0)
        self.clip_start, self.clip_duration = QDoubleSpinBox(), QDoubleSpinBox()
        self.clip_start.setRange(0, 86400); self.clip_duration.setRange(.1, 24)
        self.clip_start.setDecimals(2); self.clip_duration.setDecimals(2); self.clip_duration.setValue(4)
        self.clip_fps = QComboBox()
        from .panorama_media import FPS
        for value in FPS:
            self.clip_fps.addItem(str(value), value)
        self.clip_fps.setCurrentIndex(self.clip_fps.findData(5))
        self.clip_rotation = QComboBox()
        for degrees in (0, 90, 180, 270):
            self.clip_rotation.addItem(f"{degrees}°", degrees)
        for label, control in [("Start (s)", self.clip_start), ("Duration (s)", self.clip_duration), ("FPS", self.clip_fps), ("Rotation", self.clip_rotation)]:
            clip_row.addWidget(QLabel(label)); clip_row.addWidget(control)
        self.clip_start.valueChanged.connect(self.refresh_preview)
        self.clip_duration.valueChanged.connect(self.refresh_preview)
        self.clip_fps.currentIndexChanged.connect(self.fps_changed)
        self.clip_rotation.currentIndexChanged.connect(self.refresh_preview)
        layout.addWidget(self.clip_controls); self.clip_controls.hide()
        from .crop_view import CropView
        self.crop_view = CropView()
        self.crop_view.positionChanged.connect(self.set_position)
        layout.addWidget(self.crop_view)
        controls = QFormLayout()
        self.position_x, self.position_y, self.zoom = QSlider(Qt.Orientation.Horizontal), QSlider(Qt.Orientation.Horizontal), QSlider(Qt.Orientation.Horizontal)
        for slider, low, high, value, label in [(self.position_x, 0, 1000, 500, "Horizontal"), (self.position_y, 0, 1000, 500, "Vertical"), (self.zoom, 100, 800, 100, "Zoom · 1× to 8×")]:
            slider.setRange(low, high); slider.setValue(value)
            slider.valueChanged.connect(self.refresh_preview)
            controls.addRow(label, slider)
        layout.addLayout(controls)
        layout.addWidget(action(self.t("Centrar y restablecer zoom", "Center and reset zoom"), self.reset_crop))
        layout.addWidget(QLabel(self.t("Pulsa o arrastra sobre la imagen para elegir la zona que se muestra.", "Click or drag over the image to choose the visible area.")))
        row = QHBoxLayout()
        self.previews = []
        for i in range(5):
            column = QVBoxLayout()
            column.addWidget(QLabel(f"0{i + 1}"), alignment=Qt.AlignmentFlag.AlignCenter)
            image = QLabel()
            image.setFixedSize(128, 128)
            image.setStyleSheet("background: #080f19; border-radius: 5px;")
            column.addWidget(image)
            row.addLayout(column)
            self.previews.append(image)
        layout.addLayout(row)
        self.play_controls = QWidget()
        play_row = QHBoxLayout(self.play_controls); play_row.setContentsMargins(0, 0, 0, 0)
        self.play_button = action(self.t("Pausar vista previa", "Pause preview"), self.toggle_play)
        self.frame_slider = QSlider(Qt.Orientation.Horizontal); self.frame_slider.valueChanged.connect(self.seek_frame)
        play_row.addWidget(self.play_button); play_row.addWidget(self.frame_slider, 1)
        layout.addWidget(self.play_controls); self.play_controls.hide()
        self.message = QLabel(self.t("Elige imagen, GIF o vídeo local. Composición: 640 × 128. Vídeo sin audio.",
                                     "Choose an image, GIF or local video. Layout: 640 × 128. Video is silent."))
        self.message.setWordWrap(True)
        layout.addWidget(self.message)
        row = QHBoxLayout()
        row.addStretch()
        row.addWidget(action(self.t("Cancelar", "Cancel"), self.reject))
        self.apply = action(self.t("Aplicar y enviar", "Apply and send"), self.accept)
        self.apply.setEnabled(False)
        row.addWidget(self.apply)
        layout.addLayout(row)

    def choose(self):
        path, _ = QFileDialog.getOpenFileName(self, self.windowTitle(), "", "Media (*.png *.jpg *.jpeg *.bmp *.webp *.gif *.mp4 *.mov *.mkv *.webm *.avi *.m4v)")
        if path:
            self.path.setText(path)
            self.refresh_preview()

    def refresh_preview(self, *args):
        self.images = []
        self.animation_blobs = []
        self.animation_frames = []
        self.movie_timer.stop()
        self.apply.setEnabled(False)
        self.cancel_conversion.set()
        self.generation += 1
        try:
            from .panorama_media import check_source, VIDEO_EXTENSIONS
            path = str(check_source(self.path.text().strip()))
            stamp = (path, Path(path).stat().st_mtime_ns)
            if self.source_path != stamp:
                self.is_animation = Path(path).suffix.lower() in VIDEO_EXTENSIONS
                self.source = None
                if not self.is_animation:
                    with Image.open(path) as source:
                        self.is_animation = bool(getattr(source, "is_animated", False))
                        rgba = ImageOps.exif_transpose(source).convert("RGBA")
                        self.source = Image.alpha_composite(Image.new("RGBA", rgba.size, "black"), rgba).convert("RGB")
                    self.crop_view.set_image(self.source)
                else:
                    self.crop_view.image = self.crop_view.pixmap = None
                    self.crop_view.update()
                self.source_path = stamp
            fit = self.fit.currentData()
            position = (self.position_x.value()/1000, self.position_y.value()/1000)
            zoom = self.zoom.value()/100
            self.zoom.setEnabled(fit == "cover")
            self.position_x.setEnabled(fit != "stretch"); self.position_y.setEnabled(fit != "stretch")
            self.crop_view.position, self.crop_view.zoom, self.crop_view.fit = position, zoom, fit
            self.crop_view.update()
            self.clip_controls.setVisible(self.is_animation)
            self.play_controls.setVisible(self.is_animation)
            if self.is_animation:
                for label in self.previews:
                    label.clear()
                self.message.setText(self.t("Preparando el fragmento… Puedes cancelar sin modificar tus pantallas.",
                                           "Preparing the clip… Cancel to keep your screens unchanged."))
                self.convert_timer.start(250)
                return
            self.convert_timer.stop()
            canvas = panorama_canvas(self.source, fit, position, zoom)
            self.show_canvas(canvas)
            self.message.setText(self.t("Vista previa de las cinco pantallas. Los envíos se realizan uno tras otro.",
                                       "Preview of all five screens. Screens are uploaded sequentially."))
            self.apply.setEnabled(True)
        except Exception as error:
            self.convert_timer.stop()
            self.crop_view.image = self.crop_view.pixmap = None
            self.crop_view.update()
            self.source_path = ""
            for label in self.previews:
                label.clear()
            self.message.setText(str(error))

    def show_canvas(self, canvas):
        self.images = [canvas.crop((i*128, 0, (i+1)*128, 128)) for i in range(5)]
        for label, image in zip(self.previews, self.images):
            label.setPixmap(QPixmap.fromImage(QImage.fromData(png_bytes(image))))

    def fps_changed(self, *_):
        self.clip_duration.setMaximum(min(30, 120/self.clip_fps.currentData()))
        self.refresh_preview()

    def start_clip(self):
        self.cancel_conversion = threading.Event()
        options = dict(path=self.path.text().strip(), start=self.clip_start.value(), duration=self.clip_duration.value(),
                       fps=self.clip_fps.currentData(), fit=self.fit.currentData(),
                       position=(self.position_x.value()/1000, self.position_y.value()/1000),
                       zoom=self.zoom.value()/100, rotation=self.clip_rotation.currentData())
        threading.Thread(target=convert_clip_worker, args=(self.results, self.generation, options, self.cancel_conversion),
                         daemon=True, name="panorama-converter").start()

    def poll_clip(self):
        while True:
            try:
                generation, result, error = self.results.get_nowait()
            except queue.Empty:
                return
            if generation != self.generation:
                continue
            if error:
                self.message.setText(error); self.apply.setEnabled(False)
                continue
            self.animation_frames, self.animation_blobs = result["frames"], result["blobs"]
            self.animation_speed = result["speed"]
            self.source = result["source"]; self.crop_view.set_image(self.source)
            self.frame_index = 0
            self.frame_slider.setRange(0, result["count"]-1); self.frame_slider.setValue(0)
            self.show_canvas(self.animation_frames[0]); self.apply.setEnabled(True)
            self.message.setText(self.t(
                f"{result['count']} fotogramas · {result['duration']:.2f} s en bucle · carga mínima {result['count']*.5:.0f} s, normalmente más. "
                "Las cinco partes se cargan por separado: pueden verse desfasadas aunque la vista previa esté sincronizada.",
                f"{result['count']} frames · {result['duration']:.2f} s loop · upload minimum {result['count']*.5:.0f} s, usually longer. "
                "Parts upload separately and may play out of sync even though the preview is synchronized."))
            self.movie_timer.start(self.animation_speed)
            self.play_button.setText(self.t("Pausar vista previa", "Pause preview"))

    def next_frame(self):
        if self.animation_frames:
            self.frame_slider.setValue((self.frame_index+1) % len(self.animation_frames))

    def seek_frame(self, value):
        if self.animation_frames:
            self.frame_index = value
            self.show_canvas(self.animation_frames[value])

    def toggle_play(self):
        if self.movie_timer.isActive():
            self.movie_timer.stop(); self.play_button.setText(self.t("Reproducir vista previa", "Play preview"))
        elif self.animation_frames:
            self.movie_timer.start(self.animation_speed); self.play_button.setText(self.t("Pausar vista previa", "Pause preview"))

    def finish_timers(self):
        self.cancel_conversion.set(); self.convert_timer.stop(); self.movie_timer.stop(); self.result_timer.stop()
        self.generation += 1

    def reject(self):
        self.finish_timers()
        super().reject()

    def set_position(self, x, y):
        self.position_x.blockSignals(True); self.position_y.blockSignals(True)
        self.position_x.setValue(round(x*1000)); self.position_y.setValue(round(y*1000))
        self.position_x.blockSignals(False); self.position_y.blockSignals(False)
        self.refresh_preview()

    def reset_crop(self):
        self.zoom.setValue(100)
        self.set_position(.5, .5)

    def accept(self):
        # Use the displayed tiles: applying must match the reviewed preview.
        if self.images and self.apply.isEnabled():
            self.finish_timers()
            super().accept()


def convert_clip_worker(results, generation, options, cancelled):
    try:
        from .panorama_media import decode_clip
        result = decode_clip(**options, stop=cancelled)
        if not cancelled.is_set():
            results.put((generation, result, ""))
    except InterruptedError:
        pass
    except Exception as error:
        if not cancelled.is_set():
            results.put((generation, None, str(error)))

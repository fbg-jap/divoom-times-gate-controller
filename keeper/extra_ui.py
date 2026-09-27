from __future__ import annotations

import copy
import json
import secrets

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (QApplication, QWidget, QDialog, QVBoxLayout, QHBoxLayout, QFormLayout,
    QTabWidget, QCheckBox, QComboBox, QLabel, QLineEdit, QPlainTextEdit, QSpinBox, QDoubleSpinBox,
    QPushButton, QListWidget, QMessageBox, QDialogButtonBox)

from .config import uid
from .extensions import METRICS, validate_content
from .content import assets
from .widgets import http_url


def number(low, high, value):
    w = QSpinBox(); w.setRange(low, high); w.setValue(int(value)); return w


def btn(text, callback):
    w = QPushButton(text); w.clicked.connect(callback); return w


def combo(options, value=None):
    w = QComboBox()
    for key, text in options:
        w.addItem(text, key)
    if value is not None:
        w.setCurrentIndex(max(0, w.findData(value)))
    return w


def hint(text):
    w = QLabel(text); w.setWordWrap(True); return w


def save_buttons(dialog, layout):
    b = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
    b.button(QDialogButtonBox.StandardButton.Save).setText("Guardar")
    b.button(QDialogButtonBox.StandardButton.Cancel).setText("Cancelar")
    b.accepted.connect(dialog.accept); b.rejected.connect(dialog.reject)
    layout.addRow(b) if isinstance(layout, QFormLayout) else layout.addWidget(b)


class ContentFields:
    def __init__(self, parent, form, screen):
        self.parent, self.screen = parent, copy.deepcopy(screen)
        kind = screen["kind"]
        if kind == "rss":
            self.url = QLineEdit(screen.get("url", "")); self.url.setPlaceholderText("https://…/feed.xml")
            self.seconds = number(5, 3600, screen.get("news_seconds", 15))
            self.size = number(10, 20, screen.get("news_size", 13))
            form.addRow("URL RSS / Atom", self.url); form.addRow("Segundos por titular", self.seconds); form.addRow("Tamaño de letra", self.size)
            form.addRow(hint("Hasta 50 titulares. Consulta la fuente cada 5 minutos; los titulares largos se recortan a la pantalla."))
        elif kind == "sensor":
            self.source = combo([("mqtt", "MQTT"), ("hardware", "LibreHardwareMonitor")], screen.get("sensor_source", "mqtt"))
            self.key = QLineEdit(screen.get("sensor_key", ""))
            self.field = QLineEdit(screen.get("sensor_field", "")); self.field.setPlaceholderText("temperature o data.value; vacío = texto completo")
            self.unit = QLineEdit(screen.get("sensor_unit", ""))
            self.stale = number(10, 86400, screen.get("sensor_stale", 300))
            form.addRow("Fuente", self.source); form.addRow("Tema MQTT / ID de sensor", self.key)
            form.addRow("Campo JSON (MQTT)", self.field); form.addRow("Unidad", self.unit); form.addRow("Caduca tras (s)", self.stale)
            form.addRow(hint("Activa la fuente en Integraciones. Allí puedes consultar los identificadores de hardware. N/D indica que no hay lectura reciente."))
        elif kind == "custom":
            form.addRow(btn("Abrir diseñador visual…", self.design))
            form.addRow(hint("Combina texto, imágenes y barras. Los datos del PC se actualizan con el widget."))
        elif kind == "music":
            form.addRow(hint("Lee la sesión multimedia actual de Windows: carátula, canción y artista. El reproductor debe publicar su sesión en Windows. No necesita tu contraseña."))
        elif kind == "pomodoro":
            form.addRow(hint("Muestra la sesión de trabajo/descanso de Studio. Inicia, pausa y configura la sesión en Automatizaciones → Pomodoro. Actualiza cada 5 segundos."))

    def design(self):
        from .designer import DesignerDialog
        dialog = DesignerDialog(self.parent, self.screen)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.screen = dialog.screen

    def apply(self, s):
        kind = s["kind"]
        if kind == "rss":
            s.update(url=http_url(self.url.text().strip()), news_seconds=self.seconds.value(), news_size=self.size.value())
        elif kind == "sensor":
            key = self.key.text().strip()
            if not key or len(key) > 256 or any(c in key for c in "+#\x00"):
                raise ValueError("Escribe un tema concreto o un identificador de sensor")
            s.update(sensor_source=self.source.currentData(), sensor_key=key, sensor_field=self.field.text().strip(),
                     sensor_unit=self.unit.text().strip()[:30], sensor_stale=self.stale.value())
        elif kind == "custom":
            s["elements"] = copy.deepcopy(self.screen.get("elements", []))
        validate_content(s)


class RuleDialog(QDialog):
    def __init__(self, window, group, rule=None):
        super().__init__(window)
        self.window, self.group = window, group
        self.rule = copy.deepcopy(rule or {"id": uid(), "device_id": window.store.get_device()["id"], "enabled": True})
        r = self.rule
        self.setWindowTitle({"alerts": "Alerta automática", "reminders": "Recordatorio recurrente", "profiles": "Perfil automático"}[group])
        self.setMinimumWidth(540)
        form = QFormLayout(self)
        self.name = QLineEdit(r.get("name", "")); form.addRow("Nombre", self.name)
        self.device = combo([(d["id"], d["name"]) for d in window.store.snapshot()["devices"]], r["device_id"])
        form.addRow("Dispositivo", self.device)
        self.enabled = QCheckBox("Activado"); self.enabled.setChecked(r.get("enabled", True)); form.addRow(self.enabled)
        if group == "profiles":
            self.trigger = combo([("process", "Aplicación abierta"), ("locked", "Windows bloqueado"), ("desktop", "Escritorio / sin aplicación coincidente")], r.get("trigger", "process"))
            self.process = QLineEdit(r.get("process", "")); self.process.setPlaceholderText("Ejemplo: juego.exe")
            self.scene = combo([(s["id"], s["name"]) for s in window.store.snapshot()["scenes"]], r.get("scene_id"))
            form.addRow("Condición", self.trigger); form.addRow("Nombre del ejecutable", self.process); form.addRow("Escena", self.scene)
            form.addRow(hint("Prioridad: bloqueo, aplicación y escritorio. Entre aplicaciones gana la primera regla de la lista. Al dejar de coincidir vuelve a la composición guardada."))
        else:
            self.panel = number(1, 5, r.get("panel", 0)+1)
            self.text = QPlainTextEdit(r.get("text", "")); self.text.setMaximumHeight(70)
            self.seconds = number(5, 300, r.get("seconds", 15))
            self.buzzer = QCheckBox("Pitido"); self.buzzer.setChecked(r.get("buzzer", False))
            if group == "reminders":
                self.minutes = number(1, 10080, r.get("minutes", 30)); form.addRow("Repetir cada (min)", self.minutes)
                form.addRow(hint("El intervalo empieza al activar la regla o abrir Studio. Requiere actualización automática; no recupera recordatorios perdidos."))
            else:
                self.metric_combo = combo([*METRICS, ("disk_free", "Disco libre (GiB)"), ("service", "Servicio caído (0 = OK, 1 = fallo)"), ("sensor", "Sensor numérico")], r.get("metric", "cpu"))
                self.operator = combo([("above", "Mayor que"), ("below", "Menor que")], r.get("operator", "above"))
                self.threshold = QDoubleSpinBox(); self.threshold.setRange(-1e12, 1e12); self.threshold.setValue(r.get("threshold", 80))
                self.source = QLineEdit(r.get("source", "")); self.source.setPlaceholderText("URL de servicio, ruta de disco o ID/tema del sensor")
                self.sensor_source = combo([("mqtt", "MQTT"), ("hardware", "LibreHardwareMonitor")], r.get("sensor_source", "mqtt"))
                self.sensor_field = QLineEdit(r.get("sensor_field", ""))
                self.hold = number(0, 3600, r.get("hold", 10)); self.cooldown = number(30, 86400, r.get("cooldown", 300))
                for label, w in [("Métrica", self.metric_combo), ("Comparación", self.operator), ("Umbral", self.threshold), ("Fuente (si corresponde)", self.source), ("Tipo de sensor", self.sensor_source), ("Campo JSON del sensor", self.sensor_field), ("Mantener condición (s)", self.hold), ("Mínimo entre avisos (s)", self.cooldown)]:
                    form.addRow(label, w)
                form.addRow(hint("Un aviso por incidente, con rearme cuando se normaliza. Para servicio caído: mayor que 0.5. Sensores ausentes no disparan alertas."))
            form.addRow("Pantalla (con imagen o widget)", self.panel); form.addRow("Mensaje", self.text); form.addRow("Duración del aviso (s)", self.seconds); form.addRow(self.buzzer)
        save_buttons(self, form)

    def accept(self):
        try:
            r = copy.deepcopy(self.rule)
            r.update(name=self.name.text().strip(), device_id=self.device.currentData(), enabled=self.enabled.isChecked())
            if self.group == "profiles":
                r.update(trigger=self.trigger.currentData(), process=self.process.text().strip(), scene_id=self.scene.currentData())
            else:
                r.update(panel=self.panel.value()-1, text=self.text.toPlainText().strip(), seconds=self.seconds.value(), buzzer=self.buzzer.isChecked())
                if self.group == "reminders":
                    r["minutes"] = self.minutes.value()
                else:
                    r.update(metric=self.metric_combo.currentData(), operator=self.operator.currentData(), threshold=self.threshold.value(),
                             source=self.source.text().strip(), sensor_source=self.sensor_source.currentData(), sensor_field=self.sensor_field.text().strip(), hold=self.hold.value(), cooldown=self.cooldown.value())
            data = self.window.store.snapshot()
            data[self.group] = [x for x in data.get(self.group, []) if x["id"] != r["id"]] + [r]
            from .extensions import validate_extensions
            validate_extensions(data)
            self.rule = r
            super().accept()
        except Exception as error:
            QMessageBox.warning(self, self.windowTitle(), str(error))


class RulesPanel(QWidget):
    def __init__(self, window, group):
        super().__init__(); self.window, self.group = window, group
        layout = QVBoxLayout(self)
        self.list = QListWidget(); self.list.itemDoubleClicked.connect(lambda *_: self.edit()); layout.addWidget(self.list)
        row = QHBoxLayout()
        for text, callback in [("Añadir", self.add), ("Editar", self.edit), ("Activar / desactivar", self.toggle), ("↑", lambda: self.move(-1)), ("↓", lambda: self.move(1)), ("Eliminar", self.remove)]:
            row.addWidget(btn(text, callback))
        layout.addLayout(row)
        layout.addWidget(hint("Las reglas se aplican a su dispositivo con Actualización automática activa. Los avisos respetan la pausa y el apagado."))
        self.refresh()

    def refresh(self):
        index = self.list.currentRow(); self.list.clear()
        self.rules = self.window.store.snapshot().get(self.group, [])
        for r in self.rules:
            self.list.addItem(f"{'●' if r.get('enabled', True) else '○'}  {r.get('name') or r.get('text') or r.get('process') or r.get('trigger')}"[:140])
        self.list.setCurrentRow(min(max(0, index), len(self.rules)-1))

    def add(self):
        self.edit(new=True)

    def edit(self, new=False):
        index = self.list.currentRow()
        if not new and index < 0:
            return
        dialog = RuleDialog(self.window, self.group, None if new else self.rules[index])
        if dialog.exec() == QDialog.DialogCode.Accepted:
            rules = copy.deepcopy(self.rules)
            if new:
                rules.append(dialog.rule)
            else:
                rules[index] = dialog.rule
            self.window.store.change(lambda data: data.update({self.group: rules})); self.refresh()

    def toggle(self):
        i = self.list.currentRow()
        if i >= 0:
            rules = copy.deepcopy(self.rules); rules[i]["enabled"] = not rules[i].get("enabled", True)
            self.window.store.change(lambda data: data.update({self.group: rules})); self.refresh()

    def move(self, offset):
        i = self.list.currentRow(); j = i+offset
        if 0 <= i < len(self.rules) and 0 <= j < len(self.rules):
            rules = copy.deepcopy(self.rules); rules[i], rules[j] = rules[j], rules[i]
            self.window.store.change(lambda data: data.update({self.group: rules})); self.refresh(); self.list.setCurrentRow(j)

    def remove(self):
        i = self.list.currentRow()
        if i >= 0:
            rules = copy.deepcopy(self.rules); rules.pop(i)
            self.window.store.change(lambda data: data.update({self.group: rules})); self.refresh()


class AutomationPanel(QWidget):
    def __init__(self, window):
        super().__init__(); self.window = window
        layout = QVBoxLayout(self); tabs = QTabWidget(); layout.addWidget(tabs)
        page = QWidget(); form = QFormLayout(page)
        saved = window.store.snapshot().get("productivity", {})
        self.work, self.rest, self.long_rest, self.cycles = number(1, 180, saved.get("work", 25)), number(1, 180, saved.get("rest", 5)), number(1, 180, saved.get("long_rest", 15)), number(1, 12, saved.get("cycles", 4))
        self.panel = number(1, 5, 1); self.buzzer = QCheckBox("Pitido al cambiar de fase")
        self.status = QLabel("Preparado · 25:00"); form.addRow(self.status)
        for text, w in [("Trabajo (min)", self.work), ("Descanso (min)", self.rest), ("Descanso largo (min)", self.long_rest), ("Descanso largo cada N ciclos", self.cycles), ("Pantalla para avisos", self.panel)]:
            form.addRow(text, w)
        form.addRow(self.buzzer)
        row = QHBoxLayout()
        for label, operation in [("Iniciar", "start"), ("Pausar", "pause"), ("Continuar", "resume"), ("Saltar fase", "skip"), ("Restablecer", "reset")]:
            row.addWidget(btn(label, lambda checked=False, op=operation: self.control(op)))
        form.addRow(row)
        form.addRow(hint("Elige el widget Pomodoro en Pantallas para ver la cuenta atrás. La sesión dura mientras Studio permanece abierto; los avisos requieren actualización automática."))
        tabs.addTab(page, "Pomodoro")
        self.panels = []
        for group, title in [("alerts", "Alertas"), ("reminders", "Recordatorios"), ("profiles", "Perfiles")]:
            panel = RulesPanel(window, group); tabs.addTab(panel, title); self.panels.append(panel)
        self.timer = QTimer(self); self.timer.timeout.connect(self.poll); self.timer.start(1000)

    def control(self, operation):
        if operation == "start":
            self.window.store.change(lambda data: data.update(productivity={"work": self.work.value(), "rest": self.rest.value(), "long_rest": self.long_rest.value(), "cycles": self.cycles.value()}))
        self.window.job("pomodoro", operation=operation, work=self.work.value(), rest=self.rest.value(),
                        long_rest=self.long_rest.value(), cycles=self.cycles.value(), panel=self.panel.value()-1, buzzer=self.buzzer.isChecked())

    def poll(self):
        data = self.window.engine.renderer.providers.extra.pomodoro
        seconds = max(0, int(data["remaining"]))
        self.status.setText(f"{data['phase']} · {seconds//60:02}:{seconds%60:02} · ciclo {data['cycle']} · {'En marcha' if data['running'] else 'En pausa'}")


class IntegrationPanel(QWidget):
    def __init__(self, window):
        super().__init__(); self.window = window
        layout = QVBoxLayout(self); tabs = QTabWidget(); layout.addWidget(tabs)
        data = window.store.snapshot().get("integrations", {}); api, mqtt = data.get("api", {}), data.get("mqtt", {})
        page = QWidget(); form = QFormLayout(page)
        self.api_on = QCheckBox("Activar API"); self.api_on.setChecked(api.get("enabled", False))
        self.api_lan = QCheckBox("Permitir conexiones desde la red local"); self.api_lan.setChecked(api.get("host") == "0.0.0.0")
        self.api_port = number(1, 65535, api.get("port", 8787))
        self.token = QLineEdit(api.get("token") or secrets.token_urlsafe(32)); self.token.setEchoMode(QLineEdit.EchoMode.Password)
        row = QHBoxLayout(); row.addWidget(self.token); row.addWidget(btn("Copiar", lambda: QApplication.clipboard().setText(self.token.text()))); row.addWidget(btn("Nuevo token", lambda: self.token.setText(secrets.token_urlsafe(32))))
        form.addRow(self.api_on); form.addRow(self.api_lan); form.addRow("Puerto", self.api_port); form.addRow("Token", row)
        self.api_status = QLabel(); form.addRow(self.api_status)
        form.addRow(hint('GET /v1/status · POST /v1/action\nCabecera: Authorization: Bearer TU_TOKEN\nEjemplo: {"action":"notice","panel":1,"text":"Hola","seconds":15}\nAcciones: notice, scene, brightness, power, send. panel usa 1–5. Consulta los ID de escenas y dispositivos en /v1/status.'))
        form.addRow(hint("Por defecto solo responde en este PC. El acceso LAN usa HTTP; resérvalo a una red de confianza. Studio no cambia el firewall."))
        tabs.addTab(page, "API local")
        page = QWidget(); form = QFormLayout(page)
        self.mqtt_on = QCheckBox("Activar MQTT / Home Assistant"); self.mqtt_on.setChecked(mqtt.get("enabled", False))
        self.mqtt_host = QLineEdit(mqtt.get("host", "")); self.mqtt_port = number(1, 65535, mqtt.get("port", 1883))
        self.mqtt_prefix = QLineEdit(mqtt.get("prefix", "keeper")); self.user = QLineEdit(mqtt.get("username", ""))
        self.password = QLineEdit(mqtt.get("password", "")); self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.tls = QCheckBox("TLS (certificado verificado)"); self.tls.setChecked(mqtt.get("tls", False))
        form.addRow(self.mqtt_on)
        for text, w in [("Servidor", self.mqtt_host), ("Puerto", self.mqtt_port), ("Prefijo único de esta instalación", self.mqtt_prefix), ("Usuario", self.user), ("Contraseña", self.password)]:
            form.addRow(text, w)
        form.addRow(self.tls); self.mqtt_status = QLabel(); form.addRow(self.mqtt_status)
        form.addRow(hint('Conecta al mismo broker que Home Assistant. Publica botones de escenas mediante MQTT Discovery.\nÓrdenes JSON en PREFIJO/command (mismo formato que la API, sin retain).\nPara mostrar un sensor, configura un widget Sensor con su tema MQTT y el campo JSON. Home Assistant debe publicar el valor en ese tema.'))
        tabs.addTab(page, "MQTT / Home Assistant")
        page = QWidget(); form = QFormLayout(page)
        self.hardware = QCheckBox("Leer sensores de LibreHardwareMonitor"); self.hardware.setChecked(data.get("hardware", False)); form.addRow(self.hardware)
        form.addRow(hint("Necesita LibreHardwareMonitor abierto y su proveedor WMI disponible. Studio no instala controladores ni eleva permisos. Las temperaturas disponibles complementan el monitor PC."))
        self.sensors = QPlainTextEdit(); self.sensors.setReadOnly(True); self.sensors.setMinimumHeight(230); form.addRow(self.sensors)
        form.addRow(btn("Actualizar lista de sensores", self.poll_sensors))
        tabs.addTab(page, "Sensores del PC")
        layout.addWidget(hint("Guarda para aplicar los cambios. Token y contraseña se guardan en tu configuración local; las exportaciones portátiles omiten esas credenciales."))
        layout.addWidget(btn("Guardar integraciones", self.save))
        self.timer = QTimer(self); self.timer.timeout.connect(self.poll); self.timer.start(1500); self.poll()

    def save(self):
        config = {"hardware": self.hardware.isChecked(),
                  "api": {"enabled": self.api_on.isChecked(), "host": "0.0.0.0" if self.api_lan.isChecked() else "127.0.0.1", "port": self.api_port.value(), "token": self.token.text().strip()},
                  "mqtt": {"enabled": self.mqtt_on.isChecked(), "host": self.mqtt_host.text().strip(), "port": self.mqtt_port.value(), "prefix": self.mqtt_prefix.text().strip(), "username": self.user.text(), "password": self.password.text(), "tls": self.tls.isChecked()}}
        try:
            self.window.store.change(lambda data: data.update(integrations=config))
            self.window.toast("Integraciones guardadas")
        except Exception as error:
            QMessageBox.warning(self, "Integraciones", str(error))

    def poll(self):
        self.api_status.setText("Estado: " + self.window.engine.bridge.api_status)
        self.mqtt_status.setText("Estado: " + self.window.engine.bridge.mqtt_status)

    def reload(self):
        from .config import defaults
        data = self.window.store.snapshot().get("integrations", defaults()["integrations"])
        api = data.get("api", {}); mqtt = data.get("mqtt", {})
        self.api_on.setChecked(api.get("enabled", False)); self.api_lan.setChecked(api.get("host") == "0.0.0.0")
        self.api_port.setValue(api.get("port", 8787)); self.token.setText(api.get("token") or secrets.token_urlsafe(32))
        self.mqtt_on.setChecked(mqtt.get("enabled", False)); self.mqtt_host.setText(mqtt.get("host", ""))
        self.mqtt_port.setValue(mqtt.get("port", 1883)); self.mqtt_prefix.setText(mqtt.get("prefix", "keeper"))
        self.user.setText(mqtt.get("username", "")); self.password.setText(mqtt.get("password", ""))
        self.tls.setChecked(mqtt.get("tls", False)); self.hardware.setChecked(data.get("hardware", False))

    def poll_sensors(self):
        extra = self.window.engine.renderer.providers.extra
        sensors = extra.hardware()
        if sensors:
            self.sensors.setPlainText("\n".join(f"{s['Identifier']}\n  {s['Name']} · {s['SensorType']} · {s.get('Value')}" for s in sensors))
        else:
            self.sensors.setPlainText(extra.hardware_probe.error or "Sin sensores. Comprueba que la integración está guardada y LibreHardwareMonitor abierto.")

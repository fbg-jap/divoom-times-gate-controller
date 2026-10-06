from __future__ import annotations

import copy
import json
import secrets
import threading

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (QApplication, QWidget, QDialog, QVBoxLayout, QHBoxLayout, QFormLayout,
    QTabWidget, QCheckBox, QComboBox, QLabel, QLineEdit, QPlainTextEdit, QSpinBox, QDoubleSpinBox,
    QPushButton, QListWidget, QMessageBox, QDialogButtonBox)

from .config import uid
from .extensions import METRICS, normalize_phase, validate_content
from .content import assets
from .platform_support import open_external
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
    b.button(QDialogButtonBox.StandardButton.Save).setText("Save")
    b.button(QDialogButtonBox.StandardButton.Cancel).setText("Cancel")
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
            form.addRow("RSS / Atom URL", self.url); form.addRow("Seconds per headline", self.seconds); form.addRow("Font size", self.size)
            form.addRow(hint("Up to 50 headlines. The feed is checked every 5 minutes; long headlines are cropped to the screen."))
        elif kind == "sensor":
            self.source = combo([("mqtt", "MQTT"), ("hardware", "LibreHardwareMonitor")], screen.get("sensor_source", "mqtt"))
            self.key = QLineEdit(screen.get("sensor_key", ""))
            self.field = QLineEdit(screen.get("sensor_field", "")); self.field.setPlaceholderText("temperature or data.value; empty = full text")
            self.unit = QLineEdit(screen.get("sensor_unit", ""))
            self.stale = number(10, 86400, screen.get("sensor_stale", 300))
            form.addRow("Source", self.source); form.addRow("MQTT topic / sensor ID", self.key)
            form.addRow("JSON field (MQTT)", self.field); form.addRow("Unit", self.unit); form.addRow("Expires after (s)", self.stale)
            form.addRow(hint("Enable the source under Integrations, where you can also look up hardware identifiers. N/A means there is no recent reading."))
        elif kind == "custom":
            form.addRow(btn("Open visual designer…", self.design))
            form.addRow(hint("Combine text, images and bars. PC data updates together with the widget."))
        elif kind == "music":
            form.addRow(hint("Reads the current Windows media session: cover art, song and artist. The player must publish its session to Windows. No password required."))
        elif kind == "prtg":
            form.addRow(hint("Shows PRTG sensor counts (up, warning, down, paused) and the worst sensor. The URL and token are set under Integrations. Refreshes every 30 s."))
        elif kind == "mail":
            form.addRow(hint(self.parent.t("Muestra el número de correos sin leer (IMAP, solo lectura). El servidor y la contraseña se configuran en Integraciones. Se actualiza cada 2 minutos.",
                                      "Shows the number of unread emails (IMAP, read-only). Server and password are set under Integrations. Refreshes every 2 minutes.")))
        elif kind == "spotify":
            form.addRow(hint(self.parent.t("Muestra la canción de Spotify (API web, solo lectura). Conecta tu cuenta en Integraciones → Spotify. Se actualiza cada 5 segundos.",
                                      "Shows the song playing on Spotify (Web API, read-only). Connect your account under Integrations → Spotify. Refreshes every 5 seconds.")))
        elif kind == "pomodoro":
            form.addRow(hint("Shows the Studio work/break session. Start, pause and configure the session under Automations → Pomodoro. Refreshes every 5 seconds."))

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
                raise ValueError("Enter a specific topic or a sensor identifier")
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
        self.setWindowTitle({"alerts": "Automatic alert", "reminders": "Recurring reminder", "profiles": "Automatic profile"}[group])
        self.setMinimumWidth(540)
        form = QFormLayout(self)
        self.name = QLineEdit(r.get("name", "")); form.addRow("Name", self.name)
        self.device = combo([(d["id"], d["name"]) for d in window.store.snapshot()["devices"]], r["device_id"])
        form.addRow("Device", self.device)
        self.enabled = QCheckBox("Enabled"); self.enabled.setChecked(r.get("enabled", True)); form.addRow(self.enabled)
        if group == "profiles":
            self.trigger = combo([("process", "Application running"), ("locked", "Windows locked"), ("desktop", "Desktop / no matching application")], r.get("trigger", "process"))
            self.process = QLineEdit(r.get("process", "")); self.process.setPlaceholderText("Example: game.exe")
            self.scene = combo([(s["id"], s["name"]) for s in window.store.snapshot()["scenes"]], r.get("scene_id"))
            form.addRow("Condition", self.trigger); form.addRow("Executable name", self.process); form.addRow("Scene", self.scene)
            form.addRow(hint("Priority: lock, application, then desktop. Among applications, the first rule in the list wins. When nothing matches any more, the saved layout is restored."))
        else:
            self.panel = number(1, 5, r.get("panel", 0)+1)
            self.text = QPlainTextEdit(r.get("text", "")); self.text.setMaximumHeight(70)
            self.seconds = number(5, 300, r.get("seconds", 15))
            self.buzzer = QCheckBox("Beep"); self.buzzer.setChecked(r.get("buzzer", False))
            if group == "reminders":
                self.minutes = number(1, 10080, r.get("minutes", 30)); form.addRow("Repeat every (min)", self.minutes)
                form.addRow(hint("The interval starts when the rule is enabled or Studio is opened. Requires automatic updates; missed reminders are not recovered."))
            else:
                self.metric_combo = combo([*METRICS, ("disk_free", "Free disk (GiB)"), ("service", "Service down (0 = OK, 1 = failed)"), ("sensor", "Numeric sensor"),
                                           ("prtg_down", window.t("Sensores PRTG en Down", "PRTG sensors Down")), ("prtg_warning", window.t("Sensores PRTG en Warning", "PRTG sensors Warning")),
                                           ("mail_unread", window.t("Correos sin leer", "Unread mail"))], r.get("metric", "cpu"))
                self.operator = combo([("above", "Greater than"), ("below", "Less than")], r.get("operator", "above"))
                self.threshold = QDoubleSpinBox(); self.threshold.setRange(-1e12, 1e12); self.threshold.setValue(r.get("threshold", 80))
                self.source = QLineEdit(r.get("source", "")); self.source.setPlaceholderText("Service URL, disk path or sensor ID/topic")
                self.sensor_source = combo([("mqtt", "MQTT"), ("hardware", "LibreHardwareMonitor")], r.get("sensor_source", "mqtt"))
                self.sensor_field = QLineEdit(r.get("sensor_field", ""))
                self.hold = number(0, 3600, r.get("hold", 10)); self.cooldown = number(30, 86400, r.get("cooldown", 300))
                for label, w in [("Metric", self.metric_combo), ("Comparison", self.operator), ("Threshold", self.threshold), ("Source (if applicable)", self.source), ("Sensor type", self.sensor_source), ("Sensor JSON field", self.sensor_field), ("Hold condition (s)", self.hold), ("Minimum between alerts (s)", self.cooldown)]:
                    form.addRow(label, w)
                form.addRow(hint("One alert per incident, re-armed once the value returns to normal. For a service that is down: greater than 0.5. Missing sensors do not trigger alerts."))
            form.addRow("Screen (with image or widget)", self.panel); form.addRow("Message", self.text); form.addRow("Alert duration (s)", self.seconds); form.addRow(self.buzzer)
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
        for text, callback in [("Add", self.add), ("Edit", self.edit), ("Enable / disable", self.toggle), ("↑", lambda: self.move(-1)), ("↓", lambda: self.move(1)), ("Delete", self.remove)]:
            row.addWidget(btn(text, callback))
        layout.addLayout(row)
        layout.addWidget(hint("Rules apply to their device while Auto-update is on. Alerts respect pause and power-off."))
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
        self.panel = number(1, 5, 1); self.buzzer = QCheckBox("Beep on phase change")
        self.status = QLabel("Ready · 25:00"); form.addRow(self.status)
        for text, w in [("Work (min)", self.work), ("Break (min)", self.rest), ("Long break (min)", self.long_rest), ("Long break every N cycles", self.cycles), ("Screen for alerts", self.panel)]:
            form.addRow(text, w)
        form.addRow(self.buzzer)
        row = QHBoxLayout()
        for label, operation in [("Start", "start"), ("Pause", "pause"), ("Resume", "resume"), ("Skip phase", "skip"), ("Reset", "reset")]:
            row.addWidget(btn(label, lambda checked=False, op=operation: self.control(op)))
        form.addRow(row)
        form.addRow(hint("Choose the Pomodoro widget under Screens to see the countdown. The session lasts while Studio stays open; alerts require automatic updates."))
        tabs.addTab(page, "Pomodoro")
        self.panels = []
        for group, title in [("alerts", "Alerts"), ("reminders", "Reminders"), ("profiles", "Profiles")]:
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
        self.status.setText(f"{normalize_phase(data['phase'])} · {seconds//60:02}:{seconds%60:02} · cycle {data['cycle']} · {'Running' if data['running'] else 'Paused'}")


class IntegrationPanel(QWidget):
    def __init__(self, window):
        super().__init__(); self.window = window
        layout = QVBoxLayout(self); tabs = QTabWidget(); layout.addWidget(tabs)
        data = window.store.snapshot().get("integrations", {}); api, mqtt = data.get("api", {}), data.get("mqtt", {})
        page = QWidget(); form = QFormLayout(page)
        self.api_on = QCheckBox("Enable API"); self.api_on.setChecked(api.get("enabled", False))
        self.api_lan = QCheckBox("Allow connections from the local network"); self.api_lan.setChecked(api.get("host") == "0.0.0.0")
        self.api_port = number(1, 65535, api.get("port", 8787))
        self.token = QLineEdit(api.get("token") or secrets.token_urlsafe(32)); self.token.setEchoMode(QLineEdit.EchoMode.Password)
        row = QHBoxLayout(); row.addWidget(self.token); row.addWidget(btn("Copy", lambda: QApplication.clipboard().setText(self.token.text()))); row.addWidget(btn("New token", lambda: self.token.setText(secrets.token_urlsafe(32))))
        form.addRow(self.api_on); form.addRow(self.api_lan); form.addRow("Port", self.api_port); form.addRow("Token", row)
        self.api_status = QLabel(); form.addRow(self.api_status)
        form.addRow(hint('GET /v1/status · POST /v1/action\nHeader: Authorization: Bearer YOUR_TOKEN\nExample: {"action":"notice","panel":1,"text":"Hello","seconds":15}\nActions: notice, scene, brightness, power, send. panel uses 1–5. See scene and device IDs in /v1/status.'))
        form.addRow(hint("By default it only responds on this PC. LAN access uses plain HTTP; reserve it for a trusted network. Studio does not change the firewall."))
        tabs.addTab(page, "Local API")
        page = QWidget(); form = QFormLayout(page)
        self.mqtt_on = QCheckBox("Enable MQTT / Home Assistant"); self.mqtt_on.setChecked(mqtt.get("enabled", False))
        self.mqtt_host = QLineEdit(mqtt.get("host", "")); self.mqtt_port = number(1, 65535, mqtt.get("port", 1883))
        self.mqtt_prefix = QLineEdit(mqtt.get("prefix", "keeper")); self.user = QLineEdit(mqtt.get("username", ""))
        self.password = QLineEdit(mqtt.get("password", "")); self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.tls = QCheckBox("TLS (verified certificate)"); self.tls.setChecked(mqtt.get("tls", False))
        form.addRow(self.mqtt_on)
        for text, w in [("Server", self.mqtt_host), ("Port", self.mqtt_port), ("Unique prefix for this installation", self.mqtt_prefix), ("User", self.user), ("Password", self.password)]:
            form.addRow(text, w)
        form.addRow(self.tls); self.mqtt_status = QLabel(); form.addRow(self.mqtt_status)
        form.addRow(hint('Connects to the same broker as Home Assistant. Publishes scene buttons through MQTT Discovery.\nJSON commands go to PREFIX/command (same format as the API, no retain).\nTo display a sensor, configure a Sensor widget with its MQTT topic and JSON field. Home Assistant must publish the value to that topic.'))
        tabs.addTab(page, "MQTT / Home Assistant")
        page = QWidget(); form = QFormLayout(page)
        self.hardware = QCheckBox("Read LibreHardwareMonitor sensors"); self.hardware.setChecked(data.get("hardware", False)); form.addRow(self.hardware)
        form.addRow(hint("Requires LibreHardwareMonitor to be open with its WMI provider available. Studio does not install drivers or elevate permissions. Available temperatures complement the PC monitor."))
        self.sensors = QPlainTextEdit(); self.sensors.setReadOnly(True); self.sensors.setMinimumHeight(230); form.addRow(self.sensors)
        form.addRow(btn("Refresh sensor list", self.poll_sensors))
        tabs.addTab(page, "PC sensors")
        self.build_new_tabs(tabs, data)
        tabs.setUsesScrollButtons(True); tabs.tabBar().setExpanding(False)
        layout.addWidget(hint("Save to apply changes. The token and password are stored in your local settings; portable exports omit these credentials."))
        layout.addWidget(btn("Save integrations", self.save))
        self.timer = QTimer(self); self.timer.timeout.connect(self.poll); self.timer.start(1500); self.poll()

    def build_new_tabs(self, tabs, data):
        t = self.window.t
        from .config import defaults
        base = defaults()["integrations"]
        spotify, prtg, mail, notif = ({**base[k], **data.get(k, {})} for k in ("spotify", "prtg", "mail", "notifications"))
        def secret(value):
            w = QLineEdit(value); w.setEchoMode(QLineEdit.EchoMode.Password); return w
        page = QWidget(); form = QFormLayout(page)
        self.sp_on = QCheckBox(t("Activar Spotify", "Enable Spotify")); self.sp_on.setChecked(spotify["enabled"])
        self.sp_client = QLineEdit(spotify["client_id"]); self.sp_token = spotify["refresh_token"]; self.sp_dirty = False
        self.sp_status = QLabel()
        form.addRow(self.sp_on); form.addRow("Client ID", self.sp_client); form.addRow(self.sp_status)
        self.sp_connect = btn(t("Conectar Spotify", "Connect Spotify"), self.spotify_connect)
        form.addRow(self.sp_connect); form.addRow(btn(t("Desconectar", "Disconnect"), self.spotify_disconnect))
        form.addRow(hint(t("Crea una app en developer.spotify.com, registra la URI de redirección http://127.0.0.1/callback y pega aquí su Client ID. Solo se guarda el token de actualización.",
                           "Create an app at developer.spotify.com, register the redirect URI http://127.0.0.1/callback and paste its Client ID here. Only the refresh token is stored.")))
        self.spotify_opener, self.sp_job = open_external, None
        tabs.addTab(page, "Spotify")
        page = QWidget(); form = QFormLayout(page)
        self.prtg_on = QCheckBox(t("Activar PRTG", "Enable PRTG")); self.prtg_on.setChecked(prtg["enabled"])
        self.prtg_url = QLineEdit(prtg["base_url"]); self.prtg_token = secret(prtg["token"])
        self.prtg_tls = QCheckBox(t("Verificar certificado TLS", "Verify TLS certificate")); self.prtg_tls.setChecked(prtg["verify_tls"])
        form.addRow(self.prtg_on); form.addRow(t("URL base", "Base URL"), self.prtg_url); form.addRow("Token", self.prtg_token); form.addRow(self.prtg_tls)
        tabs.addTab(page, "PRTG")
        page = QWidget(); form = QFormLayout(page)
        self.mail_on = QCheckBox(t("Activar correo (IMAP)", "Enable mail (IMAP)")); self.mail_on.setChecked(mail["enabled"])
        self.mail_host = QLineEdit(mail["host"]); self.mail_port = number(1, 65535, mail["port"])
        self.mail_user = QLineEdit(mail["user"]); self.mail_password = secret(mail["password"])
        self.mail_box = QLineEdit(mail["mailbox"])
        self.mail_subject = QCheckBox(t("Mostrar el asunto", "Show the subject")); self.mail_subject.setChecked(mail["show_subject"])
        form.addRow(self.mail_on)
        for text, w in [(t("Servidor", "Server"), self.mail_host), (t("Puerto", "Port"), self.mail_port), (t("Usuario", "User"), self.mail_user),
                        (t("Contraseña", "Password"), self.mail_password), (t("Buzón", "Mailbox"), self.mail_box)]:
            form.addRow(text, w)
        form.addRow(self.mail_subject)
        tabs.addTab(page, t("Correo", "Mail"))
        page = QWidget(); form = QFormLayout(page)
        self.nt_on = QCheckBox(t("Activar notificaciones del PC", "Enable PC notifications")); self.nt_on.setChecked(notif["enabled"])
        self.nt_panel = number(1, 5, notif["panel"]); self.nt_seconds = number(5, 60, notif["seconds"]); self.nt_rate = number(1, 60, notif["per_minute"])
        self.nt_allow = QLineEdit(", ".join(notif["allow_apps"])); self.nt_deny = QLineEdit(", ".join(notif["deny_apps"]))
        self.nt_body = QCheckBox(t("Mostrar el cuerpo del mensaje", "Show the message body")); self.nt_body.setChecked(notif["show_body"])
        form.addRow(self.nt_on)
        for text, w in [(t("Pantalla", "Screen"), self.nt_panel), (t("Segundos", "Seconds"), self.nt_seconds), (t("Máximo por minuto", "Maximum per minute"), self.nt_rate),
                        (t("Apps permitidas (separadas por comas)", "Allowed apps (comma separated)"), self.nt_allow),
                        (t("Apps bloqueadas (separadas por comas)", "Blocked apps (comma separated)"), self.nt_deny)]:
            form.addRow(text, w)
        form.addRow(self.nt_body)
        self.nt_status = QLabel(); form.addRow(self.nt_status)
        tabs.addTab(page, t("Notificaciones", "Notifications"))
        self.refresh_spotify_status()

    def refresh_spotify_status(self):
        t = self.window.t
        self.sp_status.setText(t("Estado: ", "Status: ") + (t("conectado", "connected") if self.sp_token else t("sin conectar", "not connected")))

    def spotify_connect(self):
        t = self.window.t
        client_id = self.sp_client.text().strip()
        if not client_id or self.sp_job is not None:
            self.sp_status.setText(t("Estado: introduce el Client ID", "Status: enter the Client ID") if not client_id else self.sp_status.text())
            return
        from .spotify import connect_loopback, SpotifyError
        job = self.sp_job = {"done": False, "token": None, "error": ""}
        def work():
            try:
                job["token"] = connect_loopback(client_id, self.spotify_opener)
            except SpotifyError as error:
                job["error"] = str(error)
            except Exception:
                job["error"] = "unexpected error"
            job["done"] = True
        threading.Thread(target=work, daemon=True, name="keeper-spotify-connect").start()
        self.sp_status.setText(t("Estado: esperando la autorización en el navegador…", "Status: waiting for authorization in the browser…"))
        QTimer.singleShot(500, self.spotify_poll)

    def spotify_poll(self):
        job = self.sp_job
        if job is None:
            return
        if not job["done"]:
            QTimer.singleShot(500, self.spotify_poll)
            return
        self.sp_job = None
        if job["token"]:
            self.spotify_store(job["token"])
        else:
            self.sp_status.setText(self.window.t("Estado: error · ", "Status: failed · ") + job["error"])

    def spotify_store(self, token):
        self.sp_token, self.sp_dirty = token, True
        try:
            self.window.store.change(lambda data: data.setdefault("integrations", {}).setdefault("spotify", {}).update(refresh_token=token, client_id=self.sp_client.text().strip()))
        except Exception as error:
            QMessageBox.warning(self, "Spotify", str(error))
        self.refresh_spotify_status()

    def spotify_disconnect(self):
        self.spotify_store("")

    def save(self):
        names = lambda w: [n.strip() for n in w.text().split(",") if n.strip()]
        config = {"spotify": {"enabled": self.sp_on.isChecked(), "client_id": self.sp_client.text().strip(), "refresh_token": self.sp_token},
                  "prtg": {"enabled": self.prtg_on.isChecked(), "base_url": self.prtg_url.text().strip(), "token": self.prtg_token.text().strip(), "verify_tls": self.prtg_tls.isChecked()},
                  "mail": {"enabled": self.mail_on.isChecked(), "host": self.mail_host.text().strip(), "port": self.mail_port.value(), "user": self.mail_user.text().strip(),
                           "password": self.mail_password.text(), "mailbox": self.mail_box.text().strip() or "INBOX", "show_subject": self.mail_subject.isChecked()},
                  "notifications": {"enabled": self.nt_on.isChecked(), "panel": self.nt_panel.value(), "seconds": self.nt_seconds.value(), "allow_apps": names(self.nt_allow),
                                    "deny_apps": names(self.nt_deny), "show_body": self.nt_body.isChecked(), "per_minute": self.nt_rate.value()},
                  "hardware": self.hardware.isChecked(),
                  "api": {"enabled": self.api_on.isChecked(), "host": "0.0.0.0" if self.api_lan.isChecked() else "127.0.0.1", "port": self.api_port.value(), "token": self.token.text().strip()},
                  "mqtt": {"enabled": self.mqtt_on.isChecked(), "host": self.mqtt_host.text().strip(), "port": self.mqtt_port.value(), "prefix": self.mqtt_prefix.text().strip(), "username": self.user.text(), "password": self.password.text(), "tls": self.tls.isChecked()}}
        try:
            def apply(data):
                if not self.sp_dirty:  # SpotifySource may have rotated the token since this panel loaded it
                    config["spotify"]["refresh_token"] = data.get("integrations", {}).get("spotify", {}).get("refresh_token", self.sp_token)
                data.update(integrations=config)
            self.window.store.change(apply)
            self.sp_dirty, self.sp_token = False, config["spotify"]["refresh_token"]
            self.window.toast("Integrations saved")
        except Exception as error:
            QMessageBox.warning(self, "Integrations", str(error))

    def poll(self):
        self.api_status.setText("Status: " + self.window.engine.bridge.api_status)
        self.mqtt_status.setText("Status: " + self.window.engine.bridge.mqtt_status)
        self.nt_status.setText("Status: " + self.window.engine.bridge.notifications.status)

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
        sp, pr, ml, nt = ({**defaults()["integrations"][k], **data.get(k, {})} for k in ("spotify", "prtg", "mail", "notifications"))
        self.sp_on.setChecked(sp["enabled"]); self.sp_client.setText(sp["client_id"]); self.sp_token, self.sp_dirty = sp["refresh_token"], False; self.refresh_spotify_status()
        self.prtg_on.setChecked(pr["enabled"]); self.prtg_url.setText(pr["base_url"]); self.prtg_token.setText(pr["token"]); self.prtg_tls.setChecked(pr["verify_tls"])
        self.mail_on.setChecked(ml["enabled"]); self.mail_host.setText(ml["host"]); self.mail_port.setValue(ml["port"]); self.mail_user.setText(ml["user"])
        self.mail_password.setText(ml["password"]); self.mail_box.setText(ml["mailbox"]); self.mail_subject.setChecked(ml["show_subject"])
        self.nt_on.setChecked(nt["enabled"]); self.nt_panel.setValue(nt["panel"]); self.nt_seconds.setValue(nt["seconds"]); self.nt_rate.setValue(nt["per_minute"])
        self.nt_allow.setText(", ".join(nt["allow_apps"])); self.nt_deny.setText(", ".join(nt["deny_apps"])); self.nt_body.setChecked(nt["show_body"])

    def poll_sensors(self):
        extra = self.window.engine.renderer.providers.extra
        sensors = extra.hardware()
        if sensors:
            self.sensors.setPlainText("\n".join(f"{s['Identifier']}\n  {s['Name']} · {s['SensorType']} · {s.get('Value')}" for s in sensors))
        else:
            self.sensors.setPlainText(extra.hardware_probe.error or "No sensors. Check that the integration is saved and LibreHardwareMonitor is open.")

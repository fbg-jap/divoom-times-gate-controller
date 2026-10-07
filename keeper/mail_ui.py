"""Integrations → Mail tab: the account list and the editor of the selected account (IMAP, Google, Microsoft)."""
from __future__ import annotations

import copy
import threading

import requests

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (QApplication, QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QCheckBox, QComboBox, QLabel,
    QLineEdit, QSpinBox, QPushButton, QListWidget, QMessageBox, QInputDialog)

from .extensions import spotify_redirect_kind
from .mail import ACCOUNT_DEFAULTS, DEFAULT_HOSTS, MAX_ACCOUNTS, migrate_conf, new_account
from .platform_support import open_external


class MailAccountsPanel(QWidget):
    def __init__(self, window, conf):
        super().__init__()
        self.window = window
        t = window.t
        self.opener, self.prompt, self.job = open_external, (lambda title, label: QInputDialog.getText(self, title, label)), None
        self.dirty, self.current, self.loading = set(), -1, False
        outer = QVBoxLayout(self)
        self.on = QCheckBox(t("Activar correo", "Enable mail")); outer.addWidget(self.on)
        row = QHBoxLayout()
        self.list = QListWidget(); self.list.setMaximumHeight(110); self.list.currentRowChanged.connect(self.select)
        row.addWidget(self.list, 1)
        buttons = QVBoxLayout()
        for text, callback in ((t("Añadir cuenta", "Add account"), self.add), (t("Quitar", "Remove"), self.remove)):
            button = QPushButton(text); button.clicked.connect(lambda checked=False, c=callback: c()); buttons.addWidget(button)
        buttons.addStretch(); row.addLayout(buttons); outer.addLayout(row)
        self.page = QWidget(); self.form = form = QFormLayout(self.page); outer.addWidget(self.page)
        self.name = QLineEdit()
        self.provider = QComboBox()
        for key, text in (("imap", t("IMAP (contraseña)", "IMAP (password)")), ("google", "Google (Gmail / Workspace)"), ("microsoft", "Microsoft (Outlook / 365)")):
            self.provider.addItem(text, key)
        self.host = QLineEdit(); self.port = QSpinBox(); self.port.setRange(1, 65535); self.port.setValue(993)
        self.user = QLineEdit(); self.user_label = QLabel()
        self.password = QLineEdit(); self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.client_id = QLineEdit(); self.client_secret = QLineEdit(); self.client_secret.setEchoMode(QLineEdit.EchoMode.Password)
        self.tenant = QLineEdit(); self.tenant.setPlaceholderText("common")
        self.redirect = QLineEdit()
        self.redirect.setPlaceholderText(t("vacío = automático (http://127.0.0.1) o una dirección https", "empty = automatic (http://127.0.0.1) or an https address"))
        self.mailbox = QLineEdit()
        self.subject = QCheckBox(t("Mostrar el asunto", "Show the subject"))
        self.enabled = QCheckBox(t("Cuenta activada", "Account enabled"))
        self.status = QLabel(); self.status.setWordWrap(True)
        self.connect_button = QPushButton(t("Conectar", "Connect")); self.connect_button.clicked.connect(lambda: self.connect())
        self.disconnect_button = QPushButton(t("Desconectar", "Disconnect")); self.disconnect_button.clicked.connect(lambda: self.disconnect())
        oauth_row = QWidget(); box = QHBoxLayout(oauth_row); box.setContentsMargins(0, 0, 0, 0)
        box.addWidget(self.connect_button); box.addWidget(self.disconnect_button)
        self.oauth_row = oauth_row
        self.hint = QLabel(t("Crea tu propia app OAuth (Google Cloud o Microsoft Entra) y pega aquí su Client ID; consulta docs/INTEGRATIONS.md. Solo se guarda el token de actualización.",
                             "Create your own OAuth app (Google Cloud or Microsoft Entra) and paste its Client ID here; see docs/INTEGRATIONS.md. Only the refresh token is stored."))
        self.hint.setWordWrap(True)
        self.rows = {}
        for key, label, widget in (
                ("enabled", None, self.enabled), ("name", t("Nombre", "Name"), self.name), ("provider", t("Proveedor", "Provider"), self.provider),
                ("host", t("Servidor", "Server"), self.host), ("port", t("Puerto", "Port"), self.port),
                ("user", self.user_label, self.user), ("password", t("Contraseña", "Password"), self.password),
                ("client_id", "Client ID", self.client_id), ("client_secret", "Client secret", self.client_secret), ("tenant", "Tenant", self.tenant),
                ("redirect", t("URI de redirección", "Redirect URI"), self.redirect), ("oauth", None, oauth_row), ("status", None, self.status),
                ("mailbox", t("Buzón", "Mailbox"), self.mailbox), ("subject", None, self.subject), ("hint", None, self.hint)):
            form.addRow(label, widget) if label is not None else form.addRow(widget)
            self.rows[key] = widget
        self.provider.currentIndexChanged.connect(self.provider_changed)
        self.load(conf)

    # ---- model -------------------------------------------------------------------------------------------------
    def load(self, conf):
        conf = migrate_conf(conf)
        self.accounts = [{**ACCOUNT_DEFAULTS, **a} for a in conf.get("accounts", []) if isinstance(a, dict)]
        self.on.setChecked(bool(conf.get("enabled")))
        self.dirty, self.current = set(), -1
        self.refresh_list(0 if self.accounts else -1)

    def refresh_list(self, row):
        self.loading = True
        self.list.clear()
        for a in self.accounts:
            self.list.addItem(("● " if a["enabled"] else "○ ") + (a["name"] or a["user"] or a["id"]))
        self.loading = False
        self.current = -1
        self.list.setCurrentRow(row)
        if row < 0:
            self.select(-1)

    def select(self, row):
        if self.loading:
            return
        self.commit()
        self.current = row
        self.page.setEnabled(row >= 0)
        a = self.accounts[row] if 0 <= row < len(self.accounts) else dict(ACCOUNT_DEFAULTS)
        self.loading = True
        self.name.setText(a["name"]); self.provider.setCurrentIndex(max(0, self.provider.findData(a["provider"])))
        self.host.setText(a["host"]); self.port.setValue(int(a["port"])); self.user.setText(a["user"]); self.password.setText(a["password"])
        self.client_id.setText(a["client_id"]); self.client_secret.setText(a["client_secret"]); self.tenant.setText(a["tenant"])
        self.redirect.setText(a["redirect_uri"]); self.mailbox.setText(a["mailbox"]); self.subject.setChecked(a["show_subject"])
        self.enabled.setChecked(a["enabled"])
        self.loading = False
        self.update_rows()

    def commit(self):
        """Copy the form into the selected account (the refresh token is only ever set by connect/disconnect)."""
        if self.loading or not 0 <= self.current < len(self.accounts):
            return
        a = self.accounts[self.current]
        a.update(name=self.name.text().strip()[:40], provider=self.provider.currentData(), host=self.host.text().strip(), port=self.port.value(),
                 user=self.user.text().strip(), password=self.password.text(), client_id=self.client_id.text().strip(),
                 client_secret=self.client_secret.text().strip(), tenant=self.tenant.text().strip() or "common",
                 redirect_uri=self.redirect.text().strip(), mailbox=self.mailbox.text().strip() or "INBOX",
                 show_subject=self.subject.isChecked(), enabled=self.enabled.isChecked())
        item = self.list.item(self.current)
        if item is not None:
            item.setText(("● " if a["enabled"] else "○ ") + (a["name"] or a["user"] or a["id"]))

    def config(self):
        self.commit()
        return {"enabled": self.on.isChecked(), "accounts": copy.deepcopy(self.accounts)}

    def merge_tokens(self, config, stored):
        """Before saving: keep the stored refresh token of every account this session did not connect/disconnect
        (the sampler may have rotated it since the panel loaded)."""
        current = {a.get("id"): a for a in migrate_conf(stored.get("integrations", {}).get("mail", {})).get("accounts", []) if isinstance(a, dict)}
        for a in config["accounts"]:
            if a["id"] not in self.dirty and a["id"] in current:
                a["refresh_token"] = current[a["id"]].get("refresh_token", "")

    def saved(self, config):
        self.dirty = set()
        for saved, a in zip(config["accounts"], self.accounts):
            a["refresh_token"] = saved["refresh_token"]
        self.update_rows()

    # ---- list buttons --------------------------------------------------------------------------------------------
    def add(self):
        if len(self.accounts) >= MAX_ACCOUNTS:
            return
        self.commit()
        self.accounts.append(new_account())
        self.refresh_list(len(self.accounts) - 1)

    def remove(self):
        row = self.list.currentRow()
        if 0 <= row < len(self.accounts):
            self.commit()
            self.accounts.pop(row)
            self.refresh_list(min(row, len(self.accounts) - 1))

    # ---- form ---------------------------------------------------------------------------------------------------
    def provider_changed(self, *_):
        if self.loading:
            return
        provider = self.provider.currentData()
        hosts = set(DEFAULT_HOSTS.values())
        if provider in DEFAULT_HOSTS:
            self.host.setText(DEFAULT_HOSTS[provider]); self.port.setValue(993)
        elif self.host.text().strip() in hosts:
            self.host.setText("")
        self.update_rows()

    def update_rows(self):
        t = self.window.t
        provider = self.provider.currentData() or "imap"
        oauth = provider in DEFAULT_HOSTS
        self.user_label.setText(t("Correo de la cuenta", "Account email") if oauth else t("Usuario", "User"))
        visible = {"password": not oauth, "client_id": oauth, "client_secret": provider == "google", "tenant": provider == "microsoft",
                   "redirect": oauth, "oauth": oauth, "status": oauth, "hint": oauth}
        for key, show in visible.items():
            self.form.setRowVisible(self.rows[key], show)
        self.refresh_status()

    def refresh_status(self, message=""):
        t = self.window.t
        a = self.accounts[self.current] if 0 <= self.current < len(self.accounts) else None
        if message:
            self.status.setText(message)
        elif a is not None and a["refresh_token"]:
            self.status.setText(t("Estado: conectado como ", "Status: connected as ") + (a["user"] or "?"))
        else:
            self.status.setText(t("Estado: sin conectar", "Status: not connected"))

    # ---- OAuth sign-in --------------------------------------------------------------------------------------------
    def connect(self):
        from . import oauth
        t = self.window.t
        self.commit()
        if self.job is not None or not 0 <= self.current < len(self.accounts):
            return
        account = copy.deepcopy(self.accounts[self.current])
        provider = account["provider"]
        if provider not in DEFAULT_HOSTS:
            return
        if not account["client_id"] or (provider == "google" and not account["client_secret"]):
            self.refresh_status(t("Estado: introduce el Client ID" + (" y el Client secret" if provider == "google" else ""),
                                  "Status: enter the Client ID" + (" and the Client secret" if provider == "google" else "")))
            return
        redirect = account["redirect_uri"]
        kind = spotify_redirect_kind(redirect)
        if kind is None:
            self.refresh_status(t("Estado: URI de redirección no válida", "Status: invalid redirect URI"))
            return
        label = oauth.PROVIDERS[provider]["label"]
        manual = verifier = state = None
        if kind == "https":
            url, verifier, state = oauth.begin_manual(provider, account, redirect)
            if not self.opener(url):
                QApplication.clipboard().setText(url)
                self.refresh_status(t("Estado: no se pudo abrir el navegador; la dirección de autorización está en el portapapeles, pégala en un navegador",
                                      "Status: could not open the browser; the authorization address is on the clipboard, paste it into a browser"))
            text, ok = self.prompt(label, t(f"Pega la dirección de la página a la que te envió {label} (empieza por {redirect}?code=…)",
                                            f"Paste the address of the page {label} sent you to (it starts with {redirect}?code=…)"))
            if not ok:
                return
            manual = text
        job = self.job = {"done": False, "token": None, "error": "", "id": account["id"]}
        def work():
            try:
                if manual is not None:
                    job["token"] = oauth.finish_manual(requests.Session(), provider, account, redirect, verifier, state, manual)
                else:
                    job["token"] = oauth.connect_loopback(provider, account, self.opener)
            except oauth.OAuthError as error:
                job["error"] = str(error)
            except Exception:
                job["error"] = "unexpected error"
            job["done"] = True
        threading.Thread(target=work, daemon=True, name="keeper-mail-connect").start()
        self.refresh_status(t("Estado: comprobando…", "Status: checking…") if manual is not None else
                            t("Estado: esperando la autorización en el navegador…", "Status: waiting for authorization in the browser…"))
        QTimer.singleShot(500, self.poll)

    def poll(self):
        job = self.job
        if job is None:
            return
        if not job["done"]:
            QTimer.singleShot(500, self.poll)
            return
        self.job = None
        if job["token"]:
            self.store_token(job["id"], job["token"])
        else:
            self.refresh_status(self.window.t("Estado: error · ", "Status: failed · ") + job["error"])

    def store_token(self, account_id, token):
        """Set (or clear) the refresh token of one account right away, together with the app settings it belongs to."""
        account = next((a for a in self.accounts if a["id"] == account_id), None)
        if account is None:
            return
        account["refresh_token"] = token
        self.dirty.add(account_id)
        owned = {k: account[k] for k in ("provider", "client_id", "client_secret", "tenant", "redirect_uri")}
        def apply(data):
            mail = data.setdefault("integrations", {}).setdefault("mail", {})
            mail.update(migrate_conf(mail))
            for stored in mail["accounts"]:
                if stored.get("id") == account_id:
                    stored.update(refresh_token=token, **owned)
                    return
            mail["accounts"].append({**copy.deepcopy(account), "enabled": False})  # not saved yet: keep it off until the panel is saved
        try:
            self.window.store.change(apply)
        except Exception as error:
            QMessageBox.warning(self, "Mail", str(error))
        self.refresh_status()

    def disconnect(self):
        self.commit()
        if 0 <= self.current < len(self.accounts):
            self.store_token(self.accounts[self.current]["id"], "")

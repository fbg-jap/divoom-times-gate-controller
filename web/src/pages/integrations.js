import {ctx} from "../ctx.js";
import {el,button,card,hint,banner,mark,field,numeric,render,toast,save,load} from "../ui.js";
import {t,setLanguage,languages} from "../i18n.js";
import {token,request} from "../api.js";
import {id,MAX_MAIL_ACCOUNTS,newMailAccount,applyMailProvider,isOAuthMail,removeMailAccount} from "../model.js";
import {startOAuth,waitConnected,completeOAuth,storedToken} from "../oauth.js";
const names = (conf, key) => ({
  get list() {
    return conf[key].join(", ");
  },
  set list(value) {
    conf[key] = value.split(",").map((n) => n.trim()).filter(Boolean);
  },
});
function timeStatus() {
  const s = ctx.state?.runtime?.timesync;
  if (!s || !s.enabled) return t("ui.timesync_off");
  if (s.offset_ms == null) return t("ui.timesync_unsynced") + (s.error ? " · " + t("ui.timesync_error", { error: s.error }) : "");
  return [
    t("ui.timesync_status", { offset: Math.round(s.offset_ms), server: s.server, source: s.source }),
    ...(s.stale ? [t("ui.timesync_stale")] : []),
    ...(s.error ? [t("ui.timesync_error", { error: s.error })] : []),
  ].join(" · ");
}
function timeCard() {
  const conf = ctx.cfg.integrations.timesync;
  return card(
    t("ui.timesync_title"),
    field(conf, "enabled", t("ui.timesync_enable"), "checkbox"),
    field(conf, "source", t("ui.timesync_source"), "select", { ntp: "NTP (UDP 123)", https: "HTTPS (Date)" }),
    field(names(conf, "servers"), "list", t("ui.timesync_servers")),
    field(conf, "https_url", t("ui.timesync_url")),
    numeric(conf, "interval_minutes", t("ui.timesync_interval"), 5, 1440),
    field(conf, "fallback_https", t("ui.timesync_fallback"), "checkbox"),
    field(conf, "sync_device", t("ui.timesync_device"), "checkbox"),
    hint(timeStatus()),
    hint(t("ui.timesync_hint")),
  );
}
const providerName = { spotify: "Spotify", google: "Google", microsoft: "Microsoft" };
// Connect / Disconnect for Spotify or one mail account. The portal holds the PKCE verifier; this page only opens the
// authorization address and then either waits for the stored token (loopback) or sends back the pasted address (manual).
function oauthControls(key, service, accountId, provider, connected) {
  const readToken = async () => storedToken((await request("/state")).config, service, accountId);
  const finish = async () => {
    delete ctx.oauth[key];
    await load();
    render();
    toast(t("ui.oauth_connected"));
  };
  const connect = async () => {
    if (ctx.dirty) await save();
    const before = storedToken(ctx.cfg, service, accountId);
    const flow = await startOAuth(request, (url) => window.open(url, "_blank", "noopener"), service, accountId);
    toast(t("ui.oauth_register_uri", { uri: flow.redirect_uri }));
    if (flow.mode === "manual") {
      ctx.oauth[key] = { state: flow.state, url: flow.url };
      render();
      return;
    }
    toast(t("ui.oauth_waiting"));
    if (await waitConnected(readToken, before)) await finish();
    else toast(t("ui.oauth_timeout"), true);
  };
  const box = el(
    "div",
    {},
    hint(connected ? t(service === "spotify" ? "ui.spotify_connected" : "ui.mail_connected") : t(service === "spotify" ? "ui.spotify_not_connected" : "ui.mail_not_connected")),
    el(
      "div",
      { class: "row" },
      button(t("ui.oauth_connect"), connect),
      button(t("ui.oauth_disconnect"), () => {
        delete ctx.oauth[key];
        if (service === "spotify") ctx.cfg.integrations.spotify.refresh_token = "";
        else ctx.cfg.integrations.mail.accounts.find((a) => a.id === accountId).refresh_token = "";
        mark();
        render();
      }),
    ),
  );
  const pending = ctx.oauth[key];
  if (pending) {
    const input = el("input", { type: "text", autocomplete: "off", spellcheck: "false" });
    box.append(
      hint(t("ui.oauth_paste_title", { service: providerName[provider] })),
      hint(t("ui.oauth_paste_hint")),
      el("a", { href: pending.url, target: "_blank", rel: "noopener" }, t("ui.oauth_open_again")),
      el("label", { class: "field" }, input),
      el(
        "div",
        { class: "row" },
        button(t("ui.oauth_submit"), async () => {
          await completeOAuth(request, pending.state, input.value);
          await finish();
        }),
        button(t("ui.oauth_cancel"), () => {
          delete ctx.oauth[key];
          render();
        }),
      ),
    );
  }
  return box;
}
function mailCard() {
  const mail = ctx.cfg.integrations.mail;
  const accounts = mail.accounts;
  const index = Math.max(0, accounts.findIndex((a) => a.id === ctx.mailAccount));
  const a = accounts[index];
  const list = el("div", { class: "row" });
  accounts.forEach((account, i) =>
    list.append(
      button(
        (account.enabled ? "● " : "○ ") + (account.name || account.user || account.id),
        () => {
          ctx.mailAccount = account.id;
          render();
        },
        i === index ? "active" : "",
      ),
    ),
  );
  const parts = [
    t("ui.mail_imap"),
    field(mail, "enabled", t("ui.enable_mail"), "checkbox"),
    list,
    el(
      "div",
      { class: "row" },
      button(t("ui.mail_add_account"), () => {
        if (accounts.length >= MAX_MAIL_ACCOUNTS) return toast(t("ui.mail_max_accounts"), true);
        const account = newMailAccount();
        accounts.push(account);
        ctx.mailAccount = account.id;
        mark();
        render();
      }),
      a
        ? button(
            t("ui.mail_remove_account"),
            () => {
              removeMailAccount(ctx.cfg, a.id);
              ctx.mailAccount = accounts[Math.min(index, accounts.length - 1)]?.id;
              mark();
              render();
            },
            "danger",
          )
        : null,
    ),
  ];
  if (!a) return card(...parts, hint(t("ui.mail_no_accounts")));
  const oauth = isOAuthMail(a);
  const provider = field(a, "provider", t("ui.mail_provider"), "select", {
    imap: t("ui.mail_provider_imap"),
    google: t("ui.mail_provider_google"),
    microsoft: t("ui.mail_provider_microsoft"),
  });
  provider.querySelector("select").addEventListener("change", (event) => {
    applyMailProvider(a, event.target.value);
    render();
  });
  parts.push(
    field(a, "enabled", t("ui.mail_account_enabled"), "checkbox"),
    el("div", { class: "grid" }, field(a, "name", t("ui.name")), provider),
    el(
      "div",
      { class: "grid" },
      field(a, "host", t("ui.server_2")),
      numeric(a, "port", t("ui.port"), 1, 65535),
    ),
    field(a, "user", oauth ? t("ui.mail_email") : t("ui.username")),
  );
  if (oauth) parts.push(field(a, "allow_custom_host", t("ui.mail_allow_custom_host"), "checkbox"), hint(t("ui.mail_allow_custom_host_hint")));
  if (!oauth) parts.push(field(a, "password", t("ui.password"), "password"));
  else {
    parts.push(field(a, "client_id", t("ui.oauth_client_id")));
    if (a.provider === "google") parts.push(field(a, "client_secret", t("ui.oauth_client_secret"), "password"));
    else parts.push(field(a, "tenant", t("ui.oauth_tenant")));
    parts.push(
      field(a, "redirect_uri", t("ui.oauth_redirect_uri")),
      hint(t("ui.oauth_redirect_hint")),
      oauthControls("mail:" + a.id, "mail", a.id, a.provider, !!a.refresh_token),
      hint(t("ui.oauth_hint")),
    );
  }
  parts.push(field(a, "mailbox", t("ui.mailbox")), field(a, "show_subject", t("ui.show_subject"), "checkbox"));
  return card(...parts);
}
export function integrationPage(main) {
  const mqtt = ctx.cfg.integrations.mqtt;
  main.append(
    card(
      "MQTT / Home Assistant",
      field(mqtt, "enabled", t("ui.enable_mqtt"), "checkbox"),
      ctx.state.capabilities.mode === "mobile"
        ? field(
            mqtt,
            "websocket_url",
            t("ui.broker_websocket_url_ws_or"),
          )
        : el(
            "div",
            { class: "grid" },
            field(mqtt, "host", t("ui.server_2")),
            numeric(mqtt, "port", t("ui.port"), 1, 65535),
          ),
      el(
        "div",
        { class: "grid" },
        field(mqtt, "username", t("ui.username")),
        field(mqtt, "password", t("ui.password"), "password"),
      ),
      field(mqtt, "prefix", t("ui.topic_prefix")),
      ctx.state.capabilities.mode === "mobile"
        ? hint(
            t("ui.the_broker_must_offer_websockets"),
          )
        : field(mqtt, "tls", "TLS", "checkbox"),
      hint(
        t("ui.credentials_are_excluded_from_exported"),
      ),
    ),
  );
  if (ctx.state.capabilities.mode !== "mobile") {
    const api = ctx.cfg.integrations.api;
    main.append(
      card(
        t("ui.automation_api"),
        field(api, "enabled", t("ui.enable_additional_api"), "checkbox"),
        el(
          "div",
          { class: "grid" },
          field(api, "host", t("ui.listen_on"), "select", {
            "127.0.0.1": t("ui.localhost_only"),
            "0.0.0.0": t("ui.local_network_2"),
          }),
          numeric(api, "port", t("ui.port_different_from_the_portal"), 1, 65535),
        ),
        field(api, "token", "Token Bearer", "password"),
        button(t("ui.generate_token"), () => {
          api.token = id() + id() + id();
          mark();
          render();
        }),
        hint(
          t("ui.this_additional_api_keeps_v1"),
        ),
      ),
      card(
        "Spotify",
        field(ctx.cfg.integrations.spotify, "enabled", t("ui.enable_spotify"), "checkbox"),
        field(ctx.cfg.integrations.spotify, "client_id", "Client ID"),
        field(ctx.cfg.integrations.spotify, "redirect_uri", t("ui.spotify_redirect_uri")),
        hint(t("ui.spotify_redirect_uri_hint")),
        ...(ctx.state.capabilities.mode === "server"
          ? [oauthControls("spotify", "spotify", "", "spotify", !!ctx.cfg.integrations.spotify.refresh_token)]
          : [hint(t("ui.spotify_desktop_server_only"))]),
      ),
      card(
        "PRTG",
        field(ctx.cfg.integrations.prtg, "enabled", t("ui.enable_prtg"), "checkbox"),
        field(ctx.cfg.integrations.prtg, "base_url", t("ui.base_url")),
        field(ctx.cfg.integrations.prtg, "token", "Token", "password"),
        field(ctx.cfg.integrations.prtg, "verify_tls", t("ui.verify_tls"), "checkbox"),
        hint(t("ui.prtg_hint")),
      ),
      mailCard(),
      card(
        t("ui.pc_notifications"),
        field(ctx.cfg.integrations.notifications, "enabled", t("ui.enable_pc_notifications"), "checkbox"),
        el(
          "div",
          { class: "grid" },
          numeric(ctx.cfg.integrations.notifications, "panel", t("ui.screen_1_5"), 1, 5),
          numeric(ctx.cfg.integrations.notifications, "seconds", t("ui.seconds_5_60"), 5, 60),
          numeric(ctx.cfg.integrations.notifications, "per_minute", t("ui.max_per_minute"), 1, 60),
        ),
        field(names(ctx.cfg.integrations.notifications, "allow_apps"), "list", t("ui.allowed_apps")),
        field(names(ctx.cfg.integrations.notifications, "deny_apps"), "list", t("ui.blocked_apps")),
        field(ctx.cfg.integrations.notifications, "show_body", t("ui.show_body"), "checkbox"),
        el("h3", {}, "Microsoft Teams"),
        field(ctx.cfg.integrations.notifications.teams, "enabled", t("ui.teams_enable"), "checkbox"),
        field(ctx.cfg.integrations.notifications.teams, "chats", t("ui.teams_chats"), "checkbox"),
        field(ctx.cfg.integrations.notifications.teams, "mentions", t("ui.teams_mentions"), "checkbox"),
        field(ctx.cfg.integrations.notifications.teams, "calls", t("ui.teams_calls"), "checkbox"),
        field(ctx.cfg.integrations.notifications.teams, "show_preview", t("ui.teams_preview"), "checkbox"),
        el(
          "div",
          { class: "grid" },
          numeric(ctx.cfg.integrations.notifications.teams, "panel", t("ui.teams_screen"), 0, 5),
          numeric(ctx.cfg.integrations.notifications.teams, "call_seconds", t("ui.teams_call_seconds"), 5, 60),
        ),
        field(ctx.cfg.integrations.notifications.teams, "buzzer_on_call", t("ui.teams_buzzer"), "checkbox"),
        field(names(ctx.cfg.integrations.notifications.teams, "patterns"), "list", t("ui.teams_patterns")),
        hint(t("ui.teams_hint")),
      ),
      timeCard(),
      card(
        t("ui.host_sources"),
        field(
          ctx.cfg.integrations,
          "hardware",
          t("ui.read_available_sensors"),
          "checkbox",
        ),
        banner(ctx.state.capabilities.metrics_label),
        hint(
          t("ui.linux_psutil_sensors_and_mpris"),
        ),
      ),
    );
  } else
    main.append(
      card(
        t("ui.mobile_sources"),
        hint(
          t("ui.you_can_show_values_from"),
        ),
      ),
    );
}
export function languageField() {
  const select = el("select");
  for (const [value, name] of Object.entries(languages))
    select.append(el("option", { value }, name));
  select.value = ctx.cfg.language;
  select.addEventListener("change", () => {
    ctx.cfg.language = select.value;
    setLanguage(ctx.cfg.language);
    mark();
    render();
  });
  return el("label", { class: "field" }, el("span", {}, t("ui.language")), select);
}

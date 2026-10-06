import {ctx} from "../ctx.js";
import {el,button,card,hint,banner,mark,field,numeric,render,toast} from "../ui.js";
import {t,setLanguage,languages} from "../i18n.js";
import {token,request} from "../api.js";
import {id} from "../model.js";
const names = (conf, key) => ({
  get list() {
    return conf[key].join(", ");
  },
  set list(value) {
    conf[key] = value.split(",").map((n) => n.trim()).filter(Boolean);
  },
});
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
        hint(
          ctx.cfg.integrations.spotify.refresh_token
            ? t("ui.spotify_connected")
            : t("ui.spotify_not_connected"),
        ),
        ...(ctx.state.capabilities.mode === "server"
          ? [
              button(t("ui.spotify_connect"), async () => {
                try {
                  const r = await request("/spotify/connect", "POST", {
                    client_id: ctx.cfg.integrations.spotify.client_id,
                  });
                  window.open(r.url, "_blank", "noopener");
                  toast(t("ui.spotify_redirect_hint", { uri: r.redirect_uri }));
                } catch (error) {
                  toast(error.message, true);
                }
              }),
              button(t("ui.spotify_disconnect"), () => {
                ctx.cfg.integrations.spotify.refresh_token = "";
                mark();
                render();
              }),
            ]
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
      card(
        t("ui.mail_imap"),
        field(ctx.cfg.integrations.mail, "enabled", t("ui.enable_mail"), "checkbox"),
        el(
          "div",
          { class: "grid" },
          field(ctx.cfg.integrations.mail, "host", t("ui.server_2")),
          numeric(ctx.cfg.integrations.mail, "port", t("ui.port"), 1, 65535),
        ),
        el(
          "div",
          { class: "grid" },
          field(ctx.cfg.integrations.mail, "user", t("ui.username")),
          field(ctx.cfg.integrations.mail, "password", t("ui.password"), "password"),
        ),
        field(ctx.cfg.integrations.mail, "mailbox", t("ui.mailbox")),
        field(ctx.cfg.integrations.mail, "show_subject", t("ui.show_subject"), "checkbox"),
      ),
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
      ),
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

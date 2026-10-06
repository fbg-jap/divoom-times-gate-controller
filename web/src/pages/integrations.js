import {ctx} from "../ctx.js";
import {el,button,card,hint,banner,mark,field,numeric,render} from "../ui.js";
import {t,setLanguage,languages} from "../i18n.js";
import {token} from "../api.js";
import {id} from "../model.js";
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

import {ctx} from "../ctx.js";
import {el,button,row,card,hint,toast,mark,field,numeric,d,load,save,action,saveAndSend,render} from "../ui.js";
import {t} from "../i18n.js";
import {device,removeDevice} from "../model.js";
function removeWithConfirm(dev) {
  if (ctx.cfg.devices.length <= 1) throw Error(t("ui.keep_at_least_one_device"));
  if (!confirm(t("ui.remove_device_confirm").replace("{name}", dev.name || dev.ip || dev.id)))
    return;
  const error = removeDevice(ctx.cfg, dev.id);
  if (error) throw Error(error);
  mark();
  render();
}
function devicesCard() {
  const online = ctx.state?.runtime?.online;
  return card(
    t("ui.devices_list"),
    el(
      "div",
      { class: "devlist" },
      ctx.cfg.devices.map((dev) => {
        const active = dev.id === ctx.cfg.active_device;
        const status = online && dev.id in online ? online[dev.id] : null;
        return el(
          "div",
          { class: "devrow" + (active ? " active" : "") },
          el(
            "div",
            { class: "devinfo" },
            el("strong", {}, dev.name || t("ui.unnamed_device")),
            el("span", { class: dev.ip ? "" : "muted" }, dev.ip || t("ui.no_ip_set")),
          ),
          el(
            "div",
            { class: "devchips" },
            active ? el("span", { class: "chip on" }, t("ui.active")) : null,
            el(
              "span",
              { class: "chip" + (dev.enabled ? " on" : "") },
              dev.enabled ? t("ui.auto_update_on") : t("ui.auto_update_off"),
            ),
            status === null
              ? null
              : el(
                  "span",
                  { class: "chip" + (status ? " on" : " off") },
                  status ? t("ui.online") : t("ui.offline"),
                ),
          ),
          row(
            active
              ? null
              : button(t("ui.select"), () => {
                  ctx.cfg.active_device = dev.id;
                  mark();
                  render();
                }),
            button(t("ui.remove"), () => removeWithConfirm(dev), "danger"),
          ),
        );
      }),
    ),
  );
}
export function devicePage(main) {
  const value = d();
  main.append(devicesCard());
  main.append(
    card(
      t("ui.local_connection"),
      el(
        "div",
        { class: "grid" },
        field(value, "name", t("ui.name")),
        field(value, "ip", t("ui.times_gate_ip_e_g")),
      ),
      field(value, "enabled", t("ui.automatic_update"), "checkbox"),
      row(
        button(t("ui.save_and_check"), async () => {
          await save();
          await action("health", d().id);
          toast(t("ui.check_complete_see_activity"));
        }),
        button(t("ui.scan_lan"), async () => {
          await save();
          const result = await action("discover", d().id, {
            seed: d().ip,
            cloud: false,
          });
          toast(
            result?.devices
              ? t("ui.devices") + JSON.stringify(result.devices)
              : t("ui.see_the_results_in_activity"),
          );
        }),
        button(t("ui.discover_via_divoom"), async () => {
          await save();
          await action("discover", d().id, { cloud: true, seed: d().ip });
          toast(t("ui.see_the_results_in_activity"));
        }),
      ),
      hint(
        t("ui.the_phone_or_server_and"),
      ),
    ),
  );
  main.append(
    card(
      t("ui.send_and_restore"),
      el(
        "div",
        { class: "grid three" },
        numeric(value, "quality", t("ui.jpeg_quality"), 30, 100),
        numeric(value, "speed", t("ui.milliseconds_per_frame"), 1, 60000),
        numeric(
          value,
          "interval_minutes",
          t("ui.resend_media_every_minutes"),
          1,
          10080,
        ),
      ),
      field(value, "suspended", t("ui.pause_sending"), "checkbox"),
      field(ctx.cfg, "resend_on_startup", t("ui.resend_on_startup"), "checkbox"),
      row(
        button(
          t("ui.resume_and_resend"),
          async () => {
            await save();
            await action("resume", d().id);
            await load();
            render();
          },
          "primary",
        ),
        button(t("ui.send_all"), () => saveAndSend()),
      ),
      hint(
        t("ui.panoramic_gifs_keep_their_own"),
      ),
    ),
  );
  main.append(
    card(
      t("ui.multiple_devices"),
      row(
        button(t("ui.add_device"), () => {
          const value = device();
          ctx.cfg.devices.push(value);
          ctx.cfg.active_device = value.id;
          mark();
          render();
        }),
        button(
          t("ui.delete_selected"),
          () => removeWithConfirm(d()),
          "danger",
        ),
      ),
      el(
        "div",
        { class: "grid" },
        field(value, "mac", t("ui.mac_optional")),
        numeric(value, "device_id", t("ui.divoom_deviceid_optional"), 0, 999999999),
        numeric(value, "port", t("ui.port_0_auto"), 0, 65535),
        field(value, "local_token", t("ui.local_token")),
      ),
    ),
  );
}

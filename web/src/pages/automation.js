import {ctx} from "../ctx.js";
import {$,el,button,row,card,hint,mark,field,numeric,d,action,deviceOptions,sceneOptions,render} from "../ui.js";
import {t} from "../i18n.js";
import {id,metrics} from "../model.js";
export function automationPage(main) {
  const p = {
    work: 25,
    rest: 5,
    long_rest: 15,
    cycles: 4,
    panel: 0,
    buzzer: false,
  };
  const pc = card(
    "Pomodoro",
    el("p", { id: "pomodoro-state" }, pomoText()),
    el(
      "div",
      { class: "grid three" },
      numeric(p, "work", t("ui.work_min"), 1, 180),
      numeric(p, "rest", t("ui.break_min"), 1, 180),
      numeric(p, "long_rest", t("ui.long_break_min"), 1, 180),
      numeric(p, "cycles", t("ui.cycles"), 1, 12),
      field(p, "panel", t("ui.alert_screen"), "select", {
        0: "1",
        1: "2",
        2: "3",
        3: "4",
        4: "5",
      }),
      field(p, "buzzer", t("ui.buzzer"), "checkbox"),
    ),
    row(
      ...Object.entries({
        start: t("ui.start"),
        pause: t("ui.pause"),
        resume: t("ui.continue"),
        skip: t("ui.skip_phase"),
        reset: t("ui.reset"),
      }).map(([operation, title]) =>
        button(title, () =>
          action("pomodoro", d().id, { operation, ...p, panel: +p.panel }),
        ),
      ),
    ),
  );
  main.append(pc);
  for (const [group, title] of [
    ["schedules", t("ui.schedules")],
    ["reminders", t("ui.reminders")],
    ["alerts", t("ui.alerts")],
    ["profiles", t("ui.automatic_profiles")],
  ]) {
    if (group === "profiles" && !ctx.state.capabilities.profiles) {
      main.append(
        card(
          title,
          hint(
            t("ui.phones_cannot_query_the_processes"),
          ),
        ),
      );
      continue;
    }
    const section = card(
      title,
      button(t("ui.add_2"), () => {
        let rule = {
          id: id(),
          name: t("ui.new_rule"),
          device_id: d().id,
          enabled: true,
        };
        if (group === "schedules")
          Object.assign(rule, {
            time: "08:00",
            days: [0, 1, 2, 3, 4],
            action: "on",
            value: 1,
          });
        else if (group === "profiles")
          Object.assign(rule, {
            trigger: "process",
            process: "",
            scene_id: ctx.cfg.scenes[0]?.id || "",
          });
        else
          Object.assign(rule, {
            panel: 0,
            seconds: 15,
            text: t("ui.reminder"),
            buzzer: false,
            ...(group === "reminders"
              ? { minutes: 30 }
              : {
                  metric:
                    ctx.state.capabilities.mode === "mobile" ? "service" : "cpu",
                  operator: "above",
                  threshold: 80,
                  hold: 10,
                  cooldown: 300,
                  source: "",
                  sensor_source:
                    ctx.state.capabilities.mode === "mobile" ? "http" : "mqtt",
                  field: "",
                }),
          });
        ctx.cfg[group].push(rule);
        ctx.editing = rule.id;
        mark();
        render();
      }),
    );
    for (const r of ctx.cfg[group]) {
      const box = el(
        "div",
        { class: "list-item" },
        row(
          field(r, "enabled", r.name || r.time || t("ui.rule"), "checkbox"),
          button(t("ui.edit"), () => {
            ctx.editing = ctx.editing === r.id ? null : r.id;
            render();
          }),
          button(
            t("ui.delete"),
            () => {
              ctx.cfg[group] = ctx.cfg[group].filter((x) => x.id !== r.id);
              mark();
              render();
            },
            "danger",
          ),
        ),
      );
      if (ctx.editing === r.id) {
        box.append(
          el(
            "div",
            { class: "grid" },
            field(r, "name", t("ui.name")),
            field(r, "device_id", t("ui.device"), "select", deviceOptions()),
          ),
        );
        if (group === "schedules") {
          box.append(
            field(r, "time", t("ui.local_time"), "time"),
            field(r, "action", t("ui.action"), "select", {
              on: t("ui.turn_on"),
              off: t("ui.turn_off"),
              brightness: t("ui.brightness"),
              scene: t("ui.scene"),
            }),
          );
          box.lastChild.addEventListener("change", () => render());
          if (r.action === "scene")
            box.append(field(r, "value", t("ui.scene"), "select", sceneOptions()));
          if (r.action === "brightness")
            box.append(numeric(r, "value", t("ui.brightness"), 0, 100));
          const days = row();
          [t("ui.day_mon"), t("ui.day_tue"), t("ui.day_wed"), t("ui.day_thu"), t("ui.day_fri"), t("ui.day_sat"), t("ui.day_sun")].forEach((label, i) => {
            const v = { use: r.days.includes(i) },
              f = field(v, "use", label, "checkbox");
            f.addEventListener("change", () => {
              r.days = r.days.filter((x) => x !== i);
              if (v.use) r.days.push(i);
              mark();
            });
            days.append(f);
          });
          box.append(days);
        } else if (group === "profiles") {
          box.append(
            field(r, "trigger", t("ui.condition"), "select", {
              process: t("ui.open_process"),
              locked: t("ui.locked_session"),
              desktop: t("ui.desktop"),
            }),
            field(r, "process", t("ui.process_name")),
            field(r, "scene_id", t("ui.scene"), "select", sceneOptions()),
            hint(
              t("ui.in_docker_only_its_own"),
            ),
          );
        } else {
          box.append(
            field(r, "text", t("ui.message"), "textarea"),
            el(
              "div",
              { class: "grid three" },
              field(r, "panel", t("ui.screen_2"), "select", {
                0: "1",
                1: "2",
                2: "3",
                3: "4",
                4: "5",
              }),
              numeric(r, "seconds", t("ui.duration_s"), 5, 300),
              field(r, "buzzer", t("ui.buzzer"), "checkbox"),
            ),
          );
          const panel = box.querySelector("select:last-of-type");
          if (panel)
            panel.addEventListener("change", () => (r.panel = +r.panel));
          if (group === "reminders")
            box.append(numeric(r, "minutes", t("ui.repeat_every_min"), 1, 10080));
          else {
            box.append(
              field(
                r,
                "metric",
                t("ui.metric"),
                "select",
                ctx.state.capabilities.mode === "mobile"
                  ? { service: t("ui.service_down_1_failure"), sensor: "Sensor" }
                  : {
                      ...metrics,
                      disk_free: t("ui.free_disk"),
                      service: t("ui.service_down_1_failure"),
                      sensor: "Sensor",
                      prtg_down: t("ui.prtg_down_sensors"),
                      prtg_warning: t("ui.prtg_warning_sensors"),
                      mail_unread: t("ui.mail_unread"),
                    },
              ),
              el(
                "div",
                { class: "grid" },
                field(r, "operator", t("ui.condition"), "select", {
                  above: t("ui.greater_than"),
                  below: t("ui.less_than"),
                }),
                numeric(r, "threshold", t("ui.threshold"), -1000000000, 1000000000, 0.1),
              ),
              field(
                r,
                "source",
                t("ui.service_sensor_url_mqtt_topic"),
              ),
              field(
                r,
                "sensor_source",
                t("ui.sensor_source"),
                "select",
                ctx.state.capabilities.mode === "mobile"
                  ? { http: "HTTP JSON", mqtt: "MQTT" }
                  : { mqtt: "MQTT", hardware: "Hardware" },
              ),
              field(r, "field", t("ui.json_path")),
              el(
                "div",
                { class: "grid" },
                numeric(r, "hold", t("ui.condition_held_s"), 0, 3600),
                numeric(r, "cooldown", t("ui.minimum_interval_s"), 30, 86400),
              ),
            );
          }
        }
      }
      section.append(box);
    }
    main.append(section);
  }
  main.append(
    hint(
      t("ui.turn_on_automatic_update_in"),
    ),
  );
}
export function pomoText() {
  const p = ctx.state.runtime?.pomodoro || {};
  // Legacy Spanish phase names (older backends) map to the English values.
  const legacy = { Preparado: "Ready", Trabajo: "Work", Descanso: "Break", "Descanso largo": "Long break" };
  return `${legacy[p.phase] || p.phase || "Ready"} · ${Math.floor((p.remaining || 0) / 60)}:${Math.floor(
    (p.remaining || 0) % 60,
  )
    .toString()
    .padStart(2, "0")} · cycle ${p.cycle || 0}`;
}

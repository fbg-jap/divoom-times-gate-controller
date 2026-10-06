import {el,button,row,card,hint,banner,toast,field,numeric,d,load,action,render} from "../ui.js";
import {t} from "../i18n.js";
export function toolPage(main) {
  const values = {
    brightness: 65,
    minutes: 25,
    seconds: 0,
    red: 0,
    blue: 0,
    panel: 0,
    text: "",
    duration: 15,
    buzzer: false,
    clock: 625,
    group: 1,
  };
  const command = (payload, pause = false) =>
    action("command", d().id, { payload, pause });
  main.append(
    card(
      t("ui.screens_and_brightness"),
      numeric(values, "brightness", t("ui.brightness"), 0, 100),
      row(
        button(t("ui.apply_brightness"), () =>
          command({
            Command: "Channel/SetBrightness",
            Brightness: values.brightness,
          }),
        ),
        button(t("ui.turn_on"), async () => {
          await command({ Command: "Channel/OnOffScreen", OnOff: 1 });
          await load();
          render();
        }),
        button(t("ui.turn_off"), async () => {
          await command({ Command: "Channel/OnOffScreen", OnOff: 0 });
          await load();
          render();
        }),
        button(t("ui.read_settings"), () => action("health", d().id)),
        button(
          t("ui.restart_device"),
          async () => {
            if (confirm(t("ui.restart_the_times_gate")))
              await command({ Command: "Device/SysReboot" });
          },
          "danger",
        ),
      ),
    ),
  );
  main.append(
    card(
      t("ui.temporary_alert"),
      field(values, "text", t("ui.message"), "textarea"),
      el(
        "div",
        { class: "grid three" },
        field(values, "panel", t("ui.screen_2"), "select", {
          0: "1",
          1: "2",
          2: "3",
          3: "4",
          4: "5",
        }),
        numeric(values, "duration", t("ui.duration_s"), 5, 300),
        field(values, "buzzer", t("ui.buzzer"), "checkbox"),
      ),
      button(
        t("ui.send_alert"),
        () =>
          action("notification", d().id, {
            panel: +values.panel,
            text: values.text,
            seconds: +values.duration,
            buzzer: values.buzzer,
          }),
        "primary",
      ),
    ),
  );
  main.append(
    card(
      t("ui.native_tools"),
      banner(
        t("ui.these_tools_can_change_the"),
        true,
      ),
      el(
        "div",
        { class: "grid" },
        numeric(values, "minutes", t("ui.timer_minutes"), 0, 999),
        numeric(values, "seconds", t("ui.seconds"), 0, 59),
      ),
      row(
        button(t("ui.start_timer"), () =>
          command(
            {
              Command: "Tools/SetTimer",
              Minute: values.minutes,
              Second: values.seconds,
              Status: 1,
            },
            true,
          ),
        ),
        button(t("ui.stop"), () =>
          command(
            { Command: "Tools/SetTimer", Minute: 0, Second: 0, Status: 0 },
            true,
          ),
        ),
      ),
      el("hr", { class: "divider" }),
      row(
        button(t("ui.stopwatch_start"), () =>
          command({ Command: "Tools/SetStopWatch", Status: 1 }, true),
        ),
        button(t("ui.pause"), () =>
          command({ Command: "Tools/SetStopWatch", Status: 2 }, true),
        ),
        button(t("ui.reset_stopwatch"), () =>
          command({ Command: "Tools/SetStopWatch", Status: 0 }, true),
        ),
      ),
      el(
        "div",
        { class: "grid" },
        numeric(values, "red", t("ui.red_score"), 0, 999),
        numeric(values, "blue", t("ui.blue_score"), 0, 999),
      ),
      row(
        button(t("ui.show_scoreboard"), () =>
          command(
            {
              Command: "Tools/SetScoreBoard",
              RedScore: values.red,
              BlueScore: values.blue,
            },
            true,
          ),
        ),
        button(t("ui.sound_meter"), () =>
          command({ Command: "Tools/SetNoiseStatus", NoiseStatus: 1 }, true),
        ),
        button(t("ui.stop_meter"), () =>
          command({ Command: "Tools/SetNoiseStatus", NoiseStatus: 0 }, true),
        ),
        button(t("ui.test_buzzer"), () =>
          command({
            Command: "Device/PlayBuzzer",
            ActiveTimeInCycle: 150,
            OffTimeInCycle: 150,
            PlayTotalTime: 600,
          }),
        ),
      ),
      button(
        t("ui.restore_composition"),
        async () => {
          await action("resume", d().id);
          await load();
          render();
        },
        "primary",
      ),
    ),
  );
  main.append(
    card(
      t("ui.experimental_native_catalog_and_clock"),
      hint(
        t("ui.use_only_a_valid_native"),
      ),
      el(
        "div",
        { class: "grid three" },
        numeric(values, "clock", "ClockId", 1, 10000000),
        numeric(values, "group", t("ui.lcdindependence_group"), 1, 100000000),
        field(values, "panel", t("ui.screen_2"), "select", {
          0: "1",
          1: "2",
          2: "3",
          3: "4",
          4: "5",
        }),
      ),
      row(
        button(t("ui.query_catalog"), async () => {
          const r = await action("catalog", d().id);
          if (r) toast(JSON.stringify(r).slice(0, 500));
          else toast(t("ui.see_activity"));
        }),
        button(t("ui.activate_clock"), () =>
          command(
            {
              Command: "Channel/SetClockSelectId",
              ClockId: values.clock,
              LcdIndependence: values.group,
              LcdIndex: +values.panel,
              DeviceId: +d().device_id,
            },
            true,
          ),
        ),
      ),
    ),
  );
}

import {ctx} from "../ctx.js";
import {$,el,button,row,card,hint,banner,mark,field,numeric,d,saveAndSend,showImage,preview,fileField,render} from "../ui.js";
import {t} from "../i18n.js";
import {native} from "../api.js";
import {id,copy,screen,kinds,metrics,mailAccountOptions,sensorGroups,sensorUnit} from "../model.js";
// Picker for a hardware sensor: the machine's sensors grouped by type; picking one fills an empty unit.
function hardwareSensorField(s) {
  const sensors = ctx.state.hardware_sensors || [];
  const select = el("select", { id: "sensor-picker" }, el("option", { value: "" }, t("ui.sensor_choose")));
  for (const group of sensorGroups(sensors, s.sensor_key, t("ui.sensor_missing"))) {
    const parent = group.type ? el("optgroup", { label: group.type }) : select;
    for (const item of group.items) parent.append(el("option", { value: item.id }, item.text));
    if (group.type) select.append(parent);
  }
  select.value = s.sensor_key ?? "";
  select.addEventListener("input", () => {
    s.sensor_key = select.value;
    const type = sensors.find((x) => x.id === select.value)?.type;
    if (type && !s.sensor_unit && sensorUnit(type)) {
      s.sensor_unit = sensorUnit(type);
      mark();
      return render();
    }
    mark();
  });
  return [
    el("label", { class: "field" }, el("span", {}, t("ui.sensor")), select),
    ...(sensors.length ? [] : [hint(t("ui.sensor_none"))]),
  ];
}
export function screenPage(main) {
  const panels = el("div", { class: "panels" });
  d().screens.forEach((s, i) => {
    const img = el("img", { alt: t("ui.screen_0_preview",[i + 1]) });
    const list = d().playlists?.[i];
    const tile = el(
      "button",
      {
        class: "panel" + (ctx.selected === i ? " active" : ""),
        onclick: () => {
          ctx.selected = i;
          ctx.editing = null;
          render();
        },
      },
      el("small", {}, "0" + (i + 1)),
      img,
      el(
        "span",
        {},
        list?.enabled
          ? t("ui.list") + list.items.length
          : s.title || kinds[s.kind],
      ),
    );
    panels.append(tile);
    if (s.kind === "media" && s.path && !list?.enabled) showImage(img, s.path);
    else preview(img, d().id, i);
  });
  main.append(panels);
  main.append(
    card(
      t("ui.screen") + (ctx.selected + 1),
      contentForm(d().screens[ctx.selected]),
      row(
        button(t("ui.save_and_send"), () => saveAndSend(ctx.selected), "primary"),
        button(t("ui.send_all_five"), () => saveAndSend()),
        button(t("ui.panorama"), () => {
          ctx.page = "panorama";
          render();
        }),
      ),
    ),
  );
  const list = d().playlists[ctx.selected];
  const box = card(
    t("ui.playlist"),
    field(list, "enabled", t("ui.use_this_list"), "checkbox"),
    hint(
      t("ui.from_5_seconds_to_24"),
    ),
  );
  list.items.forEach((item, index) => {
    const itemBox = el(
      "div",
      { class: "list-item" },
      row(
        el(
          "strong",
          {},
          `${index + 1}. ${item.screen.title || kinds[item.screen.kind]}`,
        ),
        button(t("ui.edit"), () => {
          ctx.editing = ctx.editing === item.id ? null : item.id;
          render();
        }),
        button("↑", () => {
          if (index) {
            [list.items[index - 1], list.items[index]] = [
              item,
              list.items[index - 1],
            ];
            mark();
            render();
          }
        }),
        button("↓", () => {
          if (index < list.items.length - 1) {
            [list.items[index + 1], list.items[index]] = [
              item,
              list.items[index + 1],
            ];
            mark();
            render();
          }
        }),
        button(
          t("ui.delete"),
          () => {
            list.items.splice(index, 1);
            if (!list.items.length) list.enabled = false;
            mark();
            render();
          },
          "danger",
        ),
      ),
      numeric(item, "seconds", t("ui.duration_seconds"), 5, 86400),
    );
    if (ctx.editing === item.id) itemBox.append(contentForm(item.screen, true));
    box.append(itemBox);
  });
  box.append(
    row(
      button(t("ui.add_widget"), () => {
        const item = { id: id(), seconds: 15, screen: screen("clock") };
        list.items.push(item);
        ctx.editing = item.id;
        mark();
        render();
      }),
      button(t("ui.copy_current_screen"), () => {
        if (
          ["empty", "native", "pc_native"].includes(d().screens[ctx.selected].kind)
        )
          throw Error(t("ui.choose_an_image_or_widget"));
        list.items.push({
          id: id(),
          seconds: 15,
          screen: copy(d().screens[ctx.selected]),
        });
        mark();
        render();
      }),
    ),
  );
  main.append(box);
}
export function contentForm(s, inList = false) {
  const form = el("div"),
    options = Object.fromEntries(
      Object.entries(kinds).filter(
        ([k]) => !inList || !["empty", "native", "pc_native"].includes(k),
      ),
    );
  const kind = field(s, "kind", t("ui.content"), "select", options);
  kind.querySelector("select").onchange = () => {
    mark();
    render();
  };
  form.append(kind);
  if (["empty", "native"].includes(s.kind)) {
    form.append(hint(t("ui.keeper_will_not_replace_the")));
    return form;
  }
  const grid = el(
    "div",
    { class: "grid" },
    field(s, "title", t("ui.title")),
    numeric(s, "refresh", t("ui.refresh_every_seconds"), 5, 86400),
  );
  form.append(grid);
  if (s.kind === "media") {
    form.append(
      fileField(s, "path", t("ui.choose_image_or_gif")),
      el(
        "div",
        { class: "grid" },
        field(s, "fit", t("ui.fit"), "select", {
          contain: t("ui.contain"),
          cover: t("ui.crop"),
          stretch: t("ui.stretch"),
        }),
        numeric(s, "frame_step", t("ui.frame_step"), 1, 100),
      ),
    );
    if (s.panorama_speed)
      form.append(
        hint(
          t("ui.panorama_part_keeps_its_own") +
            s.panorama_speed +
            " ms).",
        ),
      );
  }
  if (s.kind === "text")
    form.append(
      field(s, "text", t("ui.text"), "textarea"),
      numeric(s, "font_size", t("ui.font_size"), 8, 64),
    );
  if (s.kind === "clock")
    form.append(field(s, "timezone", t("ui.time_zone_e_g_europe")));
  if (s.kind === "weather")
    form.append(
      el(
        "div",
        { class: "grid" },
        numeric(s, "latitude", t("ui.latitude"), -90, 90, 0.0001),
        numeric(s, "longitude", t("ui.longitude"), -180, 180, 0.0001),
      ),
    );
  if (s.kind === "countdown")
    form.append(field(s, "target", t("ui.date_and_time"), "datetime-local"));
  if (["service", "rss"].includes(s.kind))
    form.append(
      field(
        s,
        "url",
        s.kind === "rss" ? t("ui.rss_atom_url") : t("ui.service_url"),
        "url",
      ),
    );
  if (s.kind === "rss") {
    s.news_seconds ??= 15;
    s.news_size ??= 13;
    form.append(
      el(
        "div",
        { class: "grid" },
        numeric(s, "news_seconds", t("ui.seconds_per_headline"), 5, 3600),
        numeric(s, "news_size", t("ui.font_size"), 8, 28),
      ),
    );
  }
  if (s.kind === "calendar")
    form.append(
      fileField(s, "path", t("ui.import_ics_calendar"), ".ics"),
      field(
        s,
        "url",
        t("ui.or_calendar_url_clear_the"),
        "url",
      ),
      button(t("ui.use_url"), () => {
        s.path = "";
        mark();
        render();
      }),
    );
  if (s.kind === "pc")
    form.append(
      banner(ctx.state.capabilities.metrics_label, !ctx.state.capabilities.pc),
      field(s, "pc_view", t("ui.view"), "select", {
        usage: "CPU / RAM / GPU",
        history: t("ui.graphs"),
        network: t("ui.network"),
        temperature: t("ui.temperatures"),
        storage: t("ui.disk"),
      }),
      field(s, "pc_disk", t("ui.disk_path_empty_main")),
    );
  if (s.kind === "music")
    form.append(
      hint(
        ctx.state.capabilities.music
          ? t("ui.reads_the_media_session_of")
          : t("ui.music_from_other_apps_on"),
      ),
    );
  if (s.kind === "sensor") {
    s.sensor_source ??= ctx.state.capabilities.mode === "mobile" ? "http" : "mqtt";
    s.sensor_stale ??= 300;
    const source = field(
      s,
      "sensor_source",
      t("ui.source"),
      "select",
      ctx.state.capabilities.mode === "mobile"
        ? { http: "HTTP JSON", mqtt: "MQTT WebSocket" }
        : { mqtt: "MQTT", hardware: "Hardware" },
    );
    source.querySelector("select").addEventListener("input", () => render()); // the key field depends on the source
    form.append(
      source,
      ...(s.sensor_source === "hardware"
        ? hardwareSensorField(s)
        : [
            field(s, "sensor_key", t("ui.http_url_mqtt_topic_or")),
            ...(s.sensor_source === "mqtt" && ctx.cfg.integrations.mqtt?.enabled === false ? [hint(t("ui.mqtt_disabled_hint"))] : []),
          ]),
      field(s, "sensor_field", t("ui.json_path_e_g_cpu")),
      field(s, "sensor_unit", t("ui.unit")),
      numeric(s, "sensor_stale", t("ui.expiry_seconds"), 10, 86400),
    );
  }
  if (s.kind === "prtg") form.append(hint(t("ui.prtg_widget_hint")));
  if (s.kind === "github") {
    s.github_query ??= "review";
    s.github_repo ??= "";
    form.append(
      hint(t("ui.github_widget_hint")),
      field(s, "github_query", t("ui.github_query"), "select", { review: t("ui.github_q_review"), mine: t("ui.github_q_mine"), issues: t("ui.github_q_issues"), mentions: t("ui.github_q_mentions"), repo: t("ui.github_q_repo"), ci: t("ui.github_q_ci") }),
      ...(s.github_query === "repo" || s.github_query === "ci" ? [field(s, "github_repo", t("ui.github_repo"))] : []),
    );
  }
  if (s.kind === "mail") {
    s.mail_account ??= "all";
    form.append(
      hint(t("ui.mail_widget_hint")),
      field(s, "mail_account", t("ui.mail_account"), "select", mailAccountOptions(ctx.cfg.integrations.mail, s.mail_account, t("ui.mail_all_accounts"))),
    );
  }
  if (s.kind === "spotify") {
    s.spotify_display ??= "both";
    form.append(
      hint(t("ui.spotify_widget_hint")),
      field(s, "spotify_display", t("ui.spotify_display"), "select", {
        both: t("ui.spotify_display_both"),
        art: t("ui.spotify_display_art"),
        text: t("ui.spotify_display_text"),
      }),
    );
  }
  if (s.kind === "pomodoro")
    form.append(
      hint(
        t("ui.start_pause_or_reset_the"),
      ),
    );
  if (s.kind === "custom") {
    s.elements ??= [];
    form.append(designer(s));
  }
  if (s.kind === "pc_native") {
    form.append(
      banner(
        t("ui.experimental_first_select_pc_monitor"),
        true,
      ),
      field(s, "native_pc_mode", t("ui.mode"), "select", {
        existing: t("ui.send_data_to_the_already"),
        activate: t("ui.activate_with_known_group"),
      }),
      numeric(s, "independence", t("ui.valid_native_group"), 1, 100000000),
    );
  }
  form.append(
    el(
      "div",
      { class: "grid" },
      field(s, "color", "Color", "color"),
      field(s, "background", t("ui.background"), "color"),
    ),
  );
  return form;
}
export function designer(s) {
  const box = el("div"),
    surface = el("div", {
      class: "designer",
      style: `background:${s.background}`,
    });
  let chosen = Math.min(s.elements.length - 1, +(s._selection || 0));
  const options = el("div");
  function paint() {
    surface.replaceChildren();
    s.elements.forEach((e, index) => {
      const item = el(
        "div",
        {
          class: "element" + (index === chosen ? " selected" : ""),
          style: `left:${e.x * 2}px;top:${e.y * 2}px;width:${e.width * 2}px;height:${e.height * 2}px;font-size:${(e.size || 16) * 2}px;color:${e.color};background:${e.type === "bar" ? e.color : "transparent"}`,
        },
        e.type === "text"
          ? e.text
          : e.type === "bar"
            ? ""
            : el("span", {}, t("ui.image")),
      );
      if (e.type === "image" && e.path) {
        const img = el("img", {
          style: "width:100%;height:100%;object-fit:contain",
        });
        item.replaceChildren(img);
        showImage(img, e.path);
      }
      item.onpointerdown = (event) => {
        event.preventDefault();
        chosen = index;
        s._selection = index;
        const ox = event.clientX,
          oy = event.clientY,
          x = e.x,
          y = e.y;
        item.setPointerCapture(event.pointerId);
        item.onpointermove = (move) => {
          e.x = Math.max(
            0,
            Math.min(127, Math.round(x + (move.clientX - ox) / 2)),
          );
          e.y = Math.max(
            0,
            Math.min(127, Math.round(y + (move.clientY - oy) / 2)),
          );
          item.style.left = e.x * 2 + "px";
          item.style.top = e.y * 2 + "px";
          mark();
        };
        item.onpointerup = () => {
          item.onpointermove = null;
          paint();
          controls();
        };
        controls();
      };
      surface.append(item);
    });
  }
  function controls() {
    options.replaceChildren();
    const e = s.elements[chosen];
    if (!e) return;
    const grid = el("div", { class: "grid" });
    for (const [key, label, min, max] of [
      ["x", "X", 0, 127],
      ["y", "Y", 0, 127],
      ["width", t("ui.width"), 1, 128],
      ["height", t("ui.height"), 1, 128],
      ["size", t("ui.font"), 6, 64],
    ]) {
      const f = numeric(e, key, label, min, max);
      f.addEventListener("input", paint);
      grid.append(f);
    }
    options.append(grid);
    if (e.type === "text") {
      const f = field(e, "text", t("ui.text_time_date_cpu"), "textarea");
      f.addEventListener("input", paint);
      options.append(f);
    }
    if (e.type === "image") options.append(fileField(e, "path"));
    if (e.type === "bar")
      options.append(
        field(e, "metric", t("ui.metric"), "select", metrics),
        numeric(e, "maximum", t("ui.maximum_value"), 1, 1000000),
      );
    const color = field(e, "color", "Color", "color");
    color.addEventListener("input", paint);
    options.append(
      color,
      row(
        button(t("ui.raise_layer"), () => {
          if (chosen < s.elements.length - 1) {
            [s.elements[chosen], s.elements[chosen + 1]] = [
              s.elements[chosen + 1],
              s.elements[chosen],
            ];
            chosen++;
            mark();
            paint();
            controls();
          }
        }),
        button(
          t("ui.delete_element"),
          () => {
            s.elements.splice(chosen, 1);
            chosen = Math.max(0, chosen - 1);
            mark();
            paint();
            controls();
          },
          "danger",
        ),
      ),
    );
  }
  box.append(
    el("div", { class: "grid" }, surface, options),
    row(
      ...["text", "image", "bar"].map((type) =>
        button(
          t("ui.add") + { text: t("ui.text_2"), image: t("ui.image_2"), bar: t("ui.bar") }[type],
          () => {
            if (s.elements.length >= 20) throw Error(t("ui.maximum_20_elements"));
            s.elements.push({
              type,
              x: 8,
              y: 8,
              width: 112,
              height: type === "bar" ? 12 : 30,
              size: 16,
              color: "#64e6ca",
              text: t("ui.new_text"),
              metric: "cpu",
              maximum: 100,
            });
            chosen = s.elements.length - 1;
            mark();
            paint();
            controls();
          },
        ),
      ),
    ),
    hint(
      t("ui.drag_the_elements_the_design"),
    ),
  );
  paint();
  controls();
  return box;
}

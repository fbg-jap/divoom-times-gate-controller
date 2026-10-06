import "./style.css";
import {t,lazy,setLanguage,languages} from "./i18n.js";
import {colorControl,lightingDefaults,lightingPayload,moods} from './colors.js';
import {
  init,
  native,
  token,
  request,
  waitJob,
  action as backendAction,
  upload,
  mediaBlob,
} from "./api.js";
import {
  id,
  copy,
  screen,
  device,
  kinds,
  composition,
  metrics,
  normalize,
} from "./model.js";

const $ = (s) => document.querySelector(s),
  app = $("#app");
let state,
  cfg,
  revision,
  page = "screens",
  selected = 0,
  dirty = false,
  version = 0,
  urls = [],
  toastTimer,
  previewTimer,
  editing = null,
  pano = null;
const names = lazy({
  screens: "ui.screens",
  panorama: "ui.panorama",
  scenes: "ui.scenes",
  device: "ui.device",
  lighting: "ui.rgb_lighting",
  tools: "ui.tools",
  automation: "ui.automations",
  integrations: "ui.integrations",
  backup: "ui.backups_and_settings",
  activity: "ui.activity",
});
function el(tag, attrs = {}, ...children) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k.startsWith("on")) e.addEventListener(k.slice(2), v);
    else if (k === "class") e.className = v;
    else if (k === "text") e.textContent = v;
    else if (k === "checked") e.checked = v;
    else e.setAttribute(k, v);
  }
  for (const child of children.flat(Infinity))
    if (child != null)
      e.append(
        child instanceof Node ? child : document.createTextNode(String(child)),
      );
  return e;
}
const button = (title, fn, cls = "") =>
  el("button", { type: "button", class: cls, onclick: () => run(fn) }, title);
const row = (...children) => el("div", { class: "row" }, children),
  card = (title, ...children) =>
    el("section", { class: "card" }, el("h2", {}, title), children);
const hint = (text) => el("p", { class: "hint" }, text),
  banner = (text, warn = false) =>
    el("div", { class: "banner" + (warn ? " warning" : "") }, text);
function toast(message, error = false) {
  const box = $("#toast");
  box.textContent = message;
  box.className = error ? "error" : "";
  box.style.display = "block";
  clearTimeout(toastTimer);
  toastTimer = setTimeout(
    () => (box.style.display = "none"),
    error ? 9000 : 5000,
  );
}
async function run(fn) {
  try {
    await fn();
  } catch (e) {
    toast(e.message, true);
  }
}
function mark() {
  dirty = true;
  const label = $("#save-state");
  if (label) label.textContent = t("ui.unsaved_changes");
}
function field(obj, key, label, type = "text", options) {
  if(type==='color')return colorControl(obj[key],label,value=>{obj[key]=value;mark();});
  const wrap = el("label", { class: "field" }),
    control =
      type === "select"
        ? el("select")
        : type === "textarea"
          ? el("textarea")
          : el("input", { type });
  if (type === "select") {
    for (const [value, text] of Object.entries(options || {}))
      control.append(el("option", { value }, text));
    control.value = obj[key] ?? "";
  } else if (type === "checkbox") control.checked = !!obj[key];
  else control.value = obj[key] ?? "";
  control.addEventListener("input", () => {
    obj[key] =
      type === "checkbox"
        ? control.checked
        : ["number", "range"].includes(type) ||
            (type === "select" &&
              Object.keys(options || {}).every(
                (k) => k !== "" && Number.isFinite(+k),
              ))
          ? +control.value
          : control.value;
    mark();
  });
  wrap.append(el("span", {}, label), control);
  return wrap;
}
function numeric(obj, key, label, min, max, step = 1) {
  const f = field(obj, key, label, "number"),
    i = f.querySelector("input");
  i.min = min;
  i.max = max;
  i.step = step;
  return f;
}
const d = () => cfg.devices.find((d) => d.id === cfg.active_device);
async function load() {
  state = await request("/state");
  cfg = normalize(state.config);
  setLanguage(cfg.language);
  revision = state.revision;
  dirty = false;
}
async function save() {
  const result = await request("/config", "PUT", { config: cfg, revision });
  await waitJob(result);
  await load();
  render();
  toast(t("ui.configuration_saved"));
}
async function action(name, deviceId, args = {}) {
  if (dirty) await save();
  try {
    return await backendAction(name, deviceId, args);
  } finally {
    // Commands can change suspension, power or the active composition even if
    // their later upload fails. Use their new revision for the next edit.
    await load();
    render();
  }
}
async function saveAndSend(panel) {
  await save();
  await action("send", d().id, panel == null ? {} : { panel });
  render();
  toast(t("ui.send_complete"));
}
async function showImage(img, path) {
  const capture = version;
  try {
    const blob = await mediaBlob(path);
    if (capture !== version) return;
    const url = URL.createObjectURL(blob);
    urls.push(url);
    img.src = url;
  } catch {
    img.alt = t("ui.file_unavailable");
  }
}
async function preview(img, deviceId, panel) {
  const capture = version;
  if (img.dataset.loading) return;
  img.dataset.loading = "true";
  try {
    let blob;
    for (let attempt = 0; attempt < 20; attempt++) {
      blob = await request(
        `/preview/${deviceId}/${panel}`,
        "GET",
        undefined,
        true,
      );
      if (capture !== version) return;
      if (blob.size) break;
      await new Promise((resolve) => setTimeout(resolve, 500));
    }
    if (!blob.size) {
      img.alt = t("ui.preview_pending");
      return;
    }
    const old = img.getAttribute("src");
    if (old?.startsWith("blob:")) {
      URL.revokeObjectURL(old);
      const i = urls.indexOf(old);
      if (i >= 0) urls.splice(i, 1);
    }
    const url = URL.createObjectURL(blob);
    urls.push(url);
    img.src = url;
  } catch {
    img.alt = t("ui.preview_unavailable");
  } finally {
    delete img.dataset.loading;
  }
}
function chooseFile(accept, fn) {
  const input = el("input", { type: "file", accept, class: "file" });
  input.onchange = () => {
    const file = input.files[0];
    if (file) run(() => fn(file));
    input.remove();
  };
  document.body.append(input);
  input.click();
}
async function download(blob, name) {
  if (native) {
    const [{ Filesystem, Directory }, { Share }] = await Promise.all([
      import("@capacitor/filesystem"),
      import("@capacitor/share"),
    ]);
    const data = await new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(reader.result.split(",")[1]);
      reader.onerror = reject;
      reader.readAsDataURL(blob);
    });
    const result = await Filesystem.writeFile({
      path: name,
      data,
      directory: Directory.Cache,
    });
    await Share.share({ title: t("ui.keeper_backup"), url: result.uri });
    return;
  }
  const url = URL.createObjectURL(blob),
    link = el("a", { href: url, download: name });
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 60000);
}
function fileField(
  obj,
  key,
  label = t("ui.file"),
  accept = ".png,.jpg,.jpeg,.gif,.webp,.bmp",
) {
  const out = el(
    "div",
    {},
    hint(
      obj[key]
        ? obj[key].replaceAll("\\", "/").split("/").pop()
        : t("ui.no_file"),
    ),
    button(label, () =>
      chooseFile(accept, async (file) => {
        const result = await upload(file);
        obj[key] = result.path;
        if (key === "path") delete obj.panorama_speed;
        mark();
        render();
      }),
    ),
  );
  return out;
}
function deviceOptions() {
  return Object.fromEntries(cfg.devices.map((d) => [d.id, d.name]));
}
function sceneOptions() {
  return Object.fromEntries(cfg.scenes.map((s) => [s.id, s.name]));
}

function render() {
  clearInterval(previewTimer);
  version++;
  for (const url of urls) URL.revokeObjectURL(url);
  urls = [];
  app.replaceChildren();
  const aside = el(
    "aside",
    {},
    el("div", { class: "brand" }, "Divoom ", el("span", {}, "Keeper")),
    el(
      "div",
      { class: "badge" },
      state.capabilities.mode === "mobile"
        ? t("ui.standalone_mobile") + (state.capabilities.demo ? "DEMO" : t("ui.local_network"))
        : t("ui.web_portal") + (state.capabilities.demo ? "DEMO" : t("ui.server")),
    ),
  );
  const nav = el("nav", { "aria-label": t("ui.sections") });
  for (const [key, title] of Object.entries(names))
    nav.append(
      button(
        title,
        () => {
          page = key;
          editing = null;
          render();
        },
        key === page ? "active" : "",
      ),
    );
  aside.append(nav);
  const main = el("main", { class: "main" }),
    selector = field(
      cfg,
      "active_device",
      t("ui.device"),
      "select",
      deviceOptions(),
    );
  selector.querySelector("select").onchange = () => {
    selected = 0;
    render();
  };
  main.append(
    el(
      "header",
      {},
      el(
        "div",
        {},
        el("h1", {}, names[page]),
        el(
          "div",
          { class: "status", id: "save-state" },
          page==='lighting' ? t("ui.adjust_the_preview_and_apply") : dirty ? t("ui.unsaved_changes") : t("ui.configuration_saved"),
        ),
      ),
      row(
        selector,
        page==='lighting' ? null : button(
          t("ui.save"),
          async () => {
            await save();
            render();
          },
          "primary",
        ),
      ),
    ),
  );
  if (!state.capabilities.continuous)
    main.append(
      banner(
        t("ui.direct_control_of_the_times"),
      ),
    );
  const pages = {
    screens: screenPage,
    panorama: panoramaPage,
    scenes: scenePage,
    device: devicePage,
    lighting: lightingPage,
    tools: toolPage,
    automation: automationPage,
    integrations: integrationPage,
    backup: backupPage,
    activity: activityPage,
  };
  pages[page](main);
  app.append(el("div", { class: "shell" }, aside, main));
}
function screenPage(main) {
  const panels = el("div", { class: "panels" });
  d().screens.forEach((s, i) => {
    const img = el("img", { alt: t("ui.screen_0_preview",[i + 1]) });
    const list = d().playlists?.[i];
    const tile = el(
      "button",
      {
        class: "panel" + (selected === i ? " active" : ""),
        onclick: () => {
          selected = i;
          editing = null;
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
      t("ui.screen") + (selected + 1),
      contentForm(d().screens[selected]),
      row(
        button(t("ui.save_and_send"), () => saveAndSend(selected), "primary"),
        button(t("ui.send_all_five"), () => saveAndSend()),
        button(t("ui.panorama"), () => {
          page = "panorama";
          render();
        }),
      ),
    ),
  );
  const list = d().playlists[selected];
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
          editing = editing === item.id ? null : item.id;
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
    if (editing === item.id) itemBox.append(contentForm(item.screen, true));
    box.append(itemBox);
  });
  box.append(
    row(
      button(t("ui.add_widget"), () => {
        const item = { id: id(), seconds: 15, screen: screen("clock") };
        list.items.push(item);
        editing = item.id;
        mark();
        render();
      }),
      button(t("ui.copy_current_screen"), () => {
        if (
          ["empty", "native", "pc_native"].includes(d().screens[selected].kind)
        )
          throw Error(t("ui.choose_an_image_or_widget"));
        list.items.push({
          id: id(),
          seconds: 15,
          screen: copy(d().screens[selected]),
        });
        mark();
        render();
      }),
    ),
  );
  main.append(box);
}
function contentForm(s, inList = false) {
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
      banner(state.capabilities.metrics_label, !state.capabilities.pc),
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
        state.capabilities.music
          ? t("ui.reads_the_media_session_of")
          : t("ui.music_from_other_apps_on"),
      ),
    );
  if (s.kind === "sensor") {
    s.sensor_source ??= state.capabilities.mode === "mobile" ? "http" : "mqtt";
    s.sensor_stale ??= 300;
    form.append(
      field(
        s,
        "sensor_source",
        t("ui.source"),
        "select",
        state.capabilities.mode === "mobile"
          ? { http: "HTTP JSON", mqtt: "MQTT WebSocket" }
          : { mqtt: "MQTT", hardware: "Hardware" },
      ),
      field(s, "sensor_key", t("ui.http_url_mqtt_topic_or")),
      field(s, "sensor_field", t("ui.json_path_e_g_cpu")),
      field(s, "sensor_unit", t("ui.unit")),
      numeric(s, "sensor_stale", t("ui.expiry_seconds"), 10, 86400),
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
function designer(s) {
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
function panoramaPage(main) {
  pano ??= {
    path: "",
    fit: "cover",
    position: [0.5, 0.5],
    x: 0.5,
    y: 0.5,
    zoom: 1,
    rotation: 0,
    start: 0,
    duration: 4,
    fps: 5,
    result: null,
    generation: 0,
  };
  const p = pano,
    preview = el("canvas", {
      class: "wide-preview",
      "aria-label": t("ui.panorama_preview"),
      width: 640,
      height: 128,
    }),
    source = el("div", { class: "crop-source" }),
    cross = el("div", {
      class: "crosshair",
      style: `left:${p.x * 100}%;top:${p.y * 100}%`,
    }),
    message = hint(t("ui.select_a_file_and_prepare"));
  let generation = p.generation;
  let previewFrames = [],
    frameIndex = 0;
  const seek = el("input", {
    type: "range",
    min: 0,
    max: 0,
    value: 0,
    "aria-label": t("ui.preview_frame"),
  });
  const paintFrame = () => {
    if (previewFrames.length)
      preview.getContext("2d").drawImage(previewFrames[frameIndex], 0, 0);
    seek.value = frameIndex;
  };
  const play = button(t("ui.pause_preview"), () => {
    if (previewTimer) {
      clearInterval(previewTimer);
      previewTimer = null;
      play.textContent = t("ui.play_preview");
    } else startPreview();
  });
  function startPreview() {
    clearInterval(previewTimer);
    previewTimer = setInterval(
      () => {
        if (previewFrames.length) {
          frameIndex = (frameIndex + 1) % previewFrames.length;
          paintFrame();
        }
      },
      1000 / (+p.fps || 5),
    );
    play.textContent = t("ui.pause_preview");
  }
  seek.oninput = () => {
    frameIndex = +seek.value;
    paintFrame();
  };
  async function loadPreview(result) {
    const capture = version;
    const { decode } = await import("./media.js");
    const blob = await mediaBlob(result.preview);
    const decoded = await decode(blob, result.preview, {
      panorama: true,
      fit: "stretch",
      fps: +p.fps,
      duration: Math.max(0.1, result.duration),
    });
    if (capture !== version) return;
    previewFrames = decoded.frames;
    frameIndex = 0;
    seek.max = previewFrames.length - 1;
    paintFrame();
    if (previewFrames.length > 1) startPreview();
  }
  const refreshSource = async () => {
    if (!p.path) return;
    const blob = await mediaBlob(p.path),
      url = URL.createObjectURL(blob);
    urls.push(url);
    const media = /\.(mp4|mov|mkv|webm|avi|m4v)$/i.test(p.path)
      ? el("video", {
          src: url,
          muted: "",
          playsinline: "",
          preload: "metadata",
        })
      : el("img", { src: url });
    source.replaceChildren(media, cross);
  };
  run(refreshSource);
  const controls = el("div", { class: "grid three" });
  for (const [key, label, min, max, step] of [
    ["x", "Horizontal", 0, 1, 0.01],
    ["y", "Vertical", 0, 1, 0.01],
    ["zoom", "Zoom", 1, 8, 0.1],
    ["start", t("ui.start_s"), 0, 86400, 0.1],
    ["duration", t("ui.duration_s"), 0.1, 30, 0.1],
  ]) {
    const f = numeric(p, key, label, min, max, step);
    f.addEventListener("input", () => {
      p.generation++;
      p.result = null;
      apply.disabled = true;
      cross.style.left = p.x * 100 + "%";
      cross.style.top = p.y * 100 + "%";
    });
    controls.append(f);
  }
  const fps = field(p, "fps", "FPS", "select", {
      1: "1",
      2: "2",
      4: "4",
      5: "5",
      10: "10",
    }),
    fit = field(p, "fit", t("ui.fit"), "select", {
      cover: t("ui.crop"),
      contain: t("ui.contain"),
      stretch: t("ui.stretch"),
    }),
    rotation = field(p, "rotation", t("ui.rotation"), "select", {
      0: "0°",
      90: "90°",
      180: "180°",
      270: "270°",
    });
  for (const f of [fps, fit, rotation])
    f.addEventListener("change", () => {
      p.generation++;
      p.result = null;
      apply.disabled = true;
    });
  controls.append(fps, fit, rotation);
  source.onpointerdown = (event) => {
    const set = (e) => {
      const r = source.getBoundingClientRect();
      p.x = Math.max(0, Math.min(1, (e.clientX - r.left) / r.width));
      p.y = Math.max(0, Math.min(1, (e.clientY - r.top) / r.height));
      p.result = null;
      p.generation++;
      apply.disabled = true;
      cross.style.left = p.x * 100 + "%";
      cross.style.top = p.y * 100 + "%";
      controls.querySelectorAll("input")[0].value = p.x.toFixed(2);
      controls.querySelectorAll("input")[1].value = p.y.toFixed(2);
    };
    source.setPointerCapture(event.pointerId);
    set(event);
    source.onpointermove = set;
    source.onpointerup = () => (source.onpointermove = null);
  };
  const apply = button(
    t("ui.apply_and_send"),
    async () => {
      if (!p.result) throw Error(t("ui.prepare_the_preview_first"));
      cfg.scenes.push({
        id: id(),
        name: t("ui.before_panorama") + new Date().toLocaleString(),
        ...composition(d()),
      });
      d().screens = copy(p.result.screens);
      d().screens.forEach((s, i) => (s.title = t("ui.panorama_2") + (i + 1)));
      d().playlists.forEach((l) => (l.enabled = false));
      mark();
      await saveAndSend();
    },
    "primary",
  );
  apply.disabled = !p.result;
  const prepare = button(t("ui.prepare_preview"), async () => {
    if (!p.path) throw Error(t("ui.choose_a_file"));
    prepare.disabled = true;
    apply.disabled = true;
    generation = ++p.generation;
    try {
      message.textContent = t("ui.converting");
      const job = await request("/panorama", "POST", {
        path: p.path,
        fit: p.fit,
        position: [+p.x, +p.y],
        zoom: +p.zoom,
        start: +p.start,
        duration: +p.duration,
        fps: +p.fps,
        rotation: +p.rotation,
      });
      p.job = job.job;
      const result = await waitJob(job);
      if (generation !== p.generation) return;
      p.result = result;
      await loadPreview(result);
      apply.disabled = false;
      message.textContent = t("ui.0_frames_1_s_minimum",[result.count,result.duration.toFixed(2),(result.count * 0.5).toFixed(0)]);
    } finally {
      prepare.disabled = false;
    }
  });
  main.append(
    card(
      t("ui.one_composition_five_screens"),
      row(
        button(t("ui.choose_image_gif_or_video"), () =>
          chooseFile(
            ".png,.jpg,.jpeg,.gif,.webp,.bmp,.mp4,.mov,.mkv,.webm,.avi,.m4v",
            async (file) => {
              p.path = (await upload(file)).path;
              p.result = null;
              p.generation++;
              render();
            },
          ),
        ),
        button(t("ui.center"), () => {
          p.x = p.y = 0.5;
          p.zoom = 1;
          p.result = null;
          p.generation++;
          render();
        }),
      ),
      hint(
        p.path
          ? p.path.split(/[\\/]/).pop()
          : t("ui.up_to_100_mb_video"),
      ),
      source,
      hint(
        t("ui.click_or_drag_to_choose"),
      ),
      controls,
      row(
        prepare,
        button(t("ui.cancel_conversion"), async () => {
          p.generation++;
          p.result = null;
          if (p.job) await request("/jobs/" + p.job + "/cancel", "POST");
          message.textContent = t("ui.conversion_cancelled");
        }),
        apply,
      ),
      message,
      preview,
      row(play, seek),
      banner(
        t("ui.the_five_parts_are_sent"),
        true,
      ),
    ),
  );
  if (p.result) {
    message.textContent = t("ui.0_frames_1_s",[p.result.count,p.result.duration.toFixed(2)]);
    run(() => loadPreview(p.result));
  }
}

function scenePage(main) {
  main.append(
    card(
      t("ui.compositions"),
      row(
        button(
          t("ui.save_current_composition"),
          () => {
            const name = prompt(t("ui.scene_name"));
            if (name?.trim()) {
              cfg.scenes.push({
                id: id(),
                name: name.trim(),
                ...composition(d()),
              });
              mark();
              render();
            }
          },
          "primary",
        ),
      ),
      hint(
        t("ui.a_scene_includes_the_five"),
      ),
    ),
  );
  for (const scene of cfg.scenes) {
    main.append(
      card(
        scene.name,
        row(
          button(t("ui.apply_and_send"), async () => {
            await save();
            await action("scene", d().id, { scene_id: scene.id });
            await load();
            render();
          }),
          button(t("ui.rename"), () => {
            const name = prompt(t("ui.name"), scene.name);
            if (name?.trim()) {
              scene.name = name.trim();
              mark();
              render();
            }
          }),
          button(
            t("ui.delete"),
            () => {
              if (
                !confirm(t("ui.this_scene_and_the_rules"))
              )
                return;
              cfg.scenes = cfg.scenes.filter((s) => s.id !== scene.id);
              cfg.schedules = cfg.schedules.filter(
                (r) => r.action !== "scene" || r.value !== scene.id,
              );
              cfg.profiles = cfg.profiles.filter(
                (r) => r.scene_id !== scene.id,
              );
              cfg.devices.forEach(
                (d) =>
                  (d.rotation = d.rotation.filter((id) => id !== scene.id)),
              );
              mark();
              render();
            },
            "danger",
          ),
        ),
      ),
    );
  }
  const rotation = card(
    t("ui.scene_rotation"),
    numeric(d(), "rotation_seconds", t("ui.change_every_seconds"), 30, 86400),
  );
  cfg.scenes.forEach((s) => {
    const obj = { use: d().rotation.includes(s.id) },
      f = field(obj, "use", s.name, "checkbox");
    f.addEventListener("change", () => {
      d().rotation = d().rotation.filter((id) => id !== s.id);
      if (obj.use) d().rotation.push(s.id);
      mark();
    });
    rotation.append(f);
  });
  main.append(rotation);
}
function devicePage(main) {
  const value = d();
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
      field(cfg, "resend_on_startup", t("ui.resend_on_startup"), "checkbox"),
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
          cfg.devices.push(value);
          cfg.active_device = value.id;
          mark();
          render();
        }),
        button(
          t("ui.delete_selected"),
          () => {
            if (cfg.devices.length === 1)
              throw Error(t("ui.keep_at_least_one_device"));
            if (!confirm(t("ui.delete_this_device_and_its")))
              return;
            const did = d().id;
            cfg.devices = cfg.devices.filter((d) => d.id !== did);
            for (const g of ["schedules", "alerts", "reminders", "profiles"])
              cfg[g] = cfg[g].filter((r) => r.device_id !== did);
            cfg.active_device = cfg.devices[0].id;
            mark();
            render();
          },
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
const lightingDrafts=new Map();
function lightingPage(main) {
  const deviceId=d().id;
  if(!lightingDrafts.has(deviceId))lightingDrafts.set(deviceId,{...lightingDefaults(),...d().lighting});
  const settings=lightingDrafts.get(deviceId);
  const preview=el('div',{class:'light-device','aria-label':t("ui.color_and_zone_preview_of"),role:'img'});
  const glow=el('div',{class:'light-back'}),panels=el('div',{class:'light-panels'},...[1,2,3,4,5].map(n=>el('div',{class:'light-screen'},el('span',{},String(n))))),keys=el('div',{class:'light-keys'});
  preview.append(glow,panels,keys);
  const status=el('p',{class:'hint'},t("ui.approximate_view_of_color_brightness"));
  const draw=()=>{
    preview.style.setProperty('--light',settings.color);preview.style.setProperty('--brightness',settings.on?settings.brightness/100:0);
    preview.classList.toggle('cycling',settings.cycle);preview.classList.toggle('edges',settings.zone!==2);preview.classList.toggle('backlight',settings.zone!==1);preview.classList.toggle('keys-on',settings.keys);
  };
  const color=colorControl(settings.color,t("ui.lighting_color"),value=>{settings.color=value;draw();});
  const brightness=el('input',{type:'range',min:0,max:100,step:1,value:settings.brightness,'aria-label':t("ui.rgb_brightness")}),percentage=el('output',{},settings.brightness+'%');
  brightness.oninput=()=>{settings.brightness=+brightness.value;percentage.textContent=settings.brightness+'%';draw();};
  const zones=el('div',{class:'segmented','aria-label':t("ui.lit_zone"),role:'group'});
  [t("ui.all_zones"),t("ui.edges"),t("ui.backlight")].forEach((name,index)=>{
    const b=button(name,()=>{settings.zone=index;for(const [i,item] of [...zones.children].entries())item.setAttribute('aria-pressed',String(i===index));draw();});b.setAttribute('aria-pressed',String(index===settings.zone));zones.append(b);
  });
  const switches=el('div',{class:'lighting-switches'});
  for(const [key,name] of [['on',t("ui.lighting_on")],['cycle',t("ui.multicolor_cycle")],['keys',t("ui.key_light")]]){
    const input=el('input',{type:'checkbox',checked:settings[key]});input.onchange=()=>{settings[key]=input.checked;draw();};switches.append(el('label',{class:'light-toggle'},input,el('span',{},name)));
  }
  const presets=el('div',{class:'mood-grid'});
  moods.forEach(([name,value,level,cycle])=>{
    const b=button(t(name),()=>{Object.assign(settings,{color:value,brightness:level,cycle,on:true});render();});b.prepend(el('span',{class:'mood-dot',style:`--swatch:${value}`}));presets.append(b);
  });
  const effects=el('div',{class:'effect-grid',role:'group','aria-label':t("ui.rgb_effects")});
  for(let i=0;i<12;i++){
    const b=button('',()=>{settings.effect=i;for(const [n,item] of [...effects.children].entries())item.setAttribute('aria-pressed',String(n===i));});
    b.setAttribute('aria-pressed',String(settings.effect===i));b.setAttribute('aria-label',t("ui.effect")+(i+1));
    b.append(el('span',{class:'effect-symbol','aria-hidden':'true'},'▱ ▱ ▱ ▱ ▱'),el('span',{},t("ui.effect")+(i+1)));effects.append(b);
  }
  main.append(card(t("ui.your_mood_at_a_glance"),preview,status,el('div',{class:'lighting-layout'},el('div',{},color),el('div',{},el('p',{class:'color-label'},t("ui.lit_zone")),zones,el('div',{class:'brightness-row'},el('span',{},t("ui.brightness")),brightness,percentage),switches))),
    card(t("ui.quick_moods"),hint(t("ui.choose_a_combination_of_color")),presets),
    card(t("ui.device_effects"),hint(t("ui.select_a_card_modes_keep")),effects,
      el('div',{class:'lighting-apply'},button(t("ui.apply_lighting"),async()=>{await action('command',deviceId,{payload:lightingPayload(settings)});toast(t("ui.lighting_sent_to_the_times"));},'primary'),hint(t("ui.the_preview_does_not_send")))));
  draw();
}
function toolPage(main) {
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
function automationPage(main) {
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
    if (group === "profiles" && !state.capabilities.profiles) {
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
            scene_id: cfg.scenes[0]?.id || "",
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
                    state.capabilities.mode === "mobile" ? "service" : "cpu",
                  operator: "above",
                  threshold: 80,
                  hold: 10,
                  cooldown: 300,
                  source: "",
                  sensor_source:
                    state.capabilities.mode === "mobile" ? "http" : "mqtt",
                  field: "",
                }),
          });
        cfg[group].push(rule);
        editing = rule.id;
        mark();
        render();
      }),
    );
    for (const r of cfg[group]) {
      const box = el(
        "div",
        { class: "list-item" },
        row(
          field(r, "enabled", r.name || r.time || t("ui.rule"), "checkbox"),
          button(t("ui.edit"), () => {
            editing = editing === r.id ? null : r.id;
            render();
          }),
          button(
            t("ui.delete"),
            () => {
              cfg[group] = cfg[group].filter((x) => x.id !== r.id);
              mark();
              render();
            },
            "danger",
          ),
        ),
      );
      if (editing === r.id) {
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
                state.capabilities.mode === "mobile"
                  ? { service: t("ui.service_down_1_failure"), sensor: "Sensor" }
                  : {
                      ...metrics,
                      disk_free: t("ui.free_disk"),
                      service: t("ui.service_down_1_failure"),
                      sensor: "Sensor",
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
                state.capabilities.mode === "mobile"
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
function pomoText() {
  const p = state.runtime?.pomodoro || {};
  // Legacy Spanish phase names (older backends) map to the English values.
  const legacy = { Preparado: "Ready", Trabajo: "Work", Descanso: "Break", "Descanso largo": "Long break" };
  return `${legacy[p.phase] || p.phase || "Ready"} · ${Math.floor((p.remaining || 0) / 60)}:${Math.floor(
    (p.remaining || 0) % 60,
  )
    .toString()
    .padStart(2, "0")} · cycle ${p.cycle || 0}`;
}
function integrationPage(main) {
  const mqtt = cfg.integrations.mqtt;
  main.append(
    card(
      "MQTT / Home Assistant",
      field(mqtt, "enabled", t("ui.enable_mqtt"), "checkbox"),
      state.capabilities.mode === "mobile"
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
      state.capabilities.mode === "mobile"
        ? hint(
            t("ui.the_broker_must_offer_websockets"),
          )
        : field(mqtt, "tls", "TLS", "checkbox"),
      hint(
        t("ui.credentials_are_excluded_from_exported"),
      ),
    ),
  );
  if (state.capabilities.mode !== "mobile") {
    const api = cfg.integrations.api;
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
          cfg.integrations,
          "hardware",
          t("ui.read_available_sensors"),
          "checkbox",
        ),
        banner(state.capabilities.metrics_label),
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
function languageField() {
  const select = el("select");
  for (const [value, name] of Object.entries(languages))
    select.append(el("option", { value }, name));
  select.value = cfg.language;
  select.addEventListener("change", () => {
    cfg.language = select.value;
    setLanguage(cfg.language);
    mark();
    render();
  });
  return el("label", { class: "field" }, el("span", {}, t("ui.language")), select);
}
function backupPage(main) {
  main.append(
    card(
      t("ui.portable_backup"),
      hint(
        t("ui.includes_media_screens_playlists_scenes"),
      ),
      row(
        button(
          t("ui.export_zip"),
          async () => {
            await save();
            await download(
              await request("/export", "GET", undefined, true),
              "Keeper-backup.zip",
            );
          },
          "primary",
        ),
        button(t("ui.import_zip"), () =>
          chooseFile(".zip", async (file) => {
            if (
              !confirm(
                t("ui.replace_the_configuration_with_this"),
              )
            )
              return;
            await waitJob(await request("/import", "POST", file));
            await load();
            render();
            toast(
              t("ui.backup_imported_check_the_ip"),
            );
          }),
        ),
      ),
    ),
  );
  main.append(
    card(
      t("ui.library"),
      button(t("ui.view_files"), async () => {
        const files = await request("/library");
        const list = $("#library-list");
        list.replaceChildren(
          ...files.map((f) =>
            el(
              "div",
              { class: "list-item" },
              row(
                el("span", {}, f.original || f.name),
                el("small", {}, (f.size / 1024).toFixed(0) + " KB"),
                button(t("ui.use_on_screen") + (selected + 1), () => {
                  d().screens[selected] = screen("media", { path: f.path });
                  mark();
                  page = "screens";
                  render();
                }),
              ),
            ),
          ),
        );
      }),
      el("div", { class: "list", id: "library-list" }),
    ),
  );
  main.append(
    card(
      t("ui.settings_and_session"),
      languageField(),
      field(cfg, "resend_on_startup", t("ui.resend_on_startup"), "checkbox"),
      button(t("ui.reload_configuration"), async () => {
        if (dirty && !confirm(t("ui.discard_unsaved_changes"))) return;
        await load();
        render();
      }),
      state.capabilities.mode === "server"
        ? button(t("ui.sign_out"), () => {
            sessionStorage.removeItem("keeper-token");
            login();
          })
        : hint(
            t("ui.data_is_stored_on_the"),
          ),
      hint(
        t("ui.windows_2_3_keeps_its"),
      ),
    ),
  );
}
function activityPage(main) {
  main.append(
    card(
      t("ui.activity"),
      el("pre", { id: "activity" }, eventText()),
      button(t("ui.refresh"), async () => {
        const fresh = await request("/state");
        state.events = fresh.events;
        $("#activity").textContent = eventText();
      }),
    ),
  );
}
function eventText() {
  return (state.events || [])
    .slice(-100)
    .map(
      (e) =>
        new Date(e.time * 1000).toLocaleTimeString() +
        " · " +
        (e.message || e.text || JSON.stringify(e)),
    )
    .join("\n");
}
function login() {
  app.replaceChildren(
    el(
      "div",
      { class: "login card" },
      el("div", { class: "brand" }, "Divoom ", el("span", {}, "Keeper")),
      el("h1", {}, t("ui.your_times_gate_at_hand")),
      hint(t("ui.enter_the_server_token_to")),
      el(
        "form",
        {
          onsubmit: (event) => {
            event.preventDefault();
            run(async () => {
              token($("#token").value);
              await load();
              render();
            });
          },
        },
        el(
          "label",
          { class: "field" },
          t("ui.access_token"),
          el("input", {
            id: "token",
            type: "password",
            required: "",
            autocomplete: "current-password",
          }),
        ),
        el("button", { class: "primary", type: "submit" }, t("ui.sign_in")),
      ),
      hint(
        t("ui.the_token_is_in_data"),
      ),
    ),
  );
}
run(async () => {
  await init();
  try {
    await load();
    render();
  } catch (e) {
    if (native) throw e;
    login();
  }
});
setInterval(async () => {
  if (!state || !$("#save-state")) return;
  try {
    const fresh = await request("/state");
    state.events = fresh.events;
    state.runtime = fresh.runtime;
    if ($("#activity")) $("#activity").textContent = eventText();
    if ($("#pomodoro-state")) $("#pomodoro-state").textContent = pomoText();
  } catch {}
}, 3000);
setInterval(() => {
  if (state && page === "screens" && !dirty) {
    document
      .querySelectorAll(".panels img")
      .forEach((img, panel) => preview(img, d().id, panel));
  }
}, 10000);

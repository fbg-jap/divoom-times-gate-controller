import "./style.css";
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
const names = {
  screens: "Screens",
  panorama: "Panorama",
  scenes: "Scenes",
  device: "Device",
  lighting: "RGB lighting",
  tools: "Tools",
  automation: "Automations",
  integrations: "Integrations",
  backup: "Backups and settings",
  activity: "Activity",
};
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
  if (label) label.textContent = "Unsaved changes";
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
  revision = state.revision;
  dirty = false;
}
async function save() {
  const result = await request("/config", "PUT", { config: cfg, revision });
  await waitJob(result);
  await load();
  render();
  toast("Configuration saved");
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
  toast("Send complete");
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
    img.alt = "File unavailable";
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
      img.alt = "Preview pending";
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
    img.alt = "Preview unavailable";
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
    await Share.share({ title: "Keeper backup", url: result.uri });
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
  label = "File",
  accept = ".png,.jpg,.jpeg,.gif,.webp,.bmp",
) {
  const out = el(
    "div",
    {},
    hint(
      obj[key]
        ? obj[key].replaceAll("\\", "/").split("/").pop()
        : "No file",
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
        ? "STANDALONE MOBILE · " + (state.capabilities.demo ? "DEMO" : "LOCAL NETWORK")
        : "WEB PORTAL · " + (state.capabilities.demo ? "DEMO" : "SERVER"),
    ),
  );
  const nav = el("nav", { "aria-label": "Sections" });
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
      "Device",
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
          page==='lighting' ? 'Adjust the preview and apply it to the device' : dirty ? "Unsaved changes" : "Configuration saved",
        ),
      ),
      row(
        selector,
        page==='lighting' ? null : button(
          "Save",
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
        "Direct control of the Times Gate. Keep the app active for playlists, widgets, schedules and alerts. GIFs already sent keep playing on the device.",
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
    const img = el("img", { alt: `Screen ${i + 1} preview` });
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
          ? "List · " + list.items.length
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
      "Screen " + (selected + 1),
      contentForm(d().screens[selected]),
      row(
        button("Save and send", () => saveAndSend(selected), "primary"),
        button("Send all five", () => saveAndSend()),
        button("Panorama", () => {
          page = "panorama";
          render();
        }),
      ),
    ),
  );
  const list = d().playlists[selected];
  const box = card(
    "Playlist",
    field(list, "enabled", "Use this list", "checkbox"),
    hint(
      "From 5 seconds to 24 hours per item. The next change starts counting when its send finishes.",
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
        button("Edit", () => {
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
          "Delete",
          () => {
            list.items.splice(index, 1);
            if (!list.items.length) list.enabled = false;
            mark();
            render();
          },
          "danger",
        ),
      ),
      numeric(item, "seconds", "Duration (seconds)", 5, 86400),
    );
    if (editing === item.id) itemBox.append(contentForm(item.screen, true));
    box.append(itemBox);
  });
  box.append(
    row(
      button("Add widget", () => {
        const item = { id: id(), seconds: 15, screen: screen("clock") };
        list.items.push(item);
        editing = item.id;
        mark();
        render();
      }),
      button("Copy current screen", () => {
        if (
          ["empty", "native", "pc_native"].includes(d().screens[selected].kind)
        )
          throw Error("Choose an image or widget");
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
  const kind = field(s, "kind", "Content", "select", options);
  kind.querySelector("select").onchange = () => {
    mark();
    render();
  };
  form.append(kind);
  if (["empty", "native"].includes(s.kind)) {
    form.append(hint("Keeper will not replace the content of this screen."));
    return form;
  }
  const grid = el(
    "div",
    { class: "grid" },
    field(s, "title", "Title"),
    numeric(s, "refresh", "Refresh every (seconds)", 5, 86400),
  );
  form.append(grid);
  if (s.kind === "media") {
    form.append(
      fileField(s, "path", "Choose image or GIF"),
      el(
        "div",
        { class: "grid" },
        field(s, "fit", "Fit", "select", {
          contain: "Contain",
          cover: "Crop",
          stretch: "Stretch",
        }),
        numeric(s, "frame_step", "Frame step", 1, 100),
      ),
    );
    if (s.panorama_speed)
      form.append(
        hint(
          "Panorama part: keeps its own speed (" +
            s.panorama_speed +
            " ms).",
        ),
      );
  }
  if (s.kind === "text")
    form.append(
      field(s, "text", "Text", "textarea"),
      numeric(s, "font_size", "Font size", 8, 64),
    );
  if (s.kind === "clock")
    form.append(field(s, "timezone", "Time zone (e.g. Europe/Madrid)"));
  if (s.kind === "weather")
    form.append(
      el(
        "div",
        { class: "grid" },
        numeric(s, "latitude", "Latitude", -90, 90, 0.0001),
        numeric(s, "longitude", "Longitude", -180, 180, 0.0001),
      ),
    );
  if (s.kind === "countdown")
    form.append(field(s, "target", "Date and time", "datetime-local"));
  if (["service", "rss"].includes(s.kind))
    form.append(
      field(
        s,
        "url",
        s.kind === "rss" ? "RSS / Atom URL" : "Service URL",
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
        numeric(s, "news_seconds", "Seconds per headline", 5, 3600),
        numeric(s, "news_size", "Font size", 8, 28),
      ),
    );
  }
  if (s.kind === "calendar")
    form.append(
      fileField(s, "path", "Import ICS calendar", ".ics"),
      field(
        s,
        "url",
        "Or calendar URL (clear the file to use it)",
        "url",
      ),
      button("Use URL", () => {
        s.path = "";
        mark();
        render();
      }),
    );
  if (s.kind === "pc")
    form.append(
      banner(state.capabilities.metrics_label, !state.capabilities.pc),
      field(s, "pc_view", "View", "select", {
        usage: "CPU / RAM / GPU",
        history: "Graphs",
        network: "Network",
        temperature: "Temperatures",
        storage: "Disk",
      }),
      field(s, "pc_disk", "Disk path (empty = main)"),
    );
  if (s.kind === "music")
    form.append(
      hint(
        state.capabilities.music
          ? "Reads the media session of the host machine; on Linux it needs playerctl and an MPRIS session."
          : "Music from other apps on the phone cannot be read here.",
      ),
    );
  if (s.kind === "sensor") {
    s.sensor_source ??= state.capabilities.mode === "mobile" ? "http" : "mqtt";
    s.sensor_stale ??= 300;
    form.append(
      field(
        s,
        "sensor_source",
        "Source",
        "select",
        state.capabilities.mode === "mobile"
          ? { http: "HTTP JSON", mqtt: "MQTT WebSocket" }
          : { mqtt: "MQTT", hardware: "Hardware" },
      ),
      field(s, "sensor_key", "HTTP URL, MQTT topic or identifier"),
      field(s, "sensor_field", "JSON path (e.g. cpu.temperature)"),
      field(s, "sensor_unit", "Unit"),
      numeric(s, "sensor_stale", "Expiry (seconds)", 10, 86400),
    );
  }
  if (s.kind === "pomodoro")
    form.append(
      hint(
        "Start, pause or reset the shared session in Automations.",
      ),
    );
  if (s.kind === "custom") {
    s.elements ??= [];
    form.append(designer(s));
  }
  if (s.kind === "pc_native") {
    form.append(
      banner(
        "Experimental: first select PC Monitor in the Divoom app. Group 0 is not allowed. Mobile has no PC metrics.",
        true,
      ),
      field(s, "native_pc_mode", "Mode", "select", {
        existing: "Send data to the already selected monitor",
        activate: "Activate with known group",
      }),
      numeric(s, "independence", "Valid native group", 1, 100000000),
    );
  }
  form.append(
    el(
      "div",
      { class: "grid" },
      field(s, "color", "Color", "color"),
      field(s, "background", "Background", "color"),
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
            : el("span", {}, "Image"),
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
      ["width", "Width", 1, 128],
      ["height", "Height", 1, 128],
      ["size", "Font", 6, 64],
    ]) {
      const f = numeric(e, key, label, min, max);
      f.addEventListener("input", paint);
      grid.append(f);
    }
    options.append(grid);
    if (e.type === "text") {
      const f = field(e, "text", "Text · {time}, {date}, {cpu}…", "textarea");
      f.addEventListener("input", paint);
      options.append(f);
    }
    if (e.type === "image") options.append(fileField(e, "path"));
    if (e.type === "bar")
      options.append(
        field(e, "metric", "Metric", "select", metrics),
        numeric(e, "maximum", "Maximum value", 1, 1000000),
      );
    const color = field(e, "color", "Color", "color");
    color.addEventListener("input", paint);
    options.append(
      color,
      row(
        button("Raise layer", () => {
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
          "Delete element",
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
          "Add " + { text: "text", image: "image", bar: "bar" }[type],
          () => {
            if (s.elements.length >= 20) throw Error("Maximum 20 elements");
            s.elements.push({
              type,
              x: 8,
              y: 8,
              width: 112,
              height: type === "bar" ? 12 : 30,
              size: 16,
              color: "#64e6ca",
              text: "New text",
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
      "Drag the elements. The design view uses sample values; the content sent uses the available sources.",
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
      "aria-label": "Panorama preview",
      width: 640,
      height: 128,
    }),
    source = el("div", { class: "crop-source" }),
    cross = el("div", {
      class: "crosshair",
      style: `left:${p.x * 100}%;top:${p.y * 100}%`,
    }),
    message = hint("Select a file and prepare the preview.");
  let generation = p.generation;
  let previewFrames = [],
    frameIndex = 0;
  const seek = el("input", {
    type: "range",
    min: 0,
    max: 0,
    value: 0,
    "aria-label": "Preview frame",
  });
  const paintFrame = () => {
    if (previewFrames.length)
      preview.getContext("2d").drawImage(previewFrames[frameIndex], 0, 0);
    seek.value = frameIndex;
  };
  const play = button("Pause preview", () => {
    if (previewTimer) {
      clearInterval(previewTimer);
      previewTimer = null;
      play.textContent = "Play preview";
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
    play.textContent = "Pause preview";
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
    ["start", "Start (s)", 0, 86400, 0.1],
    ["duration", "Duration (s)", 0.1, 30, 0.1],
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
    fit = field(p, "fit", "Fit", "select", {
      cover: "Crop",
      contain: "Contain",
      stretch: "Stretch",
    }),
    rotation = field(p, "rotation", "Rotation", "select", {
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
    "Apply and send",
    async () => {
      if (!p.result) throw Error("Prepare the preview first");
      cfg.scenes.push({
        id: id(),
        name: "Before panorama · " + new Date().toLocaleString(),
        ...composition(d()),
      });
      d().screens = copy(p.result.screens);
      d().screens.forEach((s, i) => (s.title = "Panorama · " + (i + 1)));
      d().playlists.forEach((l) => (l.enabled = false));
      mark();
      await saveAndSend();
    },
    "primary",
  );
  apply.disabled = !p.result;
  const prepare = button("Prepare preview", async () => {
    if (!p.path) throw Error("Choose a file");
    prepare.disabled = true;
    apply.disabled = true;
    generation = ++p.generation;
    try {
      message.textContent = "Converting…";
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
      message.textContent = `${result.count} frames · ${result.duration.toFixed(2)} s · minimum upload time ${(result.count * 0.5).toFixed(0)} s, usually longer.`;
    } finally {
      prepare.disabled = false;
    }
  });
  main.append(
    card(
      "One composition, five screens",
      row(
        button("Choose image, GIF or video", () =>
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
        button("Center", () => {
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
          : "Up to 100 MB. Video without audio. On mobile, codecs supported by the phone.",
      ),
      source,
      hint(
        "Click or drag to choose the area; fine-tune with Horizontal, Vertical and Zoom.",
      ),
      controls,
      row(
        prepare,
        button("Cancel conversion", async () => {
          p.generation++;
          p.result = null;
          if (p.job) await request("/jobs/" + p.job + "/cancel", "POST");
          message.textContent = "Conversion cancelled";
        }),
        apply,
      ),
      message,
      preview,
      row(play, seek),
      banner(
        "The five parts are sent one after another: they may drift out of sync even if the preview is synchronized. Maximum 30 seconds and 120 frames per screen.",
        true,
      ),
    ),
  );
  if (p.result) {
    message.textContent = `${p.result.count} frames · ${p.result.duration.toFixed(2)} s`;
    run(() => loadPreview(p.result));
  }
}

function scenePage(main) {
  main.append(
    card(
      "Compositions",
      row(
        button(
          "Save current composition",
          () => {
            const name = prompt("Scene name");
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
        "A scene includes the five screens and their playlists. It is saved with the library files.",
      ),
    ),
  );
  for (const scene of cfg.scenes) {
    main.append(
      card(
        scene.name,
        row(
          button("Apply and send", async () => {
            await save();
            await action("scene", d().id, { scene_id: scene.id });
            await load();
            render();
          }),
          button("Rename", () => {
            const name = prompt("Name", scene.name);
            if (name?.trim()) {
              scene.name = name.trim();
              mark();
              render();
            }
          }),
          button(
            "Delete",
            () => {
              if (
                !confirm("This scene and the rules that use it will be deleted.")
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
    "Scene rotation",
    numeric(d(), "rotation_seconds", "Change every (seconds)", 30, 86400),
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
      "Local connection",
      el(
        "div",
        { class: "grid" },
        field(value, "name", "Name"),
        field(value, "ip", "Times Gate IP (e.g. 192.168.1.116)"),
      ),
      field(value, "enabled", "Automatic update", "checkbox"),
      row(
        button("Save and check", async () => {
          await save();
          await action("health", d().id);
          toast("Check complete; see Activity");
        }),
        button("Scan LAN", async () => {
          await save();
          const result = await action("discover", d().id, {
            seed: d().ip,
            cloud: false,
          });
          toast(
            result?.devices
              ? "Devices: " + JSON.stringify(result.devices)
              : "See the results in Activity",
          );
        }),
        button("Discover via Divoom", async () => {
          await save();
          await action("discover", d().id, { cloud: true, seed: d().ip });
          toast("See the results in Activity");
        }),
      ),
      hint(
        "The phone or server and the Times Gate must be able to communicate over the local network. In Docker you may need to enter the IP: discovery uses the subnet visible from the container.",
      ),
    ),
  );
  main.append(
    card(
      "Send and restore",
      el(
        "div",
        { class: "grid three" },
        numeric(value, "quality", "JPEG quality", 30, 100),
        numeric(value, "speed", "Milliseconds per frame", 1, 60000),
        numeric(
          value,
          "interval_minutes",
          "Resend media every (minutes)",
          1,
          10080,
        ),
      ),
      field(value, "suspended", "Pause sending", "checkbox"),
      field(cfg, "resend_on_startup", "Resend on startup", "checkbox"),
      row(
        button(
          "Resume and resend",
          async () => {
            await save();
            await action("resume", d().id);
            await load();
            render();
          },
          "primary",
        ),
        button("Send all", () => saveAndSend()),
      ),
      hint(
        "Panoramic GIFs keep their own speed. Pausing leaves the content already sent on the device.",
      ),
    ),
  );
  main.append(
    card(
      "Multiple devices",
      row(
        button("Add device", () => {
          const value = device();
          cfg.devices.push(value);
          cfg.active_device = value.id;
          mark();
          render();
        }),
        button(
          "Delete selected",
          () => {
            if (cfg.devices.length === 1)
              throw Error("Keep at least one device");
            if (!confirm("Delete this device and its schedules and rules?"))
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
        field(value, "mac", "MAC (optional)"),
        numeric(value, "device_id", "Divoom DeviceId (optional)", 0, 999999999),
        numeric(value, "port", "Port (0 = auto: 80 or 9000)", 0, 65535),
        field(value, "local_token", "Local token (from the Divoom app)"),
      ),
    ),
  );
}
const lightingDrafts=new Map();
function lightingPage(main) {
  const deviceId=d().id;
  if(!lightingDrafts.has(deviceId))lightingDrafts.set(deviceId,{...lightingDefaults(),...d().lighting});
  const settings=lightingDrafts.get(deviceId);
  const preview=el('div',{class:'light-device','aria-label':'Color and zone preview of the Times Gate',role:'img'});
  const glow=el('div',{class:'light-back'}),panels=el('div',{class:'light-panels'},...[1,2,3,4,5].map(n=>el('div',{class:'light-screen'},el('span',{},String(n))))),keys=el('div',{class:'light-keys'});
  preview.append(glow,panels,keys);
  const status=el('p',{class:'hint'},'Approximate view of color, brightness and zones. Animated effects are checked on the Times Gate.');
  const draw=()=>{
    preview.style.setProperty('--light',settings.color);preview.style.setProperty('--brightness',settings.on?settings.brightness/100:0);
    preview.classList.toggle('cycling',settings.cycle);preview.classList.toggle('edges',settings.zone!==2);preview.classList.toggle('backlight',settings.zone!==1);preview.classList.toggle('keys-on',settings.keys);
  };
  const color=colorControl(settings.color,'Lighting color',value=>{settings.color=value;draw();});
  const brightness=el('input',{type:'range',min:0,max:100,step:1,value:settings.brightness,'aria-label':'RGB brightness'}),percentage=el('output',{},settings.brightness+'%');
  brightness.oninput=()=>{settings.brightness=+brightness.value;percentage.textContent=settings.brightness+'%';draw();};
  const zones=el('div',{class:'segmented','aria-label':'Lit zone',role:'group'});
  ['All zones','Edges','Backlight'].forEach((name,index)=>{
    const b=button(name,()=>{settings.zone=index;for(const [i,item] of [...zones.children].entries())item.setAttribute('aria-pressed',String(i===index));draw();});b.setAttribute('aria-pressed',String(index===settings.zone));zones.append(b);
  });
  const switches=el('div',{class:'lighting-switches'});
  for(const [key,name] of [['on','Lighting on'],['cycle','Multicolor cycle'],['keys','Key light']]){
    const input=el('input',{type:'checkbox',checked:settings[key]});input.onchange=()=>{settings[key]=input.checked;draw();};switches.append(el('label',{class:'light-toggle'},input,el('span',{},name)));
  }
  const presets=el('div',{class:'mood-grid'});
  moods.forEach(([name,value,level,cycle])=>{
    const b=button(name,()=>{Object.assign(settings,{color:value,brightness:level,cycle,on:true});render();});b.prepend(el('span',{class:'mood-dot',style:`--swatch:${value}`}));presets.append(b);
  });
  const effects=el('div',{class:'effect-grid',role:'group','aria-label':'RGB effects'});
  for(let i=0;i<12;i++){
    const b=button('',()=>{settings.effect=i;for(const [n,item] of [...effects.children].entries())item.setAttribute('aria-pressed',String(n===i));});
    b.setAttribute('aria-pressed',String(settings.effect===i));b.setAttribute('aria-label','Effect '+(i+1));
    b.append(el('span',{class:'effect-symbol','aria-hidden':'true'},'▱ ▱ ▱ ▱ ▱'),el('span',{},'Effect '+(i+1)));effects.append(b);
  }
  main.append(card('Your mood at a glance',preview,status,el('div',{class:'lighting-layout'},el('div',{},color),el('div',{},el('p',{class:'color-label'},'Lit zone'),zones,el('div',{class:'brightness-row'},el('span',{},'Brightness'),brightness,percentage),switches))),
    card('Quick moods',hint('Choose a combination of color and brightness. Keeps the effect and zone you selected.'),presets),
    card('Device effects',hint('Select a card. Modes keep the device order; their animations vary by firmware.'),effects,
      el('div',{class:'lighting-apply'},button('Apply lighting',async()=>{await action('command',deviceId,{payload:lightingPayload(settings)});toast('Lighting sent to the Times Gate');},'primary'),hint('The preview does not send changes until you press Apply lighting.'))));
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
      "Screens and brightness",
      numeric(values, "brightness", "Brightness", 0, 100),
      row(
        button("Apply brightness", () =>
          command({
            Command: "Channel/SetBrightness",
            Brightness: values.brightness,
          }),
        ),
        button("Turn on", async () => {
          await command({ Command: "Channel/OnOffScreen", OnOff: 1 });
          await load();
          render();
        }),
        button("Turn off", async () => {
          await command({ Command: "Channel/OnOffScreen", OnOff: 0 });
          await load();
          render();
        }),
        button("Read settings", () => action("health", d().id)),
        button(
          "Restart device",
          async () => {
            if (confirm("Restart the Times Gate?"))
              await command({ Command: "Device/SysReboot" });
          },
          "danger",
        ),
      ),
    ),
  );
  main.append(
    card(
      "Temporary alert",
      field(values, "text", "Message", "textarea"),
      el(
        "div",
        { class: "grid three" },
        field(values, "panel", "Screen", "select", {
          0: "1",
          1: "2",
          2: "3",
          3: "4",
          4: "5",
        }),
        numeric(values, "duration", "Duration (s)", 5, 300),
        field(values, "buzzer", "Buzzer", "checkbox"),
      ),
      button(
        "Send alert",
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
      "Native tools",
      banner(
        "These tools can change the device mode. Using them pauses resending; press Restore composition to go back.",
        true,
      ),
      el(
        "div",
        { class: "grid" },
        numeric(values, "minutes", "Timer: minutes", 0, 999),
        numeric(values, "seconds", "Seconds", 0, 59),
      ),
      row(
        button("Start timer", () =>
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
        button("Stop", () =>
          command(
            { Command: "Tools/SetTimer", Minute: 0, Second: 0, Status: 0 },
            true,
          ),
        ),
      ),
      el("hr", { class: "divider" }),
      row(
        button("Stopwatch: start", () =>
          command({ Command: "Tools/SetStopWatch", Status: 1 }, true),
        ),
        button("Pause", () =>
          command({ Command: "Tools/SetStopWatch", Status: 2 }, true),
        ),
        button("Reset stopwatch", () =>
          command({ Command: "Tools/SetStopWatch", Status: 0 }, true),
        ),
      ),
      el(
        "div",
        { class: "grid" },
        numeric(values, "red", "Red score", 0, 999),
        numeric(values, "blue", "Blue score", 0, 999),
      ),
      row(
        button("Show scoreboard", () =>
          command(
            {
              Command: "Tools/SetScoreBoard",
              RedScore: values.red,
              BlueScore: values.blue,
            },
            true,
          ),
        ),
        button("Sound meter", () =>
          command({ Command: "Tools/SetNoiseStatus", NoiseStatus: 1 }, true),
        ),
        button("Stop meter", () =>
          command({ Command: "Tools/SetNoiseStatus", NoiseStatus: 0 }, true),
        ),
        button("Test buzzer", () =>
          command({
            Command: "Device/PlayBuzzer",
            ActiveTimeInCycle: 150,
            OffTimeInCycle: 150,
            PlayTotalTime: 600,
          }),
        ),
      ),
      button(
        "Restore composition",
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
      "Experimental native catalog and clock",
      hint(
        "Use only a valid native group. Group 0 is blocked because it alters other screens.",
      ),
      el(
        "div",
        { class: "grid three" },
        numeric(values, "clock", "ClockId", 1, 10000000),
        numeric(values, "group", "LcdIndependence group", 1, 100000000),
        field(values, "panel", "Screen", "select", {
          0: "1",
          1: "2",
          2: "3",
          3: "4",
          4: "5",
        }),
      ),
      row(
        button("Query catalog", async () => {
          const r = await action("catalog", d().id);
          if (r) toast(JSON.stringify(r).slice(0, 500));
          else toast("See Activity");
        }),
        button("Activate clock", () =>
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
      numeric(p, "work", "Work (min)", 1, 180),
      numeric(p, "rest", "Break (min)", 1, 180),
      numeric(p, "long_rest", "Long break (min)", 1, 180),
      numeric(p, "cycles", "Cycles", 1, 12),
      field(p, "panel", "Alert screen", "select", {
        0: "1",
        1: "2",
        2: "3",
        3: "4",
        4: "5",
      }),
      field(p, "buzzer", "Buzzer", "checkbox"),
    ),
    row(
      ...Object.entries({
        start: "Start",
        pause: "Pause",
        resume: "Continue",
        skip: "Skip phase",
        reset: "Reset",
      }).map(([operation, title]) =>
        button(title, () =>
          action("pomodoro", d().id, { operation, ...p, panel: +p.panel }),
        ),
      ),
    ),
  );
  main.append(pc);
  for (const [group, title] of [
    ["schedules", "Schedules"],
    ["reminders", "Reminders"],
    ["alerts", "Alerts"],
    ["profiles", "Automatic profiles"],
  ]) {
    if (group === "profiles" && !state.capabilities.profiles) {
      main.append(
        card(
          title,
          hint(
            "Phones cannot query the processes or session lock of a PC. Imported profiles are kept, but they do not run on mobile.",
          ),
        ),
      );
      continue;
    }
    const section = card(
      title,
      button("Add", () => {
        let rule = {
          id: id(),
          name: "New rule",
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
            text: "Reminder",
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
          field(r, "enabled", r.name || r.time || "Rule", "checkbox"),
          button("Edit", () => {
            editing = editing === r.id ? null : r.id;
            render();
          }),
          button(
            "Delete",
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
            field(r, "name", "Name"),
            field(r, "device_id", "Device", "select", deviceOptions()),
          ),
        );
        if (group === "schedules") {
          box.append(
            field(r, "time", "Local time", "time"),
            field(r, "action", "Action", "select", {
              on: "Turn on",
              off: "Turn off",
              brightness: "Brightness",
              scene: "Scene",
            }),
          );
          box.lastChild.addEventListener("change", () => render());
          if (r.action === "scene")
            box.append(field(r, "value", "Scene", "select", sceneOptions()));
          if (r.action === "brightness")
            box.append(numeric(r, "value", "Brightness", 0, 100));
          const days = row();
          ["M", "T", "W", "T", "F", "S", "S"].forEach((label, i) => {
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
            field(r, "trigger", "Condition", "select", {
              process: "Open process",
              locked: "Locked session",
              desktop: "Desktop",
            }),
            field(r, "process", "Process name"),
            field(r, "scene_id", "Scene", "select", sceneOptions()),
            hint(
              "In Docker only its own processes are visible. Session lock is received from the Windows desktop app; it is not detected from the container.",
            ),
          );
        } else {
          box.append(
            field(r, "text", "Message", "textarea"),
            el(
              "div",
              { class: "grid three" },
              field(r, "panel", "Screen", "select", {
                0: "1",
                1: "2",
                2: "3",
                3: "4",
                4: "5",
              }),
              numeric(r, "seconds", "Duration (s)", 5, 300),
              field(r, "buzzer", "Buzzer", "checkbox"),
            ),
          );
          const panel = box.querySelector("select:last-of-type");
          if (panel)
            panel.addEventListener("change", () => (r.panel = +r.panel));
          if (group === "reminders")
            box.append(numeric(r, "minutes", "Repeat every (min)", 1, 10080));
          else {
            box.append(
              field(
                r,
                "metric",
                "Metric",
                "select",
                state.capabilities.mode === "mobile"
                  ? { service: "Service down (1=failure)", sensor: "Sensor" }
                  : {
                      ...metrics,
                      disk_free: "Free disk",
                      service: "Service down (1=failure)",
                      sensor: "Sensor",
                    },
              ),
              el(
                "div",
                { class: "grid" },
                field(r, "operator", "Condition", "select", {
                  above: "Greater than",
                  below: "Less than",
                }),
                numeric(r, "threshold", "Threshold", -1000000000, 1000000000, 0.1),
              ),
              field(
                r,
                "source",
                "Service / sensor URL, MQTT topic or disk path",
              ),
              field(
                r,
                "sensor_source",
                "Sensor source",
                "select",
                state.capabilities.mode === "mobile"
                  ? { http: "HTTP JSON", mqtt: "MQTT" }
                  : { mqtt: "MQTT", hardware: "Hardware" },
              ),
              field(r, "field", "JSON path"),
              el(
                "div",
                { class: "grid" },
                numeric(r, "hold", "Condition held (s)", 0, 3600),
                numeric(r, "cooldown", "Minimum interval (s)", 30, 86400),
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
      "Turn on Automatic update in Device. Schedules follow the time zone of the phone or server; missed schedules are not recovered. Alerts need restorable content.",
    ),
  );
}
function pomoText() {
  const p = state.runtime?.pomodoro || {};
  // The backend reports Spanish phase names as stable protocol values.
  const phases = {
    Preparado: "Ready",
    Trabajo: "Work",
    Descanso: "Break",
    "Descanso largo": "Long break",
  };
  return `${phases[p.phase] || p.phase || "Ready"} · ${Math.floor((p.remaining || 0) / 60)}:${Math.floor(
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
      field(mqtt, "enabled", "Enable MQTT", "checkbox"),
      state.capabilities.mode === "mobile"
        ? field(
            mqtt,
            "websocket_url",
            "Broker WebSocket URL (ws:// or wss://)",
          )
        : el(
            "div",
            { class: "grid" },
            field(mqtt, "host", "Server"),
            numeric(mqtt, "port", "Port", 1, 65535),
          ),
      el(
        "div",
        { class: "grid" },
        field(mqtt, "username", "Username"),
        field(mqtt, "password", "Password", "password"),
      ),
      field(mqtt, "prefix", "Topic prefix"),
      state.capabilities.mode === "mobile"
        ? hint(
            "The broker must offer WebSockets. Sensors and commands are received while the app is active. It does not use the Keeper server.",
          )
        : field(mqtt, "tls", "TLS", "checkbox"),
      hint(
        "Credentials are excluded from exported backups. Configure each Sensor widget with its MQTT topic.",
      ),
    ),
  );
  if (state.capabilities.mode !== "mobile") {
    const api = cfg.integrations.api;
    main.append(
      card(
        "Automation API",
        field(api, "enabled", "Enable additional API", "checkbox"),
        el(
          "div",
          { class: "grid" },
          field(api, "host", "Listen on", "select", {
            "127.0.0.1": "Localhost only",
            "0.0.0.0": "Local network",
          }),
          numeric(api, "port", "Port (different from the portal)", 1, 65535),
        ),
        field(api, "token", "Token Bearer", "password"),
        button("Generate token", () => {
          api.token = id() + id() + id();
          mark();
          render();
        }),
        hint(
          "This additional API keeps /v1/status and /v1/action. The portal uses its own token, defined in KEEPER_TOKEN or data/admin.token.",
        ),
      ),
      card(
        "Host sources",
        field(
          cfg.integrations,
          "hardware",
          "Read available sensors",
          "checkbox",
        ),
        banner(state.capabilities.metrics_label),
        hint(
          "Linux: psutil sensors and MPRIS music via playerctl. Windows: LibreHardwareMonitor and media session. The container does not automatically receive the desktop sources.",
        ),
      ),
    );
  } else
    main.append(
      card(
        "Mobile sources",
        hint(
          "You can show values from Home Assistant or other machines through an HTTP JSON sensor or an MQTT topic. The phone does not get your PC CPU, GPU or temperatures automatically. The listening HTTP API and PC process profiles are not available here.",
        ),
      ),
    );
}
function backupPage(main) {
  main.append(
    card(
      "Portable backup",
      hint(
        "Includes media, screens, playlists, scenes and rules. Importing disables automatic sending and integrations so you can review the configuration.",
      ),
      row(
        button(
          "Export ZIP",
          async () => {
            await save();
            await download(
              await request("/export", "GET", undefined, true),
              "Keeper-backup.zip",
            );
          },
          "primary",
        ),
        button("Import ZIP", () =>
          chooseFile(".zip", async (file) => {
            if (
              !confirm(
                "Replace the configuration with this backup? A copy of the current one will be kept.",
              )
            )
              return;
            await waitJob(await request("/import", "POST", file));
            await load();
            render();
            toast(
              "Backup imported; check the IP and enable sending when you are ready.",
            );
          }),
        ),
      ),
    ),
  );
  main.append(
    card(
      "Library",
      button("View files", async () => {
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
                button("Use on screen " + (selected + 1), () => {
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
      "Settings and session",
      field(cfg, "resend_on_startup", "Resend on startup", "checkbox"),
      button("Reload configuration", async () => {
        if (dirty && !confirm("Discard unsaved changes?")) return;
        await load();
        render();
      }),
      state.capabilities.mode === "server"
        ? button("Sign out", () => {
            sessionStorage.removeItem("keeper-token");
            login();
          })
        : hint(
            "Data is stored on the phone. Export a backup before uninstalling the app or clearing its data.",
          ),
      hint(
        "Windows 2.3 keeps its own application and data. This version uses the same send protocol and keeps the restrictions of the native modes.",
      ),
    ),
  );
}
function activityPage(main) {
  main.append(
    card(
      "Activity",
      el("pre", { id: "activity" }, eventText()),
      button("Refresh", async () => {
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
      el("h1", {}, "Your Times Gate, at hand"),
      hint("Enter the server token to access your screens."),
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
          "Access token",
          el("input", {
            id: "token",
            type: "password",
            required: "",
            autocomplete: "current-password",
          }),
        ),
        el("button", { class: "primary", type: "submit" }, "Sign in"),
      ),
      hint(
        "The token is in data/admin.token or in the server's KEEPER_TOKEN variable.",
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

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
  screens: "Pantallas",
  panorama: "Panorámica",
  scenes: "Escenas",
  device: "Dispositivo",
  lighting: "Iluminación RGB",
  tools: "Herramientas",
  automation: "Automatizaciones",
  integrations: "Integraciones",
  backup: "Copias y ajustes",
  activity: "Actividad",
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
  if (label) label.textContent = "Cambios pendientes";
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
  toast("Configuración guardada");
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
  toast("Envío terminado");
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
    img.alt = "Archivo no disponible";
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
      img.alt = "Vista previa pendiente";
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
    img.alt = "Vista previa no disponible";
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
    await Share.share({ title: "Copia de Keeper", url: result.uri });
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
  label = "Archivo",
  accept = ".png,.jpg,.jpeg,.gif,.webp,.bmp",
) {
  const out = el(
    "div",
    {},
    hint(
      obj[key]
        ? obj[key].replaceAll("\\", "/").split("/").pop()
        : "Sin archivo",
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
        ? "MÓVIL AUTÓNOMO · " + (state.capabilities.demo ? "DEMO" : "RED LOCAL")
        : "PORTAL WEB · " + (state.capabilities.demo ? "DEMO" : "SERVIDOR"),
    ),
  );
  const nav = el("nav", { "aria-label": "Secciones" });
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
      "Dispositivo",
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
          page==='lighting' ? 'Ajusta la vista previa y aplica al dispositivo' : dirty ? "Cambios pendientes" : "Configuración guardada",
        ),
      ),
      row(
        selector,
        page==='lighting' ? null : button(
          "Guardar",
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
        "Control directo al Times Gate. Mantén la app activa para listas, widgets, horarios y avisos. Los GIF ya enviados siguen reproduciéndose en el dispositivo.",
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
    const img = el("img", { alt: `Vista previa pantalla ${i + 1}` });
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
          ? "Lista · " + list.items.length
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
      "Pantalla " + (selected + 1),
      contentForm(d().screens[selected]),
      row(
        button("Guardar y enviar", () => saveAndSend(selected), "primary"),
        button("Enviar las cinco", () => saveAndSend()),
        button("Panorámica", () => {
          page = "panorama";
          render();
        }),
      ),
    ),
  );
  const list = d().playlists[selected];
  const box = card(
    "Lista de reproducción",
    field(list, "enabled", "Usar esta lista", "checkbox"),
    hint(
      "De 5 segundos a 24 horas por elemento. El siguiente cambio empieza a contar al terminar su envío.",
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
        button("Editar", () => {
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
          "Eliminar",
          () => {
            list.items.splice(index, 1);
            if (!list.items.length) list.enabled = false;
            mark();
            render();
          },
          "danger",
        ),
      ),
      numeric(item, "seconds", "Duración (segundos)", 5, 86400),
    );
    if (editing === item.id) itemBox.append(contentForm(item.screen, true));
    box.append(itemBox);
  });
  box.append(
    row(
      button("Añadir widget", () => {
        const item = { id: id(), seconds: 15, screen: screen("clock") };
        list.items.push(item);
        editing = item.id;
        mark();
        render();
      }),
      button("Copiar pantalla actual", () => {
        if (
          ["empty", "native", "pc_native"].includes(d().screens[selected].kind)
        )
          throw Error("Elige una imagen o widget");
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
  const kind = field(s, "kind", "Contenido", "select", options);
  kind.querySelector("select").onchange = () => {
    mark();
    render();
  };
  form.append(kind);
  if (["empty", "native"].includes(s.kind)) {
    form.append(hint("Keeper no reemplazará el contenido de esta pantalla."));
    return form;
  }
  const grid = el(
    "div",
    { class: "grid" },
    field(s, "title", "Título"),
    numeric(s, "refresh", "Actualizar cada (segundos)", 5, 86400),
  );
  form.append(grid);
  if (s.kind === "media") {
    form.append(
      fileField(s, "path", "Elegir imagen o GIF"),
      el(
        "div",
        { class: "grid" },
        field(s, "fit", "Ajuste", "select", {
          contain: "Encajar",
          cover: "Recortar",
          stretch: "Estirar",
        }),
        numeric(s, "frame_step", "Salto de fotogramas", 1, 100),
      ),
    );
    if (s.panorama_speed)
      form.append(
        hint(
          "Parte de panorámica: conserva su velocidad propia (" +
            s.panorama_speed +
            " ms).",
        ),
      );
  }
  if (s.kind === "text")
    form.append(
      field(s, "text", "Texto", "textarea"),
      numeric(s, "font_size", "Tamaño de letra", 8, 64),
    );
  if (s.kind === "clock")
    form.append(field(s, "timezone", "Zona horaria (ej. Europe/Madrid)"));
  if (s.kind === "weather")
    form.append(
      el(
        "div",
        { class: "grid" },
        numeric(s, "latitude", "Latitud", -90, 90, 0.0001),
        numeric(s, "longitude", "Longitud", -180, 180, 0.0001),
      ),
    );
  if (s.kind === "countdown")
    form.append(field(s, "target", "Fecha y hora", "datetime-local"));
  if (["service", "rss"].includes(s.kind))
    form.append(
      field(
        s,
        "url",
        s.kind === "rss" ? "URL de RSS / Atom" : "URL del servicio",
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
        numeric(s, "news_seconds", "Segundos por titular", 5, 3600),
        numeric(s, "news_size", "Tamaño de letra", 8, 28),
      ),
    );
  }
  if (s.kind === "calendar")
    form.append(
      fileField(s, "path", "Importar calendario ICS", ".ics"),
      field(
        s,
        "url",
        "O URL de calendario (vacía el archivo para usarla)",
        "url",
      ),
      button("Usar URL", () => {
        s.path = "";
        mark();
        render();
      }),
    );
  if (s.kind === "pc")
    form.append(
      banner(state.capabilities.metrics_label, !state.capabilities.pc),
      field(s, "pc_view", "Vista", "select", {
        usage: "CPU / RAM / GPU",
        history: "Gráficas",
        network: "Red",
        temperature: "Temperaturas",
        storage: "Disco",
      }),
      field(s, "pc_disk", "Ruta del disco (vacío = principal)"),
    );
  if (s.kind === "music")
    form.append(
      hint(
        state.capabilities.music
          ? "Se lee la sesión multimedia del equipo servidor; en Linux necesita playerctl y una sesión MPRIS."
          : "La música de otras apps del teléfono no se puede leer aquí.",
      ),
    );
  if (s.kind === "sensor") {
    s.sensor_source ??= state.capabilities.mode === "mobile" ? "http" : "mqtt";
    s.sensor_stale ??= 300;
    form.append(
      field(
        s,
        "sensor_source",
        "Fuente",
        "select",
        state.capabilities.mode === "mobile"
          ? { http: "HTTP JSON", mqtt: "MQTT WebSocket" }
          : { mqtt: "MQTT", hardware: "Hardware" },
      ),
      field(s, "sensor_key", "URL HTTP, tema MQTT o identificador"),
      field(s, "sensor_field", "Ruta JSON (ej. cpu.temperature)"),
      field(s, "sensor_unit", "Unidad"),
      numeric(s, "sensor_stale", "Caducidad (segundos)", 10, 86400),
    );
  }
  if (s.kind === "pomodoro")
    form.append(
      hint(
        "Inicia, pausa o reinicia la sesión compartida en Automatizaciones.",
      ),
    );
  if (s.kind === "custom") {
    s.elements ??= [];
    form.append(designer(s));
  }
  if (s.kind === "pc_native") {
    form.append(
      banner(
        "Experimental: selecciona primero PC Monitor en la app Divoom. El grupo 0 no se permite. El móvil no dispone de métricas del PC.",
        true,
      ),
      field(s, "native_pc_mode", "Modo", "select", {
        existing: "Enviar datos al monitor ya elegido",
        activate: "Activar con grupo conocido",
      }),
      numeric(s, "independence", "Grupo nativo válido", 1, 100000000),
    );
  }
  form.append(
    el(
      "div",
      { class: "grid" },
      field(s, "color", "Color", "color"),
      field(s, "background", "Fondo", "color"),
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
            : el("span", {}, "Imagen"),
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
      ["width", "Ancho", 1, 128],
      ["height", "Alto", 1, 128],
      ["size", "Letra", 6, 64],
    ]) {
      const f = numeric(e, key, label, min, max);
      f.addEventListener("input", paint);
      grid.append(f);
    }
    options.append(grid);
    if (e.type === "text") {
      const f = field(e, "text", "Texto · {time}, {date}, {cpu}…", "textarea");
      f.addEventListener("input", paint);
      options.append(f);
    }
    if (e.type === "image") options.append(fileField(e, "path"));
    if (e.type === "bar")
      options.append(
        field(e, "metric", "Métrica", "select", metrics),
        numeric(e, "maximum", "Valor máximo", 1, 1000000),
      );
    const color = field(e, "color", "Color", "color");
    color.addEventListener("input", paint);
    options.append(
      color,
      row(
        button("Subir capa", () => {
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
          "Eliminar elemento",
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
          "Añadir " + { text: "texto", image: "imagen", bar: "barra" }[type],
          () => {
            if (s.elements.length >= 20) throw Error("Máximo 20 elementos");
            s.elements.push({
              type,
              x: 8,
              y: 8,
              width: 112,
              height: type === "bar" ? 12 : 30,
              size: 16,
              color: "#64e6ca",
              text: "Nuevo texto",
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
      "Arrastra los elementos. La vista de diseño usa valores de ejemplo; el contenido enviado usa las fuentes disponibles.",
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
      "aria-label": "Vista previa panorámica",
      width: 640,
      height: 128,
    }),
    source = el("div", { class: "crop-source" }),
    cross = el("div", {
      class: "crosshair",
      style: `left:${p.x * 100}%;top:${p.y * 100}%`,
    }),
    message = hint("Selecciona un archivo y prepara la vista previa.");
  let generation = p.generation;
  let previewFrames = [],
    frameIndex = 0;
  const seek = el("input", {
    type: "range",
    min: 0,
    max: 0,
    value: 0,
    "aria-label": "Fotograma de vista previa",
  });
  const paintFrame = () => {
    if (previewFrames.length)
      preview.getContext("2d").drawImage(previewFrames[frameIndex], 0, 0);
    seek.value = frameIndex;
  };
  const play = button("Pausar vista previa", () => {
    if (previewTimer) {
      clearInterval(previewTimer);
      previewTimer = null;
      play.textContent = "Reproducir vista previa";
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
    play.textContent = "Pausar vista previa";
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
    ["start", "Inicio (s)", 0, 86400, 0.1],
    ["duration", "Duración (s)", 0.1, 30, 0.1],
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
    fit = field(p, "fit", "Ajuste", "select", {
      cover: "Recortar",
      contain: "Encajar",
      stretch: "Estirar",
    }),
    rotation = field(p, "rotation", "Giro", "select", {
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
    "Aplicar y enviar",
    async () => {
      if (!p.result) throw Error("Prepara antes la vista previa");
      cfg.scenes.push({
        id: id(),
        name: "Antes de panorámica · " + new Date().toLocaleString(),
        ...composition(d()),
      });
      d().screens = copy(p.result.screens);
      d().screens.forEach((s, i) => (s.title = "Panorámica · " + (i + 1)));
      d().playlists.forEach((l) => (l.enabled = false));
      mark();
      await saveAndSend();
    },
    "primary",
  );
  apply.disabled = !p.result;
  const prepare = button("Preparar vista previa", async () => {
    if (!p.path) throw Error("Elige un archivo");
    prepare.disabled = true;
    apply.disabled = true;
    generation = ++p.generation;
    try {
      message.textContent = "Convirtiendo…";
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
      message.textContent = `${result.count} fotogramas · ${result.duration.toFixed(2)} s · carga mínima ${(result.count * 0.5).toFixed(0)} s, normalmente más.`;
    } finally {
      prepare.disabled = false;
    }
  });
  main.append(
    card(
      "Una composición, cinco pantallas",
      row(
        button("Elegir imagen, GIF o vídeo", () =>
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
        button("Centrar", () => {
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
          : "Hasta 100 MB. Vídeo sin audio. En móvil, códecs compatibles con el teléfono.",
      ),
      source,
      hint(
        "Pulsa o arrastra para elegir la zona; afina con Horizontal, Vertical y Zoom.",
      ),
      controls,
      row(
        prepare,
        button("Cancelar conversión", async () => {
          p.generation++;
          p.result = null;
          if (p.job) await request("/jobs/" + p.job + "/cancel", "POST");
          message.textContent = "Conversión cancelada";
        }),
        apply,
      ),
      message,
      preview,
      row(play, seek),
      banner(
        "Las cinco partes se envían una tras otra: puede haber desfase aunque la vista previa esté sincronizada. Máximo 30 segundos y 120 fotogramas por pantalla.",
        true,
      ),
    ),
  );
  if (p.result) {
    message.textContent = `${p.result.count} fotogramas · ${p.result.duration.toFixed(2)} s`;
    run(() => loadPreview(p.result));
  }
}

function scenePage(main) {
  main.append(
    card(
      "Composiciones",
      row(
        button(
          "Guardar composición actual",
          () => {
            const name = prompt("Nombre de la escena");
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
        "Una escena incluye las cinco pantallas y sus listas. Se guarda con los archivos de la biblioteca.",
      ),
    ),
  );
  for (const scene of cfg.scenes) {
    main.append(
      card(
        scene.name,
        row(
          button("Aplicar y enviar", async () => {
            await save();
            await action("scene", d().id, { scene_id: scene.id });
            await load();
            render();
          }),
          button("Renombrar", () => {
            const name = prompt("Nombre", scene.name);
            if (name?.trim()) {
              scene.name = name.trim();
              mark();
              render();
            }
          }),
          button(
            "Eliminar",
            () => {
              if (
                !confirm("Se eliminarán esta escena y las reglas que la usan.")
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
    "Rotación de escenas",
    numeric(d(), "rotation_seconds", "Cambiar cada (segundos)", 30, 86400),
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
      "Conexión local",
      el(
        "div",
        { class: "grid" },
        field(value, "name", "Nombre"),
        field(value, "ip", "IP del Times Gate (ej. 192.168.1.116)"),
      ),
      field(value, "enabled", "Actualización automática", "checkbox"),
      row(
        button("Guardar y comprobar", async () => {
          await save();
          await action("health", d().id);
          toast("Comprobación terminada; consulta Actividad");
        }),
        button("Buscar LAN", async () => {
          await save();
          const result = await action("discover", d().id, {
            seed: d().ip,
            cloud: false,
          });
          toast(
            result?.devices
              ? "Dispositivos: " + JSON.stringify(result.devices)
              : "Consulta los resultados en Actividad",
          );
        }),
        button("Descubrir mediante Divoom", async () => {
          await save();
          await action("discover", d().id, { cloud: true, seed: d().ip });
          toast("Consulta los resultados en Actividad");
        }),
      ),
      hint(
        "El teléfono o servidor y el Times Gate deben poder comunicarse por la red local. En Docker puede ser necesario indicar la IP: la búsqueda usa la subred visible desde el contenedor.",
      ),
    ),
  );
  main.append(
    card(
      "Enviar y restaurar",
      el(
        "div",
        { class: "grid three" },
        numeric(value, "quality", "Calidad JPEG", 30, 100),
        numeric(value, "speed", "Milisegundos por fotograma", 1, 60000),
        numeric(
          value,
          "interval_minutes",
          "Reenviar medios cada (minutos)",
          1,
          10080,
        ),
      ),
      field(value, "suspended", "Pausar envíos", "checkbox"),
      field(cfg, "resend_on_startup", "Reenviar al iniciar", "checkbox"),
      row(
        button(
          "Reanudar y reenviar",
          async () => {
            await save();
            await action("resume", d().id);
            await load();
            render();
          },
          "primary",
        ),
        button("Enviar todo", () => saveAndSend()),
      ),
      hint(
        "Los GIF panorámicos conservan su velocidad propia. La pausa deja el contenido ya enviado en el dispositivo.",
      ),
    ),
  );
  main.append(
    card(
      "Varios dispositivos",
      row(
        button("Añadir dispositivo", () => {
          const value = device();
          cfg.devices.push(value);
          cfg.active_device = value.id;
          mark();
          render();
        }),
        button(
          "Eliminar seleccionado",
          () => {
            if (cfg.devices.length === 1)
              throw Error("Conserva al menos un dispositivo");
            if (!confirm("Eliminar este dispositivo y sus horarios y reglas?"))
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
        field(value, "mac", "MAC (opcional)"),
        numeric(value, "device_id", "DeviceId Divoom (opcional)", 0, 999999999),
        numeric(value, "port", "Puerto (0 = auto: 80 o 9000)", 0, 65535),
        field(value, "local_token", "Token local (de la app Divoom)"),
      ),
    ),
  );
}
const lightingDrafts=new Map();
function lightingPage(main) {
  const deviceId=d().id;
  if(!lightingDrafts.has(deviceId))lightingDrafts.set(deviceId,{...lightingDefaults(),...d().lighting});
  const settings=lightingDrafts.get(deviceId);
  const preview=el('div',{class:'light-device','aria-label':'Vista previa de color y zonas del Times Gate',role:'img'});
  const glow=el('div',{class:'light-back'}),panels=el('div',{class:'light-panels'},...[1,2,3,4,5].map(n=>el('div',{class:'light-screen'},el('span',{},String(n))))),keys=el('div',{class:'light-keys'});
  preview.append(glow,panels,keys);
  const status=el('p',{class:'hint'},'Vista orientativa de color, brillo y zonas. Los efectos animados se comprueban en el Times Gate.');
  const draw=()=>{
    preview.style.setProperty('--light',settings.color);preview.style.setProperty('--brightness',settings.on?settings.brightness/100:0);
    preview.classList.toggle('cycling',settings.cycle);preview.classList.toggle('edges',settings.zone!==2);preview.classList.toggle('backlight',settings.zone!==1);preview.classList.toggle('keys-on',settings.keys);
  };
  const color=colorControl(settings.color,'Color de la iluminación',value=>{settings.color=value;draw();});
  const brightness=el('input',{type:'range',min:0,max:100,step:1,value:settings.brightness,'aria-label':'Brillo RGB'}),percentage=el('output',{},settings.brightness+'%');
  brightness.oninput=()=>{settings.brightness=+brightness.value;percentage.textContent=settings.brightness+'%';draw();};
  const zones=el('div',{class:'segmented','aria-label':'Zona iluminada',role:'group'});
  ['Todas las zonas','Bordes','Luz trasera'].forEach((name,index)=>{
    const b=button(name,()=>{settings.zone=index;for(const [i,item] of [...zones.children].entries())item.setAttribute('aria-pressed',String(i===index));draw();});b.setAttribute('aria-pressed',String(index===settings.zone));zones.append(b);
  });
  const switches=el('div',{class:'lighting-switches'});
  for(const [key,name] of [['on','Iluminación encendida'],['cycle','Ciclo multicolor'],['keys','Luz de teclas']]){
    const input=el('input',{type:'checkbox',checked:settings[key]});input.onchange=()=>{settings[key]=input.checked;draw();};switches.append(el('label',{class:'light-toggle'},input,el('span',{},name)));
  }
  const presets=el('div',{class:'mood-grid'});
  moods.forEach(([name,value,level,cycle])=>{
    const b=button(name,()=>{Object.assign(settings,{color:value,brightness:level,cycle,on:true});render();});b.prepend(el('span',{class:'mood-dot',style:`--swatch:${value}`}));presets.append(b);
  });
  const effects=el('div',{class:'effect-grid',role:'group','aria-label':'Efectos RGB'});
  for(let i=0;i<12;i++){
    const b=button('',()=>{settings.effect=i;for(const [n,item] of [...effects.children].entries())item.setAttribute('aria-pressed',String(n===i));});
    b.setAttribute('aria-pressed',String(settings.effect===i));b.setAttribute('aria-label','Efecto '+(i+1));
    b.append(el('span',{class:'effect-symbol','aria-hidden':'true'},'▱ ▱ ▱ ▱ ▱'),el('span',{},'Efecto '+(i+1)));effects.append(b);
  }
  main.append(card('Tu ambiente, de un vistazo',preview,status,el('div',{class:'lighting-layout'},el('div',{},color),el('div',{},el('p',{class:'color-label'},'Zona iluminada'),zones,el('div',{class:'brightness-row'},el('span',{},'Brillo'),brightness,percentage),switches))),
    card('Ambientes rápidos',hint('Elige una combinación de color y brillo. Conserva el efecto y la zona que hayas seleccionado.'),presets),
    card('Efectos del dispositivo',hint('Selecciona una tarjeta. Los modos conservan el orden del dispositivo; sus animaciones varían según el firmware.'),effects,
      el('div',{class:'lighting-apply'},button('Aplicar iluminación',async()=>{await action('command',deviceId,{payload:lightingPayload(settings)});toast('Iluminación enviada al Times Gate');},'primary'),hint('La vista previa no envía cambios hasta que pulses Aplicar iluminación.'))));
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
      "Pantallas y brillo",
      numeric(values, "brightness", "Brillo", 0, 100),
      row(
        button("Aplicar brillo", () =>
          command({
            Command: "Channel/SetBrightness",
            Brightness: values.brightness,
          }),
        ),
        button("Encender", async () => {
          await command({ Command: "Channel/OnOffScreen", OnOff: 1 });
          await load();
          render();
        }),
        button("Apagar", async () => {
          await command({ Command: "Channel/OnOffScreen", OnOff: 0 });
          await load();
          render();
        }),
        button("Leer configuración", () => action("health", d().id)),
        button(
          "Reiniciar dispositivo",
          async () => {
            if (confirm("¿Reiniciar el Times Gate?"))
              await command({ Command: "Device/SysReboot" });
          },
          "danger",
        ),
      ),
    ),
  );
  main.append(
    card(
      "Aviso temporal",
      field(values, "text", "Mensaje", "textarea"),
      el(
        "div",
        { class: "grid three" },
        field(values, "panel", "Pantalla", "select", {
          0: "1",
          1: "2",
          2: "3",
          3: "4",
          4: "5",
        }),
        numeric(values, "duration", "Duración (s)", 5, 300),
        field(values, "buzzer", "Pitido", "checkbox"),
      ),
      button(
        "Enviar aviso",
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
      "Herramientas nativas",
      banner(
        "Estas herramientas pueden cambiar el modo del dispositivo. Al usarlas se pausa el reenvío; pulsa Recuperar composición para volver.",
        true,
      ),
      el(
        "div",
        { class: "grid" },
        numeric(values, "minutes", "Temporizador: minutos", 0, 999),
        numeric(values, "seconds", "Segundos", 0, 59),
      ),
      row(
        button("Iniciar temporizador", () =>
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
        button("Detener", () =>
          command(
            { Command: "Tools/SetTimer", Minute: 0, Second: 0, Status: 0 },
            true,
          ),
        ),
      ),
      el("hr", { class: "divider" }),
      row(
        button("Cronómetro: iniciar", () =>
          command({ Command: "Tools/SetStopWatch", Status: 1 }, true),
        ),
        button("Pausar", () =>
          command({ Command: "Tools/SetStopWatch", Status: 2 }, true),
        ),
        button("Reiniciar cronómetro", () =>
          command({ Command: "Tools/SetStopWatch", Status: 0 }, true),
        ),
      ),
      el(
        "div",
        { class: "grid" },
        numeric(values, "red", "Marcador rojo", 0, 999),
        numeric(values, "blue", "Marcador azul", 0, 999),
      ),
      row(
        button("Mostrar marcador", () =>
          command(
            {
              Command: "Tools/SetScoreBoard",
              RedScore: values.red,
              BlueScore: values.blue,
            },
            true,
          ),
        ),
        button("Medidor de sonido", () =>
          command({ Command: "Tools/SetNoiseStatus", NoiseStatus: 1 }, true),
        ),
        button("Parar medidor", () =>
          command({ Command: "Tools/SetNoiseStatus", NoiseStatus: 0 }, true),
        ),
        button("Probar pitido", () =>
          command({
            Command: "Device/PlayBuzzer",
            ActiveTimeInCycle: 150,
            OffTimeInCycle: 150,
            PlayTotalTime: 600,
          }),
        ),
      ),
      button(
        "Recuperar composición",
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
      "Catálogo y reloj nativo experimental",
      hint(
        "Usa únicamente un grupo nativo válido. El grupo 0 está bloqueado porque altera otras pantallas.",
      ),
      el(
        "div",
        { class: "grid three" },
        numeric(values, "clock", "ClockId", 1, 10000000),
        numeric(values, "group", "Grupo LcdIndependence", 1, 100000000),
        field(values, "panel", "Pantalla", "select", {
          0: "1",
          1: "2",
          2: "3",
          3: "4",
          4: "5",
        }),
      ),
      row(
        button("Consultar catálogo", async () => {
          const r = await action("catalog", d().id);
          if (r) toast(JSON.stringify(r).slice(0, 500));
          else toast("Consulta Actividad");
        }),
        button("Activar reloj", () =>
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
      numeric(p, "work", "Trabajo (min)", 1, 180),
      numeric(p, "rest", "Descanso (min)", 1, 180),
      numeric(p, "long_rest", "Descanso largo (min)", 1, 180),
      numeric(p, "cycles", "Ciclos", 1, 12),
      field(p, "panel", "Pantalla de avisos", "select", {
        0: "1",
        1: "2",
        2: "3",
        3: "4",
        4: "5",
      }),
      field(p, "buzzer", "Pitido", "checkbox"),
    ),
    row(
      ...Object.entries({
        start: "Iniciar",
        pause: "Pausar",
        resume: "Continuar",
        skip: "Saltar fase",
        reset: "Reiniciar",
      }).map(([operation, title]) =>
        button(title, () =>
          action("pomodoro", d().id, { operation, ...p, panel: +p.panel }),
        ),
      ),
    ),
  );
  main.append(pc);
  for (const [group, title] of [
    ["schedules", "Horarios"],
    ["reminders", "Recordatorios"],
    ["alerts", "Alertas"],
    ["profiles", "Perfiles automáticos"],
  ]) {
    if (group === "profiles" && !state.capabilities.profiles) {
      main.append(
        card(
          title,
          hint(
            "Los teléfonos no permiten consultar los procesos ni el bloqueo de sesión de un PC. Los perfiles importados se conservan, pero no se ejecutan en el móvil.",
          ),
        ),
      );
      continue;
    }
    const section = card(
      title,
      button("Añadir", () => {
        let rule = {
          id: id(),
          name: "Nueva regla",
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
            text: "Recordatorio",
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
          field(r, "enabled", r.name || r.time || "Regla", "checkbox"),
          button("Editar", () => {
            editing = editing === r.id ? null : r.id;
            render();
          }),
          button(
            "Eliminar",
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
            field(r, "name", "Nombre"),
            field(r, "device_id", "Dispositivo", "select", deviceOptions()),
          ),
        );
        if (group === "schedules") {
          box.append(
            field(r, "time", "Hora local", "time"),
            field(r, "action", "Acción", "select", {
              on: "Encender",
              off: "Apagar",
              brightness: "Brillo",
              scene: "Escena",
            }),
          );
          box.lastChild.addEventListener("change", () => render());
          if (r.action === "scene")
            box.append(field(r, "value", "Escena", "select", sceneOptions()));
          if (r.action === "brightness")
            box.append(numeric(r, "value", "Brillo", 0, 100));
          const days = row();
          ["L", "M", "X", "J", "V", "S", "D"].forEach((label, i) => {
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
            field(r, "trigger", "Condición", "select", {
              process: "Proceso abierto",
              locked: "Sesión bloqueada",
              desktop: "Escritorio",
            }),
            field(r, "process", "Nombre del proceso"),
            field(r, "scene_id", "Escena", "select", sceneOptions()),
            hint(
              "En Docker solo se ven sus procesos. El bloqueo de sesión se recibe en la aplicación de escritorio Windows; no se detecta desde el contenedor.",
            ),
          );
        } else {
          box.append(
            field(r, "text", "Mensaje", "textarea"),
            el(
              "div",
              { class: "grid three" },
              field(r, "panel", "Pantalla", "select", {
                0: "1",
                1: "2",
                2: "3",
                3: "4",
                4: "5",
              }),
              numeric(r, "seconds", "Duración (s)", 5, 300),
              field(r, "buzzer", "Pitido", "checkbox"),
            ),
          );
          const panel = box.querySelector("select:last-of-type");
          if (panel)
            panel.addEventListener("change", () => (r.panel = +r.panel));
          if (group === "reminders")
            box.append(numeric(r, "minutes", "Repetir cada (min)", 1, 10080));
          else {
            box.append(
              field(
                r,
                "metric",
                "Métrica",
                "select",
                state.capabilities.mode === "mobile"
                  ? { service: "Servicio caído (1=falla)", sensor: "Sensor" }
                  : {
                      ...metrics,
                      disk_free: "Disco libre",
                      service: "Servicio caído (1=falla)",
                      sensor: "Sensor",
                    },
              ),
              el(
                "div",
                { class: "grid" },
                field(r, "operator", "Condición", "select", {
                  above: "Mayor que",
                  below: "Menor que",
                }),
                numeric(r, "threshold", "Umbral", -1000000000, 1000000000, 0.1),
              ),
              field(
                r,
                "source",
                "URL del servicio / sensor, tema MQTT o ruta de disco",
              ),
              field(
                r,
                "sensor_source",
                "Fuente de sensor",
                "select",
                state.capabilities.mode === "mobile"
                  ? { http: "HTTP JSON", mqtt: "MQTT" }
                  : { mqtt: "MQTT", hardware: "Hardware" },
              ),
              field(r, "field", "Ruta JSON"),
              el(
                "div",
                { class: "grid" },
                numeric(r, "hold", "Condición mantenida (s)", 0, 3600),
                numeric(r, "cooldown", "Separación mínima (s)", 30, 86400),
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
      "Activa Actualización automática en Dispositivo. Horarios según la zona horaria del teléfono o servidor; no se recuperan horarios perdidos. Los avisos necesitan contenido restaurable.",
    ),
  );
}
function pomoText() {
  const p = state.runtime?.pomodoro || {};
  return `${p.phase || "Preparado"} · ${Math.floor((p.remaining || 0) / 60)}:${Math.floor(
    (p.remaining || 0) % 60,
  )
    .toString()
    .padStart(2, "0")} · ciclo ${p.cycle || 0}`;
}
function integrationPage(main) {
  const mqtt = cfg.integrations.mqtt;
  main.append(
    card(
      "MQTT / Home Assistant",
      field(mqtt, "enabled", "Activar MQTT", "checkbox"),
      state.capabilities.mode === "mobile"
        ? field(
            mqtt,
            "websocket_url",
            "URL WebSocket del broker (ws:// o wss://)",
          )
        : el(
            "div",
            { class: "grid" },
            field(mqtt, "host", "Servidor"),
            numeric(mqtt, "port", "Puerto", 1, 65535),
          ),
      el(
        "div",
        { class: "grid" },
        field(mqtt, "username", "Usuario"),
        field(mqtt, "password", "Contraseña", "password"),
      ),
      field(mqtt, "prefix", "Prefijo de temas"),
      state.capabilities.mode === "mobile"
        ? hint(
            "El broker debe ofrecer WebSockets. Sensores y comandos se reciben mientras la app está activa. No usa el servidor Keeper.",
          )
        : field(mqtt, "tls", "TLS", "checkbox"),
      hint(
        "Las credenciales se excluyen de las copias exportadas. Configura cada widget Sensor con su tema MQTT.",
      ),
    ),
  );
  if (state.capabilities.mode !== "mobile") {
    const api = cfg.integrations.api;
    main.append(
      card(
        "API de automatización",
        field(api, "enabled", "Activar API adicional", "checkbox"),
        el(
          "div",
          { class: "grid" },
          field(api, "host", "Escuchar en", "select", {
            "127.0.0.1": "Solo localhost",
            "0.0.0.0": "Red local",
          }),
          numeric(api, "port", "Puerto (distinto al portal)", 1, 65535),
        ),
        field(api, "token", "Token Bearer", "password"),
        button("Generar token", () => {
          api.token = id() + id() + id();
          mark();
          render();
        }),
        hint(
          "Esta API adicional conserva /v1/status y /v1/action. El portal usa su propio token, definido en KEEPER_TOKEN o data/admin.token.",
        ),
      ),
      card(
        "Fuentes del equipo",
        field(
          cfg.integrations,
          "hardware",
          "Leer sensores disponibles",
          "checkbox",
        ),
        banner(state.capabilities.metrics_label),
        hint(
          "Linux: sensores de psutil y música MPRIS con playerctl. Windows: LibreHardwareMonitor y sesión multimedia. El contenedor no recibe automáticamente las fuentes del escritorio.",
        ),
      ),
    );
  } else
    main.append(
      card(
        "Fuentes en el móvil",
        hint(
          "Puedes mostrar valores de Home Assistant u otros equipos mediante un sensor HTTP JSON o un tema MQTT. El teléfono no obtiene CPU, GPU ni temperaturas de tu PC automáticamente. La API HTTP de escucha y los perfiles de procesos del PC no están disponibles aquí.",
        ),
      ),
    );
}
function backupPage(main) {
  main.append(
    card(
      "Copia portátil",
      hint(
        "Incluye medios, pantallas, listas, escenas y reglas. La importación desactiva los envíos automáticos y las integraciones para revisar la configuración.",
      ),
      row(
        button(
          "Exportar ZIP",
          async () => {
            await save();
            await download(
              await request("/export", "GET", undefined, true),
              "Keeper-backup.zip",
            );
          },
          "primary",
        ),
        button("Importar ZIP", () =>
          chooseFile(".zip", async (file) => {
            if (
              !confirm(
                "¿Sustituir la configuración por esta copia? Se conservará una copia de la actual.",
              )
            )
              return;
            await waitJob(await request("/import", "POST", file));
            await load();
            render();
            toast(
              "Copia importada; revisa la IP y activa los envíos cuando quieras.",
            );
          }),
        ),
      ),
    ),
  );
  main.append(
    card(
      "Biblioteca",
      button("Ver archivos", async () => {
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
                button("Usar en pantalla " + (selected + 1), () => {
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
      "Ajustes y sesión",
      field(cfg, "resend_on_startup", "Reenviar al iniciar", "checkbox"),
      button("Recargar configuración", async () => {
        if (dirty && !confirm("¿Descartar los cambios pendientes?")) return;
        await load();
        render();
      }),
      state.capabilities.mode === "server"
        ? button("Cerrar sesión", () => {
            sessionStorage.removeItem("keeper-token");
            login();
          })
        : hint(
            "Los datos se guardan en el teléfono. Exporta una copia antes de desinstalar la app o borrar sus datos.",
          ),
      hint(
        "Windows 2.3 conserva su aplicación y datos. Esta versión utiliza el mismo protocolo de envío y mantiene las restricciones de los modos nativos.",
      ),
    ),
  );
}
function activityPage(main) {
  main.append(
    card(
      "Actividad",
      el("pre", { id: "activity" }, eventText()),
      button("Actualizar", async () => {
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
      el("h1", {}, "Tu Times Gate, a mano"),
      hint("Introduce el token del servidor para acceder a tus pantallas."),
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
          "Token de acceso",
          el("input", {
            id: "token",
            type: "password",
            required: "",
            autocomplete: "current-password",
          }),
        ),
        el("button", { class: "primary", type: "submit" }, "Entrar"),
      ),
      hint(
        "El token está en data/admin.token o en la variable KEEPER_TOKEN del servidor.",
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

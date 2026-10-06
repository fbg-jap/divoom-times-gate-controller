import {ctx} from "./ctx.js";
import {t,setLanguage} from "./i18n.js";
import {colorControl} from "./colors.js";
import {native,request,waitJob,upload,mediaBlob} from "./api.js";
import {composition,normalize} from "./model.js";
import {action as backendAction} from "./api.js";
export const $ = (s) => document.querySelector(s),
  app = $("#app");
export function el(tag, attrs = {}, ...children) {
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
export const button = (title, fn, cls = "") =>
  el("button", { type: "button", class: cls, onclick: () => run(fn) }, title);
export const row = (...children) => el("div", { class: "row" }, children),
  card = (title, ...children) =>
    el("section", { class: "card" }, el("h2", {}, title), children);
export const hint = (text) => el("p", { class: "hint" }, text),
  banner = (text, warn = false) =>
    el("div", { class: "banner" + (warn ? " warning" : "") }, text);
export function toast(message, error = false) {
  const box = $("#toast");
  box.textContent = message;
  box.className = error ? "error" : "";
  box.style.display = "block";
  clearTimeout(ctx.toastTimer);
  ctx.toastTimer = setTimeout(
    () => (box.style.display = "none"),
    error ? 9000 : 5000,
  );
}
export async function run(fn) {
  try {
    await fn();
  } catch (e) {
    toast(e.message, true);
  }
}
export function mark() {
  ctx.dirty = true;
  const label = $("#save-state");
  if (label) label.textContent = t("ui.unsaved_changes");
}
export function field(obj, key, label, type = "text", options) {
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
export function numeric(obj, key, label, min, max, step = 1) {
  const f = field(obj, key, label, "number"),
    i = f.querySelector("input");
  i.min = min;
  i.max = max;
  i.step = step;
  return f;
}
export const d = () => ctx.cfg.devices.find((d) => d.id === ctx.cfg.active_device);
export async function load() {
  ctx.state = await request("/state");
  ctx.cfg = normalize(ctx.state.config);
  setLanguage(ctx.cfg.language);
  ctx.revision = ctx.state.revision;
  ctx.dirty = false;
}
export async function save() {
  const result = await request("/config", "PUT", { config: ctx.cfg, revision: ctx.revision });
  await waitJob(result);
  await load();
  render();
  toast(t("ui.configuration_saved"));
}
export async function action(name, deviceId, args = {}) {
  if (ctx.dirty) await save();
  try {
    return await backendAction(name, deviceId, args);
  } finally {
    // Commands can change suspension, power or the active composition even if
    // their later upload fails. Use their new ctx.revision for the next edit.
    await load();
    render();
  }
}
export async function saveAndSend(panel) {
  await save();
  await action("send", d().id, panel == null ? {} : { panel });
  render();
  toast(t("ui.send_complete"));
}
export async function showImage(img, path) {
  const capture = ctx.version;
  try {
    const blob = await mediaBlob(path);
    if (capture !== ctx.version) return;
    const url = URL.createObjectURL(blob);
    ctx.urls.push(url);
    img.src = url;
  } catch {
    img.alt = t("ui.file_unavailable");
  }
}
export async function preview(img, deviceId, panel) {
  const capture = ctx.version;
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
      if (capture !== ctx.version) return;
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
      const i = ctx.urls.indexOf(old);
      if (i >= 0) ctx.urls.splice(i, 1);
    }
    const url = URL.createObjectURL(blob);
    ctx.urls.push(url);
    img.src = url;
  } catch {
    img.alt = t("ui.preview_unavailable");
  } finally {
    delete img.dataset.loading;
  }
}
export function chooseFile(accept, fn) {
  const input = el("input", { type: "file", accept, class: "file" });
  input.onchange = () => {
    const file = input.files[0];
    if (file) run(() => fn(file));
    input.remove();
  };
  document.body.append(input);
  input.click();
}
export async function download(blob, name) {
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
export function fileField(
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
export function deviceOptions() {
  return Object.fromEntries(ctx.cfg.devices.map((d) => [d.id, d.name]));
}
export function sceneOptions() {
  return Object.fromEntries(ctx.cfg.scenes.map((s) => [s.id, s.name]));
}
export const render = () => ctx.render();

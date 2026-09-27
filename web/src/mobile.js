import { CapacitorHttp } from "@capacitor/core";
import { App } from "@capacitor/app";
import JSZip from "jszip";
import ICAL from "ical.js";
import {
  defaults,
  screen,
  copy,
  composition,
  allScreens,
  assets,
  validIp,
  validate,
  id,
  normalize,
} from "./model.js";
import { openStorage, read, write, entries } from "./storage.js";
import { lightingFromPayload } from './colors.js';
import {
  canvas,
  drawFit,
  decode,
  encodePanorama,
  image,
  jpeg,
  pause,
} from "./media.js";

const now = () => Date.now() / 1000;
export function validateCommand(payload) {
  if(payload?.Command==='Channel/SetRGBInfo'){lightingFromPayload(payload);return;}
  const commands = {
    "Channel/GetAllConf": {},
    "Device/SysReboot": {},
    "Channel/SetBrightness": { Brightness: [0, 100] },
    "Channel/Set5LcdBrightness": { Brightness: [0, 100] },
    "Channel/OnOffScreen": { OnOff: [0, 1] },
    "Tools/SetTimer": { Minute: [0, 999], Second: [0, 59], Status: [0, 1] },
    "Tools/SetStopWatch": { Status: [0, 2] },
    "Tools/SetScoreBoard": { RedScore: [0, 999], BlueScore: [0, 999] },
    "Tools/SetNoiseStatus": { NoiseStatus: [0, 1] },
    "Device/PlayBuzzer": {
      ActiveTimeInCycle: [0, 10000],
      OffTimeInCycle: [0, 10000],
      PlayTotalTime: [0, 10000],
    },
    "Channel/SetClockSelectId": {
      ClockId: [1, 10000000],
      LcdIndependence: [1, 100000000],
      LcdIndex: [0, 4],
    },
  };
  const schema = commands[payload?.Command];
  if (!schema) throw Error("Comando no admitido");
  for (const [key, [low, high]] of Object.entries(schema))
    if (
      !Number.isInteger(payload[key]) ||
      payload[key] < low ||
      payload[key] > high
    )
      throw Error("Parámetro inválido: " + key);
  if (
    Object.keys(payload).some(
      (key) => !["Command", "DeviceId", ...Object.keys(schema)].includes(key),
    )
  )
    throw Error("Parámetro desconocido");
}
export function payloadForFrame(panel, count, index, picId, speed, data) {
  return {
    Command: "Draw/SendHttpGif",
    LcdArray: Array.from({ length: 5 }, (_, i) => +(i === panel)),
    PicNum: count,
    PicOffset: index,
    PicID: picId,
    PicSpeed: Math.max(1, Math.round(speed)),
    PicWidth: 128,
    PicData: data,
  };
}
export class MobileEngine {
  constructor(demo = false) {
    this.demo = demo;
    this.revision = 0;
    this.jobs = new Map();
    this.events = [];
    this.serial = Promise.resolve();
    this.busy = false;
    this.active = true;
    this.lastId = 0;
    this.last = new Map();
    this.cursors = new Map();
    this.overrides = new Map();
    this.rules = new Map();
    this.cache = new Map();
    this.rotation = new Map();
    this.sensors = new Map();
    this.alarms = new Map();
    this.pomo = {
      phase: "Preparado",
      remaining: 1500,
      total: 1500,
      running: false,
      cycle: 0,
    };
    this.pomoSettings = { work: 25, rest: 5, long_rest: 15, cycles: 4 };
    this.pomoAt = now();
  }
  async init() {
    await openStorage();
    this.config = normalize((await read("state", "config")) || defaults());
    if (this.demo && !this.config.devices[0].ip) {
      this.config.devices[0].ip = "192.168.1.116";
      this.config.devices[0].screens = [
        screen("clock"),
        screen("text", { text: "KEEPER\nMOBILE" }),
        screen("weather"),
        screen("pomodoro"),
        screen("text", { text: "Sin servidor" }),
      ];
    }
    if (!this.demo)
      await App.addListener("appStateChange", ({ isActive }) => {
        this.active = isActive;
        this.log(
          isActive
            ? "Aplicación activa: se reanudan las tareas"
            : "Aplicación en segundo plano: tareas pausadas",
        );
      });
    this.timer = setInterval(() => this.tick(), 1000);
    this.log(
      this.demo
        ? "Móvil DEMO: no envía al dispositivo"
        : "Control autónomo · tareas continuas mientras la app esté activa",
    );
  }
  log(message, level = "info") {
    this.events.push({
      id: Date.now() + Math.random(),
      time: now(),
      event: "log",
      message,
      level,
    });
    this.events = this.events.slice(-300);
  }
  async persist() {
    await write("state", "config", this.config);
    this.revision++;
  }
  task(operation, fn) {
    if (
      [...this.jobs.values()].filter((j) =>
        ["queued", "running"].includes(j.status),
      ).length >= 20
    )
      throw Error("Cola llena");
    const key = id(),
      job = { id: key, operation, status: "queued" };
    this.jobs.set(key, job);
    while (this.jobs.size > 100) {
      const oldest = [...this.jobs].find(([, j]) =>
        ["done", "error", "cancelled"].includes(j.status),
      );
      if (!oldest) break;
      this.jobs.delete(oldest[0]);
    }
    this.serial = this.serial.then(async () => {
      this.busy = true;
      job.status = "running";
      try {
        job.result = await fn();
        job.status = "done";
      } catch (error) {
        job.status = "error";
        job.error = error.message;
        this.log(error.message, "error");
      } finally {
        this.busy = false;
      }
    });
    return { job: key };
  }
  async http(url, options = {}) {
    if (!/^https?:\/\//.test(url)) throw Error("Se necesita URL HTTP o HTTPS");
    if (this.demo) throw Error("Fuente externa no disponible en demo móvil");
    const response = await CapacitorHttp.request({
      url,
      method: "GET",
      connectTimeout: 10000,
      readTimeout: 10000,
      ...options,
    });
    if (response.status < 200 || response.status >= 300)
      throw Error("HTTP " + response.status);
    return response.data;
  }
  async command(d, payload) {
    if (!this.active) throw Error("Abre la app para controlar el dispositivo");
    const ip = validIp(d.ip);
    if (
      payload.Command === "Channel/SetClockSelectId" &&
      !(payload.LcdIndependence > 0)
    )
      throw Error("El grupo nativo 0 puede alterar otras pantallas");
    const result = this.demo
      ? { error_code: 0, demo: true }
      : await this.http(`http://${ip}/post`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          data: payload,
          responseType: "json",
        });
    if (!result || ![0, "0"].includes(result.error_code))
      throw Error("El dispositivo rechazó " + payload.Command);
    return result;
  }
  async cached(key, seconds, fn) {
    const saved = this.cache.get(key);
    if (saved && now() - saved.time < seconds) return saved.value;
    const value = await fn();
    this.cache.set(key, { value, time: now() });
    return value;
  }
  async file(path) {
    const value = await read("media", path.split("/").pop());
    if (!value) throw Error("Archivo no encontrado en el teléfono");
    return value.blob;
  }
  async saveFile(blob, name) {
    if (blob.size > 100 * 1024 ** 2) throw Error("Máximo 100 MB");
    const ext = name.split(".").pop().toLowerCase();
    if (
      ![
        "png",
        "jpg",
        "jpeg",
        "webp",
        "bmp",
        "gif",
        "ics",
        "mp4",
        "mov",
        "mkv",
        "webm",
        "avi",
        "m4v",
      ].includes(ext)
    )
      throw Error("Archivo no compatible");
    const digest = crypto.subtle
      ? await crypto.subtle.digest("SHA-256", await blob.arrayBuffer())
      : crypto.getRandomValues(new Uint8Array(32));
    const key =
      [...new Uint8Array(digest)]
        .map((b) => b.toString(16).padStart(2, "0"))
        .join("")
        .slice(0, 20) +
      "." +
      ext;
    const item = {
      path: "media/" + key,
      name: key,
      original: name,
      size: blob.size,
      blob,
    };
    await write("media", key, item);
    return { path: item.path, name: key, original: name };
  }
  async render(s) {
    const c = canvas(),
      ctx = c.getContext("2d");
    ctx.fillStyle = s.background || "#101b2b";
    ctx.fillRect(0, 0, 128, 128);
    const text = (value, y, size = 18, color = "white", x = 8, width = 112) => {
      ctx.fillStyle = color;
      ctx.font = `600 ${size}px sans-serif`;
      ctx.textBaseline = "top";
      let yy = y;
      for (const paragraph of String(value).split("\n")) {
        let line = "";
        for (const ch of paragraph) {
          if (ctx.measureText(line + ch).width > width && line) {
            if (yy + size > 128) return;
            ctx.fillText(line, x, yy);
            yy += size + 3;
            line = "";
          }
          line += ch;
        }
        if (yy + size <= 128) ctx.fillText(line, x, yy);
        yy += size + 3;
      }
    };
    const color = s.color || "#64e6ca";
    text(s.title || "", 7, 11, color);
    const metric = async () => {
      if (s.sensor_source === "http") {
        const data = await this.cached("sensor:" + s.sensor_key, 5, () =>
          this.http(s.sensor_key, { responseType: "json" }),
        );
        return (s.sensor_field || "")
          .split(".")
          .filter(Boolean)
          .reduce((v, k) => v?.[k], data);
      }
      const found = this.sensors.get(s.sensor_key);
      return found && now() - found.time < +(s.sensor_stale || 300)
        ? (s.sensor_field || "")
            .split(".")
            .filter(Boolean)
            .reduce((v, k) => v?.[k], found.value)
        : null;
    };
    switch (s.kind) {
      case "media": {
        const parsed = await decode(await this.file(s.path), s.path, { ...s });
        return parsed.frames[0];
      }
      case "clock": {
        const zone = s.timezone || "Europe/Madrid";
        text(
          new Intl.DateTimeFormat("es", {
            timeZone: zone,
            hour: "2-digit",
            minute: "2-digit",
            hour12: false,
          }).format(new Date()),
          42,
          30,
        );
        text(
          new Intl.DateTimeFormat("es", {
            timeZone: zone,
            day: "2-digit",
            month: "short",
          }).format(new Date()),
          97,
          14,
          color,
        );
        break;
      }
      case "text":
        text(s.text || "", 32, +s.font_size || 24);
        break;
      case "pc":
      case "pc_native":
        text("Datos del PC\nno disponibles\nen el móvil", 32, 15);
        break;
      case "music":
        text("Usa una fuente\nexterna para la\nmúsica del PC", 32, 15);
        break;
      case "weather": {
        let v = { temperature_2m: 23, relative_humidity_2m: 48 };
        if (!this.demo)
          v = (
            await this.cached(
              "weather:" + s.latitude + "," + s.longitude,
              600,
              () =>
                this.http(
                  `https://api.open-meteo.com/v1/forecast?latitude=${+s.latitude}&longitude=${+s.longitude}&current=temperature_2m,relative_humidity_2m`,
                  { responseType: "json" },
                ),
            )
          ).current;
        text(Math.round(v.temperature_2m) + "°", 38, 40);
        text("Humedad " + v.relative_humidity_2m + "%", 101, 12, color);
        break;
      }
      case "countdown": {
        const seconds = Math.max(
          0,
          Math.ceil((new Date(s.target) - Date.now()) / 1000),
        );
        if (!Number.isFinite(seconds))
          throw Error("Fecha de cuenta atrás inválida");
        text(Math.floor(seconds / 86400) + " días", 34, 24);
        text(
          `${Math.floor(seconds / 3600) % 24}h ${Math.floor(seconds / 60) % 60}m`,
          79,
          20,
          color,
        );
        break;
      }
      case "service": {
        let ok = true;
        try {
          await this.http(s.url);
        } catch {
          ok = false;
        }
        text(ok ? "ONLINE" : "OFFLINE", 45, 22, ok ? color : "#ff8a89");
        break;
      }
      case "rss": {
        const titles = await this.cached("rss:" + s.url, 300, async () => {
          const xml = String(await this.http(s.url, { responseType: "text" }));
          if (xml.length > 2000000 || /<!DOCTYPE|<!ENTITY/i.test(xml))
            throw Error("Fuente RSS inválida");
          const doc = new DOMParser().parseFromString(xml, "text/xml");
          return [...doc.querySelectorAll("item > title, entry > title")]
            .slice(0, 50)
            .map((e) => e.textContent);
        });
        text(
          titles[Math.floor(now() / +(s.news_seconds || 15)) % titles.length] ||
            "Sin noticias",
          30,
          +(s.news_size || 13),
        );
        break;
      }
      case "calendar": {
        const events = await this.cached(
          "ics:" + (s.path || s.url),
          60,
          async () => {
            const raw = s.path
              ? await (await this.file(s.path)).text()
              : String(await this.http(s.url, { responseType: "text" }));
            if (raw.length > 2000000)
              throw Error("Calendario demasiado grande");
            const parsed = new ICAL.Component(ICAL.parse(raw));
            return parsed
              .getAllSubcomponents("vevent")
              .map((e) => new ICAL.Event(e));
          },
        );
        const future = [];
        for (const event of events) {
          const iterator = event.iterator();
          for (let n = 0; n < 500; n++) {
            const date = iterator.next();
            if (!date) break;
            const t = date.toJSDate();
            if (t >= new Date()) {
              future.push({ date: t, summary: event.summary });
              break;
            }
          }
        }
        future.sort((a, b) => a.date - b.date);
        text(future[0]?.summary || "Sin eventos", 30, 15);
        if (future[0])
          text(
            future[0].date.toLocaleString("es", {
              day: "2-digit",
              month: "short",
              hour: "2-digit",
              minute: "2-digit",
            }),
            92,
            11,
            color,
          );
        break;
      }
      case "sensor": {
        const value = await metric();
        text(
          value == null
            ? "N/D"
            : typeof value === "number"
              ? value.toFixed(1)
              : String(value),
          43,
          28,
        );
        text(s.sensor_unit || "", 102, 13, color);
        break;
      }
      case "pomodoro":
        text(this.pomo.phase, 25, 13, color);
        text(
          `${Math.floor(this.pomo.remaining / 60)
            .toString()
            .padStart(2, "0")}:${Math.floor(this.pomo.remaining % 60)
            .toString()
            .padStart(2, "0")}`,
          52,
          29,
        );
        text("Ciclo " + this.pomo.cycle, 101, 12, color);
        break;
      case "custom":
        for (const e of s.elements || []) {
          ctx.save();
          ctx.beginPath();
          ctx.rect(e.x, e.y, e.width, e.height);
          ctx.clip();
          if (e.type === "text") {
            let value = e.text || "";
            value = value
              .replaceAll("{time}", new Date().toLocaleTimeString("es"))
              .replaceAll("{date}", new Date().toLocaleDateString("es"))
              .replace(/\{[^}]+\}/g, "N/D");
            text(value, e.y, e.size || 16, e.color, e.x, e.width);
          } else if (e.type === "image" && e.path)
            ctx.drawImage(
              await image(await this.file(e.path)),
              e.x,
              e.y,
              e.width,
              e.height,
            );
          else if (e.type === "bar") {
            ctx.fillStyle = "#26334b";
            ctx.fillRect(e.x, e.y, e.width, e.height);
            text("N/D", e.y, 8, e.color, e.x, e.width);
          }
          ctx.restore();
        }
        break;
      default:
        text("Sin gestionar", 48, 15);
    }
    return c;
  }
  effective(d, panel) {
    const list = d.playlists?.[panel];
    if (!list?.enabled || !list.items.length) return d.screens[panel];
    const key = d.id + ":" + panel,
      signature = JSON.stringify(list);
    let cursor = this.cursors.get(key);
    if (!cursor || cursor.signature !== signature) {
      cursor = { signature, index: 0, at: 0 };
      this.cursors.set(key, cursor);
    }
    if (cursor.at && now() - cursor.at >= list.items[cursor.index].seconds) {
      cursor.index = (cursor.index + 1) % list.items.length;
      cursor.at = 0;
    }
    return list.items[cursor.index].screen;
  }
  async sendPanel(d, panel, force = false, replacement = null) {
    if (!this.active) throw Error("Vuelve a abrir la app para enviar");
    const key = d.id + ":" + panel,
      s = replacement || this.effective(d, panel);
    if (["empty", "native"].includes(s.kind)) return;
    if (s.kind === "pc_native")
      throw Error("El PC nativo necesita datos de un ordenador");
    const signature = JSON.stringify(s),
      last = this.last.get(key),
      interval =
        s.kind === "media"
          ? +d.interval_minutes * 60
          : Math.max(5, +s.refresh || 30);
    if (!force && last?.signature === signature && now() - last.time < interval)
      return;
    const frames =
      s.kind === "media"
        ? (await decode(await this.file(s.path), s.path, s)).frames
        : [await this.render(s)];
    const picId = (this.lastId = Math.max(Math.floor(now()), this.lastId + 1));
    for (let index = 0; index < frames.length; index++) {
      if (!this.active)
        throw Error(
          "Envío interrumpido al pasar a segundo plano. Reenvía al volver.",
        );
      await this.command(
        d,
        payloadForFrame(
          panel,
          frames.length,
          index,
          picId,
          s.panorama_speed || d.speed,
          jpeg(frames[index], d.quality),
        ),
      );
      await pause(100);
    }
    this.last.set(key, { signature, time: now() });
    const cursor = this.cursors.get(key);
    if (cursor && !cursor.at) cursor.at = now();
    this.log(`${d.name} · pantalla ${panel + 1} enviada`);
  }
  async send(d, panel, force = true) {
    if (d.screens_off) throw Error("Enciende primero las pantallas");
    const failures = [];
    for (const i of panel == null ? [0, 1, 2, 3, 4] : [+panel]) {
      if (this.overrides.has(d.id + ":" + i)) continue;
      try {
        await this.sendPanel(d, i, force);
      } catch (e) {
        failures.push(`${i + 1}: ${e.message}`);
      }
    }
    if (failures.length) throw Error(failures.join("; "));
  }
  async operate(operation, deviceId, args = {}) {
    const d = this.config.devices.find(
      (d) => d.id === (deviceId || this.config.active_device),
    );
    if (!d) throw Error("Dispositivo desconocido");
    if (operation === "send" || operation === "resume") {
      d.suspended = false;
      await this.persist();
      return this.send(d, args.panel);
    }
    if (operation === "health")
      return this.command(d, { Command: "Channel/GetAllConf" });
    if (operation === "command") {
      validateCommand(args.payload);
      const result = await this.command(d, args.payload);
      if(args.payload.Command==='Channel/SetRGBInfo')d.lighting=lightingFromPayload(args.payload);
      if (args.pause) d.suspended = true;
      if (args.payload.Command === "Channel/OnOffScreen") {
        d.screens_off = !args.payload.OnOff;
        this.last.clear();
      }
      await this.persist();
      return result;
    }
    if (operation === "scene") {
      const scene = this.config.scenes.find((s) => s.id === args.scene_id);
      if (!scene) throw Error("Escena no encontrada");
      Object.assign(d, composition(scene));
      this.cursors.clear();
      this.last.clear();
      await this.persist();
      return this.send(d);
    }
    if (operation === "notification") {
      const s = this.effective(d, args.panel);
      if (["empty", "native", "pc_native"].includes(s.kind) || d.screens_off)
        throw Error(
          "El aviso necesita una pantalla activa con contenido recuperable",
        );
      if (this.overrides.has(d.id + ":" + args.panel))
        throw Error("Ya hay un aviso en esa pantalla");
      await this.sendPanel(
        d,
        args.panel,
        true,
        screen("text", { text: args.text, title: args.title || "AVISO" }),
      );
      this.overrides.set(d.id + ":" + args.panel, {
        until: now() + args.seconds,
        deviceId: d.id,
        panel: args.panel,
      });
      if (args.buzzer)
        await this.command(d, {
          Command: "Device/PlayBuzzer",
          ActiveTimeInCycle: 150,
          OffTimeInCycle: 150,
          PlayTotalTime: 600,
        });
      return;
    }
    if (operation === "pomodoro") {
      this.pomodoro(args.operation, { ...args, device_id: d.id });
      return;
    }
    if (operation === "discover") {
      if (!args.seed)
        throw Error("Indica una IP para comprobarla desde el móvil");
      await this.command(
        { ...d, ip: args.seed },
        { Command: "Channel/GetAllConf" },
      );
      return { devices: [{ name: "Times Gate", ip: args.seed }] };
    }
    if (operation === "catalog")
      return this.http(
        `https://app.divoom-gz.com/Channel/Get5LcdInfoV2?DeviceType=LCD&DeviceId=${+d.device_id || 0}`,
        { responseType: "json" },
      );
    throw Error("Acción no compatible");
  }
  pomodoro(operation, args) {
    const p = this.pomo;
    if (operation === "start") {
      for (const k of ["work", "rest", "long_rest", "cycles"]) {
        const value = +(args[k] || this.pomoSettings[k]);
        if (value < 1 || value > (k === "cycles" ? 12 : 180))
          throw Error("Duración inválida");
        this.pomoSettings[k] = value;
      }
      Object.assign(p, {
        phase: "Trabajo",
        running: true,
        cycle: 1,
        total: this.pomoSettings.work * 60,
        remaining: this.pomoSettings.work * 60,
      });
      this.pomoTarget = args;
    } else if (operation === "pause") p.running = false;
    else if (operation === "resume") p.running = p.phase !== "Preparado";
    else if (operation === "reset")
      Object.assign(p, {
        phase: "Preparado",
        running: false,
        cycle: 0,
        remaining: this.pomoSettings.work * 60,
        total: this.pomoSettings.work * 60,
      });
    else if (operation === "skip") {
      const rest = p.phase === "Trabajo";
      p.phase = rest
        ? p.cycle % this.pomoSettings.cycles === 0
          ? "Descanso largo"
          : "Descanso"
        : "Trabajo";
      if (!rest) p.cycle++;
      p.total = p.remaining =
        60 *
        this.pomoSettings[
          rest ? (p.phase === "Descanso largo" ? "long_rest" : "rest") : "work"
        ];
    }
    this.pomoAt = now();
  }
  async tick() {
    if (this.busy || !this.active) return;
    this.task("Actualización", async () => {
      const time = now();
      if (this.pomo.running) {
        this.pomo.remaining = Math.max(
          0,
          this.pomo.remaining - (time - this.pomoAt),
        );
        if (this.pomo.remaining === 0) {
          this.pomodoro("skip", {});
          const d = this.config.devices.find(
            (d) => d.id === this.pomoTarget?.device_id,
          );
          if (d?.enabled && !d.suspended && !d.screens_off)
            try {
              await this.operate("notification", d.id, {
                panel: this.pomoTarget.panel || 0,
                text: this.pomo.phase,
                seconds: 10,
              });
            } catch (e) {
              this.log(e.message);
            }
        }
      }
      this.pomoAt = time;
      for (const [key, o] of this.overrides)
        if (time >= o.until) {
          const d = this.config.devices.find((d) => d.id === o.deviceId);
          try {
            if (d && !d.screens_off) await this.sendPanel(d, o.panel, true);
            this.overrides.delete(key);
          } catch (e) {
            o.until = time + 5;
            this.log(e.message, "error");
          }
        }
      for (const d of this.config.devices) {
        if (!d.enabled || !d.ip) continue;
        const date = new Date(),
          stamp =
            date.toLocaleDateString("en-CA") +
            " " +
            date.toTimeString().slice(0, 5),
          day = (date.getDay() + 6) % 7;
        for (const rule of this.config.schedules.filter(
          (r) =>
            r.device_id === d.id &&
            r.enabled &&
            r.days.includes(day) &&
            r.time === stamp.slice(-5),
        )) {
          if (this.rules.get(rule.id) === stamp) continue;
          this.rules.set(rule.id, stamp);
          try {
            if (rule.action === "scene")
              await this.operate("scene", d.id, { scene_id: rule.value });
            else
              await this.operate("command", d.id, {
                payload:
                  rule.action === "brightness"
                    ? {
                        Command: "Channel/SetBrightness",
                        Brightness: +rule.value,
                      }
                    : {
                        Command: "Channel/OnOffScreen",
                        OnOff: +(rule.action === "on"),
                      },
              });
          } catch (e) {
            this.log(e.message, "error");
          }
        }
        if (d.suspended || d.screens_off) continue;
        for (const r of (this.config.reminders || []).filter(
          (r) => r.device_id === d.id && r.enabled,
        )) {
          if (!this.rules.has(r.id)) this.rules.set(r.id, time);
          if (time - this.rules.get(r.id) >= r.minutes * 60) {
            this.rules.set(r.id, time);
            try {
              await this.operate("notification", d.id, r);
            } catch (e) {
              this.log(e.message);
            }
          }
        }
        for (const r of (this.config.alerts || []).filter(
          (r) => r.device_id === d.id && r.enabled,
        ))
          await this.alert(d, r, time);
        const rotation =
          d.rotation?.filter((id) =>
            this.config.scenes.some((s) => s.id === id),
          ) || [];
        if (rotation.length) {
          const current = this.rotation.get(d.id) || { at: time, index: 0 };
          if (time - current.at >= Math.max(30, d.rotation_seconds)) {
            await this.operate("scene", d.id, {
              scene_id: rotation[current.index % rotation.length],
            });
            current.index++;
            current.at = now();
          }
          this.rotation.set(d.id, current);
        }
        try {
          await this.send(d, null, false);
        } catch (e) {
          this.log(e.message, "error");
        }
      }
      await this.configureMqtt();
    });
  }
  async alert(d, r, time) {
    let value = null;
    if (r.metric === "service") {
      try {
        await this.cached("service:" + r.source, 10, () => this.http(r.source));
        value = 0;
      } catch {
        value = 1;
      }
    } else if (r.metric === "sensor") {
      try {
        if (r.sensor_source === "http") {
          let v = await this.cached("alert:" + r.source, 5, () =>
            this.http(r.source, { responseType: "json" }),
          );
          for (const k of (r.field || "").split(".").filter(Boolean))
            v = v?.[k];
          value = +v;
        } else {
          const s = this.sensors.get(r.source);
          if (s && time - s.time < 300) value = +s.value;
        }
      } catch {}
    }
    if (value == null || !Number.isFinite(value)) return;
    const hit =
      r.operator === "below" ? value < +r.threshold : value > +r.threshold;
    const state = this.alarms.get(r.id) || {
      since: null,
      last: -Infinity,
      fired: false,
    };
    this.alarms.set(r.id, state);
    if (!hit) {
      state.since = null;
      state.fired = false;
      return;
    }
    state.since ??= time;
    if (
      !state.fired &&
      time - state.since >= +(r.hold || 0) &&
      time - state.last >= +(r.cooldown || 300)
    ) {
      try {
        await this.operate("notification", d.id, r);
        state.fired = true;
        state.last = time;
      } catch (e) {
        this.log(e.message);
      }
    }
  }
  async configureMqtt() {
    const c = this.config.integrations.mqtt,
      signature =
        JSON.stringify(c) +
        JSON.stringify([
          this.config.devices.map((d) => ({ id: d.id, name: d.name })),
          this.config.scenes.map((s) => ({ id: s.id, name: s.name })),
          this.config.alerts,
        ]) +
        JSON.stringify(
          allScreens(this.config).filter((s) => s.kind === "sensor"),
        );
    if (signature === this.mqttSignature) return;
    this.mqttSignature = signature;
    if (this.mqtt?.connected) {
      for (const topic of this.discoveryTopics || [])
        this.mqtt.publish(topic, "", { retain: true });
      if (this.availabilityTopic)
        this.mqtt.publish(this.availabilityTopic, "offline", { retain: true });
    }
    this.mqtt?.end();
    this.mqtt = null;
    if (!c.enabled || this.demo) return;
    if (!/^wss?:\/\//.test(c.websocket_url || "")) {
      this.log(
        "En el móvil MQTT necesita la URL WebSocket del broker",
        "warning",
      );
      return;
    }
    const { connect } = await import("mqtt");
    this.mqtt = connect(c.websocket_url, {
      username: c.username || undefined,
      password: c.password || undefined,
      reconnectPeriod: 5000,
      clientId: "keeper_mobile_" + id(),
      queueQoSZero: false,
      will: {
        topic: c.prefix + "/availability",
        payload: "offline",
        qos: 1,
        retain: true,
      },
    });
    this.mqtt.on("connect", () => {
      this.log("MQTT conectado");
      this.discoveryTopics = [];
      this.availabilityTopic = c.prefix + "/availability";
      this.mqtt.publish(c.prefix + "/availability", "online", { retain: true });
      for (const d of this.config.devices)
        for (const scene of [
          { id: "restore", name: "Enviar composición" },
          ...this.config.scenes,
        ]) {
          const uid = "keeper_mobile_" + d.id + "_" + scene.id;
          this.discoveryTopics.push("homeassistant/button/" + uid + "/config");
          const command =
            scene.id === "restore"
              ? { action: "send", device_id: d.id }
              : { action: "scene", device_id: d.id, scene_id: scene.id };
          this.mqtt.publish(
            "homeassistant/button/" + uid + "/config",
            JSON.stringify({
              name: scene.name,
              unique_id: uid,
              command_topic: c.prefix + "/command",
              payload_press: JSON.stringify(command),
              availability_topic: c.prefix + "/availability",
              device: {
                identifiers: ["keeper_mobile_" + d.id],
                name: "Keeper móvil · " + d.name,
              },
            }),
            { retain: true },
          );
        }
      const topics = new Set(
        allScreens(this.config)
          .filter((s) => s.kind === "sensor" && s.sensor_source === "mqtt")
          .map((s) => s.sensor_key),
      );
      for (const r of this.config.alerts || [])
        if (r.metric === "sensor" && r.sensor_source === "mqtt")
          topics.add(r.source);
      topics.add(c.prefix + "/command");
      for (const topic of topics) if (topic) this.mqtt.subscribe(topic);
    });
    this.mqtt.on("message", (topic, payload, packet) => {
      if (payload.length > 16384) return;
      let value = payload.toString();
      try {
        value = JSON.parse(value);
      } catch {}
      if (topic === c.prefix + "/command") {
        if (
          packet.retain ||
          !this.active ||
          !value ||
          typeof value !== "object"
        )
          return;
        try {
          const d = value.device_id || this.config.active_device;
          if (value.action === "send")
            this.task("MQTT", () => this.operate("send", d));
          if (value.action === "scene")
            this.task("MQTT", () =>
              this.operate("scene", d, { scene_id: value.scene_id }),
            );
          if (value.action === "power" && typeof value.on === "boolean")
            this.task("MQTT", () =>
              this.operate("command", d, {
                payload: { Command: "Channel/OnOffScreen", OnOff: +value.on },
              }),
            );
          if (
            value.action === "notice" &&
            typeof value.text === "string" &&
            value.text.length <= 500 &&
            +value.panel >= 1 &&
            +value.panel <= 5 &&
            +value.seconds >= 5 &&
            +value.seconds <= 300
          )
            this.task("MQTT", () =>
              this.operate("notification", d, {
                panel: +value.panel - 1,
                seconds: +value.seconds,
                text: value.text,
                title: value.title,
                buzzer: !!value.buzzer,
              }),
            );
          if (
            value.action === "brightness" &&
            +value.value >= 0 &&
            +value.value <= 100
          )
            this.task("MQTT", () =>
              this.operate("command", d, {
                payload: {
                  Command: "Channel/SetBrightness",
                  Brightness: +value.value,
                },
              }),
            );
        } catch (error) {
          this.log("MQTT: " + error.message, "warning");
        }
      } else {
        if (this.sensors.size >= 200 && !this.sensors.has(topic))
          this.sensors.delete(this.sensors.keys().next().value);
        this.sensors.set(topic, { value, time: now() });
      }
    });
    this.mqtt.on("error", (e) => this.log("MQTT: " + e.message, "warning"));
  }
  async request(path, method, data) {
    const url = new URL("http://local" + path),
      route = url.pathname;
    if (route === "/state")
      return {
        config: copy(this.config),
        revision: String(this.revision),
        events: copy(this.events),
        version: "3.1.0",
        runtime: { pomodoro: copy(this.pomo) },
        capabilities: {
          mode: "mobile",
          demo: this.demo,
          pc: false,
          music: false,
          profiles: false,
          mqtt: true,
          hardware: false,
          continuous: false,
          metrics_label:
            "El móvil no puede leer las métricas del PC. Usa un sensor HTTP o MQTT.",
        },
      };
    if (route === "/config") {
      return this.task("Guardar", async () => {
        if (data.revision !== String(this.revision))
          throw Error("La configuración cambió; recarga antes de guardar");
        validate(data.config);
        for (const a of assets(data.config))
          if (a.path) await this.file(a.path);
        this.config = copy(data.config);
        await this.persist();
        this.last.clear();
        this.cursors.clear();
      });
    }
    if (route === "/upload")
      return this.saveFile(data, url.searchParams.get("name"));
    if (route === "/library")
      return (await entries("media")).map(({ blob, ...item }) => item);
    if (route.startsWith("/media/")) return this.file(route.split("/").pop());
    if (route.startsWith("/jobs/")) {
      if (route.endsWith("/cancel")) {
        this.cancelConversion?.abort();
        return { cancelled: true };
      }
      const job = this.jobs.get(route.split("/").pop());
      if (!job) throw Error("Tarea caducada");
      return copy(job);
    }
    if (route.startsWith("/preview/")) {
      const [, , deviceId, panel] = route.split("/"),
        d = this.config.devices.find((d) => d.id === deviceId);
      return new Promise(async (resolve, reject) => {
        try {
          const c = await this.render(this.effective(d, +panel));
          c.toBlob(resolve, "image/png");
        } catch (e) {
          reject(e);
        }
      });
    }
    if (route === "/action")
      return this.task(data.action, () =>
        this.operate(data.action, data.device_id, data.args),
      );
    if (route === "/panorama")
      return this.task("Panorámica", async () => {
        this.cancelConversion = new AbortController();
        const result = await decode(
          await this.file(data.path),
          data.path,
          { ...data, panorama: true },
          this.cancelConversion.signal,
        );
        const blobs = await encodePanorama(result.frames, result.speed);
        const saved = [];
        for (const blob of blobs)
          saved.push(await this.saveFile(blob, "panorama.gif"));
        return {
          screens: saved.slice(0, 5).map((a) =>
            screen("media", {
              path: a.path,
              fit: "stretch",
              panorama_speed: result.speed,
            }),
          ),
          preview: saved[5].path,
          count: result.frames.length,
          duration: (result.frames.length * result.speed) / 1000,
          animated: result.animated,
        };
      });
    if (route === "/export") {
      const zip = new JSZip(),
        cfg = copy(this.config);
      for (const a of assets(cfg))
        if (a.path) {
          const name = a.path.split("/").pop();
          zip.file("media/" + name, await this.file(a.path));
          a.path = "media/" + name;
        }
      cfg.integrations = defaults().integrations;
      zip.file("config.json", JSON.stringify(cfg));
      return zip.generateAsync({ type: "blob" });
    }
    if (route === "/import")
      return this.task("Importar", async () => {
        if (data.size > 100 * 1024 ** 2) throw Error("Copia demasiado grande");
        const zip = await JSZip.loadAsync(data);
        let total = 0;
        for (const f of Object.values(zip.files)) {
          total += f._data?.uncompressedSize || 0;
          if (total > 250 * 1024 ** 2)
            throw Error("Copia descomprimida demasiado grande");
        }
        const cfg = normalize(
          JSON.parse(await zip.file("config.json").async("string")),
        );
        validate(cfg);
        for (const a of assets(cfg))
          if (a.path) {
            if (!/^media\/[\w.-]+$/.test(a.path) || a.path.includes(".."))
              throw Error("Ruta de copia inválida");
            const f = zip.file(a.path);
            if (!f) throw Error("Falta un archivo");
            a.path = (await this.saveFile(await f.async("blob"), a.path)).path;
          }
        for (const d of cfg.devices) d.enabled = false;
        cfg.integrations = defaults().integrations;
        cfg.startup = false;
        await write("state", "before-import", this.config);
        this.config = cfg;
        this.last.clear();
        this.cursors.clear();
        this.overrides.clear();
        await this.persist();
      });
    throw Error("Ruta no compatible: " + route);
  }
}

import {validateLighting} from './colors.js';
export const id = () =>
  Array.from(crypto.getRandomValues(new Uint8Array(12)), (b) =>
    b.toString(16).padStart(2, "0"),
  ).join("");
export const copy = (value) => structuredClone(value);
export const lists = () =>
  Array.from({ length: 5 }, () => ({ enabled: false, items: [] }));
export const screen = (kind = "empty", extra = {}) => ({
  kind,
  path: "",
  title: "",
  text: "",
  color: "#64e6ca",
  background: "#101b2b",
  fit: "contain",
  refresh: 30,
  timezone: "Europe/Madrid",
  latitude: 40.4168,
  longitude: -3.7038,
  url: "",
  target: "",
  font_size: 24,
  frame_step: 1,
  native_id: 625,
  independence: 0,
  pc_view: "usage",
  pc_disk: "",
  native_pc_mode: "existing",
  ...extra,
});
export const device = () => ({
  id: id(),
  name: "Times Gate",
  ip: "",
  mac: "",
  device_id: 0,
  enabled: false,
  suspended: false,
  screens_off: false,
  quality: 85,
  speed: 100,
  interval_minutes: 60,
  screens: Array.from({ length: 5 }, () => screen()),
  playlists: lists(),
  rotation: [],
  rotation_seconds: 300,
});
export function defaults() {
  const d = device();
  return {
    version: 2,
    language: "en",
    theme: "dark",
    startup: false,
    resend_on_startup: true,
    active_device: d.id,
    devices: [d],
    scenes: [],
    schedules: [],
    alerts: [],
    reminders: [],
    profiles: [],
    integrations: {
      api: { enabled: false, host: "127.0.0.1", port: 8787, token: "" },
      mqtt: {
        enabled: false,
        host: "",
        port: 1883,
        prefix: "keeper",
        username: "",
        password: "",
        tls: false,
      },
      hardware: false,
    },
  };
}
export const kinds = {
  empty: "Unmanaged",
  media: "Image / GIF",
  text: "Text",
  clock: "Clock",
  pc: "PC monitor",
  weather: "Weather",
  countdown: "Countdown",
  service: "Service status",
  calendar: "ICS calendar",
  music: "Music",
  rss: "RSS news",
  custom: "Design",
  pomodoro: "Pomodoro",
  sensor: "Sensor",
  native: "Native unmanaged",
  pc_native: "Experimental native PC",
};
export function normalize(value) {
  const cfg = { ...defaults(), ...copy(value) };
  cfg.integrations = { ...defaults().integrations, ...cfg.integrations };
  for (const key of ["api", "mqtt"])
    cfg.integrations[key] = {
      ...defaults().integrations[key],
      ...cfg.integrations[key],
    };
  cfg.devices = cfg.devices.map((d) => ({
    ...device(),
    ...d,
    playlists: d.playlists || lists(),
    screens: d.screens.map((s) => screen(s.kind, s)),
  }));
  cfg.scenes = cfg.scenes.map((s) => ({
    ...s,
    playlists: s.playlists || lists(),
    screens: s.screens.map((item) => screen(item.kind, item)),
  }));
  return cfg;
}
export const composition = (d) => ({
  screens: copy(d.screens),
  playlists: copy(d.playlists || lists()),
});
export const allScreens = (cfg) =>
  [...cfg.devices, ...cfg.scenes].flatMap((o) => [
    ...o.screens,
    ...(o.playlists || []).flatMap((l) => l.items.map((i) => i.screen)),
  ]);
export const assets = (cfg) =>
  allScreens(cfg).flatMap((s) => [s, ...(s.elements || [])]);
export const metrics = {
  cpu: "CPU %",
  ram: "RAM %",
  gpu: "GPU %",
  disk: "Disk %",
  cpu_temp: "CPU °C",
  gpu_temp: "GPU °C",
  download: "Download B/s",
  upload: "Upload B/s",
};
export function validIp(ip) {
  const parts = String(ip).split(".");
  if (
    parts.length !== 4 ||
    parts.some((p) => !/^\d{1,3}$/.test(p) || +p > 255) ||
    !(
      parts[0] === "10" ||
      (parts[0] === "192" && parts[1] === "168") ||
      (parts[0] === "172" && +parts[1] >= 16 && +parts[1] <= 31)
    )
  )
    throw Error("Enter a private IPv4 address for the Times Gate");
  return parts.map(Number).join(".");
}
export function validate(cfg) {
  if (cfg.version !== 2 || !cfg.devices?.length || cfg.devices.length > 30)
    throw Error("Unsupported configuration");
  const ids = new Set(cfg.devices.map((d) => d.id)),
    scenes = new Set(cfg.scenes.map((s) => s.id));
  if (ids.size !== cfg.devices.length || !ids.has(cfg.active_device))
    throw Error("Invalid device");
  for (const d of cfg.devices) {
    if(d.lighting)validateLighting(d.lighting);
    if (d.ip) validIp(d.ip);
    if (d.screens.length !== 5) throw Error("Five screens are required");
    if (
      !Number.isInteger(+d.quality) ||
      +d.quality < 30 ||
      +d.quality > 100 ||
      !Number.isInteger(+d.speed) ||
      +d.speed < 1 ||
      +d.speed > 60000
    )
      throw Error("Invalid quality or speed");
  }
  for (const owner of [...cfg.devices, ...cfg.scenes])
    if (owner.screens.length !== 5 || owner.playlists?.length !== 5)
      throw Error("Five screens and five playlists are required");
  for (const s of allScreens(cfg)) {
    if (!kinds[s.kind]) throw Error("Unknown content");
    if (
      !(+s.refresh >= 5 && +s.refresh <= 86400) ||
      !(+s.frame_step >= 1 && +s.frame_step <= 100)
    )
      throw Error("Invalid interval");
    if (s.elements?.length > 20) throw Error("Maximum 20 design elements");
  }
  for (const owner of [...cfg.devices, ...cfg.scenes])
    for (const list of owner.playlists || lists()) {
      if (list.items.length > 50 || (list.enabled && !list.items.length))
        throw Error("Playlist empty or too long");
      for (const item of list.items)
        if (
          !(item.seconds >= 5 && item.seconds <= 86400) ||
          ["empty", "native", "pc_native"].includes(item.screen.kind)
        )
          throw Error("Invalid playlist item");
    }
  for (const rule of cfg.schedules)
    if (
      !ids.has(rule.device_id) ||
      !/^([01]\d|2[0-3]):[0-5]\d$/.test(rule.time) ||
      (rule.action === "scene" && !scenes.has(rule.value))
    )
      throw Error("Invalid schedule");
  for (const group of ["alerts", "reminders", "profiles"])
    for (const rule of cfg[group] || []) {
      if (
        !ids.has(rule.device_id) ||
        (group === "profiles" && !scenes.has(rule.scene_id))
      )
        throw Error("Invalid rule target");
      if (
        group !== "profiles" &&
        (!rule.text ||
          !(rule.panel >= 0 && rule.panel <= 4) ||
          !(rule.seconds >= 5 && rule.seconds <= 300))
      )
        throw Error("Invalid alert");
    }
}

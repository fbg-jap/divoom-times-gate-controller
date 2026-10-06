import {validateLighting} from './colors.js';
import {t,lazy} from "./i18n.js";
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
  port: 0,
  local_token: "",
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
export function removeDevice(cfg, id) {
  if (!cfg.devices.some((d) => d.id === id)) return null;
  if (cfg.devices.length <= 1) return t("ui.keep_at_least_one_device");
  cfg.devices = cfg.devices.filter((d) => d.id !== id);
  for (const g of ["schedules", "alerts", "reminders", "profiles"])
    cfg[g] = cfg[g].filter((r) => r.device_id !== id);
  if (cfg.active_device === id) cfg.active_device = cfg.devices[0].id;
  return null;
}
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
      spotify: { enabled: false, client_id: "", refresh_token: "", redirect_uri: "" },
      prtg: { enabled: false, base_url: "", token: "", verify_tls: true },
      timesync: {
        enabled: false,
        source: "ntp",
        servers: ["pool.ntp.org"],
        https_url: "https://www.cloudflare.com/",
        interval_minutes: 60,
        fallback_https: true,
        sync_device: false,
      },
      mail: {
        enabled: false,
        host: "",
        port: 993,
        user: "",
        password: "",
        mailbox: "INBOX",
        show_subject: false,
      },
      notifications: {
        enabled: false,
        panel: 1,
        seconds: 8,
        allow_apps: [],
        deny_apps: [],
        show_body: false,
        per_minute: 6,
        teams: {
          enabled: false,
          patterns: ["microsoft teams", "msteams", "teams-for-linux", "teams.microsoft.com", "teams.cloud.microsoft", "teams.live.com"],
          show_preview: false,
          chats: true,
          mentions: true,
          calls: true,
          panel: 0,
          seconds: 0,
          call_seconds: 20,
          buzzer_on_call: false,
        },
      },
      hardware: false,
    },
  };
}
export const kinds = lazy({
  empty: "model.unmanaged",
  media: "model.image_gif",
  text: "model.text",
  clock: "model.clock",
  pc: "model.pc_monitor",
  weather: "model.weather",
  countdown: "model.countdown",
  service: "model.service_status",
  calendar: "model.ics_calendar",
  music: "model.music",
  rss: "model.rss_news",
  custom: "model.design",
  pomodoro: "Pomodoro",
  sensor: "Sensor",
  prtg: "PRTG",
  mail: "ui.mail_unread",
  spotify: "Spotify",
  native: "model.native_unmanaged",
  pc_native: "model.experimental_native_pc",
});
export function normalize(value) {
  const cfg = { ...defaults(), ...copy(value) };
  cfg.integrations = { ...defaults().integrations, ...cfg.integrations };
  for (const key of ["api", "mqtt", "spotify", "prtg", "mail", "notifications", "timesync"])
    cfg.integrations[key] = {
      ...defaults().integrations[key],
      ...cfg.integrations[key],
    };
  cfg.integrations.notifications.teams = {
    ...defaults().integrations.notifications.teams,
    ...cfg.integrations.notifications.teams,
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
export const metrics = lazy({
  cpu: "CPU %",
  ram: "RAM %",
  gpu: "GPU %",
  disk: "model.disk",
  cpu_temp: "CPU °C",
  gpu_temp: "GPU °C",
  download: "model.download_b_s",
  upload: "model.upload_b_s",
});
// Hardware 400 serves POST /post on port 80; hardware 402 serves POST /divoom_api on port 9000.
export const ENDPOINTS = [
  [80, "/post"],
  [9000, "/divoom_api"],
];
export function endpointCandidates(port = 0) {
  port = +port || 0;
  if (!port) return ENDPOINTS.map((e) => [...e]);
  return [[port, port === 9000 ? "/divoom_api" : "/post"]];
}
export const replyOk = (body) =>
  !!body &&
  typeof body === "object" &&
  [0, "0"].includes("error_code" in body ? body.error_code : body.ReturnCode);
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
    throw Error(t("model.enter_a_private_ipv4_address"));
  return parts.map(Number).join(".");
}
export function validate(cfg) {
  if (cfg.version !== 2 || !cfg.devices?.length || cfg.devices.length > 30)
    throw Error(t("model.unsupported_configuration"));
  const ids = new Set(cfg.devices.map((d) => d.id)),
    scenes = new Set(cfg.scenes.map((s) => s.id));
  if (ids.size !== cfg.devices.length || !ids.has(cfg.active_device))
    throw Error(t("model.invalid_device"));
  for (const d of cfg.devices) {
    if(d.lighting)validateLighting(d.lighting);
    if (d.ip) validIp(d.ip);
    if (!Number.isInteger(+d.port) || +d.port < 0 || +d.port > 65535)
      throw Error(t("model.port_range"));
    if (d.screens.length !== 5) throw Error(t("model.five_screens"));
    if (
      !Number.isInteger(+d.quality) ||
      +d.quality < 30 ||
      +d.quality > 100 ||
      !Number.isInteger(+d.speed) ||
      +d.speed < 1 ||
      +d.speed > 60000
    )
      throw Error(t("model.invalid_quality_or_speed"));
  }
  for (const owner of [...cfg.devices, ...cfg.scenes])
    if (owner.screens.length !== 5 || owner.playlists?.length !== 5)
      throw Error(t("model.five_screens_and_five_playlists"));
  for (const s of allScreens(cfg)) {
    if (!kinds[s.kind]) throw Error(t("model.unknown_content"));
    if (
      !(+s.refresh >= 5 && +s.refresh <= 86400) ||
      !(+s.frame_step >= 1 && +s.frame_step <= 100)
    )
      throw Error(t("model.invalid_interval"));
    if (s.elements?.length > 20) throw Error(t("model.maximum_20_design_elements"));
  }
  for (const owner of [...cfg.devices, ...cfg.scenes])
    for (const list of owner.playlists || lists()) {
      if (list.items.length > 50 || (list.enabled && !list.items.length))
        throw Error(t("model.playlist_empty_or_too_long"));
      for (const item of list.items)
        if (
          !(item.seconds >= 5 && item.seconds <= 86400) ||
          ["empty", "native", "pc_native"].includes(item.screen.kind)
        )
          throw Error(t("model.invalid_playlist_item"));
    }
  for (const rule of cfg.schedules)
    if (
      !ids.has(rule.device_id) ||
      !/^([01]\d|2[0-3]):[0-5]\d$/.test(rule.time) ||
      (rule.action === "scene" && !scenes.has(rule.value))
    )
      throw Error(t("model.invalid_schedule"));
  for (const group of ["alerts", "reminders", "profiles"])
    for (const rule of cfg[group] || []) {
      if (
        !ids.has(rule.device_id) ||
        (group === "profiles" && !scenes.has(rule.scene_id))
      )
        throw Error(t("model.invalid_rule_target"));
      if (
        group !== "profiles" &&
        (!rule.text ||
          !(rule.panel >= 0 && rule.panel <= 4) ||
          !(rule.seconds >= 5 && rule.seconds <= 300))
      )
        throw Error(t("model.invalid_alert"));
    }
}

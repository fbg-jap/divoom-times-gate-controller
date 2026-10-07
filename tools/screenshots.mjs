#!/usr/bin/env node
// Retakes docs/screenshots/*.png from the web UI: starts the app in demo mode (fake data, no device, temporary
// config folder, free port), drives a system Chromium-family browser with playwright-core and saves the pages.
//
//   cd web && npm ci && node ../tools/screenshots.mjs [name ...]      (names = file names without .png)
//
// App command: KEEPER_SCREENSHOT_APP (default `.venv-linux/bin/python app.py` if present, else `python3 app.py`).
// Browser: KEEPER_SCREENSHOT_BROWSER, else brave-browser, google-chrome(-stable), chromium(-browser), microsoft-edge.
import { spawn } from "node:child_process";
import fs from "node:fs";
import net from "node:net";
import os from "node:os";
import path from "node:path";
import zlib from "node:zlib";
import { fileURLToPath } from "node:url";
import { createRequire } from "node:module";
import { findBrowser, parseLaunchUrl } from "./screenshot_helpers.mjs";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
// playwright-core is a devDependency of web/ (the script lives outside it), so resolve it from there.
const { chromium } = createRequire(path.join(root, "web", "package.json"))("playwright-core");
const outDir = path.join(root, "docs", "screenshots");
const DESKTOP = { width: 1440, height: 940 };
const MOBILE = { width: 375, height: 812 };

// A colourful 640x128 PNG (no external file needed) for the panorama page.
function demoPanorama(width = 640, height = 128) {
  const raw = Buffer.alloc((width * 3 + 1) * height);
  for (let y = 0; y < height; y++)
    for (let x = 0; x < width; x++) {
      const at = y * (width * 3 + 1) + 1 + x * 3;
      const stripe = Math.floor(x / 64) % 2 ? 0.8 : 1;
      raw[at] = Math.round((40 + 200 * (x / width)) * stripe);
      raw[at + 1] = Math.round((230 - 150 * (y / height)) * stripe);
      raw[at + 2] = Math.round((255 - 180 * (x / width)) * stripe);
    }
  const chunk = (type, data) => {
    const head = Buffer.alloc(8), tail = Buffer.alloc(4);
    head.writeUInt32BE(data.length);
    head.write(type, 4, "latin1");
    tail.writeUInt32BE(zlib.crc32(Buffer.concat([head.subarray(4), data])));
    return Buffer.concat([head, data, tail]);
  };
  const header = Buffer.alloc(13);
  header.writeUInt32BE(width);
  header.writeUInt32BE(height, 4);
  header.set([8, 2, 0, 0, 0], 8);
  return Buffer.concat([Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]), chunk("IHDR", header), chunk("IDAT", zlib.deflateSync(raw)), chunk("IEND", Buffer.alloc(0))]);
}

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

function freePort() {
  return new Promise((resolve, reject) => {
    const server = net.createServer().unref().on("error", reject);
    server.listen(0, "127.0.0.1", () => {
      const { port } = server.address();
      server.close(() => resolve(port));
    });
  });
}

async function startApp(configDir, port) {
  const venv = path.join(root, ".venv-linux", "bin", "python");
  const command = (process.env.KEEPER_SCREENSHOT_APP || `${fs.existsSync(venv) ? venv : "python3"} app.py`).split(" ");
  const urlFile = path.join(configDir, "launch-url.txt");
  const env = { ...process.env, KEEPER_ALLOW_PIPED_LAUNCH_URL: "1", KEEPER_LAUNCH_URL_FILE: urlFile };
  const args = [...command.slice(1), "--demo", "--minimized", "--config-dir", configDir, "--port", String(port), "--print-launch-url"];
  const proc = spawn(command[0], args, { cwd: root, env, stdio: ["ignore", "pipe", "pipe"] });
  let output = "";
  for (const stream of [proc.stdout, proc.stderr]) stream.on("data", (chunk) => (output += chunk));
  for (let i = 0; i < 300; i++) {
    if (proc.exitCode !== null) break;
    let found = null;
    try { found = parseLaunchUrl(fs.readFileSync(urlFile, "utf8")); } catch {}
    found ||= parseLaunchUrl(output);
    if (found && found[0] === port) {
      try {
        if ((await fetch(`http://127.0.0.1:${port}/healthz`)).ok) return { proc, url: `http://127.0.0.1:${port}/#launch=${found[1]}` };
      } catch {}
    }
    await sleep(200);
  }
  proc.kill();
  throw new Error(`the app did not start\n${output.slice(-2000)}`);
}

// Demo content, applied through the app's own config API (the configuration lives in the temporary folder).
const BASE = (cfg) => {
  const mk = (kind, extra) => ({ kind, path: "", title: "", text: "", color: "#64e6ca", background: "#101b2b", fit: "contain", refresh: 30,
    timezone: "Europe/London", latitude: 51.5072, longitude: -0.1276, url: "", target: "", font_size: 24, frame_step: 1, native_id: 625,
    independence: 0, pc_view: "usage", pc_disk: "", native_pc_mode: "existing", ...extra });
  const screens = [mk("clock", { title: "Clock" }), mk("pc", { title: "PC monitor", pc_view: "usage" }),
    mk("text", { title: "Notice", text: "Hello!\nDemo", font_size: 22, color: "#ffc879" }),
    mk("weather", { title: "Weather" }), mk("pc", { title: "Network", pc_view: "network", color: "#5295ff" })];
  const item = (id, seconds, screen) => ({ id, seconds, screen });
  const device = cfg.devices[0];
  device.name = "Times Gate";
  device.screens = screens;
  device.playlists = [0, 1, 2, 3, 4].map((n) => (n === 2
    ? { enabled: true, items: [item("a1", 15, screens[2]), item("a2", 20, mk("clock", { title: "Clock", timezone: "Asia/Tokyo" })),
        item("a3", 30, mk("weather", { title: "Weather" }))] }
    : { enabled: false, items: [] }));
  const scene = (id, name, shown) => ({ id, name, screens: shown, playlists: [0, 1, 2, 3, 4].map(() => ({ enabled: false, items: [] })) });
  cfg.scenes = [scene("s1", "Work desk", screens), scene("s2", "Evening", [screens[0], screens[3], screens[2], screens[0], screens[3]]),
    scene("s3", "Monitoring", [screens[1], screens[4], screens[1], screens[4], screens[1]])];
  device.rotation = ["s1", "s3"];
  device.rotation_seconds = 120;
  const id = device.id;
  cfg.schedules = [{ id: "r1", name: "Dim in the evening", device_id: id, enabled: true, time: "22:00", days: [0, 1, 2, 3, 4], action: "brightness", value: 25 },
    { id: "r2", name: "Evening scene", device_id: id, enabled: true, time: "19:30", days: [0, 1, 2, 3, 4, 5, 6], action: "scene", value: "s2" }];
  cfg.reminders = [{ id: "r3", name: "Stretch", device_id: id, enabled: true, panel: 2, seconds: 15, text: "Stand up and stretch", buzzer: false, minutes: 45 }];
  cfg.alerts = [{ id: "r4", name: "CPU above 90%", device_id: id, enabled: true, panel: 1, seconds: 20, text: "CPU is very high", buzzer: true,
    metric: "cpu", operator: "above", threshold: 90, hold: 10, cooldown: 300, source: "", sensor_source: "mqtt", field: "" }];
  cfg.profiles = [{ id: "r5", name: "Video call", device_id: id, enabled: true, trigger: "process", process: "zoom", scene_id: "s2" }];
};
const PC_VIEWS = (cfg) => {
  const views = ["usage", "history", "network", "temperature", "storage"];
  cfg.devices[0].screens = views.map((pc_view, i) => ({ ...cfg.devices[0].screens[i], kind: "pc", title: "", pc_view }));
  cfg.devices[0].playlists.forEach((list) => (list.enabled = false));
};

/** Applies mutate(cfg) to the stored configuration with the app's API, then reloads the page (still logged in). */
async function seed(page, mutate) {
  await page.evaluate(async (source) => {
    const headers = { Authorization: "Bearer " + sessionStorage.getItem("keeper-token"), "Content-Type": "application/json" };
    const state = await (await fetch("/api/state", { headers })).json();
    (0, eval)(`(${source})`)(state.config);
    const response = await fetch("/api/config", { method: "PUT", headers, body: JSON.stringify({ config: state.config, revision: state.revision }) });
    if (!response.ok) throw new Error("seeding the demo configuration failed: " + (await response.text()));
  }, mutate.toString());
  await page.reload();
  await page.waitForSelector("nav button");
}

const nav = (page, name) => page.locator("nav button", { hasText: new RegExp(`^${name}$`) }).click();
const card = (page, title) => page.locator("section.card", { has: page.locator("h2", { hasText: new RegExp(`^${title}$`) }) });
const settle = async (page, ms = 4000) => { await page.waitForLoadState("networkidle"); await sleep(ms); };
const panel = (page, n) => page.locator(".panels > button").nth(n - 1).click();

// name, viewport, and a function that drives the logged-in page and returns the element to capture (default: the page).
const SHOTS = [
  ["screens", DESKTOP, async (page) => { await nav(page, "Screens"); await settle(page); }],
  ["scenes", DESKTOP, async (page) => { await nav(page, "Scenes"); await settle(page, 500); }],
  ["automations", DESKTOP, async (page) => {
    await nav(page, "Automations");
    await card(page, "Schedules").locator("button", { hasText: "Edit" }).first().click();
    await settle(page, 500);
    await page.evaluate(() => document.querySelector("main").scrollIntoView());
  }],
  ["integrations", DESKTOP, async (page) => { await nav(page, "Integrations"); await settle(page, 500); }],
  ["pc-monitor", DESKTOP, async (page) => { await nav(page, "Screens"); await panel(page, 2); await settle(page); }],
  ["playlist", DESKTOP, async (page) => {
    await nav(page, "Screens");
    await panel(page, 3);
    await card(page, "Playlist").locator("button", { hasText: "Edit" }).nth(1).click();
    await settle(page, 1500);
    return card(page, "Playlist");
  }],
  ["designer", DESKTOP, async (page) => {
    await nav(page, "Screens");
    await panel(page, 3);
    await page.locator("section.card select").first().selectOption("custom");
    const input = (label) => page.locator("label.field", { hasText: new RegExp(`^${label}$`) }).locator("input");
    await page.getByRole("button", { name: "Add text" }).click();
    await page.locator("textarea").first().fill("CPU {cpu}%");
    await input("Y").fill("30");
    await page.getByRole("button", { name: "Add bar" }).click();
    await input("Y").fill("72");
    await page.locator(".designer").first().evaluate((node) => node.scrollIntoView());
    await settle(page, 500);
    return card(page, "Screen 3");
  }],
  ["panorama-video", DESKTOP, async (page) => {
    await nav(page, "Panorama");
    const chooser = page.waitForEvent("filechooser");
    await page.getByRole("button", { name: "Choose image, GIF or video" }).click();
    await (await chooser).setFiles({ name: "demo-panorama.png", mimeType: "image/png", buffer: demoPanorama() });
    await settle(page, 2500);
  }],
  ["rgb-desktop", DESKTOP, async (page) => {
    await nav(page, "RGB lighting");
    await page.getByRole("button", { name: "Neon" }).click();
    await settle(page, 500);
  }],
  ["rgb-web", DESKTOP, async (page) => { await nav(page, "RGB lighting"); await settle(page, 500); return page.locator("main"); }],
  ["color-picker", DESKTOP, async (page) => {
    await nav(page, "RGB lighting");
    await page.locator(".color-choice").first().click();
    await settle(page, 500);
    return page.locator(".color-dialog");
  }],
  ["color-mobile", MOBILE, async (page) => { await nav(page, "RGB lighting"); await page.locator(".color-choice").first().click(); await settle(page, 500); }],
  ["pc-views", DESKTOP, async (page) => { await seed(page, PC_VIEWS); await nav(page, "Screens"); await settle(page); return page.locator(".panels"); }],
];

async function main() {
  const wanted = process.argv.slice(2);
  const shots = SHOTS.filter(([name]) => !wanted.length || wanted.includes(name));
  if (wanted.length && shots.length !== wanted.length) throw new Error("unknown screenshot name; known: " + SHOTS.map(([n]) => n).join(", "));
  const executablePath = findBrowser();
  if (!executablePath) throw new Error("no Chromium-family browser found; install brave-browser, google-chrome, chromium or microsoft-edge, or set KEEPER_SCREENSHOT_BROWSER");
  const configDir = fs.mkdtempSync(path.join(os.tmpdir(), "keeper-shots-"));
  const app = await startApp(configDir, await freePort());
  const browser = await chromium.launch({ executablePath, headless: true });
  fs.mkdirSync(outDir, { recursive: true });
  try {
    let session = null; // sign in once per viewport; the launch code is single use, so later contexts reuse the token
    for (const [name, viewport, drive] of shots) {
      const context = await browser.newContext({ viewport, locale: "en-US", colorScheme: "dark", deviceScaleFactor: 1 });
      if (session) await context.addInitScript((token) => sessionStorage.setItem("keeper-token", token), session);
      const page = await context.newPage();
      await page.goto(session ? app.url.split("#")[0] : app.url);
      await page.waitForSelector("nav button");
      session ||= await page.evaluate(() => sessionStorage.getItem("keeper-token"));
      await seed(page, BASE);
      const target = (await drive(page)) || page;
      await target.screenshot({ path: path.join(outDir, name + ".png") });
      console.log("saved docs/screenshots/" + name + ".png");
      await context.close();
    }
  } finally {
    await browser.close();
    app.proc.kill();
    fs.rmSync(configDir, { recursive: true, force: true });
  }
}
main().catch((error) => { console.error("screenshots failed: " + error.message); process.exit(1); });

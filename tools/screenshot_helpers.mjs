// Pure helpers for tools/screenshots.mjs (kept apart so they can be unit tested without a browser).
import fs from "node:fs";
import path from "node:path";

export const BROWSERS = ["brave-browser", "google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "microsoft-edge"];

/** Path of the browser to drive: KEEPER_SCREENSHOT_BROWSER (as given), else the first known browser on PATH, else null. */
export function findBrowser(env = process.env, names = BROWSERS) {
  if (env.KEEPER_SCREENSHOT_BROWSER) return env.KEEPER_SCREENSHOT_BROWSER;
  for (const dir of (env.PATH || "").split(path.delimiter).filter(Boolean))
    for (const name of names) {
      const file = path.join(dir, name);
      try {
        fs.accessSync(file, fs.constants.X_OK);
        if (fs.statSync(file).isFile()) return file;
      } catch {}
    }
  return null;
}

/** [port, code] from a printed launch URL (http://127.0.0.1:PORT/#launch=CODE), else null. */
export function parseLaunchUrl(text) {
  const match = /http:\/\/127\.0\.0\.1:(\d+)\/#launch=(\S+)/.exec(text || "");
  return match ? [Number(match[1]), match[2]] : null;
}

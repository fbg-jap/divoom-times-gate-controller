import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { findBrowser, parseLaunchUrl } from "../../tools/screenshot_helpers.mjs";

function fakeBin(names) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "keeper-bin-"));
  for (const name of names) fs.writeFileSync(path.join(dir, name), "#!/bin/sh\n", { mode: 0o755 });
  return dir;
}

test("findBrowser prefers the environment override", () => {
  assert.equal(findBrowser({ KEEPER_SCREENSHOT_BROWSER: "/x/browser", PATH: fakeBin(["chromium"]) }), "/x/browser");
});

test("findBrowser takes the first known browser on PATH in list order", () => {
  const dir = fakeBin(["chromium", "google-chrome", "unrelated"]);
  assert.equal(findBrowser({ PATH: dir }), path.join(dir, "google-chrome"));
});

test("findBrowser returns null when nothing is installed", () => {
  assert.equal(findBrowser({ PATH: fakeBin(["unrelated"]) }), null);
  assert.equal(findBrowser({}), null);
});

test("parseLaunchUrl reads the port and code", () => {
  assert.deepEqual(parseLaunchUrl("opening http://127.0.0.1:4321/#launch=abc_DEF-1 now"), [4321, "abc_DEF-1"]);
  assert.equal(parseLaunchUrl("nothing here"), null);
});

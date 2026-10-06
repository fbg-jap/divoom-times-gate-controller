import test from "node:test";
import assert from "node:assert/strict";
import { defaults, normalize } from "../src/model.js";

test("timesync defaults to off with NTP and an https fallback", () => {
  const t = defaults().integrations.timesync;
  assert.equal(t.enabled, false);
  assert.equal(t.source, "ntp");
  assert.deepEqual(t.servers, ["pool.ntp.org"]);
  assert.equal(t.interval_minutes, 60);
  assert.equal(t.fallback_https, true);
  assert.equal(t.sync_device, false);
});

test("normalize fills timesync for old configs and keeps saved values", () => {
  const old = defaults();
  delete old.integrations.timesync;
  assert.equal(normalize(old).integrations.timesync.https_url, "https://www.cloudflare.com/");
  old.integrations.timesync = { enabled: true, servers: ["time.example.org"] };
  const t = normalize(old).integrations.timesync;
  assert.equal(t.enabled, true);
  assert.deepEqual(t.servers, ["time.example.org"]);
  assert.equal(t.interval_minutes, 60);
});

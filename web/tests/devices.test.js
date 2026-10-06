import test from "node:test";
import assert from "node:assert/strict";
import { defaults, device, removeDevice } from "../src/model.js";

function twoDevices() {
  const cfg = defaults();
  const a = cfg.devices[0];
  const b = device();
  cfg.devices.push(b);
  for (const g of ["schedules", "alerts", "reminders", "profiles"])
    cfg[g] = [{ device_id: a.id }, { device_id: b.id }];
  return { cfg, a, b };
}

test("removeDevice refuses the last device", () => {
  const cfg = defaults();
  assert.ok(removeDevice(cfg, cfg.devices[0].id));
  assert.equal(cfg.devices.length, 1);
});

test("removeDevice reassigns the active device", () => {
  const { cfg, a, b } = twoDevices();
  cfg.active_device = b.id;
  assert.equal(removeDevice(cfg, b.id), null);
  assert.deepEqual(cfg.devices.map((d) => d.id), [a.id]);
  assert.equal(cfg.active_device, a.id);
});

test("removeDevice keeps the active device when another is removed", () => {
  const { cfg, a, b } = twoDevices();
  cfg.active_device = a.id;
  removeDevice(cfg, b.id);
  assert.equal(cfg.active_device, a.id);
});

test("removeDevice prunes dependent rules", () => {
  const { cfg, a, b } = twoDevices();
  removeDevice(cfg, a.id);
  for (const g of ["schedules", "alerts", "reminders", "profiles"])
    assert.deepEqual(cfg[g], [{ device_id: b.id }]);
});

test("removeDevice ignores unknown ids", () => {
  const { cfg } = twoDevices();
  assert.equal(removeDevice(cfg, "nope"), null);
  assert.equal(cfg.devices.length, 2);
  assert.equal(cfg.schedules.length, 2);
});

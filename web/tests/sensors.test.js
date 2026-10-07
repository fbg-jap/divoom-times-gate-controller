import test from "node:test";
import assert from "node:assert/strict";
import { sensorUnit, sensorText, sensorGroups, listenerStatus } from "../src/model.js";
import { en, es, t, setLanguage } from "../src/i18n.js";

test.afterEach(() => setLanguage("en"));

const sensors = [
  { id: "/nvme/temperature/0", name: "Composite", type: "Temperature", value: 41.5 },
  { id: "/cpu/power/0", name: "Package", type: "Power", value: 12.3 },
  { id: "/coretemp/temperature/0", name: "Package id 0", type: "Temperature", value: 54 },
  { id: "/x/other/0", name: "Mystery", type: "Weird", value: null },
];

test("units follow the sensor type and fall back to none", () => {
  assert.equal(sensorUnit("Temperature"), "°C");
  assert.equal(sensorUnit("Power"), "W");
  assert.equal(sensorUnit("Voltage"), "V");
  assert.equal(sensorUnit("Fan"), "RPM");
  assert.equal(sensorUnit("Load"), "%");
  assert.equal(sensorUnit("Weird"), "");
  assert.equal(sensorUnit(undefined), "");
});

test("option text is name, value and unit; no value gives the name only", () => {
  assert.equal(sensorText(sensors[0]), "Composite — 41.5 °C");
  assert.equal(sensorText(sensors[3]), "Mystery");
  assert.equal(sensorText({ id: "/a", name: "", type: "Weird", value: 3 }), "/a — 3");
});

test("sensors are grouped by type in alphabetical order, keeping their own order", () => {
  const groups = sensorGroups(sensors, "/coretemp/temperature/0", "(missing) {0}");
  assert.deepEqual(groups.map((g) => g.type), ["Power", "Temperature", "Weird"]);
  assert.deepEqual(groups[1].items.map((i) => i.id), ["/nvme/temperature/0", "/coretemp/temperature/0"]);
});

test("a saved key that is no longer listed stays selectable as (missing)", () => {
  const groups = sensorGroups(sensors, "/gone/temperature/9", "(missing) {0}");
  assert.deepEqual(groups[0], { type: "", items: [{ id: "/gone/temperature/9", text: "(missing) /gone/temperature/9" }] });
  assert.equal(sensorGroups([], "", "(missing) {0}").length, 0);
  assert.equal(sensorGroups(undefined, "/a", "(missing) {0}").length, 1);
});

test("listener status is parsed from the server text", () => {
  assert.deepEqual(listenerStatus("Running"), { state: "running", reason: "" });
  assert.deepEqual(listenerStatus("Starting"), { state: "starting", reason: "" });
  assert.deepEqual(listenerStatus("Disabled"), { state: "disabled", reason: "" });
  assert.deepEqual(listenerStatus(undefined), { state: "disabled", reason: "" });
  assert.deepEqual(listenerStatus("Unavailable (no session D-Bus: OSError)"), { state: "unavailable", reason: "no session D-Bus: OSError" });
});

test("the new sensor and notification texts exist in both languages", () => {
  for (const key of ["notif_running", "notif_starting", "notif_disabled", "notif_unavailable", "notif_test", "notif_test_sent",
    "teams_alone_hint", "sensor_choose", "sensor_missing", "sensor_none", "sensor", "mqtt_disabled_hint"]) {
    assert.ok(en["ui." + key] && es["ui." + key], key);
  }
  setLanguage("es");
  assert.match(t("ui.notif_unavailable", ["x"]), /no disponible \(x\)/);
});

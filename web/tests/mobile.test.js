import test from "node:test";
import assert from "node:assert/strict";
import {
  MobileEngine,
  payloadForFrame,
  validateCommand,
} from "../src/mobile.js";
import {
  defaults,
  screen,
  composition,
  validate,
  validIp,
  endpointCandidates,
  replyOk,
  normalize,
} from "../src/model.js";

test("older portable configurations receive complete independent defaults", () => {
  const cfg = defaults();
  delete cfg.devices[0].playlists;
  cfg.devices[0].screens = [
    { kind: "text", text: "Original" },
    ...Array.from({ length: 4 }, () => ({ kind: "empty" })),
  ];
  cfg.integrations = { mqtt: { enabled: false } };
  const upgraded = normalize(cfg);
  validate(upgraded);
  assert.equal(upgraded.devices[0].screens[0].text, "Original");
  assert.equal(upgraded.integrations.mqtt.prefix, "keeper");
  assert.equal(upgraded.devices[0].playlists.length, 5);
  upgraded.devices[0].screens[0].text = "Changed";
  assert.equal(cfg.devices[0].screens[0].text, "Original");
});
test("mobile native controls reject invalid values and unsafe group zero", () => {
  validateCommand({ Command: "Channel/SetBrightness", Brightness: 50 });
  for (const Brightness of [-1, 101, NaN, 0.5, "20"])
    assert.throws(() =>
      validateCommand({ Command: "Channel/SetBrightness", Brightness }),
    );
  assert.throws(() =>
    validateCommand({
      Command: "Channel/SetClockSelectId",
      ClockId: 625,
      LcdIndependence: 0,
      LcdIndex: 1,
    }),
  );
  assert.throws(() => validateCommand({ Command: "Device/Unknown" }));
});

test("mobile transport retains the original device protocol and one target screen", () => {
  const p = payloadForFrame(3, 8, 7, 1700000000, 200, "jpeg-base64");
  assert.deepEqual(p, {
    Command: "Draw/SendHttpGif",
    LcdArray: [0, 0, 0, 1, 0],
    PicNum: 8,
    PicOffset: 7,
    PicID: 1700000000,
    PicSpeed: 200,
    PicWidth: 128,
    PicData: "jpeg-base64",
  });
});
test("native transport uses direct LAN HTTP and treats device rejection as failure", async () => {
  const engine = new MobileEngine(),
    calls = [];
  engine.http = async (url, options) => {
    calls.push({ url, options });
    return { error_code: 0 };
  };
  await engine.command(
    { ip: "192.168.1.116" },
    { Command: "Channel/GetAllConf" },
  );
  assert.equal(calls[0].url, "http://192.168.1.116/post");
  assert.equal(calls[0].options.method, "POST");
  assert.equal(calls[0].options.data.Command, "Channel/GetAllConf");
  engine.http = async () => ({ error_code: 1 });
  await assert.rejects(
    engine.command({ ip: "192.168.1.116" }, { Command: "Channel/GetAllConf" }),
    /rejected/,
  );
  await assert.rejects(
    engine.command(
      { ip: "192.168.1.116" },
      { Command: "Channel/SetClockSelectId", LcdIndependence: 0 },
    ),
    /Native group 0/,
  );
});
test("invalid targets and corrupted imported lists are rejected", () => {
  for (const ip of [
    "https://example.com",
    "1.2.3.4",
    "192.168.999.1",
    "localhost",
    "127.0.0.1",
  ])
    assert.throws(() => validIp(ip));
  const cfg = defaults();
  validate(cfg);
  cfg.devices[0].playlists[0].enabled = true;
  assert.throws(() => validate(cfg), /Playlist/);
});
test("serial mobile tasks keep order and failures visible without blocking later work", async () => {
  const engine = new MobileEngine(true),
    order = [];
  const a = engine.task("first", async () => {
    await new Promise((r) => setTimeout(r, 10));
    order.push(1);
  });
  const b = engine.task("bad", async () => {
    throw Error("test error");
  });
  const c = engine.task("last", async () => order.push(3));
  await engine.serial;
  assert.deepEqual(order, [1, 3]);
  assert.equal(engine.jobs.get(a.job).status, "done");
  assert.equal(engine.jobs.get(b.job).status, "error");
  assert.equal(engine.jobs.get(c.job).status, "done");
});
test("playlist waits until an upload has finished before advancing", () => {
  const engine = new MobileEngine(true),
    cfg = defaults(),
    d = cfg.devices[0];
  d.playlists[0] = {
    enabled: true,
    items: [
      { id: "a", seconds: 10, screen: screen("text", { text: "A" }) },
      { id: "b", seconds: 20, screen: screen("text", { text: "B" }) },
    ],
  };
  assert.equal(engine.effective(d, 0).text, "A");
  const cursor = engine.cursors.get(d.id + ":0");
  assert.equal(cursor.at, 0);
  assert.equal(engine.effective(d, 0).text, "A");
  cursor.at = Date.now() / 1000 - 11;
  assert.equal(engine.effective(d, 0).text, "B");
  assert.equal(cursor.at, 0);
  assert.equal(engine.effective(d, 0).text, "B");
});
test("scene snapshots remain independent of later screen edits", () => {
  const d = defaults().devices[0];
  d.screens[0] = screen("text", { text: "Saved" });
  const scene = composition(d);
  d.screens[0].text = "Changed";
  assert.equal(scene.screens[0].text, "Saved");
});
test("Pomodoro phases, pause and long break keep selected durations", () => {
  const engine = new MobileEngine(true);
  engine.pomodoro("start", {
    work: 30,
    rest: 6,
    long_rest: 18,
    cycles: 2,
    device_id: "x",
  });
  assert.equal(engine.pomo.remaining, 1800);
  engine.pomodoro("pause", {});
  assert.equal(engine.pomo.running, false);
  engine.pomodoro("resume", {});
  engine.pomodoro("skip", {});
  assert.equal(engine.pomo.phase, "Break");
  assert.equal(engine.pomo.remaining, 360);
  engine.pomodoro("skip", {});
  assert.equal(engine.pomo.cycle, 2);
  engine.pomodoro("skip", {});
  assert.equal(engine.pomo.phase, "Long break");
  assert.equal(engine.pomo.remaining, 1080);
});
test("background state prevents device writes", async () => {
  const engine = new MobileEngine(true);
  engine.active = false;
  let called = false;
  engine.command = async () => (called = true);
  await assert.rejects(
    engine.sendPanel({ id: "x", screens: [screen("text")] }, 0, true),
    /Reopen the app/,
  );
  assert.equal(called, false);
});
test("mobile engine falls back to port 9000, remembers it and sends the token", async () => {
  const engine = new MobileEngine(false);
  engine.active = true;
  const urls = [], bodies = [];
  engine.http = async (url, options) => {
    urls.push(url);
    bodies.push(options.data);
    if (!url.includes(":9000/")) throw Error("refused");
    return { ReturnCode: 0 };
  };
  const d = { id: "d1", ip: "10.0.0.5", port: 0, local_token: "207245" };
  await engine.command(d, { Command: "Channel/GetAllConf" });
  await engine.command(d, { Command: "Channel/GetAllConf" });
  assert.deepEqual(urls, [
    "http://10.0.0.5/post",
    "http://10.0.0.5:9000/divoom_api",
    "http://10.0.0.5:9000/divoom_api",
  ]);
  assert.ok(bodies.every((b) => b.LocalToken === "207245"));
});
test("endpoint helpers and reply formats", () => {
  assert.deepEqual(endpointCandidates(0), [[80, "/post"], [9000, "/divoom_api"]]);
  assert.deepEqual(endpointCandidates(8080), [[8080, "/post"]]);
  assert.equal(replyOk({ error_code: 0 }), true);
  assert.equal(replyOk({ ReturnCode: 0 }), true);
  assert.equal(replyOk({ error_code: 1, ReturnCode: 0 }), false);
  assert.equal(replyOk(null), false);
});

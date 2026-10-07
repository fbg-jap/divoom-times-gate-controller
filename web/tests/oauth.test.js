import test from "node:test";
import assert from "node:assert/strict";
import { startBody, storedToken, startOAuth, waitConnected, completeOAuth } from "../src/oauth.js";

const config = {
  integrations: { spotify: { refresh_token: "SP" }, mail: { accounts: [{ id: "a1", refresh_token: "T1" }, { id: "a2", refresh_token: "" }] } },
};

test("start body carries the account id for mail only", () => {
  assert.deepEqual(startBody("mail", "a1"), { service: "mail", account_id: "a1" });
  assert.deepEqual(startBody("spotify", "ignored"), { service: "spotify" });
});

test("storedToken reads Spotify and per-account tokens defensively", () => {
  assert.equal(storedToken(config, "spotify"), "SP");
  assert.equal(storedToken(config, "mail", "a1"), "T1");
  assert.equal(storedToken(config, "mail", "a2"), "");
  assert.equal(storedToken(config, "mail", "nope"), "");
  assert.equal(storedToken({}, "mail", "a1"), "");
  assert.equal(storedToken(undefined, "spotify"), "");
});

test("startOAuth posts the body, opens the authorize address and returns what the page needs", async () => {
  const calls = [], opened = [];
  const request = async (...args) => (calls.push(args), { authorize_url: "https://accounts.example/auth?x=1", state: "S", mode: "manual", redirect_uri: "https://r.example/cb" });
  const flow = await startOAuth(request, (url) => opened.push(url), "mail", "a1");
  assert.deepEqual(calls, [["/oauth/start", "POST", { service: "mail", account_id: "a1" }]]);
  assert.deepEqual(opened, ["https://accounts.example/auth?x=1"]);
  assert.deepEqual(flow, { mode: "manual", state: "S", redirect_uri: "https://r.example/cb", url: "https://accounts.example/auth?x=1" });
});

test("startOAuth refuses a response without an http(s) authorize address and never opens it", async () => {
  for (const bad of [{}, { authorize_url: "javascript:alert(1)" }, { authorize_url: 5 }, null]) {
    const opened = [];
    await assert.rejects(startOAuth(async () => bad, (url) => opened.push(url), "spotify"), /Unexpected response/);
    assert.deepEqual(opened, []);
  }
});

test("waitConnected resolves when the token changes and ignores transient errors", async () => {
  let clock = 0, reads = 0;
  const opts = { sleep: async (ms) => { clock += ms; }, now: () => clock, interval: 1000, timeout: 10000 };
  const ok = await waitConnected(async () => { reads++; if (reads === 2) throw Error("net"); return reads < 4 ? "OLD" : "NEW"; }, "OLD", opts);
  assert.equal(ok, true);
  assert.equal(reads, 4);
});

test("waitConnected accepts a first token and times out otherwise", async () => {
  let clock = 0;
  const opts = { sleep: async (ms) => { clock += ms; }, now: () => clock, interval: 1000, timeout: 5000 };
  assert.equal(await waitConnected(async () => "FIRST", "", opts), true);
  clock = 0;
  assert.equal(await waitConnected(async () => "SAME", "SAME", opts), false);
  assert.equal(clock, 5000);
  clock = 0;
  assert.equal(await waitConnected(async () => "", "", opts), false);
});

test("completeOAuth trims and posts the pasted address; empty input never reaches the server", async () => {
  const calls = [];
  const request = async (...args) => (calls.push(args), { connected: true });
  assert.deepEqual(await completeOAuth(request, "S", "  https://r.example/cb?code=C&state=S \n"), { connected: true });
  assert.deepEqual(calls, [["/oauth/complete", "POST", { state: "S", pasted: "https://r.example/cb?code=C&state=S" }]]);
  await assert.rejects(completeOAuth(request, "S", "   "), /Paste the address/);
  assert.equal(calls.length, 1);
  await assert.rejects(completeOAuth(async () => { throw Error("fixed message"); }, "S", "x"), /fixed message/);
});

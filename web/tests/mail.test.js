import test from "node:test";
import assert from "node:assert/strict";
import {
  defaults, normalize, migrateMail, newMailAccount, applyMailProvider, isOAuthMail, mailAccountOptions,
  mailAccountDefaults, MAIL_HOSTS, MAX_MAIL_ACCOUNTS,
} from "../src/model.js";
import { setLanguage } from "../src/i18n.js";

test.afterEach(() => setLanguage("en"));

const legacy = (extra = {}) => ({ enabled: true, host: "imap.example.test", port: 993, user: "me@example.test", password: "pw", mailbox: "Work", show_subject: true, ...extra });

test("defaults have no accounts", () => {
  assert.deepEqual(defaults().integrations.mail, { enabled: false, accounts: [] });
});

test("legacy flat mail config becomes accounts[0] exactly like the Python migration", () => {
  const out = migrateMail(legacy());
  assert.deepEqual(Object.keys(out).sort(), ["accounts", "enabled"]);
  assert.equal(out.enabled, true);
  assert.deepEqual(out.accounts, [{
    ...mailAccountDefaults(), id: "main", name: "me@example.test", provider: "imap", enabled: true,
    host: "imap.example.test", port: 993, user: "me@example.test", password: "pw", mailbox: "Work", show_subject: true,
  }]);
  // enabled carries over; a long user name is cut to 40 characters; an empty user falls back to "Mail"
  assert.equal(migrateMail(legacy({ enabled: false })).accounts[0].enabled, false);
  assert.equal(migrateMail(legacy({ user: "u".repeat(60) })).accounts[0].name, "u".repeat(40));
  assert.equal(migrateMail(legacy({ user: "" })).accounts[0].name, "Mail");
});

test("an empty legacy config yields no account and the default flat keys are dropped", () => {
  assert.deepEqual(migrateMail({ enabled: false, host: "", port: 993, user: "", password: "", mailbox: "INBOX", show_subject: false }), { enabled: false, accounts: [] });
  assert.deepEqual(migrateMail({ enabled: true }), { enabled: true, accounts: [] });
});

test("existing accounts are kept, completed with defaults, and stale flat keys are dropped", () => {
  const out = migrateMail({ enabled: true, host: "ignored", accounts: [{ id: "a1", provider: "google", user: "g@x.test" }, "junk"] });
  assert.equal(out.host, undefined);
  assert.deepEqual(out.accounts[0], { ...mailAccountDefaults(), id: "a1", provider: "google", user: "g@x.test" });
  assert.equal(out.accounts[1], "junk");
  assert.equal(migrateMail("x"), "x");
  assert.equal(migrateMail(null), null);
});

test("migration is pure and idempotent", () => {
  const input = legacy();
  const snapshot = structuredClone(input);
  const once = migrateMail(input);
  assert.deepEqual(input, snapshot);
  assert.deepEqual(migrateMail(once), once);
});

test("normalize migrates old configs and resets alert rules that point at an unknown account", () => {
  const old = defaults();
  old.integrations.mail = legacy();
  old.alerts = [
    { id: "1", metric: "mail_unread", source: "main" },
    { id: "2", metric: "mail_unread", source: "gone" },
    { id: "3", metric: "mail_unread", source: "all" },
    { id: "4", metric: "service", source: "gone" },
  ];
  const cfg = normalize(old);
  assert.equal(cfg.integrations.mail.accounts[0].id, "main");
  assert.equal(cfg.integrations.mail.host, undefined);
  assert.deepEqual(cfg.alerts.map((a) => a.source), ["main", "", "all", "gone"]);
  assert.equal(old.integrations.mail.host, "imap.example.test"); // the input is not mutated
  delete old.integrations.mail;
  assert.deepEqual(normalize(old).integrations.mail, { enabled: false, accounts: [] });
});

test("provider presets", () => {
  const a = newMailAccount();
  assert.match(a.id, /^[a-z0-9]{8}$/);
  assert.deepEqual([a.provider, a.host, a.port, a.enabled], ["imap", "", 993, true]);
  applyMailProvider(a, "google");
  assert.deepEqual([a.provider, a.host, a.port], ["google", MAIL_HOSTS.google, 993]);
  assert.equal(isOAuthMail(a), true);
  applyMailProvider(a, "microsoft");
  assert.equal(a.host, MAIL_HOSTS.microsoft);
  applyMailProvider(a, "imap");
  assert.deepEqual([a.provider, a.host, isOAuthMail(a)], ["imap", "", false]);
  a.host = "mail.example.test";
  applyMailProvider(a, "google");
  applyMailProvider(a, "imap");
  assert.equal(a.host, ""); // a preset host never survives a switch back
  assert.equal(MAX_MAIL_ACCOUNTS, 10);
  assert.notEqual(newMailAccount().id, newMailAccount().id);
});

test("account select: all first, then each account, unknown saved ids kept as (missing)", () => {
  const mail = { accounts: [{ id: "a1", name: "Work", user: "w@x.test" }, { id: "a2", name: "", user: "p@x.test" }, { id: "a3" }] };
  assert.deepEqual(mailAccountOptions(mail, "all", "All accounts"), { all: "All accounts", a1: "Work", a2: "p@x.test", a3: "a3" });
  assert.deepEqual(mailAccountOptions(mail, "a2", "All"), { all: "All", a1: "Work", a2: "p@x.test", a3: "a3" });
  assert.equal(mailAccountOptions(mail, "zzz", "All").zzz, "(missing) zzz");
  setLanguage("es");
  assert.equal(mailAccountOptions(mail, "zzz", "Todas").zzz, "(falta) zzz");
  assert.deepEqual(mailAccountOptions(undefined, "", "All"), { all: "All" });
});

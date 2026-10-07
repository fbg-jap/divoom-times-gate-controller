import { t } from "./i18n.js";
// Browser side of the portal OAuth routes (POST /api/oauth/start|complete). Pure helpers: the page injects request/open/sleep.
export const POLL_MS = 2000;
export const POLL_TIMEOUT_MS = 180000;
export const startBody = (service, accountId) =>
  service === "mail" ? { service, account_id: accountId } : { service };
// The stored refresh token of Spotify or of one mail account ("" when there is none).
export function storedToken(config, service, accountId) {
  const integrations = config?.integrations || {};
  if (service === "spotify") return integrations.spotify?.refresh_token || "";
  const accounts = integrations.mail?.accounts;
  return (Array.isArray(accounts) && accounts.find((a) => a?.id === accountId)?.refresh_token) || "";
}
// Ask the portal for an authorization URL and hand it to `open` (window.open with noopener in the page).
export async function startOAuth(request, open, service, accountId) {
  const start = await request("/oauth/start", "POST", startBody(service, accountId));
  if (!start || typeof start.authorize_url !== "string" || !/^https?:\/\//.test(start.authorize_url))
    throw Error(t("ui.oauth_bad_response"));
  open(start.authorize_url);
  return { mode: start.mode, state: start.state, redirect_uri: start.redirect_uri || "", url: start.authorize_url };
}
// Loopback mode: poll until the stored token differs from the one seen before the attempt. true = connected, false = timed out.
export async function waitConnected(readToken, before, { timeout = POLL_TIMEOUT_MS, interval = POLL_MS, sleep, now = Date.now } = {}) {
  const wait = sleep || ((ms) => new Promise((resolve) => setTimeout(resolve, ms)));
  const deadline = now() + timeout;
  while (now() < deadline) {
    await wait(interval);
    try {
      const token = await readToken();
      if (token && token !== before) return true;
    } catch {
      // a transient network error must not abort the wait
    }
  }
  return false;
}
// Manual (https paste-back) mode: submit the pasted address; resolves {connected: true} or throws the server's fixed message.
export async function completeOAuth(request, state, pasted) {
  const text = String(pasted || "").trim();
  if (!text) throw Error(t("ui.oauth_paste_first"));
  return request("/oauth/complete", "POST", { state, pasted: text });
}

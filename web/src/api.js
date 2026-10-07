import { t } from "./i18n.js";
import { Capacitor } from "@capacitor/core";
export const native = Capacitor.isNativePlatform();
let adapter;
export async function init() {
  if (native || new URLSearchParams(location.search).has("mobile-demo")) {
    const { MobileEngine } = await import("./mobile.js");
    adapter = new MobileEngine(!native);
    await adapter.init();
  }
}
export function token(value) {
  if (value !== undefined) sessionStorage.setItem("keeper-token", value);
  return sessionStorage.getItem("keeper-token") || "";
}
// A pasted token often carries a trailing newline/space (or terminal line wrapping): drop all whitespace.
export const cleanToken = (value) => String(value ?? "").replace(/\s+/g, "");
export function launchCode(hash) {
  const match = /^#launch=([A-Za-z0-9_-]{16,128})$/.exec(hash || "");
  return match ? match[1] : "";
}
// Exchange a one-time launch code (put in the URL fragment by the desktop shell) for the access token.
export async function redeemLaunch(hash) {
  const code = launchCode(hash);
  if (!code) return false;
  history.replaceState(null, "", location.pathname + location.search);
  try {
    const response = await fetch("/api/launch", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ code }),
    });
    if (!response.ok) return false;
    token((await response.json()).token);
    return true;
  } catch {
    return false;
  }
}
export async function request(path, method = "GET", data, binary = false) {
  if (adapter) return adapter.request(path, method, data, binary);
  const response = await fetch("/api" + path, {
    method,
    headers: {
      Authorization: "Bearer " + token(),
      ...(data && !(data instanceof Blob)
        ? { "Content-Type": "application/json" }
        : {}),
    },
    body: data instanceof Blob ? data : data ? JSON.stringify(data) : undefined,
  });
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw Object.assign(
      Error(error.error || error.detail || `HTTP ${response.status}`),
      { status: response.status },
    );
  }
  if (binary) return response.blob();
  return response.json();
}
export async function waitJob(value, progress = () => {}) {
  if (!value?.job) return value;
  while (true) {
    const job = await request("/jobs/" + value.job);
    progress(job);
    if (job.status === "done") return job.result;
    if (["error", "cancelled"].includes(job.status))
      throw Error(job.error || t("api.cancelled"));
    await new Promise((resolve) => setTimeout(resolve, 300));
  }
}
export const action = (name, device_id, args = {}) =>
  request("/action", "POST", { action: name, device_id, args }).then(waitJob);
export async function mediaBlob(path) {
  return request(
    "/media/" + path.replaceAll("\\", "/").split("/").pop(),
    "GET",
    undefined,
    true,
  );
}
export async function upload(file) {
  return request("/upload?name=" + encodeURIComponent(file.name), "POST", file);
}

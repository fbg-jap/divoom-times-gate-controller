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
    throw Error(error.error || error.detail || `HTTP ${response.status}`);
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
      throw Error(job.error || "Cancelado");
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

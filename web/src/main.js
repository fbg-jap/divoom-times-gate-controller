import "./style.css";
import {t,lazy} from "./i18n.js";
import {init,native,token,request,redeemLaunch,cleanToken} from "./api.js";
import {ctx} from "./ctx.js";
import {$,app,el,button,row,banner,hint,run,field,load,save,deviceOptions,preview,d} from "./ui.js";
import {screenPage} from "./pages/screens.js";
import {panoramaPage} from "./pages/panorama.js";
import {scenePage} from "./pages/scenes.js";
import {devicePage} from "./pages/device.js";
import {lightingPage} from "./pages/lighting.js";
import {toolPage} from "./pages/tools.js";
import {automationPage} from "./pages/automation.js";
import {integrationPage,notificationStatusText} from "./pages/integrations.js";
import {backupPage} from "./pages/backup.js";
import {activityPage,eventText} from "./pages/activity.js";
import {pomoText} from "./pages/automation.js";
const names = lazy({
  screens: "ui.screens",
  panorama: "ui.panorama",
  scenes: "ui.scenes",
  device: "ui.device",
  lighting: "ui.rgb_lighting",
  tools: "ui.tools",
  automation: "ui.automations",
  integrations: "ui.integrations",
  backup: "ui.backups_and_settings",
  activity: "ui.activity",
});
function render() {
  clearInterval(ctx.previewTimer);
  ctx.version++;
  for (const url of ctx.urls) URL.revokeObjectURL(url);
  ctx.urls = [];
  app.replaceChildren();
  const aside = el(
    "aside",
    {},
    el("div", { class: "brand" }, "Divoom ", el("span", {}, "Keeper")),
    el(
      "div",
      { class: "badge" },
      ctx.state.capabilities.mode === "mobile"
        ? t("ui.standalone_mobile") + (ctx.state.capabilities.demo ? "DEMO" : t("ui.local_network"))
        : t("ui.web_portal") + (ctx.state.capabilities.demo ? "DEMO" : t("ui.server")),
    ),
  );
  const nav = el("nav", { "aria-label": t("ui.sections") });
  for (const [key, title] of Object.entries(names))
    nav.append(
      button(
        title,
        () => {
          ctx.page = key;
          ctx.editing = null;
          render();
        },
        key === ctx.page ? "active" : "",
      ),
    );
  aside.append(nav);
  const main = el("main", { class: "main" }),
    selector = field(
      ctx.cfg,
      "active_device",
      t("ui.device"),
      "select",
      deviceOptions(),
    );
  selector.querySelector("select").onchange = () => {
    ctx.selected = 0;
    render();
  };
  main.append(
    el(
      "header",
      {},
      el(
        "div",
        {},
        el("h1", {}, names[ctx.page]),
        el(
          "div",
          { class: "status", id: "save-state" },
          ctx.page==='lighting' ? t("ui.adjust_the_preview_and_apply") : ctx.dirty ? t("ui.unsaved_changes") : t("ui.configuration_saved"),
        ),
      ),
      row(
        selector,
        ctx.page==='lighting' ? null : button(
          t("ui.save"),
          async () => {
            await save();
            render();
          },
          "primary",
        ),
      ),
    ),
  );
  if (!ctx.state.capabilities.continuous)
    main.append(
      banner(
        t("ui.direct_control_of_the_times"),
      ),
    );
  const pages = {
    screens: screenPage,
    panorama: panoramaPage,
    scenes: scenePage,
    device: devicePage,
    lighting: lightingPage,
    tools: toolPage,
    automation: automationPage,
    integrations: integrationPage,
    backup: backupPage,
    activity: activityPage,
  };
  pages[ctx.page](main);
  app.append(el("div", { class: "shell" }, aside, main));
}
ctx.render = render;
ctx.login = login;
function login() {
  app.replaceChildren(
    el(
      "div",
      { class: "login card" },
      el("div", { class: "brand" }, "Divoom ", el("span", {}, "Keeper")),
      el("h1", {}, t("ui.your_times_gate_at_hand")),
      hint(t("ui.enter_the_server_token_to")),
      el(
        "form",
        {
          onsubmit: (event) => {
            event.preventDefault();
            run(async () => {
              token(cleanToken($("#token").value));
              try {
                await load();
              } catch (e) {
                token("");
                sessionStorage.removeItem("keeper-token");
                if (e.status === 401) throw Error(t("ui.token_not_accepted"));
                throw e;
              }
              render();
            });
          },
        },
        el(
          "label",
          { class: "field" },
          t("ui.access_token"),
          el("input", {
            id: "token",
            type: "password",
            required: "",
            autocomplete: "current-password",
          }),
        ),
        el("button", { class: "primary", type: "submit" }, t("ui.sign_in")),
      ),
      hint(
        t("ui.the_token_is_in_data"),
      ),
    ),
  );
}
run(async () => {
  await init();
  await redeemLaunch(location.hash);
  try {
    await load();
    render();
  } catch (e) {
    if (native) throw e;
    login();
  }
});
setInterval(async () => {
  if (!ctx.state || !$("#save-state")) return;
  try {
    const fresh = await request("/state");
    ctx.state.events = fresh.events;
    ctx.state.runtime = fresh.runtime;
    const sensorsAppeared = !ctx.state.hardware_sensors?.length && fresh.hardware_sensors?.length;
    ctx.state.hardware_sensors = fresh.hardware_sensors;
    if ($("#notif-status")) $("#notif-status").textContent = notificationStatusText();
    if (sensorsAppeared && $("#sensor-picker") && !$("#sensor-picker").matches(":focus")) render(); // the first probe finished
    if ($("#activity")) $("#activity").textContent = eventText();
    if ($("#pomodoro-state")) $("#pomodoro-state").textContent = pomoText();
  } catch {}
}, 3000);
function previewTick() {
  if (ctx.state && ctx.page === "screens" && !ctx.dirty) {
    document
      .querySelectorAll(".panels img")
      .forEach((img, panel) => preview(img, d().id, panel));
  }
}
let previewTicks = 0;
// Desktop shell: refresh previews every 3 s while the window has focus, otherwise every 10 s.
setInterval(() => {
  previewTicks++;
  const every = ctx.state?.desktop && document.hasFocus() ? 3 : 10;
  if (previewTicks % every === 0) previewTick();
}, 1000);

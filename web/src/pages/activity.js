import {ctx} from "../ctx.js";
import {$,el,button,card} from "../ui.js";
import {t} from "../i18n.js";
import {request} from "../api.js";
import {id} from "../model.js";
export function activityPage(main) {
  main.append(
    card(
      t("ui.activity"),
      el("pre", { id: "activity" }, eventText()),
      button(t("ui.refresh"), async () => {
        const fresh = await request("/state");
        ctx.state.events = fresh.events;
        $("#activity").textContent = eventText();
      }),
    ),
  );
}
export function eventText() {
  return (ctx.state.events || [])
    .slice(-100)
    .map(
      (e) =>
        new Date(e.time * 1000).toLocaleTimeString() +
        " · " +
        (e.message || e.text || JSON.stringify(e)),
    )
    .join("\n");
}

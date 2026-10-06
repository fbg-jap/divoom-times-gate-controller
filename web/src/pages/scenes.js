import {ctx} from "../ctx.js";
import {button,row,card,hint,mark,field,numeric,d,load,save,action,render} from "../ui.js";
import {t} from "../i18n.js";
import {id,composition} from "../model.js";
export function scenePage(main) {
  main.append(
    card(
      t("ui.compositions"),
      row(
        button(
          t("ui.save_current_composition"),
          () => {
            const name = prompt(t("ui.scene_name"));
            if (name?.trim()) {
              ctx.cfg.scenes.push({
                id: id(),
                name: name.trim(),
                ...composition(d()),
              });
              mark();
              render();
            }
          },
          "primary",
        ),
      ),
      hint(
        t("ui.a_scene_includes_the_five"),
      ),
    ),
  );
  for (const scene of ctx.cfg.scenes) {
    main.append(
      card(
        scene.name,
        row(
          button(t("ui.apply_and_send"), async () => {
            await save();
            await action("scene", d().id, { scene_id: scene.id });
            await load();
            render();
          }),
          button(t("ui.rename"), () => {
            const name = prompt(t("ui.name"), scene.name);
            if (name?.trim()) {
              scene.name = name.trim();
              mark();
              render();
            }
          }),
          button(
            t("ui.delete"),
            () => {
              if (
                !confirm(t("ui.this_scene_and_the_rules"))
              )
                return;
              ctx.cfg.scenes = ctx.cfg.scenes.filter((s) => s.id !== scene.id);
              ctx.cfg.schedules = ctx.cfg.schedules.filter(
                (r) => r.action !== "scene" || r.value !== scene.id,
              );
              ctx.cfg.profiles = ctx.cfg.profiles.filter(
                (r) => r.scene_id !== scene.id,
              );
              ctx.cfg.devices.forEach(
                (d) =>
                  (d.rotation = d.rotation.filter((id) => id !== scene.id)),
              );
              mark();
              render();
            },
            "danger",
          ),
        ),
      ),
    );
  }
  const rotation = card(
    t("ui.scene_rotation"),
    numeric(d(), "rotation_seconds", t("ui.change_every_seconds"), 30, 86400),
  );
  ctx.cfg.scenes.forEach((s) => {
    const obj = { use: d().rotation.includes(s.id) },
      f = field(obj, "use", s.name, "checkbox");
    f.addEventListener("change", () => {
      d().rotation = d().rotation.filter((id) => id !== s.id);
      if (obj.use) d().rotation.push(s.id);
      mark();
    });
    rotation.append(f);
  });
  main.append(rotation);
}

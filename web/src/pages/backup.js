import {ctx} from "../ctx.js";
import {$,el,button,row,card,hint,toast,mark,field,d,load,save,chooseFile,download,render} from "../ui.js";
import {t} from "../i18n.js";
import {token,request,waitJob} from "../api.js";
import {id,screen} from "../model.js";
import {languageField} from "./integrations.js";
export function backupPage(main) {
  main.append(
    card(
      t("ui.portable_backup"),
      hint(
        t("ui.includes_media_screens_playlists_scenes"),
      ),
      row(
        button(
          t("ui.export_zip"),
          async () => {
            await save();
            await download(
              await request("/export", "GET", undefined, true),
              "Keeper-backup.zip",
            );
          },
          "primary",
        ),
        button(t("ui.import_zip"), () =>
          chooseFile(".zip", async (file) => {
            if (
              !confirm(
                t("ui.replace_the_configuration_with_this"),
              )
            )
              return;
            await waitJob(await request("/import", "POST", file));
            await load();
            render();
            toast(
              t("ui.backup_imported_check_the_ip"),
            );
          }),
        ),
      ),
    ),
  );
  main.append(
    card(
      t("ui.library"),
      button(t("ui.view_files"), async () => {
        const files = await request("/library");
        const list = $("#library-list");
        list.replaceChildren(
          ...files.map((f) =>
            el(
              "div",
              { class: "list-item" },
              row(
                el("span", {}, f.original || f.name),
                el("small", {}, (f.size / 1024).toFixed(0) + " KB"),
                button(t("ui.use_on_screen") + (ctx.selected + 1), () => {
                  d().screens[ctx.selected] = screen("media", { path: f.path });
                  mark();
                  ctx.page = "screens";
                  render();
                }),
              ),
            ),
          ),
        );
      }),
      el("div", { class: "list", id: "library-list" }),
    ),
  );
  main.append(
    card(
      t("ui.settings_and_session"),
      languageField(),
      field(ctx.cfg, "resend_on_startup", t("ui.resend_on_startup"), "checkbox"),
      button(t("ui.reload_configuration"), async () => {
        if (ctx.dirty && !confirm(t("ui.discard_unsaved_changes"))) return;
        await load();
        render();
      }),
      ctx.state.capabilities.mode === "server"
        ? button(t("ui.sign_out"), () => {
            sessionStorage.removeItem("keeper-token");
            ctx.login();
          })
        : hint(
            t("ui.data_is_stored_on_the"),
          ),
      hint(
        t("ui.windows_2_3_keeps_its"),
      ),
    ),
  );
}

import {ctx} from "../ctx.js";
import {$,el,button,row,card,hint,banner,run,mark,field,numeric,d,saveAndSend,preview,chooseFile,render} from "../ui.js";
import {t} from "../i18n.js";
import {request,waitJob,upload,mediaBlob} from "../api.js";
import {id,copy,composition} from "../model.js";
export function panoramaPage(main) {
  ctx.pano ??= {
    path: "",
    fit: "cover",
    position: [0.5, 0.5],
    x: 0.5,
    y: 0.5,
    zoom: 1,
    rotation: 0,
    start: 0,
    duration: 4,
    fps: 5,
    result: null,
    generation: 0,
  };
  const p = ctx.pano,
    preview = el("canvas", {
      class: "wide-preview",
      "aria-label": t("ui.panorama_preview"),
      width: 640,
      height: 128,
    }),
    source = el("div", { class: "crop-source" }),
    cross = el("div", {
      class: "crosshair",
      style: `left:${p.x * 100}%;top:${p.y * 100}%`,
    }),
    message = hint(t("ui.select_a_file_and_prepare"));
  let generation = p.generation;
  let previewFrames = [],
    frameIndex = 0;
  const seek = el("input", {
    type: "range",
    min: 0,
    max: 0,
    value: 0,
    "aria-label": t("ui.preview_frame"),
  });
  const paintFrame = () => {
    if (previewFrames.length)
      preview.getContext("2d").drawImage(previewFrames[frameIndex], 0, 0);
    seek.value = frameIndex;
  };
  const play = button(t("ui.pause_preview"), () => {
    if (ctx.previewTimer) {
      clearInterval(ctx.previewTimer);
      ctx.previewTimer = null;
      play.textContent = t("ui.play_preview");
    } else startPreview();
  });
  function startPreview() {
    clearInterval(ctx.previewTimer);
    ctx.previewTimer = setInterval(
      () => {
        if (previewFrames.length) {
          frameIndex = (frameIndex + 1) % previewFrames.length;
          paintFrame();
        }
      },
      1000 / (+p.fps || 5),
    );
    play.textContent = t("ui.pause_preview");
  }
  seek.oninput = () => {
    frameIndex = +seek.value;
    paintFrame();
  };
  async function loadPreview(result) {
    const capture = ctx.version;
    const { decode } = await import("../media.js");
    const blob = await mediaBlob(result.preview);
    const decoded = await decode(blob, result.preview, {
      panorama: true,
      fit: "stretch",
      fps: +p.fps,
      duration: Math.max(0.1, result.duration),
    });
    if (capture !== ctx.version) return;
    previewFrames = decoded.frames;
    frameIndex = 0;
    seek.max = previewFrames.length - 1;
    paintFrame();
    if (previewFrames.length > 1) startPreview();
  }
  const refreshSource = async () => {
    if (!p.path) return;
    const blob = await mediaBlob(p.path),
      url = URL.createObjectURL(blob);
    ctx.urls.push(url);
    const media = /\.(mp4|mov|mkv|webm|avi|m4v)$/i.test(p.path)
      ? el("video", {
          src: url,
          muted: "",
          playsinline: "",
          preload: "metadata",
        })
      : el("img", { src: url });
    source.replaceChildren(media, cross);
  };
  run(refreshSource);
  const controls = el("div", { class: "grid three" });
  for (const [key, label, min, max, step] of [
    ["x", "Horizontal", 0, 1, 0.01],
    ["y", "Vertical", 0, 1, 0.01],
    ["zoom", "Zoom", 1, 8, 0.1],
    ["start", t("ui.start_s"), 0, 86400, 0.1],
    ["duration", t("ui.duration_s"), 0.1, 30, 0.1],
  ]) {
    const f = numeric(p, key, label, min, max, step);
    f.addEventListener("input", () => {
      p.generation++;
      p.result = null;
      apply.disabled = true;
      cross.style.left = p.x * 100 + "%";
      cross.style.top = p.y * 100 + "%";
    });
    controls.append(f);
  }
  const fps = field(p, "fps", "FPS", "select", {
      1: "1",
      2: "2",
      4: "4",
      5: "5",
      10: "10",
    }),
    fit = field(p, "fit", t("ui.fit"), "select", {
      cover: t("ui.crop"),
      contain: t("ui.contain"),
      stretch: t("ui.stretch"),
    }),
    rotation = field(p, "rotation", t("ui.rotation"), "select", {
      0: "0°",
      90: "90°",
      180: "180°",
      270: "270°",
    });
  for (const f of [fps, fit, rotation])
    f.addEventListener("change", () => {
      p.generation++;
      p.result = null;
      apply.disabled = true;
    });
  controls.append(fps, fit, rotation);
  source.onpointerdown = (event) => {
    const set = (e) => {
      const r = source.getBoundingClientRect();
      p.x = Math.max(0, Math.min(1, (e.clientX - r.left) / r.width));
      p.y = Math.max(0, Math.min(1, (e.clientY - r.top) / r.height));
      p.result = null;
      p.generation++;
      apply.disabled = true;
      cross.style.left = p.x * 100 + "%";
      cross.style.top = p.y * 100 + "%";
      controls.querySelectorAll("input")[0].value = p.x.toFixed(2);
      controls.querySelectorAll("input")[1].value = p.y.toFixed(2);
    };
    source.setPointerCapture(event.pointerId);
    set(event);
    source.onpointermove = set;
    source.onpointerup = () => (source.onpointermove = null);
  };
  const apply = button(
    t("ui.apply_and_send"),
    async () => {
      if (!p.result) throw Error(t("ui.prepare_the_preview_first"));
      ctx.cfg.scenes.push({
        id: id(),
        name: t("ui.before_panorama") + new Date().toLocaleString(),
        ...composition(d()),
      });
      d().screens = copy(p.result.screens);
      d().screens.forEach((s, i) => (s.title = t("ui.panorama_2") + (i + 1)));
      d().playlists.forEach((l) => (l.enabled = false));
      mark();
      await saveAndSend();
    },
    "primary",
  );
  apply.disabled = !p.result;
  const prepare = button(t("ui.prepare_preview"), async () => {
    if (!p.path) throw Error(t("ui.choose_a_file"));
    prepare.disabled = true;
    apply.disabled = true;
    generation = ++p.generation;
    try {
      message.textContent = t("ui.converting");
      const job = await request("/panorama", "POST", {
        path: p.path,
        fit: p.fit,
        position: [+p.x, +p.y],
        zoom: +p.zoom,
        start: +p.start,
        duration: +p.duration,
        fps: +p.fps,
        rotation: +p.rotation,
      });
      p.job = job.job;
      const result = await waitJob(job);
      if (generation !== p.generation) return;
      p.result = result;
      await loadPreview(result);
      apply.disabled = false;
      message.textContent = t("ui.0_frames_1_s_minimum",[result.count,result.duration.toFixed(2),(result.count * 0.5).toFixed(0)]);
    } finally {
      prepare.disabled = false;
    }
  });
  main.append(
    card(
      t("ui.one_composition_five_screens"),
      row(
        button(t("ui.choose_image_gif_or_video"), () =>
          chooseFile(
            ".png,.jpg,.jpeg,.gif,.webp,.bmp,.mp4,.mov,.mkv,.webm,.avi,.m4v",
            async (file) => {
              p.path = (await upload(file)).path;
              p.result = null;
              p.generation++;
              render();
            },
          ),
        ),
        button(t("ui.center"), () => {
          p.x = p.y = 0.5;
          p.zoom = 1;
          p.result = null;
          p.generation++;
          render();
        }),
      ),
      hint(
        p.path
          ? p.path.split(/[\\/]/).pop()
          : t("ui.up_to_100_mb_video"),
      ),
      source,
      hint(
        t("ui.click_or_drag_to_choose"),
      ),
      controls,
      row(
        prepare,
        button(t("ui.cancel_conversion"), async () => {
          p.generation++;
          p.result = null;
          if (p.job) await request("/jobs/" + p.job + "/cancel", "POST");
          message.textContent = t("ui.conversion_cancelled");
        }),
        apply,
      ),
      message,
      preview,
      row(play, seek),
      banner(
        t("ui.the_five_parts_are_sent"),
        true,
      ),
    ),
  );
  if (p.result) {
    message.textContent = t("ui.0_frames_1_s",[p.result.count,p.result.duration.toFixed(2)]);
    run(() => loadPreview(p.result));
  }
}


import { parseGIF, decompressFrame } from "gifuct-js";
import * as gifenc from "gifenc";
const { GIFEncoder, quantize, applyPalette } = gifenc.GIFEncoder
  ? gifenc
  : gifenc.default;

export const pause = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
export function canvas(width = 128, height = 128) {
  const c = document.createElement("canvas");
  c.width = width;
  c.height = height;
  return c;
}
export function drawFit(
  source,
  width,
  height,
  fit = "contain",
  position = [0.5, 0.5],
  zoom = 1,
  rotation = 0,
) {
  let sw = source.videoWidth || source.width,
    sh = source.videoHeight || source.height;
  if (!sw || !sh || sw * sh > 20000000)
    throw Error("Dimensiones inválidas (máximo 20 megapíxeles)");
  if (rotation) {
    const rotated = canvas(rotation % 180 ? sh : sw, rotation % 180 ? sw : sh),
      ctx = rotated.getContext("2d");
    ctx.translate(rotated.width / 2, rotated.height / 2);
    ctx.rotate((rotation * Math.PI) / 180);
    ctx.drawImage(source, -sw / 2, -sh / 2);
    source = rotated;
    sw = source.width;
    sh = source.height;
  }
  const c = canvas(width, height),
    ctx = c.getContext("2d");
  ctx.fillStyle = "black";
  ctx.fillRect(0, 0, width, height);
  const [x, y] = position.map((n) => Math.max(0, Math.min(1, n)));
  if (fit === "stretch") ctx.drawImage(source, 0, 0, width, height);
  else if (fit === "cover") {
    const scale =
        Math.max(width / sw, height / sh) * Math.max(1, Math.min(8, zoom)),
      w = width / scale,
      h = height / scale;
    ctx.drawImage(
      source,
      (sw - w) * x,
      (sh - h) * y,
      w,
      h,
      0,
      0,
      width,
      height,
    );
  } else {
    const scale = Math.min(width / sw, height / sh),
      w = sw * scale,
      h = sh * scale;
    ctx.drawImage(source, (width - w) * x, (height - h) * y, w, h);
  }
  return c;
}
export async function image(blob) {
  const url = URL.createObjectURL(blob),
    result = new Image();
  try {
    result.src = url;
    await result.decode();
    return result;
  } finally {
    URL.revokeObjectURL(url);
  }
}
export async function decode(blob, name, options = {}, signal) {
  if (blob.size > 100 * 1024 ** 2) throw Error("Máximo 100 MB");
  const panoramic = !!options.panorama,
    width = panoramic ? 640 : 128,
    height = 128;
  const fps = +(options.fps || 5),
    start = +(options.start || 0),
    duration = +(options.duration || 4);
  if (
    panoramic &&
    (![1, 2, 4, 5, 10].includes(fps) ||
      start < 0 ||
      start > 86400 ||
      duration <= 0 ||
      duration > 30 ||
      Math.ceil(duration * fps - 1e-9) > 120)
  )
    throw Error("Máximo 30 segundos / 120 fotogramas; revisa inicio y FPS");
  const frames = [],
    max = panoramic ? Math.ceil(duration * fps - 1e-9) : 600,
    deadline = Date.now() + 60000;
  const check = () => {
    if (signal?.aborted) throw Error("Cancelado");
    if (Date.now() > deadline)
      throw Error("Conversión demasiado lenta; usa un fragmento más corto");
  };
  const append = (source) => {
    check();
    frames.push(
      drawFit(
        source,
        width,
        height,
        options.fit,
        options.position,
        options.zoom,
        options.rotation,
      ),
    );
  };
  const ext = name.toLowerCase().split(".").pop();
  if (ext === "gif") {
    const parsed = parseGIF(await blob.arrayBuffer()),
      parts = parsed.frames.filter((f) => f.image);
    if (parsed.lsd.width * parsed.lsd.height > 20000000 || parts.length > 10000)
      throw Error("GIF demasiado grande");
    if (!panoramic && Math.ceil(parts.length / (options.frame_step || 1)) > 600)
      throw Error("Máximo 600 fotogramas; aumenta el salto");
    const surface = canvas(parsed.lsd.width, parsed.lsd.height),
      ctx = surface.getContext("2d", { willReadFrequently: true });
    let timestamp = 0,
      previous,
      restore;
    for (let i = 0; i < parts.length; i++) {
      check();
      if (previous?.disposalType === 2)
        ctx.clearRect(
          previous.dims.left,
          previous.dims.top,
          previous.dims.width,
          previous.dims.height,
        );
      if (previous?.disposalType === 3 && restore)
        ctx.putImageData(restore, 0, 0);
      const p = parts[i].image.descriptor;
      if (p.width * p.height > 20000000)
        throw Error("Fotograma demasiado grande");
      const frame = decompressFrame(parts[i], parsed.gct, true);
      restore =
        frame.disposalType === 3
          ? ctx.getImageData(0, 0, surface.width, surface.height)
          : null;
      const patch = canvas(frame.dims.width, frame.dims.height);
      patch
        .getContext("2d")
        .putImageData(
          new ImageData(frame.patch, frame.dims.width, frame.dims.height),
          0,
          0,
        );
      ctx.drawImage(patch, frame.dims.left, frame.dims.top);
      const end = timestamp + Math.max(10, frame.delay || 100) / 1000;
      if (panoramic || options.panorama_speed) {
        const rate = options.panorama_speed
            ? 1000 / options.panorama_speed
            : fps,
          offset = options.panorama_speed ? 0 : start;
        while (
          frames.length < max &&
          offset + frames.length / rate < end - 1e-8
        )
          append(surface);
      } else if (i % (options.frame_step || 1) === 0) append(surface);
      timestamp = end;
      previous = frame;
      if (frames.length >= max) break;
      if (i % 10 === 0) await pause(0);
    }
  } else if (["mp4", "mov", "mkv", "webm", "avi", "m4v"].includes(ext)) {
    if (!panoramic) throw Error("Usa Panorámica para convertir un vídeo");
    const video = document.createElement("video"),
      url = URL.createObjectURL(blob);
    video.muted = true;
    video.playsInline = true;
    video.preload = "auto";
    const wait = (event, perform) =>
      new Promise((resolve, reject) => {
        const cleanup = () => {
          clearTimeout(timer);
          video.removeEventListener(event, done);
          video.removeEventListener("error", bad);
        };
        const done = () => {
            cleanup();
            resolve();
          },
          bad = () => {
            cleanup();
            reject(
              Error("Vídeo no compatible con este teléfono; prueba MP4 H.264"),
            );
          };
        const timer = setTimeout(bad, 10000);
        video.addEventListener(event, done, { once: true });
        video.addEventListener("error", bad, { once: true });
        perform();
      });
    try {
      await wait("loadeddata", () => {
        video.src = url;
        video.load();
      });
      for (let i = 0; i < max && start + i / fps < video.duration - 1e-8; i++) {
        check();
        const target = start + i / fps;
        if (Math.abs(video.currentTime - target) > 0.0001)
          await wait("seeked", () => (video.currentTime = target));
        append(video);
        await pause(0);
      }
    } finally {
      video.pause();
      video.removeAttribute("src");
      video.load();
      URL.revokeObjectURL(url);
    }
  } else append(await image(blob));
  if (!frames.length) throw Error("El fragmento no contiene fotogramas");
  return {
    frames,
    speed: options.panorama_speed || 1000 / fps,
    animated: frames.length > 1,
  };
}
export async function encodePanorama(frames, speed) {
  const encoders = Array.from({ length: 6 }, () => GIFEncoder());
  for (const frame of frames) {
    const data = frame.getContext("2d").getImageData(0, 0, 640, 128).data,
      palette = quantize(data, 256);
    encoders[5].writeFrame(applyPalette(data, palette), 640, 128, {
      palette,
      delay: speed,
      repeat: 0,
    });
    for (let panel = 0; panel < 5; panel++) {
      const tile = canvas(),
        ctx = tile.getContext("2d");
      ctx.drawImage(frame, panel * 128, 0, 128, 128, 0, 0, 128, 128);
      encoders[panel].writeFrame(
        applyPalette(ctx.getImageData(0, 0, 128, 128).data, palette),
        128,
        128,
        { palette, delay: speed, repeat: 0 },
      );
    }
    await pause(0);
  }
  return encoders.map((encoder) => {
    encoder.finish();
    return new Blob([encoder.bytes()], { type: "image/gif" });
  });
}
export function jpeg(c, quality = 85) {
  return c
    .toDataURL("image/jpeg", Math.max(0.3, Math.min(1, quality / 100)))
    .split(",")[1];
}

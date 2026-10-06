"""Decode local clips to a bounded, uniform timeline; keep device transport unchanged."""
from __future__ import annotations

import io
import math
from pathlib import Path
import time

from PIL import Image, ImageOps, ImageSequence
from .content import panorama_canvas

VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v"}
MAX_FRAMES = 120
FPS = (1, 2, 4, 5, 10)


def check_source(path):
    path = Path(path)
    if not path.is_file():
        raise ValueError("Choose a local file")
    if path.stat().st_size > 100 * 1024**2:
        raise ValueError("Maximum 100 MB per file. Trim large videos first.")
    return path


def rgb(image):
    rgba = image.convert("RGBA")
    return Image.alpha_composite(Image.new("RGBA", rgba.size, "black"), rgba).convert("RGB")


def decode_clip(path, start=0., duration=4., fps=5, fit="cover", position=(.5, .5), zoom=1., rotation=0, stop=None):
    path = check_source(path)
    start, duration = float(start), float(duration)
    if not math.isfinite(start) or not 0 <= start <= 86400 or not math.isfinite(duration) or not .1 <= duration <= 30 or fps not in FPS:
        raise ValueError("Invalid clip or frame rate")
    wanted = math.ceil(duration * fps - 1e-9)
    if wanted > MAX_FRAMES or rotation not in (0, 90, 180, 270):
        raise ValueError("Maximum 120 frames. Reduce the duration or FPS.")
    frames, source_preview = [], None
    deadline = time.monotonic() + 60

    def check():
        if stop is not None and stop.is_set():
            raise InterruptedError("Conversion cancelled")
        if time.monotonic() > deadline:
            raise ValueError("The conversion exceeds 60 seconds. Try a shorter clip.")

    def append(image):
        nonlocal source_preview
        check()
        if image.width * image.height > 20_000_000:
            raise ValueError("Maximum 20 megapixels per frame")
        image = rgb(image)
        if rotation:
            image = image.rotate(-rotation, expand=True)
        if source_preview is None:
            source_preview = ImageOps.contain(image, (1600, 1600))
        frames.append(panorama_canvas(image, fit, position, zoom))

    if path.suffix.lower() not in VIDEO_EXTENSIONS:
        with Image.open(path) as image:
            timestamp = 0.
            for count, frame in enumerate(ImageSequence.Iterator(image)):
                check()
                if count > 10000:
                    raise ValueError("Too many frames in the source GIF")
                end = timestamp + max(10, int(frame.info.get("duration", 100) or 100)) / 1000
                while len(frames) < wanted and start + len(frames) / fps < end - 1e-8:
                    append(frame)
                timestamp = end
                if len(frames) >= wanted:
                    break
    else:
        import av
        # Only local file I/O is allowed; playlist containers cannot open remote URLs.
        with av.open(str(path), options={"protocol_whitelist": "file,pipe", "threads": "2"}, timeout=10) as container:
            if not container.streams.video:
                raise ValueError("The file contains no video")
            stream = container.streams.video[0]
            if stream.codec_context.width * stream.codec_context.height > 20_000_000:
                raise ValueError("Maximum 20 megapixels per frame")
            origin = float((stream.start_time or 0) * stream.time_base)
            total = float(stream.duration * stream.time_base) if stream.duration is not None else None
            if total is not None and start >= total:
                raise ValueError("The start is after the end of the video")
            container.seek(int((start + origin) / stream.time_base), stream=stream, backward=True)
            previous = None
            previous_time = 0.
            last_duration = 1 / float(stream.average_rate or 25)
            for frame in container.decode(stream):
                check()
                if frame.pts is None:
                    raise ValueError("The video has no valid timestamps")
                timestamp = float(frame.pts * frame.time_base) - origin
                if previous is not None:
                    while len(frames) < wanted and start + len(frames) / fps < timestamp - 1e-8:
                        append(previous.to_image())
                if len(frames) >= wanted:
                    break
                previous, previous_time = frame, timestamp
                last_duration = float(frame.duration * frame.time_base) if frame.duration else last_duration
            if previous is not None:
                end = min(total, previous_time + last_duration) if total is not None else previous_time + last_duration
                while len(frames) < wanted and start + len(frames) / fps < end - 1e-8:
                    append(previous.to_image())
    if not frames:
        raise ValueError("No frames in that clip. Reduce the start.")
    check()
    speed = 1000 // fps
    blobs = encode_panels(frames, speed, check)
    # Preview the saved GIF palette, which is what the sender will actually read.
    panels = [animation_frames(io.BytesIO(blob), speed) for blob in blobs]
    preview = []
    for i in range(len(frames)):
        canvas = Image.new("RGB", (640, 128))
        for panel in range(5):
            canvas.paste(panels[panel][i], (panel*128, 0))
        preview.append(canvas)
    return {"frames": preview, "source": source_preview, "blobs": blobs, "speed": speed,
            "duration": len(frames)/fps, "count": len(frames)}


def encode_panels(frames, speed, check=lambda: None):
    if not frames or len(frames) > MAX_FRAMES or any(f.size != (640, 128) for f in frames):
        raise ValueError("Invalid panorama sequence")
    # One palette per entire panoramic frame keeps colours consistent at the seams.
    quantized = []
    for frame in frames:
        check()
        quantized.append(frame.quantize(colors=256, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE))
    blobs = []
    for panel in range(5):
        check()
        tiles = [f.crop((panel*128, 0, (panel+1)*128, 128)) for f in quantized]
        target = io.BytesIO()
        tiles[0].save(target, "GIF", save_all=True, append_images=tiles[1:], duration=speed,
                      loop=0, optimize=False, disposal=1)
        blobs.append(target.getvalue())
    return blobs


def animation_frames(path, speed):
    """Pillow merges identical GIF frames: expand their durations back to the shared cadence."""
    speed = int(speed)
    if speed not in {1000 // fps for fps in FPS}:
        raise ValueError("Invalid panorama speed")
    frames = []
    with Image.open(path) as source:
        if source.size != (128, 128):
            raise ValueError("Each part must measure 128 × 128")
        for frame in ImageSequence.Iterator(source):
            milliseconds = int(frame.info.get("duration", speed))
            count = max(1, round(milliseconds / speed))
            if len(frames) + count > MAX_FRAMES:
                raise ValueError("Maximum 120 frames per part")
            image = rgb(frame)
            frames.extend([image] * count)
    return frames

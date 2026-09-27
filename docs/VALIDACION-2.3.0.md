# Validation · 2.3.0

**Historical report for animated panoramas.** See [current validation](RGB-3.1.1.md#validation) and [platform status](MULTIPLATAFORMA.md). Local paths identify private development evidence and backups, not public downloads.

Date: September 27, 2026.

## Preservation

Version 2.2 was preserved in `dist/2.2.0/` and `backups/working-v2.2.0-20260927-203514/`, with source, tests, package, data and a SHA-256 manifest. Local `run_stable_2.2.ps1` prepared an independent copy in `compat/2.2.0-data/`, without changing the checkpoint or registering autostart. The 2.1 recovery and original app remained available.

`keeper/protocol.py` retained SHA-256 `54faa7df993e05cebee38fc072c2d5be028587eea123ee7bf55d41cc14c3ae59`. The same working image/GIF transport was used, without new native commands.

## Automated checks

**102 tests passed**, including the previous 92. Log: `artifacts/tests-2.3.0.log`.

- GIFs with variable durations, static regions and expansion of encoder-merged frames: all five parts retained the same frame count and cadence.
- Actual decoding of a PyAV-generated MP4, with start, duration and end-of-file selection.
- Crop, zoom and rotation applied to every frame; preview reconstructed from saved GIFs.
- Limit validation, cancellation, invalid files and mismatched part durations.
- Previous layout and playlists preserved in a scene; portable backup retained media and clip speed.
- Simulated sending of all five parts at their clip speed; normal GIFs retained global speed and the original decoder.
- Asynchronous UI conversion, playback, preview seeking, save, reload and cancel; outdated results discarded.
- Preview GIF file released when closing or changing the layout.

## Packaged executable

Successful PyInstaller build in `dist/2.3.0/`, including PyAV and its FFmpeg DLLs. The executable check returned exit 0, `frozen: true`, nine sections, a panoramic GIF and an MP4 converted to ten frames. Existing calendar, GIF, PC metrics and Windows media features were also checked.

Result: `artifacts/packaged-ui-2.3.0/smoke-result.json`. Reviewed animated-dialog screenshot: `artifacts/packaged-ui-2.3.0/18-panorama-video.png`. All 48 files in the 2.2 checkpoint matched its SHA-256 manifest.

## Physical device

A reversible test with temporary settings used GIF and MP4 clips of eight frames at 2 FPS, cropped from the lower half of a 640 × 256 image. Each screen showed its number, a counter and a moving bar. The five parts were uploaded through the normal engine using their saved GIFs.

All requests were accepted with `error_code: 0`; the original layout was restored and user configuration bytes were confirmed unchanged. Log: `artifacts/live-test-2.3.0.json`.

**The user visually confirmed animation on all five screens.** This confirms playback across the device, not exact synchronization.

## Limits

The five GIFs share duration and cadence, but **simultaneous startup and physical synchronization are not guaranteed**: the transport sends one screen at a time. The preview plays the parts together. No live video streaming or audio was added.

Local files up to 100 MB, 30 seconds and 120 frames per part; 1, 2, 4, 5 or 10 FPS. Maximum 20 megapixels per frame. Codec support depended on FFmpeg bundled with PyAV 18.1.0. The test used MP4/MPEG-4; it did not cover every container/codec combination. Rotation was manual. Conversion checked cancellation and timeout between frames but could not instantly interrupt a blocked decoder call.

Implementation references: [PyAV containers, seek and decode](https://pyav.org/docs/stable/api/container.html) and [Pillow GIF handling](https://pillow.readthedocs.io/en/stable/handbook/image-file-formats.html#gif).

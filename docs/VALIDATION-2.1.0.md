# Validation · 2.1.0

**Historical report.** Later versions add animated panoramas and other features. See [current validation](RGB-3.1.1.md#validation) and [platform status](MULTIPLATFORM.md). Paths below identify private local evidence, not public downloads.

Date: September 27, 2026.

## Preservation

- Source, data and the 2.0.1 executable ZIP saved in `backups/working-v2.0.1-20260927-193746/`, with file SHA-256 values.
- The 2.0.1 executable in `dist/DivoomKeeperStudio/` remained separate from `dist/2.1.0/DivoomKeeperStudio/`.
- `keeper/protocol.py` was unchanged, preserving the sender the user had physically validated.
- Schema 2 and older profile reading retained. Optional playlists kept fallback content compatible with the previous version.

## Tests

68 core, HTTP, widget and UI tests, including:

- JPG/PNG/GIF request comparison with the original sender, increasing IDs and native group 0 protection.
- Playlist rotation with different item durations and independent screens.
- Transfer time excluded from visible item duration.
- Failed sends did not advance the playlist; retries were separated by at least five seconds.
- Widget refresh did not restart item duration.
- Pause, automatic updates off, temporary notices and restoration of the active item.
- Old/new scenes, duplicate playlist content and media export/import.
- Rejection of enabled empty playlists, native content types and out-of-range durations.
- Ordered panorama crops, preservation of the previous layout and rejection of animated GIFs as panoramas in this version.
- Network rates from counter differences, shared caching and counter resets.
- Missing disk readings shown as N/D and rendering of five PC views.
- Dialog save/cancel, playlist order/duration and panorama application through the UI.

Reviewed screenshots in `artifacts/ui-2.1.0/`: seven sections, light theme, PC editor, playlists, panorama and five monitor views.

The packaged Windows executable also passed startup, navigation, metrics, GIF decoding and calendar checks. Result: `artifacts/packaged-ui-2.1.0/smoke-result.json`.

## Physical Times Gate test

- Panorama numbered 1–5 across all screens.
- Screen 3 playlist alternated PC graphs and network traffic using real readings for about 35 seconds.
- The user visually confirmed that both worked.
- The previous layout, including the GIF, was restored afterward. User settings were unchanged during the test.
- Request/restoration log: `artifacts/live-test-2.1.0.json`.

## Limits at this version

- CPU, RAM, disk and network metrics did not require extra drivers. NVIDIA GPU/temperature depended on `nvidia-smi`; no Windows CPU temperature driver was added.
- Playlists required Studio and automatic updates. Large GIFs or slow sources could delay other screens because transfers were serialized.
- Panoramas were still images sent in sections. Cross-screen GIF synchronization was not provided.
- Native PC activation remained experimental, with group 0 blocked. No native commands were extended.
- Automated writes used doubles and a test HTTP server; the separate physical test and visual confirmation are documented above.

## Technical sources

- [psutil: network counters, disks and sensors](https://psutil.io/).
- [Pillow: image fitting and cropping](https://pillow.readthedocs.io/en/stable/reference/ImageOps.html).

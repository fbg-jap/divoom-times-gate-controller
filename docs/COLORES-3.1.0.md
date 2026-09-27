# Keeper 3.1.0 · Visual colors and RGB

**Historical report for 3.1.0.** For current effect names, solid backlight color, corrected sending and platform scope, use the [3.1.1 RGB guide](RGB-3.1.1.md). Build status below describes the local checks performed at that time; subsequent [CI checks](VALIDACION-CI-3.1.0.md) and [3.1.1 validation](RGB-3.1.1.md#validation) supersede the earlier build limitations.

## Usage in 3.1.0

- **Windows/Linux:** Device → RGB lighting. Click the color swatch to open the palette and hue selector. Screen, playlist and layout editors use the same picker for text and background.
- **Portal, Android and iOS:** RGB lighting section. Screen, playlist and layout editors also provide swatches and a quick palette.
- Drag in the color area, move the hue slider, choose among 16 swatches or reuse the last eight colors from the session. Keyboard input is supported. Cancel keeps the previous color; Use color confirms.
- The RGB panel approximates Times Gate color, brightness and the selected main zone. Choose all zones, edges or backlight, adjust brightness, lighting power, color cycling and key lighting.
- Six presets combine color and brightness: Ocean, Aurora, Sunset, Neon, Reading and Color cycle. They preserve the chosen effect and zone.
- Twelve cards select the existing device modes without entering codes. In 3.1.0, **Effect 1–12** maps to internal identifiers 0–11; animation names were not assigned at that stage. Actual animation depends on firmware and is not simulated in the preview.
- Click **Apply lighting** to send. Colors, presets and cards only change the preview until applied. The last accepted settings are stored per device. RGB does not pause playlists or replace screen layouts.

## Builds and preserved versions

Paths under `dist/`, `backups/` and `artifacts/` refer to private local validation; their contents are not published in Git. From a clone, use `build_windows.ps1`, `build_linux.sh` and the mobile instructions. Available CI outputs are on [GitHub Actions](https://github.com/raishack/divoom-times-gate-controller/actions/workflows/multiplatform.yml). The [original v0.1.3 release](https://github.com/raishack/divoom-times-gate-controller/releases/tag/v0.1.3) remains published.

The local Windows 3.1.0 executable was generated at `dist/3.1.0/DivoomKeeperStudio/DivoomKeeperStudio.exe`, with ZIP `dist/DivoomKeeper-3.1.0-windows.zip`. Copy the whole folder, including `_internal`. Exit the previous instance through its tray menu before opening another version with the same data. Use `--demo` to explore without sending.

Version 2.3 remained in `dist/2.3.0/`, and 3.0 packages in `dist/`. The previous source backup was stored in `backups/working-v3.0.0-20260927-214107/` with a SHA-256 manifest. These tests did not change active settings, media or the user's startup entry.

The local APK was `dist/DivoomKeeper-3.1.0-android-debug.apk`. Linux, Docker and iOS source projects were included. At this local validation stage, the Linux package contained source rather than a compiled binary. iOS required Mac, Xcode and signing. See [current platform instructions](MULTIPLATAFORMA.md).

## Local validation

- 121 Python tests: original protocol, content, panoramas, settings, UI, portal and engine. Includes invalid RGB parameters, preservation of screens/playlists and persistence only after acceptance.
- 13 Node tests: standalone engine, RGB, color conversion, validation and mobile transport.
- Windows PyInstaller build and packaged demo check: nine pages, images/GIFs, calendars, GIF/video panoramas and Windows providers. Sample video converted to ten frames per screen. Local result: `artifacts/smoke-3.1.0/smoke-result.json`.
- Vite build and Android/iOS resource synchronization. Android debug APK built with Gradle and signature checked; its resources matched the web build.
- Browser checks: palette, confirm/cancel, hue, brightness, presets, zone, effect and persistence after applying to the simulator. Phone-width view at 390 px without horizontal overflow; no console errors.
- No RGB commands were sent to the physical device during these 3.1.0 checks, and the APK was not installed on a phone. Linux/Docker and iOS were not run on their respective systems from the Windows development computer at this stage.

The original image/GIF sender `keeper/protocol.py` retained SHA-256 `54faa7df993e05cebee38fc072c2d5be028587eea123ee7bf55d41cc14c3ae59`.

The 3.1.0 RGB command retained the earlier `Channel/SetRGBInfo` fields. Zone identifiers matched [LightIndex in Divoom.Client](https://github.com/usausa/divoom-tool/blob/6a60147bf5bb17b25cc603fa5252a78f4c4a0c46/Divoom.Client/Enums.cs), which did not document verified animation names. The later [3.1.1 correction](RGB-3.1.1.md#sending-correction) changed the effect-list structure.

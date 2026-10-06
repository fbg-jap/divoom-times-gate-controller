# Desktop RGB lighting · 3.1.1

In **Device → RGB lighting**, effect cards have descriptive names and movement explanations. They change when you select **Edges / All zones** or **Backlight**, because Times Gate uses two different effect catalogs.

For a solid color, click **Solid backlight color · no animation**, choose the color and brightness, then click **Apply lighting**. The shortcut selects the rear zone, the steady effect and disables color cycling. Selecting the steady effect card also disables cycling. The app saves the setting only after the device accepts it and restores it at startup or reconnection, even when automatic screen updates are off. It does not restart effects on every connection check. Importing a backup pauses RGB restoration until you apply lighting to the reviewed device again.

**Edges** and **All zones** offer **Steady light** without animation. Community documentation indicates that this mode's edge color may be fixed by firmware; a custom solid edge color is not guaranteed. An RGB change can affect both zones, and brightness and power are global.

![Desktop RGB with named effects and a solid color shortcut](screenshots/rgb-desktop.png)

The screenshot uses the Spanish desktop interface. The same controls and descriptive effect names are available in English.

## Scope by platform

- **Windows/Linux desktop 3.1.1:** named effects, descriptions and the solid backlight shortcut.
- **Python server / Docker 3.1.1:** the corrected RGB sender and restoration behavior are shared with desktop.
- **Web interface 3.1.0:** visual color selection and numbered effect cards; commands pass through the corrected Python engine.
- **Standalone Android/iOS 3.1.0:** the previous interface and mobile RGB implementation. The Python correction does not automatically update the autonomous phone engine, so equivalent zone behavior still needs implementation and testing there.

## Sending correction

`Channel/SetRGBInfo` uses three entries in `LightList`: the main effect belongs at the position selected by `SelectLightIndex`. Previously, only one entry was sent, which did not select rear effects correctly. The Python engine still accepts older one-entry commands and converts them to the corrected format before sending.

The effect table and descriptions are based on the [documented observations in RGB_LIGHTS.md](https://github.com/averhaegen/hacs-divoom-times-gate-dev/blob/e8475a1485e00340646bcd52f39971ad34429990/docs/RGB_LIGHTS.md). The English and Spanish names describe behavior; they are not official Divoom names. The preview shows color and the main zone, not the real animation or a guaranteed secondary-zone state.

## Validation

- 126 Python tests passed, including zone addressing, older command compatibility, persistence after acceptance, import without automatic sending and RGB recovery without stopping images/GIFs when lighting fails.
- Windows UI and packaged executable checked in demo mode; image/GIF loading and video conversion verified in the executable.
- [Final GitHub Actions build](https://github.com/raishack/divoom-times-gate-controller/actions/runs/36348139691), from commit [`9c4186f`](https://github.com/raishack/divoom-times-gate-controller/commit/9c4186f72252fac8f07d446e69729a2545e0cfd9): Windows, Linux, Android and iOS simulator jobs passed; Docker built and startup checked. The shared frontend also passed 13 Node tests. These are build/startup checks, not physical phone validation.
- Times Gate accepted a violet steady-light test for both zones. Physical appearance is still awaiting user confirmation; API success alone does not prove the visible color.
- `keeper/protocol.py` retains its original SHA-256: `54faa7df993e05cebee38fc072c2d5be028587eea123ee7bf55d41cc14c3ae59`.

## Download Windows 3.1.1

Open the [verified run](https://github.com/raishack/divoom-times-gate-controller/actions/runs/36348139691) while signed in to GitHub and download **windows-portable** under **Artifacts**. It contains `DivoomKeeper-3.1.1-windows.zip`. Extract the entire folder, including `_internal`, exit the older version through **Exit** in its tray menu, and open `DivoomKeeperStudio.exe`.

Artifacts follow GitHub Actions retention. If they expire, rerun **Multiplatform builds** or build from source. No new binary release has been created; the [original v0.1.3](https://github.com/raishack/divoom-times-gate-controller/releases/tag/v0.1.3) remains available.

The local 3.1.0 build and previous source backup were preserved in `dist/3.1.0/` and `backups/`; the local 3.1.1 build was generated in `dist/3.1.1/`. These private development paths are not public downloads.

[README](../README.md) · [Desktop guide](DESKTOP.md) · [Platform installation](MULTIPLATFORM.md)

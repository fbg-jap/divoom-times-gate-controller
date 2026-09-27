# Divoom Keeper Studio validation · 2.0 / 2.0.1

**Historical report.** See [current validation](RGB-3.1.1.md#validation) and [platform status](MULTIPLATAFORMA.md). Local paths below identify development evidence and private backups, not public downloads.

Date: September 27, 2026.

## 2.0.1 correction after the reported regression

- Preserved another copy of Studio source and data in `backups/studio-before-fix-20260927-191324/`; the original 0.1.3 backup remained intact.
- Reproduced physical sends using the `DivoomSender` class extracted from the original backup, without starting or modifying the old app.
- Restored Unix-second-based increasing PicIDs, separate POSTs, a ten-second timeout and a 100 ms pause after every frame, including still images.
- Automated comparison against a frozen reference of the original sender: JSON, JPEG bytes, destination, timing and URL for JPG, transparent PNG and GIF across all five screens. Earlier tests had not caught these differences.
- 48 automated tests passed, including new regression checks and native PC settings without cloud IDs.
- Corrected engine sent three images, one GIF and one CPU/RAM/GPU image to the physical device. All frames were accepted; `Draw/GetHttpGifId` returned the final sent identifier. Evidence: `artifacts/device-send-2.0.1.json`.
- Actual CPU, RAM, disk, NVIDIA usage and temperature readings were available; CPU temperature was unavailable on this Windows system.
- Packaged 2.0.1 executable exited with code 0, rendered seven sections and handled GIFs and recurring calendars. It also read actual CPU, RAM, disk and NVIDIA data. Evidence: `artifacts/packaged-ui-2.0.1/smoke-result.json`.
- Native mode could send metrics to a PC Monitor selected in the Divoom app without cloud IDs. Direct activation blocked group 0 and omitted fabricated DeviceIds. Sent metrics were logged.
- The user visually confirmed that images, the GIF and PC values were visible. This validated restored content transfer. Divoom documentation requires increasing IDs; the earlier modulo counter could go backwards. Other transport differences were not tested in isolation.
- The cloud returned an empty catalog for this device. A physical native activation test used clock 625, group 0, screen index 1, followed by six metrics. Both commands returned `error_code: 0`, but the user saw the monitor on two screens without data and the other three blank. The full layout was restored and group 0 was blocked in UI, engine and transport. HTTP acceptance did not validate screen selection. Evidence: `artifacts/native-pc-probe-2.0.1.json`.

## Earlier 2.0 checks that did not catch the regression

- Copied the five original files and previous settings before editing.
- Verified SHA-256 values for the five preserved files.
- Checked Python module syntax and dependencies with `pip check`.
- Packaging excluded incompatible ICU DLLs found on PATH; Qt used the Windows 10/11 ICU API.
- 40 automated core, HTTP, widget and UI tests passed.
- Rendered seven UI sections and the light theme with offscreen Qt.
- Final PyInstaller executable test: exit 0, seven pages, GIF decoding and recurring calendar. Result: `artifacts/packaged-ui/smoke-result.json`, with `frozen: true`.
- Migrated actual settings in a temporary directory: one device and five available files, original unchanged and automatic sending disabled.
- Checked the UI at 1120 × 760 without horizontal scrolling.
- Read-only device queries returned `error_code: 0`: `Channel/GetAllConf` reported brightness 100, 24-hour time, °C, no mirroring and screens on; `Channel/GetIndex` returned five indices; `Device/GetDeviceTime` returned UTC and local time.

## Scope of the earlier 2.0 checks

Those read-only device queries did not change images, modes, brightness or settings. Write tests used test doubles and a local HTTP device simulator. The new commands' physical visual results had not yet been verified.

RGB, clock selection, native PC Monitor and per-screen tools depended most on firmware. The UI identified these paths as experimental or community-supported. Pillow-generated widgets reused the original JPEG transport.

Some tests deliberately produced `offline` errors to verify recovery and fault isolation; these did not indicate failed tests.

Sources checked for the correction: [animation protocol](https://docin.divoom-gz.com/web/#/5/133), [individual selection](https://docin.divoom-gz.com/web/#/5/119) and [official PC monitor source](https://github.com/DivoomDevelop/DivoomPCMonitorTool/blob/main/DivoomPCMonitorTool/WindowsFormsApplication1/Form1.cs).

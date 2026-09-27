# Build validation · Keeper 3.1.0

**Historical CI report.** The latest desktop/server build is covered by [3.1.1 validation](RGB-3.1.1.md#validation). Counts and artifacts below refer specifically to 3.1.0.

On September 27, 2026, [GitHub Actions run 36347165150](https://github.com/raishack/divoom-times-gate-controller/actions/runs/36347165150) completed successfully from commit [`1796b3f`](https://github.com/raishack/divoom-times-gate-controller/commit/1796b3f6962a41dcc7afa11617fb9108fcda323a).

| Platform | Completed checks | Run artifact |
| --- | --- | --- |
| Windows | Clean installation, 121 Python tests and PyInstaller build | `windows-portable` |
| Linux x86_64 | Clean installation, 121 Python tests, 13 Node tests, frontend and PyInstaller build | `linux-x86_64` |
| Android | Clean installation, 13 Node tests, frontend, Capacitor sync and Gradle build | `android-debug-apk` |
| iOS | Clean installation, frontend, Capacitor sync and Xcode simulator build | `ios-simulator-unsigned` |
| Docker | Image build, startup and successful `/healthz` response | Built from source; no registry image published |

To download, open the run while signed in to GitHub and find **Artifacts** at the bottom. Files follow GitHub Actions retention; if expired, rerun **Multiplatform builds** or build from source. CI downloads do not create a new release or replace the [original v0.1.3](https://github.com/raishack/divoom-times-gate-controller/releases/tag/v0.1.3).

The APK uses a debug signature; the iOS artifact is a simulator app, not an IPA for iPhone. Physical phone installation and transfers remain unvalidated. The Linux build does not replace an interactive desktop test, and Docker checks cover startup rather than physical Times Gate communication.

The first run exposed three issues absent from the installed local environment: altered dependency references in `package-lock.json`, a retired Android SDK package and Activity button overflow with Linux fonts. The second run verified those fixes from a clean environment. The original image/GIF transport in `keeper/protocol.py` retained its bytes.

[Historical local/RGB checks](COLORES-3.1.0.md) · [Current installation](MULTIPLATAFORMA.md) · [Screenshots](CAPTURAS.md)

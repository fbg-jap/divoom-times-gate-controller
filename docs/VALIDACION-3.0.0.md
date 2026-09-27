# Keeper 3.0 validation

**Historical report for 3.0.0.** Later builds and current limitations are documented in [3.1.1 validation](RGB-3.1.1.md#validation) and the [platform guide](MULTIPLATAFORMA.md). Pending items below describe the state at this earlier checkpoint.

Date: September 27, 2026. Development environment: Windows. This report distinguishes implementation, builds and physical hardware checks.

## Verified

- 115 Python tests passed: the previous 102, nine portal tests and four Linux adaptation tests. Coverage included protocol, queues, media, scenes, playlists, schedules, notices, integrations, Qt UI and panorama conversion.
- Ten Node tests passed: mobile HTTP payload equivalence, rejection of invalid IPs/values and native group 0, job ordering, error recovery, playlist duration after transfer, scene independence, Pomodoro, background pause and older settings migration.
- Vite frontend built and synchronized with both native projects. Fixed a startup blockage caused by circular asynchronous imports.
- Android 3.0.0 debug APK built with Gradle 8.14.3, JDK 21 and SDK 36, using a debug signature.
- Actual FastAPI portal in demo mode on Windows: authentication, rejection of foreign origins, private files, revision-aware saving, panorama conversion and simulated five-screen sends.
- Phone-width browser UI reviewed. The mobile engine used IndexedDB and simulated transport without relying on server endpoints to generate content.
- Local panoramic GIF: eight frames at 200 ms, lower crop selection, animated preview and simulated five-screen send.
- Local H.264 MP4: ten frames, two seconds, browser decoding and five generated GIFs.
- Two consecutive mobile saves/sends checked after fixing revision updates following a command.
- Mobile-exported ZIP imported into Python `ConfigStore`: five eight-frame GIFs and 200 ms timing retained, scenes present and automatic sending disabled.
- `keeper/protocol.py` retained the 2.3 SHA-256: `54faa7df993e05cebee38fc072c2d5be028587eea123ee7bf55d41cc14c3ae59`.

Local logs: `artifacts/tests-3.0.0.log`, `artifacts/tests-mobile.log`, `artifacts/android-build-final.log`, `artifacts/web-build-final.log` and `artifacts/portable-check.json`. Logs were excluded from distribution packages.

## Pending at the 3.0 checkpoint

| Environment | Validation still pending at that time |
| --- | --- |
| Physical Android | APK installation, LAN permission/connectivity, actual sends, file selection, ZIP sharing and suspend/resume |
| iPhone | Xcode build, signing, installation, local-network permission, native HTTP, codecs and export |
| Linux | Qt startup on a real distribution, PyInstaller packaging, tray, autostart, sensors, MPRIS and session lock |
| Docker | Image build/startup with Docker Engine, Times Gate networking and volume persistence |
| Mobile MQTT | Actual WebSocket broker, authentication, sensors and Home Assistant discovery |

At this checkpoint the GitHub workflow was prepared but had not run. There was no signed IPA, Linux binary or prebuilt Docker image in the delivery. Testing the portal on Windows did not validate Docker, and testing the mobile engine in a browser did not validate the Android APK. Subsequent CI builds are linked at the top.

## Preserved compatibility

Windows 2.3 was preserved in `dist/2.3.0/`, with the earlier backup in `backups/working-v2.3.0-20260927-210000/`. This delivery did not replace that executable or its data. Tests used independent demo settings and did not send content to the physical Times Gate.

The user had already visually confirmed animated panoramas across all five screens in 2.3. That validated the underlying device protocol, but did not replace the pending tests of native phone transport.

For a first physical test on each platform: exit the previous controller, enter the IP, send a single image, then a short GIF and panorama. Check Activity and import the previous backup to restore the layout if needed.

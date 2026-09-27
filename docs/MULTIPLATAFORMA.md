# Divoom Keeper · Platform installation

Keeper runs as a Windows/Linux desktop app, a web server or a standalone Android/iOS app. All use the Times Gate's local HTTP protocol. The computer, server or phone must be able to reach its private IP address; sending images does not require a Divoom account.

**Current versions:** desktop and Python server **3.1.1**; shared web interface and standalone Android/iOS apps **3.1.0**. The latest [verified CI run](https://github.com/raishack/divoom-times-gate-controller/actions/runs/36348139691) built Windows, Linux, Android and the iOS simulator, and checked Docker startup.

## Feature comparison

| Feature | Windows/Linux desktop | Docker / web portal | Standalone Android / iOS |
| --- | --- | --- | --- |
| Per-screen images and GIFs | Yes | Yes | Yes |
| Image/GIF/video panorama with crop, zoom and rotation | Yes | Yes, server conversion | Yes, phone conversion |
| Scenes, five playlists, rotation and schedules | While the process runs | While the container runs, even with the browser closed | While the app runs in the foreground |
| Text, clock, weather, RSS, ICS, countdown, services and layouts | Yes | Yes | Yes |
| Pomodoro, reminders and temporary notices | Yes | Yes | While the app is active |
| HTTP and MQTT sensors | Yes | Yes | Yes; MQTT requires the broker's WebSocket endpoint |
| Home Assistant / MQTT commands | Yes | Yes | While active; scene-button discovery |
| CPU/RAM/disk/network metrics | Local computer | Environment visible to the container | External sensors instead |
| Music and artwork | Windows media session; Linux MPRIS with optional `playerctl` | No automatic access to the desktop session | Does not read music from other apps |
| Temperatures | Available system/hardware providers | Only sensors exposed to the container | External sensor |
| Process/session-lock profiles | Local processes and supported session state | Container processes; no desktop lock state | Does not observe PC processes or lock state |
| Incoming integration API | Optional local API | Optional integration API plus portal API | No incoming HTTP server; MQTT commands |
| ZIP backup including media | Yes | Yes | Import/export through local files |
| Native tools and controls | Firmware-dependent | Firmware-dependent | Firmware-dependent |
| Visual color picker and RGB panel | Yes | Yes | Yes |
| Named RGB effects and solid backlight shortcut | Desktop 3.1.1 | Numbered effect cards | Numbered effect cards |
| Corrected RGB zone addressing and restoration | Python 3.1.1 engine | Python 3.1.1 engine | Previous 3.1.0 mobile implementation; not updated by the Python fix |

Platform limitations are shown in the interface. Mobile does not invent PC readings. Imported layouts that use PC metrics need external sensors or a controller running on the computer that supplies those metrics.

Native tools still depend on firmware. Native group 0 remains blocked because earlier tests changed other screens. Activating a native clock does not guarantee PC data. [RGB behavior and validation](RGB-3.1.1.md).

## Migrating your layouts

1. Export a ZIP backup from the current app's settings.
2. Import it through **Settings → Import backup…** on desktop, or the backup/settings section in web/mobile.
3. Check the device IP and review operating-system-specific features.
4. Exit the other controller for that Times Gate before sending.
5. Enable automatic updates for continuous playlists and widgets. In desktop/server 3.1.1, apply lighting explicitly to enable RGB restoration after import.

Import preserves a copy of the previous configuration and disables automatic sending and integrations. Portable ZIPs exclude API/MQTT credentials. They include screen, playlist and scene files; generated panoramas do not need the source video. Export a backup before uninstalling a mobile app.

## Docker and web portal

Requirements: Docker Engine with Compose, network access to Times Gate and an available port 8080. The build context includes source and `web/package-lock.json`, excluding private backups, user images and credentials.

```sh
docker compose up -d --build
docker compose exec keeper cat /data/admin.token
```

Open `http://SERVER_IP:8080` and enter the token. It is generated on first startup and kept in the persistent `keeper-data` volume. To choose your own, copy `.env.example` to `.env` and set `KEEPER_TOKEN` to at least 24 characters. When this variable is set, use its value instead of `admin.token`.

The container runs as user 10001 and stores data in `/data`. The image includes the interface, conversion and sending engine. Playlists, schedules, widgets and notices continue with the browser closed. Do not run multiple replicas against the same volume: the engine and locking support a single instance.

A bridge network with outbound LAN access allows direct IP entry. Discovery may not cross VLANs, Wi-Fi isolation or NAT; use the device IP in that case. A phone connected to the portal is a server client; **the standalone APK is a separate mode**.

Compose publishes the portal on all interfaces by default. Set `KEEPER_BIND=127.0.0.1` to restrict it to the server itself. For an HTTPS proxy, set `KEEPER_ORIGINS=https://keeper.example.com` to the exact browser origin. Keep the portal on your LAN or behind an authenticated HTTPS proxy for remote access. The `/api/*` endpoints, media and backups require the token; `/healthz` only reports availability.

```sh
docker compose logs --tail=100 keeper
docker compose down       # preserves the data volume
```

Metrics describe the environment visible to the container, not necessarily its configured CPU/memory limits or the desktop session. Music, desktop lock state and hardware sensors are not automatically available in Docker. Use HTTP/MQTT sensors for another computer's data.

### Server without Docker

Python 3.11+ and Node 22+; frontend builds were verified with Node 24:

```sh
python3 -m venv .venv-server
.venv-server/bin/python -m pip install -r requirements-server.txt
cd web
npm ci
npm run build
cd ..
.venv-server/bin/python server.py --host 0.0.0.0 --port 8080 --data-dir server-data
```

The token is stored in `server-data/admin.token`. To test without sending to Times Gate, add `--demo` and use a separate data directory. On Windows, use `.venv-server/Scripts/python.exe`. `packaging/keeper-server.service` is a systemd user-service template; adjust its paths before installing. The server does not use Qt.

The optional desktop integration API on port 8787 is separate from the authenticated portal API on 8080. Compose publishes only 8080. MQTT does not require an additional incoming port. Portal API clients send `POST /api/action` with `{"action":"send","device_id":"ID","args":{}}` and `Authorization: Bearer TOKEN`; the returned job can be checked at `GET /api/jobs/ID`.

## Linux desktop

Requirements: a Linux distribution with a graphical desktop, Python 3.11+, `venv` and Qt libraries. On Debian/Ubuntu:

```sh
sudo apt install python3-venv libgl1 libegl1 libxkbcommon0 libxkbcommon-x11-0 libxcb-cursor0 libxcb-xinerama0 libxcb-icccm4 libxcb-image0 libxcb-keysyms1 libxcb-render-util0 fonts-dejavu-core
bash run_linux.sh
```

First startup creates `.venv-linux` and installs dependencies. Data is stored in `$XDG_DATA_HOME/divoom-keeper-studio` or `~/.local/share/divoom-keeper-studio`. Autostart uses a Desktop Entry under `$XDG_CONFIG_HOME/autostart` or `~/.config/autostart`.

```sh
sudo apt install playerctl    # optional: music from MPRIS players
bash run_linux.sh --demo
bash build_linux.sh
```

The local build produces `dist/DivoomKeeperStudio-3.1.1-linux-ARCHITECTURE.tar.gz`. Build artifacts are also available from the verified CI run.

Build on Linux for the target architecture. The package includes Python/Qt but still needs system graphics libraries. Some Wayland sessions lack a tray; without one, closing the window exits the program. Lock detection requires `XDG_SESSION_ID` and a `loginctl` session exposing `LockedHint`.

The [verified CI run](https://github.com/raishack/divoom-times-gate-controller/actions/runs/36348139691) provides a **linux-x86_64** binary artifact. An interactive desktop test on physical Linux hardware remains pending. `linux-source.tar.gz` from `packaging/bundle_universal.py` contains source, not a compiled binary.

## Standalone Android

The debug APK includes the interface, conversion, storage and native HTTP transport. Minimum Android version: 7.0 / API 24. It has no embedded server URL and does not require Docker.

1. Build using the commands below or download **android-debug-apk** from the verified CI run, copy it to the phone and install it. The local development package is named `DivoomKeeper-3.1.0-android-debug.apk`.
2. Connect to a network that can reach Times Gate.
3. Enter its private IP in the device section or import a ZIP backup.
4. Start with an image on one screen, then a GIF and a short panorama.

The APK uses a debug signature. Production distribution requires your own keystore and a release build; keep the keystore for future updates. The app is not published on Google Play. Physical installation and transfers are still pending validation.

To rebuild: Node 22+, JDK 21, Android SDK 36 and build-tools 36.0.0. Set `ANDROID_HOME` or `web/android/local.properties` to your SDK location.

```sh
cd web
npm ci
npm test
npm run build
npx cap sync android
cd android
./gradlew assembleDebug
```

On Windows, use `gradlew.bat`. Output: `web/android/app/build/outputs/apk/debug/app-debug.apk`.

## Standalone iOS

The Xcode project includes the shared frontend, native HTTP transport, local-network permission and the file plugin's privacy declaration. **The simulator app built successfully in CI; no signed IPA or physical iPhone installation has been validated.**

On a Mac with Node 22+, Xcode 26 and its tools:

```sh
cd web
npm ci
npm run build
npx cap sync ios
npx cap open ios
```

In Xcode, select your team under **Signing & Capabilities**, connect the iPhone and run the app. Allow local-network access when prompted. The default identifier is `com.raishack.divoomkeeper`; change it if your team needs another. Use Archive and appropriate Apple signing for distribution. Native dependencies use Swift Package Manager.

Plain HTTP is enabled because the local Times Gate endpoint is `http://IP/post`. HTTPS certificate verification is not disabled. The app does not request access to PC files or other apps' sessions.

## Mobile limitations

- Tasks run **in the foreground**. There is no permanent Android background service or unlimited iOS background execution. Suspension stops tasks; missed schedules are not replayed later.
- Uploaded images and animations remain on Times Gate, which plays GIFs without the phone. Keep the app open during transfer; resend the layout if interrupted.
- Video conversion depends on phone codecs. MP4 H.264 is a useful first compatibility test; MKV/AVI or other codecs may not open. Desktop/server use PyAV.
- Maximum 100 MB per file, 30 seconds and 120 frames per screen. At 10 FPS, the maximum is 12 seconds. No audio or live video streaming. Five sequential uploads can start out of sync.
- IndexedDB stores media inside the app. Clearing app data or uninstalling removes the library; export a ZIP first. Native export opens the system share/save dialog.
- Mobile MQTT requires a `ws://` or `wss://` broker endpoint. TCP host/port settings apply to desktop/server. Retained commands are ignored to avoid replaying old actions after reconnection.
- PC/music widgets and process/lock profiles are marked unavailable. HTTP/MQTT sensors can display data published by another computer.
- The standalone mobile RGB engine remains at 3.1.0; the desktop/server zone-addressing fix and desktop named-effect shortcut are not included.

## Development and checks

```sh
python -m pip install -r requirements.txt -r requirements-server.txt httpx
python -m unittest discover -s tests
cd web
npm ci
npm test
npm run build
```

The portal's `?mobile-demo=1` mode runs the mobile engine with browser storage and simulated sends, without connecting to Times Gate. Normal browser mode always uses the server; native apps select the standalone engine automatically.

`.github/workflows/multiplatform.yml` builds Windows, Linux, Android and an unsigned iOS simulator app, and checks Docker. The [verified 3.1.1 run](https://github.com/raishack/divoom-times-gate-controller/actions/runs/36348139691) passed all four jobs, with 126 Python and 13 Node tests. Downloads require a GitHub login and remain subject to artifact retention. Docker is built from source; no container registry image was published.

The iOS job requires Xcode 26. Simulator artifacts cannot be installed on a real iPhone. Android debug builds may use different keys across computers/runs: export a backup before replacing an installation with an incompatible signature.

References: [Capacitor environment](https://capacitorjs.com/docs/getting-started/environment-setup), [native HTTP](https://capacitorjs.com/docs/apis/http), [Qt for Python deployment](https://doc.qt.io/qtforpython-6.8/deployment/index.html), [Docker Compose networking](https://docs.docker.com/compose/how-tos/networking/).

[README](../README.md) · [Desktop guide](ESCRITORIO.md) · [RGB 3.1.1](RGB-3.1.1.md)

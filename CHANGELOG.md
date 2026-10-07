# Changelog

Versions 2.x and 3.0 were developed and checked locally. Their evolution is published with the 3.1 source; this does not imply a separate binary release for every version. Desktop and the Python server are currently **3.1.1**; the shared web interface and standalone mobile apps remain **3.1.0**.

## Unreleased

- **Review fixes for the browser shell.** The windowed Windows build no longer crashes at startup (no stdout/stderr; uvicorn logs through the shell's `studio.log`); an enabled autostart entry is refreshed on every launch so it follows version upgrades; a damaged or invalid `config.json` shows a message (Windows message box, `notify-send` on Linux), is logged and exits with code 1 without touching the file; removing a mail account resets alerts that used it to *All accounts*; refresh tokens are owned by the server (a background token rotation no longer makes an open editor stale, and a saved configuration cannot overwrite or forge them; Disconnect still clears); profiles of the original DivoomKeeper app are imported again on first start (with a one-time notice); `--self-test` checks the bundled libraries (calendar, GIF, video, psutil, tzdata, platform modules) and `tools/smoke_shell.py` runs it first; a minimized start without a tray still opens the browser.
- **Spotify sign-in from the web UI redirects to `{portal}/api/oauth/callback`** (previously `/api/spotify/callback`): existing users must register this redirect URI in the Spotify Dashboard (or use an https address with paste-back) to reconnect; existing tokens keep working. The legacy `POST /api/spotify/connect` and `GET /api/spotify/callback` routes and the desktop-only loopback helpers were removed.
- **The Qt desktop interface has been replaced by the web interface in a local browser window plus tray** (tag `qt-ui-last` has the last Qt version); smaller downloads (about 60 MB AppImage vs 116 MB). `app.py` is now the web shell entry (`--ui web` is accepted for old autostart entries; `--ui qt` and `--screenshot-dir` exit with an error), PySide6 is no longer a dependency, `requirements.txt` installs everything the shell needs, and `packaging/DivoomKeeperStudio.spec` is the single spec. The screenshots in `docs/screenshots` show the old Qt interface and will be retaken from the web UI.
- **Online time** (`integrations.timesync`, off by default): an SNTP client (random request nonce, reply validation, best-of-3, 8 s budget) with an HTTPS `Date` fallback corrects the clock and countdown widgets, schedules, the calendar "now", custom-screen `{time}`/`{date}` and **Sync computer time**; the offset is ignored after 6 h without a sync, and an optional setting sends `Device/SetUTC` to the devices after each sync (at most every 6 h). Desktop Time tab and web Time card with a status line. Tested against a local fake NTP server only; not yet tried against real servers. See [Integrations](docs/INTEGRATIONS.md#online-time).
- **Packaging for the Qt-free browser shell** (`--ui web`): new `shell_main.py` entry, `packaging/DivoomKeeperStudioWeb.spec` (PySide6 excluded, `web/dist` bundled), `build_linux.sh --ui web`, `build_windows.ps1 -Ui web` (untested), a web AppImage (`APP_NAME=DivoomKeeperStudioWeb packaging/build_appimage.sh`, CI artifact `linux-appimage-web-x86_64`) and `tools/smoke_shell.py`. Autostart relaunches the shell with `--ui web` when it was started that way. The Qt build and AppImage are unchanged.
- **Microsoft Teams in PC notifications**: Teams chat, mention and call pop-ups (native app, `teams-for-linux`, or Teams in a browser matched by domain) are recognised and shown as `Teams · <sender>` with a purple accent, per-kind filters, own screen, longer call notices with optional buzzer; sender only by default (preview opt-in). Heuristic on notification text, untested against a real Teams client. See [Integrations](docs/INTEGRATIONS.md#microsoft-teams).
- Spotify widget **Display** option (`spotify_display`: `both`, `art` or `text`) on desktop and the web editor; the default `both` leaves the layout unchanged. See [Integrations](docs/INTEGRATIONS.md#spotify).
- New **Spotify** widget (now playing, read-only) over the Spotify Web API with PKCE; connect from the desktop app (loopback redirect) or the server portal (`/api/spotify/callback`). Only the client ID and refresh token are stored. Tested with a fake session only, not a real account. See [Integrations](docs/INTEGRATIONS.md#spotify).
- Spotify **Redirect URI** setting (`integrations.spotify.redirect_uri`) and a paste-back desktop connect flow that works with any registered `https` redirect address (no local server), for Dashboards that reject the `http://127.0.0.1` loopback URI. Tested with a fake session only. See [Integrations](docs/INTEGRATIONS.md#spotify).
- **PRTG widget works with PRTG's new v2 API** (`/api/v2/sensors`, Bearer API key), detected automatically with a fallback to the classic API; a pasted `/api/...` address is trimmed to the server, and failures show a fixed reason (`cannot connect`, `timeout`, `not an API endpoint`, `invalid API key`, `access denied`, `unexpected response`). On v2, paused is derived from the totals. See [Integrations](docs/INTEGRATIONS.md#prtg).
- Documented the PRTG widget and alert metrics. See [Integrations](docs/INTEGRATIONS.md#prtg).
- New **Unread mail** widget and `mail_unread` alert metric over IMAP (read-only, count only unless the subject is enabled; STARTTLS enforced on port 143). Polled every 120 s in the background. Not yet tried against a real IMAP server. See [Integrations](docs/INTEGRATIONS.md#unread-mail-imap).
- PC notifications on the Times Gate (off by default, app name and summary only unless the body is enabled, allow/deny app lists, per-minute limit). Linux uses D-Bus through the optional `jeepney` package; the Windows listener is unverified. See [Integrations](docs/INTEGRATIONS.md#pc-notifications).
- Support for hardware revision 402 firmware: the local API on `http://<ip>:9000/divoom_api` replying with `ReturnCode`, plus the device's local token.
- New per-device **Port** and **Local token** fields on desktop, web portal and mobile. With the port left empty (auto), Keeper tries port 80, then port 9000, and remembers the one that answers. Existing configurations keep working unchanged.
- The Pomodoro `phase` value in `/state` and the `pomodoro` events is now English (`Ready`, `Work`, `Break`, `Long break`) instead of Spanish. Scripts or Home Assistant automations that match the old Spanish values must be updated.
- Fixed "got multiple values for argument 'device_id'" when saving a connection.
- All remaining Spanish source text, defaults and documentation file names translated to English. English is now the default language; Spanish stays selectable on desktop. Existing configurations keep their saved language.
- Linux AppImage: `packaging/build_appimage.sh` wraps the PyInstaller build into `DivoomKeeperStudio-<version>-x86_64.AppImage` (built and smoke-tested by a new CI job). Autostart inside an AppImage now points at the AppImage file instead of its temporary mount, and the app sets its desktop file name for correct taskbar grouping.
- **Devices list with remove**: the Device page (desktop and web) now lists every device with its IP, active marker, auto-update state and (web, server mode) online status, with Select and Remove. Removing a device deletes its screens, playlists, schedules, alerts, reminders and profiles; the last device cannot be removed.
- **Windows session lock without Qt**: a ctypes `SessionLockWatcher` (hidden message-only window + `WTSRegisterSessionNotification`) feeds the `locked` profile trigger, so it works in the browser shell on Windows. Started lazily when a `locked` profile exists; the state is unknown until the first lock/unlock event. Tested with a fake `ctypes.windll` only; not tried on real Windows. The Qt window's own detection is unchanged.
- **Mail: Google and Microsoft sign-in and multiple accounts**: `integrations.mail` now holds up to 10 accounts (`accounts[]`), each plain IMAP or Google / Microsoft over IMAP with XOAUTH2 (authorization code + PKCE, your own OAuth app, only the refresh token is stored, with compare-and-swap rotation). Older flat mail settings migrate to account `main` (backend, desktop and web). A Mail screen and a `mail_unread` alert pick one account or *All accounts*. Tested with fake sessions and servers only; no real Google, Microsoft or IMAP account was used. See [Integrations](docs/INTEGRATIONS.md#unread-mail-imap).
- **Web UI mail accounts and OAuth connect**: the Integrations → Mail card is an account list editor (provider presets, Connect/Disconnect with a status line), the Mail screen and the `mail_unread` alert have an account select, and Spotify and mail accounts connect through new portal routes `POST /api/oauth/start`, `GET /api/oauth/callback` (exact-path, single-use `state`) and `POST /api/oauth/complete` (https paste-back for Dashboards that reject `http` loopback). `/api/spotify/connect` and `/api/spotify/callback` keep working. English and Spanish strings.
- Fixed a stale duplicate of the Mail tests and the Qt small-window overflow caused by long account names or mount paths in the screen editor.

## 3.1.1 · Desktop RGB and Python engine fixes

- Named effects and descriptions specific to edges and backlight.
- Solid backlight shortcut with color cycling disabled, plus steady edge lighting with documented firmware color limitations.
- Correct effect addressing through the three entries in `LightList`.
- Restore the last accepted RGB setting at startup or reconnection without stopping images/GIFs if the RGB command fails.
- Importing a backup pauses RGB restoration until lighting is explicitly applied.
- The corrected Python engine also serves the web portal; standalone mobile RGB retains its previous implementation.
- 126 Python tests. Windows/Linux/Android/iOS simulator builds and Docker startup verified in CI. [Usage and validation](docs/RGB-3.1.1.md).
- Documentation updated in English, with current platform versions, downloads and historical validation reports clearly distinguished.
- Corrected the local Linux archive filename to match desktop version 3.1.1.

## 3.1.0 · Visual colors and RGB

- Hue and saturation/lightness selector, 16 swatches and eight recent colors per session.
- Visual color selection in screen editors, playlists, the designer and RGB panels on desktop/web/mobile.
- Color, brightness and zone preview; six quick presets.
- Cards for the twelve existing effects, lighting power, color cycling and key lighting.
- Per-device persistence after acceptance. Applying RGB does not pause screens or change playlists.
- 121 Python tests and 13 Node tests; local Windows and Android debug APK builds.
- Publication of the complete source, platform guides and 14 example screenshots.
- Windows/Linux/Android/iOS simulator builds and Docker startup verified in GitHub Actions. Fixed the web dependency lockfile, Android SDK installation and Activity button widths on Linux.

## 3.0.0 · Multiple platforms

- Linux desktop with XDG paths, autostart, optional MPRIS and platform-specific metrics/session handling.
- Authenticated FastAPI portal, private media library, revision-aware editing and a single sending queue.
- Docker with persistent storage, media conversion and an engine that runs independently of the browser.
- Standalone Android/iOS: Capacitor, direct Times Gate HTTP, local storage and conversion.
- Migration, portable ZIP backups and mobile sensors/MQTT over WebSocket.
- Visible platform limitations; mobile tasks run in the foreground.

## 2.3.0 · GIF and video panoramas

- GIF/video cropping, start/duration/FPS selection and generation of five GIFs.
- Animated preview, pause and frame seeking; background conversion.
- Preserved frame cadence and the previous layout saved as a scene.
- Animation confirmed on all five screens; exact physical synchronization is not guaranteed.

## 2.2.0 · Framing, design and automation

- Panorama framing through dragging, offset, zoom and rotation.
- Windows music, RSS/Atom and a text/image/bar designer.
- Pomodoro, alerts, reminders and process/session-lock profiles.
- Local API, MQTT, Home Assistant and additional sensors.

## 2.1.0 · Playlists and advanced monitoring

- Independent per-screen playlists with item durations.
- PC views with graphs, networking, disks and available temperatures.
- Still-image panoramas and scene rotation.

## 2.0 / 2.0.1 · Keeper Studio

- Renewed interface with themes, per-screen editing, scenes and schedules.
- Local widgets, notifications, device controls and tools.
- Managed media library, original profile migration and portable backups.
- Sending correction to preserve the image/GIF method that worked in v0.1.3.
- Separate Keeper-rendered PC monitoring from experimental native activation; block native group 0.

## 0.1.3 · Original application

- Five persistent media slots, images/GIFs, manual/periodic sending and startup recovery.
- LAN discovery, device selection, profiles, tray, status and autostart.
- [Original release preserved](https://github.com/raishack/divoom-times-gate-controller/releases/tag/v0.1.3).

## Unreleased · OAuth security fixes

- Callback no longer lets forged states lock out sign-in (separate budgets, Sec-Fetch checks, restrictive CSP); the account must not change during sign-in.
- Mail OAuth host pinning with `allow_custom_host`, stricter `user` and tenant validation, no uvicorn access log in server mode.

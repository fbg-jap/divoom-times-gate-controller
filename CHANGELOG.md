# Changelog

Versions 2.x and 3.0 were developed and checked locally. Their evolution is published with the 3.1 source; this does not imply a separate binary release for every version. Desktop and the Python server are currently **3.1.1**; the shared web interface and standalone mobile apps remain **3.1.0**.

## Unreleased

- New **Spotify** widget (now playing, read-only) over the Spotify Web API with PKCE; connect from the desktop app (loopback redirect) or the server portal (`/api/spotify/callback`). Only the client ID and refresh token are stored. Tested with a fake session only, not a real account. See [Integrations](docs/INTEGRATIONS.md#spotify).
- Spotify **Redirect URI** setting (`integrations.spotify.redirect_uri`) and a paste-back desktop connect flow that works with any registered `https` redirect address (no local server), for Dashboards that reject the `http://127.0.0.1` loopback URI. Tested with a fake session only. See [Integrations](docs/INTEGRATIONS.md#spotify).
- Documented the PRTG widget and alert metrics. See [Integrations](docs/INTEGRATIONS.md#prtg).
- New **Unread mail** widget and `mail_unread` alert metric over IMAP (read-only, count only unless the subject is enabled; STARTTLS enforced on port 143). Polled every 120 s in the background. Not yet tried against a real IMAP server. See [Integrations](docs/INTEGRATIONS.md#unread-mail-imap).
- PC notifications on the Times Gate (off by default, app name and summary only unless the body is enabled, allow/deny app lists, per-minute limit). Linux uses D-Bus through the optional `jeepney` package; the Windows listener is unverified. See [Integrations](docs/INTEGRATIONS.md#pc-notifications).
- Support for hardware revision 402 firmware: the local API on `http://<ip>:9000/divoom_api` replying with `ReturnCode`, plus the device's local token.
- New per-device **Port** and **Local token** fields on desktop, web portal and mobile. With the port left empty (auto), Keeper tries port 80, then port 9000, and remembers the one that answers. Existing configurations keep working unchanged.
- The Pomodoro `phase` value in `/state` and the `pomodoro` events is now English (`Ready`, `Work`, `Break`, `Long break`) instead of Spanish. Scripts or Home Assistant automations that match the old Spanish values must be updated.
- Fixed "got multiple values for argument 'device_id'" when saving a connection.
- All remaining Spanish source text, defaults and documentation file names translated to English. English is now the default language; Spanish stays selectable on desktop. Existing configurations keep their saved language.
- Linux AppImage: `packaging/build_appimage.sh` wraps the PyInstaller build into `DivoomKeeperStudio-<version>-x86_64.AppImage` (built and smoke-tested by a new CI job). Autostart inside an AppImage now points at the AppImage file instead of its temporary mount, and the app sets its desktop file name for correct taskbar grouping.

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

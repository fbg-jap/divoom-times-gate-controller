# Keeper integrations

The engine must stay running. Integrations are disabled initially and configured in the integrations section. They do not change the Times Gate image/GIF transport.

This guide covers the desktop/Python integration API and MQTT features. The web portal has a separate authenticated API; standalone mobile uses MQTT over WebSocket and has no incoming HTTP server. See [platform differences](MULTIPLATFORM.md#feature-comparison).

## Local API

Enable the API and copy its token. By default, it listens only on `127.0.0.1:8787`. The LAN option binds to all interfaces; Studio does not modify the firewall. Use plain HTTP only on a trusted network; use a VPN or an authenticated HTTPS proxy for remote access.

Every request requires `Authorization: Bearer YOUR_TOKEN`. The API does not accept arbitrary firmware commands or program execution. Requests are limited to 16 KiB; browser requests carrying an Origin header are rejected.

PowerShell example, prompting for the token instead of putting it in command history:

```powershell
$keeperToken = Read-Host 'Studio token'
$keeperHeaders = @{ Authorization = "Bearer $keeperToken" }
Invoke-RestMethod 'http://127.0.0.1:8787/v1/status' -Headers $keeperHeaders
$keeperBody = @{ action = 'notice'; panel = 3; text = 'Take a short break'; seconds = 15 } | ConvertTo-Json
Invoke-RestMethod 'http://127.0.0.1:8787/v1/action' -Method Post -Headers $keeperHeaders -ContentType 'application/json' -Body $keeperBody
```

`GET /v1/status` returns device and scene IDs without credentials. `POST /v1/action` accepts:

| action | Fields |
| --- | --- |
| `notice` | `panel`: 1–5, `text`: up to 500 characters, `seconds`: 5–300; optional `title`, `buzzer` |
| `scene` | `scene_id`: an existing ID |
| `brightness` | `value`: 0–100 |
| `power` | `on`: boolean `true` or `false` |
| `send` | Resend the layout |

All actions accept `device_id`; if omitted, they use the selected device. **202** means the command is queued. Check Activity for the send result; acceptance does not confirm its visual appearance. A full queue returns 503. Explicit API/MQTT commands can run with automatic updates disabled; notices still require a powered-on screen with a restorable image or widget.

The portal's `POST /api/action` uses a different request shape and job endpoint; see [server API details](MULTIPLATFORM.md#server-without-docker).

## MQTT and Home Assistant

Configure the broker's host, port, username and password. Enable TLS when appropriate; certificates are checked against system authorities. Use a unique prefix per installation, such as `keeper_desktop`. Mobile requires a WebSocket URL instead of the desktop TCP connection.

With MQTT Discovery enabled in Home Assistant, each Times Gate appears with buttons for its scenes and for resending its layout. The engine publishes:

- `PREFIX/availability`: `online` / `offline`, with a last will.
- `PREFIX/status`: a credential-free summary every 30 seconds.
- `homeassistant/button/keeper_DEVICE_SCENE/config`: button discovery.

Send JSON commands to `PREFIX/command` using the same fields as the integration API. **Do not retain commands**: retained commands are discarded to prevent old actions from replaying after reconnection.

### Display a Home Assistant sensor

Home Assistant must publish the reading to a topic. Connecting to the broker does not automatically expose every Home Assistant entity to Keeper.

Example automation; replace `sensor.living_room_temperature` with your actual entity:

```yaml
alias: Living room temperature for Keeper
triggers:
  - trigger: state
    entity_id: sensor.living_room_temperature
  - trigger: time_pattern
    minutes: "/1"
actions:
  - action: mqtt.publish
    data:
      topic: keeper_desktop/sensor/living_room
      payload: "{{ states('sensor.living_room_temperature') }}"
      retain: true
```

In the sensor widget, choose MQTT, topic `keeper_desktop/sensor/living_room`, an empty JSON field and unit `°C`. For a payload of `{"temperature":23.5}`, use `temperature` as the field. Paths such as `data.temperature` and array positions such as `values.0` are supported. Readings expire after the configured interval and then display N/D. Age is measured from receipt, so a retained reading counts as newly received after reconnection.

The engine subscribes to topics used by widgets, playlists, scenes and alerts, plus `PREFIX/sensor/#`. MQTT uses broker authentication and permissions, not the API token. Discovery buttons remain stored in the broker when the engine exits and show as unavailable until it reconnects.

## LibreHardwareMonitor on Windows

Run [LibreHardwareMonitor](https://github.com/LibreHardwareMonitor/LibreHardwareMonitor) and enable its provider in Studio. Its WMI namespace `root\LibreHardwareMonitor` must be available. Refreshing the sensor list shows names, types, identifiers and readings; the first query runs in the background and may take a few seconds.

For a sensor widget, choose LibreHardwareMonitor and paste the exact identifier. For an alert, choose a numeric sensor, the LibreHardwareMonitor source and its identifier. Available CPU/GPU temperatures also feed the PC widget. Availability varies by computer; Studio does not install or load drivers or request elevation.

## Music

Windows reads metadata and artwork from the current exposed media session; both were checked on the development PC. Linux uses MPRIS through optional `playerctl`. Some players do not expose a session, artist or artwork, so only available information is shown. Keeper does not control audio or start playback.

Docker does not automatically have access to the host desktop's media session. Standalone mobile apps do not read other apps' music. See the [platform comparison](MULTIPLATFORM.md#feature-comparison).

## PRTG

The **PRTG status** widget and the `prtg_down` / `prtg_warning` alert metrics read sensor states from a PRTG server. Configure the base URL, API token and TLS option under Integrations → PRTG.

- **Address**: just the PRTG server, e.g. `https://prtg.example.com:1616`. A pasted `/api/...` URL (such as `/api/table.json`) is accepted and trimmed back to the server; a path prefix before `/api` is kept.
- Create an **API key** in PRTG (web interface → Setup → Account Settings → API Keys) and paste it in the Token field. It works for both API versions. On the v2 API it is sent only as an `Authorization: Bearer` header, on the classic API only as the `apitoken` query parameter of the request to your server. It is never logged, is stored in `config.json` (mode 0600) and is blanked in exports.
- **Two APIs**: Keeper first tries the PRTG **v2 API** (`/api/v2/sensors`). If the server answers with something else (a 404 or the web page), it uses the classic v1 API (`/api/table.json`). The detected version is remembered and re-detected after an error, so normally only one version is used.
- **Verify TLS certificate** (`verify_tls`, on by default) checks the server certificate. Turn it off only for a self-signed server on a network you trust.
- The widget counts sensors by state: **up**, **warning**, **down** (down, acknowledged down and, on the classic API, partial down), **paused** and **unusual**; it also names the worst sensor (`device · sensor`). On the classic API paused means paused by user, dependency, schedule, license or until, and unknown/collecting/no probe are not counted. On the v2 API paused is **derived**: the total number of sensors minus every counted state (up, down, acknowledged, warning, unusual, unknown, collecting), never below 0, so it also includes any other state.
- **Cost**: the v2 API needs 8 small requests (one per state plus the total, each `limit=1`) every 30 seconds, all within one 20 second budget. The classic API is a single request.
- `prtg_down` and `prtg_warning` compare the number of sensors in that state with the threshold, like other alert metrics.
- The server is queried at most every 30 seconds, with an 8 second timeout and a 2 MB response cap; a failure shows "Source unavailable" and is not retried every frame.
- The widget and the settings show one of a fixed set of reasons, never the address or the key: `cannot connect`, `timeout`, `not an API endpoint (check the address)` (the address answers with a web page, so it is not the API), `invalid API key`, `access denied` and `unexpected response`.
- The v2 API was checked against a live server; the classic API shape was taken from the PRTG documentation.

## Spotify

The **Spotify** widget shows the track playing on your Spotify account (title, artist, cover, play/pause and a progress bar). It is read-only: Keeper cannot play, pause or skip. It uses the Spotify Web API with the Authorization Code + PKCE flow, so no client secret exists anywhere.

1. Create an app at <https://developer.spotify.com/dashboard>.
2. Under **Redirect URIs** register the URI for how you connect (Spotify accepts `https`, or `http` only on a loopback IP literal; `localhost` is rejected):
   - **Desktop app**: `http://127.0.0.1/callback`. Keeper opens a one-shot server on `127.0.0.1` with a random port and sends that port with the authorization request; Spotify allows leaving the port out of a registered loopback URI. If the Dashboard insists on a port, register `http://127.0.0.1:<port>/callback` for a port of your choice.
   - **Server portal**: `{portal address}/api/spotify/callback`, where the address is the one in your browser's address bar, for example `http://127.0.0.1:8080/api/spotify/callback` (reach a remote server through an SSH tunnel to its port) or `https://keeper.example.com/api/spotify/callback`. A plain `http://` address that is not `127.0.0.1` / `[::1]` is refused by Keeper and by Spotify. Behind a reverse proxy the portal must see the same scheme and host as your browser.
3. Copy the app's **Client ID** into Integrations → Spotify and enable it. Do not enter a client secret.
4. Press **Connect Spotify** and approve in the browser. Scopes requested: `user-read-currently-playing user-read-playback-state`. On the portal, reload the page afterwards.
5. Add a Spotify widget to a screen.

**Display option.** Each Spotify screen has a *Display* setting (`spotify_display`): `both` (default: cover, play state, title and artist), `art` (the cover fills the screen, with a small PLAY/PAUSE label and a thin progress bar) or `text` (large title and artist, no cover). Screens without the setting use `both`. The not-connected, connecting and nothing-playing messages ignore it. Mobile does not render this widget.

**Two ways to connect from the desktop app.** Spotify's documentation permits `http` redirect URIs on loopback IP literals (`127.0.0.1`, `[::1]`; the port may be omitted), but some Dashboards demand `https` anyway. Keeper therefore has a *Redirect URI* setting (`integrations.spotify.redirect_uri`, empty by default, not a secret):

- **Empty or `http://127.0.0.1...`**: the loopback flow above; Keeper runs a one-shot local server and nothing needs pasting.
- **Any `https` address** (one you control, or even a placeholder such as `https://example.org/callback`): the paste-back flow, with no local server:
  1. Register that exact address under **Redirect URIs** in the Spotify Dashboard.
  2. Enter the same address in Integrations → Spotify → **Redirect URI** and press Save.
  3. Press **Connect Spotify**. Keeper opens the authorization page (if it cannot open a browser it copies the address to the clipboard so you can paste it into one).
  4. Approve. Spotify redirects to your address; the page itself may show an error or not load at all, which is fine.
  5. Copy the **full address from the browser's address bar** (it looks like `https://example.org/callback?code=...&state=...`) and paste it into the dialog Keeper shows. A bare `code=...&state=...` query string also works; the `state` is always required and checked.

  The code is exchanged immediately with the PKCE verifier kept in memory; the pasted address is never stored or logged. Pasted text is limited to 2048 characters. The portal flow ignores this setting and derives its address from the request.

What is stored: only the **client ID** and the **refresh token** (`integrations.spotify`, in `config.json`, mode 0600; the token is blanked in exports). Access tokens live in memory, authorization codes are never stored, and neither is logged. Spotify refresh tokens last about six months; Keeper stores a replacement if Spotify issues one.

To disconnect press **Disconnect** (this clears the token; on the portal press Save afterwards), and optionally remove Keeper under spotify.com/account/apps.

Behaviour: the player is polled every 5 seconds in the background, only while a Spotify widget is rendered. "Spotify not connected" appears without a token or after Spotify rejects it twice (reconnect), "Nothing playing" when no player is active, "Spotify unavailable" on network errors; `Retry-After` is honoured when Spotify rate-limits. Cover art is fetched once per track from Spotify's CDN (`*.scdn.co`, `*.spotifycdn.com`, 1 MB cap). Podcast episodes show the show name; ads show "Advertisement". Standalone mobile apps cannot connect; the widget shows a placeholder.

Verification status: the OAuth parameters, redirect rules and endpoint were checked against the official documentation; the response field names were written from memory of the documented shape. Everything is tested with a fake HTTP session; it has not been tried with a real Spotify account.

## Unread mail (IMAP)

The **Unread mail** widget and the `mail_unread` alert metric show how many unread messages a mailbox holds. Configure the server, user, password and mailbox under Integrations → Mail.

- Port 993 uses TLS from the start; port 143 uses STARTTLS and Keeper never sends the password unless STARTTLS succeeded. Certificates are always verified; there is no option to disable it.
- Use an **app password** with providers that require one: Gmail (Google Account → Security → App passwords, IMAP must be enabled) and Fastmail (Settings → Privacy & Security → App passwords, IMAP scope). Your normal account password usually does not work.
- Privacy: only the unread count is read by default (`STATUS ... (UNSEEN)` on a read-only `EXAMINE`d mailbox). Keeper never marks mail as read and never downloads message bodies. With **Show the subject** on, it also fetches only the Subject header of the newest unread message (`BODY.PEEK`), shown on the widget; it is off by default.
- The mailbox is polled every 120 seconds in the background, never on the display loop; a reading older than 10 minutes is treated as unavailable and the alert does not fire. Errors are shown as a short reason (authentication failed, cannot connect, timeout, protocol error) that never includes your credentials.
- The password is stored in `config.json` (mode 0600) and is blanked in exports.
- Standalone mobile apps cannot use IMAP; the widget shows a placeholder there. Not yet tried against a real IMAP server.

## PC notifications

Keeper can show desktop notifications as notices on a Times Gate screen (**Integrations > Notifications**). Notices reuse the normal notice queue: they wait for a free moment, expire after two minutes, and the previous content is restored afterwards. The screen must show restorable content (an image or widget); otherwise the notice is dropped.

Privacy: notification text can be sensitive and the Times Gate is visible to anyone in the room.

- It is **off by default**.
- By default only the **app name and the summary** are sent to the screen; the message body is shown only if you enable *Show the message body*.
- Use the **allowed apps** list to restrict it to chosen apps, and the **blocked apps** list to exclude apps (the blocked list wins; names are matched case-insensitively against the app name the notification reports). These lists match the app name chosen by the sender, so they are not a security boundary, and notification summaries may contain one-time codes that would then be shown on the device.
- At most *per minute* notices are shown; extra ones are dropped. Control characters and line breaks are removed; titles are cut at 80 and text at 500 characters.
- Notices go to the active device, on the chosen screen (1-5), for the chosen number of seconds. Nothing is stored or sent anywhere else.

The status line shows `Running`, `Disabled` or `Unavailable (reason)`; toggling the option takes effect without a restart.

**Linux** needs a session D-Bus and the `jeepney` package (pure Python, listed in the requirements). Keeper observes `Notify` calls through the D-Bus Monitoring interface; it does not replace your notification daemon. Some D-Bus setups refuse monitoring, in which case the status says so. This path has not been verified against a live desktop yet.

**Windows** uses the `UserNotificationListener` API through `winrt` and requires allowing notification access to Keeper in Windows settings. This backend is **unverified**: it has not been run on a real Windows machine.

### Microsoft Teams

Keeper can recognise Teams chat, mention and call pop-ups from this PC and show them with a Teams layout (title `Teams · <sender>`, purple accent). There is no Microsoft sign-in and no Graph access: it only reads the desktop notifications that Teams itself raises. Enable **Microsoft Teams** in **Integrations > Notifications**; it applies only while *Enable PC notifications* is also on.

- **What is matched**: a notification is treated as Teams when any entry of the *patterns* list (case-insensitive) appears in its app name, summary or body. Defaults: `microsoft teams` (the native Windows app), `msteams`, `teams-for-linux` (the unofficial Linux client) and the domains `teams.microsoft.com`, `teams.cloud.microsoft`, `teams.live.com` (Teams running as a browser app, where Chrome or Brave notifications carry the site domain).
- **Kinds**: *call* (the text says calling, incoming call, meeting started, `ringer`, `llamando`, `ruft an`), *mention* (mentioned, `nævnte`, `mencionó`, `erwähnt`, or an `@`), otherwise *chat*. Each kind can be switched off. Calls stay on screen for *call seconds* and can sound the buzzer.
- **Privacy**: by default only the sender and `New message` / `Mentioned you` / `Incoming call` are shown; the message preview appears only with *Show message preview*.
- **Screen and filters**: the Teams *screen* can differ from the general one (0 = same). The general rate limit still applies first, and the general blocked-apps list still wins over Teams (a blocked app is dropped before Teams is evaluated); an allowed-apps list that excludes the app also excludes it.
- **Limitations**: the kinds are heuristics on the notification text, so they depend on the Teams display language. Teams must have operating-system notifications enabled; Focus assist / Do not disturb silences them and Keeper sees nothing. Linux needs `jeepney` as above. The Windows backend is still unverified, and no real Teams client has been tested yet.

## Online time

By default Keeper trusts the PC clock. Under **Integrations → Time** (`integrations.timesync`, off by default) it can instead correct the time it uses from an online time server. **Enabling it makes network requests**: UDP port 123 to the configured NTP servers and, as a fallback, HTTPS to the configured URL. Nothing else is sent; the system clock itself is never changed.

What is corrected: the clock and countdown widgets, the calendar widget's "now", the wall clock the engine uses for schedules, the `{time}` / `{date}` placeholders of custom screens, and the value sent by **Sync computer time** (`Device/SetUTC`, UTC seconds, so it is independent of time zone and daylight saving). Scene names such as "Before panorama" keep using the system time.

| Setting | Meaning |
| --- | --- |
| `enabled` | Off by default. |
| `source` | `ntp` (SNTP, RFC 4330, typically accurate to a few milliseconds) or `https` (the `Date` header of `https_url`, one-second resolution, so about ±1 s). |
| `servers` | 1-5 host names or IP addresses, default `pool.ntp.org`. Up to three answers are compared; the median (or the lowest round-trip delay) is used. |
| `https_url` | An `https://` address used when `source` is `https` or when NTP fails and `fallback_https` is true. Redirects are not followed and the certificate is verified. |
| `interval_minutes` | 5-1440, default 60. A failed attempt is retried after 1 min, then 2, 4, 8 and up to 15 min. |
| `sync_device` | Off by default. After a successful sync Keeper sends `Device/SetUTC` to each enabled, non-paused device, then at most every 6 h. |

Replies are checked before use: the answer must echo a random request value (so a forged or stale packet is rejected), be a server reply of version 3 or 4, not flagged unsynchronised, stratum 1-15 (a stratum 0 "Kiss-o'-Death" answer is rejected and its code shown), carry a transmit time and have a round trip under 2 s. An offset of more than one day is treated as a bad sample and shown as an error instead of being applied.

If the last good offset is more than **6 hours** old (for example the network is down), it is ignored and the PC clock is used again; the status shows "stale". Many firewalls and corporate networks block outgoing UDP 123: then NTP fails and, with `fallback_https` on, the HTTPS source is used with its lower accuracy. The Time tab (desktop) and card (web) show the offset, the server used, the age of the last sync and the last error; the desktop tab has a **Sync now** button. The phone/standalone mobile engine does not use this setting (phones already use network time).

## Credentials and backups

The API token and MQTT password are stored in local user settings. Portable exports omit them and disable integrations; configure them again after importing. Complete copies of the data directory, including manual backups, may contain credentials present at the time.

## References

- [Microsoft: Windows media sessions](https://learn.microsoft.com/en-us/uwp/api/windows.media.control).
- [PyWinRT: asynchronous operations and types](https://pywinrt.readthedocs.io/en/stable/types.html).
- [Microsoft: session lock/unlock notifications](https://learn.microsoft.com/en-us/windows/win32/termserv/wm-wtssession-change).
- [Paho MQTT for Python](https://eclipse.dev/paho/files/paho.mqtt.python/html/client.html).
- [Home Assistant MQTT](https://www.home-assistant.io/integrations/mqtt/).
- [Spotify: Authorization Code with PKCE](https://developer.spotify.com/documentation/web-api/tutorials/code-pkce-flow), [redirect URIs](https://developer.spotify.com/documentation/web-api/concepts/redirect_uri) and [currently playing](https://developer.spotify.com/documentation/web-api/reference/get-the-users-currently-playing-track).

[README](../README.md) · [Desktop guide](DESKTOP.md)

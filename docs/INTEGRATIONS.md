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

## PC notifications

Keeper can show desktop notifications as notices on a Times Gate screen (**Integrations > Notifications**). Notices reuse the normal notice queue: they wait for a free moment, expire after two minutes, and the previous content is restored afterwards. The screen must show restorable content (an image or widget); otherwise the notice is dropped.

Privacy: notification text can be sensitive and the Times Gate is visible to anyone in the room.

- It is **off by default**.
- By default only the **app name and the summary** are sent to the screen; the message body is shown only if you enable *Show the message body*.
- Use the **allowed apps** list to restrict it to chosen apps, and the **blocked apps** list to exclude apps (the blocked list wins; names are matched case-insensitively against the app name the notification reports).
- At most *per minute* notices are shown; extra ones are dropped. Control characters and line breaks are removed; titles are cut at 80 and text at 500 characters.
- Notices go to the active device, on the chosen screen (1-5), for the chosen number of seconds. Nothing is stored or sent anywhere else.

The status line shows `Running`, `Disabled` or `Unavailable (reason)`; toggling the option takes effect without a restart.

**Linux** needs a session D-Bus and the `jeepney` package (pure Python, listed in the requirements). Keeper observes `Notify` calls through the D-Bus Monitoring interface; it does not replace your notification daemon. Some D-Bus setups refuse monitoring, in which case the status says so. This path has not been verified against a live desktop yet.

**Windows** uses the `UserNotificationListener` API through `winrt` and requires allowing notification access to Keeper in Windows settings. This backend is **unverified**: it has not been run on a real Windows machine.

## Credentials and backups

The API token and MQTT password are stored in local user settings. Portable exports omit them and disable integrations; configure them again after importing. Complete copies of the data directory, including manual backups, may contain credentials present at the time.

## References

- [Microsoft: Windows media sessions](https://learn.microsoft.com/en-us/uwp/api/windows.media.control).
- [PyWinRT: asynchronous operations and types](https://pywinrt.readthedocs.io/en/stable/types.html).
- [Microsoft: session lock/unlock notifications](https://learn.microsoft.com/en-us/windows/win32/termserv/wm-wtssession-change).
- [Paho MQTT for Python](https://eclipse.dev/paho/files/paho.mqtt.python/html/client.html).
- [Home Assistant MQTT](https://www.home-assistant.io/integrations/mqtt/).

[README](../README.md) · [Desktop guide](DESKTOP.md)

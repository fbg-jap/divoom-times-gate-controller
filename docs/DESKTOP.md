# Desktop guide · Keeper 3.1.1

[README](../README.md) · [Platform installation](MULTIPLATFORM.md)

The Windows/Linux desktop interface supports English and Spanish. Select English in **Settings** to use the labels shown in this guide.

## Getting started

1. Exit the original app from its tray before enabling Studio transfers. Two controllers can overwrite each other's content.
2. In **Device**, review the imported IP or use LAN discovery. Divoom discovery is a separate option that contacts its servers and can obtain the MAC address and DeviceId.
3. In **Screens**, select a card, choose content and click **Save and send**. Switching screens saves valid pending edits.
4. Enable automatic updates to maintain images and widgets. This is configured per device; several devices can run at the same time.
5. Save layouts in **Scenes** and add rotation or schedules as needed.

Closing the window hides it in the tray when a tray is available. Choose **Exit** in the tray menu to stop the engine. Without a tray, closing the window exits the app.

## Screens and media library

- Five configurable screens per device, with previews of generated content.
- PNG, JPEG, BMP, WebP and GIF images; animated GIF preview.
- Fit with borders, crop or stretch. Imported legacy profiles retain the original stretch behavior.
- Images and animations sent as **base64 128 × 128 JPEG frames**, with `LcdArray`, `PicNum`, `PicOffset`, `PicID` and `PicSpeed`, preserving the original protocol.
- JPEG quality and frame duration configured per device. Normal GIF playback uses a uniform interval rather than each source frame's duration.
- Frame skipping to reduce transfers. Explicit limits of 600 frames per send and 100 MB per imported file.
- Managed library: moving the original file after saving it does not break the profile.
- Unmanaged/native screens are excluded from Studio content uploads.
- Per-screen playlists alternate items with separate durations. Transfer time does not consume the item's visible duration.
- Image/GIF/video panoramas split a composition across five screens, with crop position, zoom, rotation and animation trimming. Animated panoramas have a separate limit of 120 frames per screen.

## Widgets and layouts

| Widget | Source / behavior |
| --- | --- |
| Text | Local rendering with adjustable color, background and font size |
| Clock | IANA timezone, such as `Europe/Madrid`; daylight saving changes through tzdata |
| PC | CPU/RAM/GPU, graphs, network traffic, selectable disk and available temperatures; NVIDIA GPU through `nvidia-smi` |
| Weather | Open-Meteo coordinates, temperature, humidity and conditions; 10-minute cache |
| Countdown | Target date/time; does not produce sound by itself |
| Calendar | ICS URL or local file; next event within seven days, including recurrence; five-minute cache |
| Service | HTTP/HTTPS status and latency; four-second timeout, 15-second cache |
| RSS/Atom | Configured feeds, cached headlines and rotation |
| Music | Available Windows media session or Linux MPRIS metadata/artwork |
| Sensor | Configured HTTP/MQTT data or available hardware providers |
| Designer | Text, images, bars and dynamic fields arranged in layers |
| Native PC Monitor | Sends metrics to a monitor selected in the Divoom app; direct clock 625 activation is experimental |

Widgets are generated on the computer: Studio must remain running to update them. Their minimum update interval is five seconds, although individual sources can cache data longer. They are not firmware applications installed on Times Gate.

Unavailable sensors display N/D. CPU temperature through psutil depends on the operating system and is normally unavailable on Windows. NVIDIA GPU metrics/temperature require `nvidia-smi`. Studio does not install hardware drivers. See the [integration guide](INTEGRATIONS.md) for additional sensor providers and music.

To try **Native PC Monitor**, first select PC Monitor on the intended screen in the Divoom app, then choose the option to send data to the already selected monitor and click **Save and send**. Enable automatic updates to keep sending the six metrics over local HTTP without cloud IDs. Direct activation of clock 625 requires a valid LcdIndependence group from the catalog. Group 0 is blocked because a physical test changed several screens without updating data. DeviceId is sent only when configured. Direct activation is not validated on this device; Keeper's rendered PC widget has been visually confirmed.

Since 2.0.1, the sender preserves the original transport: Unix-second-based increasing `PicID`, a separate POST, a ten-second timeout and a 100 ms pause after every frame, including still images. **Stretch** preserves the original image conversion. Regression tests compare the sender with the preserved original; HTTP acceptance alone does not prove the visible result.

Open-Meteo requires internet access: [service and attribution](https://open-meteo.com/). Calendars, feeds and service URLs are fetched only when configured.

## RGB lighting

Open **Device → RGB lighting**. Choose a color visually, adjust brightness and select an effect card. Names and descriptions change with the selected zone because edges and backlight have different effects.

For a steady rear color, choose **Solid backlight color · no animation**, select the color and brightness, then click **Apply lighting**. The shortcut and steady effect card disable color cycling. Preview changes are sent only when you apply them.

The Python engine saves settings after acceptance and restores them at startup or reconnection, even with automatic screen updates disabled. Importing a backup pauses restoration until you explicitly apply lighting again. RGB errors do not stop image/GIF transfers.

Brightness and lighting power are global. Firmware can also change the other zone, and the **Steady light** edge mode may use a firmware-defined color. [Detailed behavior, source and validation](RGB-3.1.1.md).

## Device controls and native tools

- Screen brightness, screen power, mirroring, 12/24-hour time and °C/°F.
- UTC synchronization with the computer and its current timezone offset. The native timezone is not automatically resynchronized at daylight saving changes; clock widgets use an IANA timezone.
- Timer, stopwatch, scoreboard, noise meter and buzzer.
- Experimental per-screen targeting for timer and scoreboard; stopwatch/noise meter commands are global.
- Temporary notices with restoration of the previous image/widget and an optional beep. Native screens without restorable content are excluded.
- Settings/channel queries and manual restart with confirmation.
- Whole-device or individual native clocks and the five-screen catalog. Valid IDs and firmware-specific testing are required.

Native tools that replace content **pause resending for that device**. Applying RGB does not pause screens. Use the restore-layout action or **Send all** to return to widgets/images. Pause and screen-off state persist across restarts. A response of `error_code: 0` confirms command acceptance, not its visual effect.

## Scenes, schedules and recovery

- Complete five-screen scenes, with rename and delete.
- Per-device rotation through selected scenes in list order.
- Daily, weekday or weekend schedules: apply a scene, change brightness, switch screens on or off.
- Schedules use the computer's local time. Studio must be running with automatic updates enabled for the device. Missed schedules are not replayed after downtime.
- Content fingerprints avoid identical uploads on every update; recovery resends use a configurable interval, defaulting to 60 minutes.
- Connection checks every 30 seconds for devices with automatic updates or saved RGB restoration enabled. Reconnection invalidates the content cache and restores managed content unless paused or powered off; lighting restoration is independent.
- Failed transfers never select a different Divoom automatically. If an IP changes, select or correct the device explicitly.
- A single communication queue avoids overlapping transfers within the app. Network requests run outside the UI thread.

## Backups and migration

Use **Settings → Export portable backup…** to save settings and media, or **Import backup…** to restore a ZIP. Import first preserves the current configuration and disables automatic sending and integrations. In 3.1.1 it also pauses RGB restoration. Review the device IP and platform-dependent sources, then re-enable the features you want and apply lighting explicitly.

[Platform differences and migration](MULTIPLATFORM.md#migrating-your-layouts) · [Screenshot gallery](SCREENSHOTS.md)

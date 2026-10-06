# Validation · 2.2.0

**Historical report.** See [current validation](RGB-3.1.1.md#validation) and [platform status](MULTIPLATFORM.md). Paths below identify private local evidence and backups, not public downloads.

Date: September 27, 2026.

## Preserving the working version

- Source, tests, documentation, 2.1.0 package and user data preserved in `backups/working-v2.1.0-20260927-200013/`, with a SHA-256 manifest.
- 2.1.0 executable left intact in `dist/2.1.0/`; 2.2.0 built separately in `dist/2.2.0/`.
- Local recovery script `run_stable_2.1.ps1` used an independent copy of 2.1 data/media in `compat/2.1.0-data/`, without modifying the checkpoint.
- `keeper/protocol.py` retained SHA-256 `54faa7df993e05cebee38fc072c2d5be028587eea123ee7bf55d41cc14c3ae59`, identical to 2.1 and 2.0.1.

## Automated checks

**92 tests passed**, including the previous 68. Log: `artifacts/tests-2.2.0.log`.

Added coverage:

- Top/bottom and horizontal crops, zoom and preview/output matching.
- RSS editing, new playlist widgets and dragging in the designer.
- New widgets, bars, metric substitution and missing sensors.
- Designer images included in portable backups; credentials excluded.
- RSS/Atom rotation, caching, size limits and XML entity rejection.
- MQTT JSON paths, stale readings and hardware identifiers.
- Sustained alerts, rearming, minimum interval and no false alerts for unavailable sensors.
- Reminders after pause, queued notices and restoration.
- Profile priorities, case-insensitive processes and preservation of the saved layout.
- Pomodoro pause, resume, phase changes, long breaks and reset.
- Local API with an actual test HTTP server: authentication, routes, size limits, action validation, full queue and separation of request acceptance from physical sending.
- MQTT with a simulated client: subscriptions, sensor reception, Discovery and retained-command rejection.
- Invalid settings rejected without saving partial changes.

## Packaged executable and UI

- Successful PyInstaller build, preserving the Windows ICU resolution used by 2.1.
- Packaged check: exit 0, nine sections, recurring calendar, GIF, CPU/RAM/disk and WinRT.
- Actual Windows media session reading returned title and artwork; private media content was omitted from the report.
- Reviewed panorama, designer, alert editor, automation, integration and widget screenshots in `artifacts/ui-2.2.0/` and `artifacts/packaged-ui-2.2.0-final/`.

## Physical device

A reversible test with temporary settings sent two panorama crops labeled “ARRIBA” and “ABAJO”, actual music metadata, a layout with real PC metrics, Pomodoro, a local test RSS feed and a simulated sensor explicitly labeled as a test. A notice was sent to screen 3 through the local HTTP API. Execution, restoration and configuration-preservation evidence: `artifacts/live-test-2.2.0.json`.

Execution completed successfully: all device requests returned `error_code: 0`, the API returned 202 and the original layout was restored with settings intact.

Visual confirmation is tracked separately in that evidence file; HTTP acceptance alone is not visual validation.

## Validation limits

- No user broker/Home Assistant installation was configured; MQTT was validated through simulation.
- LibreHardwareMonitor WMI was unavailable on this computer. Reads used simulated data and remained N/D when absent.
- Lock profiles used simulated session state; the user's desktop was not locked during testing.
- Panoramas remained still images in this version; animation synchronization was not promised.
- Experimental native features retained their existing restrictions; no new native commands were added.
- Rules and widgets required Studio to run; updates and automation required automatic sending. External integrations activated only when configured.

from __future__ import annotations

from datetime import date, datetime, time as dt_time, timedelta, timezone
from collections import deque
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from urllib.parse import urlparse, urlunparse
from zoneinfo import ZoneInfo

from PIL import Image, ImageColor, ImageDraw, ImageFont
import psutil
import requests

from .timesync import timesource


def http_url(value):
    p = urlparse(value)
    if p.scheme not in {"http", "https"} or not p.hostname:
        raise ValueError("An http:// or https:// URL is required")
    return value


class PrtgError(Exception):
    """A PRTG failure whose text is one of a small fixed set of safe reasons (never the URL, token or server text)."""


PRTG_NOT_API = "not an API endpoint (check the address)"


def prtg_base(value):
    """scheme://host[:port][prefix]: everything from the first /api path segment on, the query and the fragment are dropped."""
    p = urlparse(http_url(value.strip()))
    parts = p.path.split("/")
    if "api" in parts:
        parts = parts[:parts.index("api")]
    return urlunparse((p.scheme, p.netloc, "/".join(parts).rstrip("/"), "", "", ""))


def prtg_reason(error):
    """Map any exception to a fixed, safe reason (requests' own text carries the URL)."""
    if isinstance(error, PrtgError):
        return str(error)
    if isinstance(error, requests.Timeout):
        return "timeout"
    if isinstance(error, requests.ConnectionError):
        return "cannot connect"
    status = getattr(getattr(error, "response", None), "status_code", None)
    if status in (401, 403):
        return "access denied"
    return "unexpected response"


GITHUB_API = "https://api.github.com"
GITHUB_QUERIES = {"review": "is:pr is:open archived:false review-requested:@me", "mine": "is:pr is:open archived:false author:@me",
                  "issues": "is:issue is:open archived:false assignee:@me", "mentions": "is:open archived:false mentions:@me"}


def github_reason(error):
    """Map any exception to a fixed, safe reason (requests' own text carries the URL; the token must never be shown)."""
    if isinstance(error, requests.Timeout):
        return "timeout"
    if isinstance(error, requests.ConnectionError):
        return "cannot connect"
    response = getattr(error, "response", None)
    status = getattr(response, "status_code", None)
    if status == 401:
        return "bad token"
    if status == 429 or (status == 403 and str(getattr(response, "headers", {}).get("X-RateLimit-Remaining", "")) == "0"):
        return "rate limited"
    if status == 403:
        return "access denied"
    if status == 422:
        return "repository not found"
    return "unexpected response"


def font(size, bold=False):
    name = "segoeuib.ttf" if bold else "segoeui.ttf"
    bundled = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
    # Segoe UI on Windows; otherwise the bundled DejaVu Sans (Pillow's built-in font has no Æ/Ø/Å and similar letters)
    for path in [Path(os.getenv("WINDIR", "C:/Windows")) / "Fonts" / name,
                 Path(getattr(sys, "_MEIPASS", "")) / "keeper" / "fonts" / bundled,
                 Path(__file__).resolve().parent / "fonts" / bundled,
                 Path("/usr/share/fonts/truetype/dejavu") / bundled]:
        if path.exists():
            return ImageFont.truetype(str(path), size)
    return ImageFont.load_default(size=size)


def png_bytes(image):
    output = io.BytesIO()
    image.save(output, "PNG")
    return output.getvalue()


def wrap_text(draw, text, f, width):
    """Wrap at spaces; a word wider than the line is split by character."""
    lines = []
    for paragraph in str(text).splitlines() or [""]:
        current = ""
        for word in paragraph.split(" "):
            candidate = word if not current else current + " " + word
            if draw.textlength(candidate, font=f) <= width:
                current = candidate
                continue
            if current:
                lines.append(current)
                current = ""
            for ch in word:
                if draw.textlength(current + ch, font=f) > width and current:
                    lines.append(current)
                    current = ""
                current += ch
        lines.append(current)
    return lines


class Providers:
    def __init__(self, demo=False):
        self.demo = demo
        self.cache = {}
        self.session = requests.Session()
        self.nvidia = shutil.which("nvidia-smi")
        self.cpu_primed = False
        self.pc_history = deque(maxlen=120)
        self.network_previous = None
        from .extensions import ExtraSources
        self.extra = ExtraSources(self)

    def cached(self, key, seconds, loader):
        stamp, data = self.cache.get(key, (0, None))
        if key not in self.cache or time.monotonic() - stamp >= seconds:
            data = loader()
            self.cache[key] = (time.monotonic(), data)
        return data

    # PRTG HTTP API (Paessler manual "API: JSON Table Requests", api_definitions, sensor_states):
    #   GET {base_url}/api/table.json?content=sensors&columns=objid,device,sensor,status_raw
    #       &count=5000&apitoken=<API token>
    #   Response JSON: {"prtg-version": "...", "treesize": N,
    #                   "sensors": [{"objid": 1, "device": "...", "sensor": "...", "status_raw": 3}, ...]}
    #   status_raw: 1 Unknown, 2 Collecting, 3 Up, 4 Warning, 5 Down, 6 No Probe, 7 Paused by user,
    #   8 Paused by dependency, 9 Paused by schedule, 10 Unusual, 11 Paused by license,
    #   12 Paused until, 13 Down (acknowledged), 14 Down (partial).
    # The token travels only in the query string of this request; it is never logged or returned.
    PRTG_DOWN, PRTG_PAUSED = {5, 13, 14}, {7, 8, 9, 11, 12}

    PRTG_V2_STATES = ("UP", "DOWN", "ACKNOWLEDGED", "WARNING", "UNUSUAL", "UNKNOWN", "COLLECTING")
    prtg_api = None  # "v2" / "v1" once detected; reset after any error so the next poll detects again

    def prtg_fetch(self, base_url, token, verify=True):
        """Blocking; raises on any failure (ExtraSources maps it with prtg_reason). Called from a background sampler, never a render."""
        base = prtg_base(base_url)
        try:
            if self.prtg_api != "v1":
                data = self.prtg_fetch_v2(base, token, verify)
                if data is not None:
                    self.prtg_api = "v2"
                    return data
            data = self.prtg_fetch_v1(base, token, verify)
            self.prtg_api = "v1"
            return data
        except Exception:
            self.prtg_api = None
            raise

    @staticmethod
    def prtg_read(response, cap):
        chunks, size = [], 0
        for chunk in response.iter_content(65536):
            size += len(chunk)
            if size > cap:
                raise ValueError("The response is too large")
            chunks.append(chunk)
        return b"".join(chunks)

    def github_headers(self, token):
        headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "DivoomKeeperStudio"}
        if token:
            headers["Authorization"] = "Bearer " + token
        return headers

    def github_ci(self, token, repo):
        """Latest GitHub Actions run of a repository: {"state", "name", "branch", "event"}; state is success, failure, running or other
        (cancelled, skipped, ...), or none when the repository has no runs. Blocking; raises on any failure."""
        with self.session.get(f"{GITHUB_API}/repos/{repo}/actions/runs", params={"per_page": 1}, headers=self.github_headers(token),
                              timeout=8, stream=True, allow_redirects=False) as response:
            response.raise_for_status()
            body = self.prtg_read(response, 512 * 1024)
        runs = json.loads(body).get("workflow_runs") or []
        if not runs:
            return {"state": "none", "name": "", "branch": "", "event": ""}
        run = runs[0]
        if run.get("status") != "completed":
            state = "running"
        else:
            state = {"success": "success", "failure": "failure", "timed_out": "failure", "startup_failure": "failure"}.get(run.get("conclusion"), "other")
        return {"state": state, "name": str(run.get("name") or "")[:60], "branch": str(run.get("head_branch") or "")[:60],
                "event": str(run.get("event") or "")[:20]}

    def github_fetch(self, token, query):
        """Open pull requests matching a GitHub search query: {"count": n, "items": [{number, title, repo, author, draft}]}.
        Blocking; raises on any failure (ExtraSources maps it with github_reason). Called from a background sampler."""
        headers = self.github_headers(token)
        with self.session.get(GITHUB_API + "/search/issues", params={"q": query, "per_page": 3, "sort": "updated", "order": "desc"},
                              headers=headers, timeout=8, stream=True, allow_redirects=False) as response:
            response.raise_for_status()
            body = self.prtg_read(response, 512 * 1024)
        data = json.loads(body)
        items = []
        for item in (data.get("items") or [])[:3]:
            repo = str(item.get("repository_url", "")).rsplit("/repos/", 1)[-1]
            items.append({"number": int(item.get("number", 0)), "title": str(item.get("title", ""))[:200], "repo": repo[:100],
                          "author": str((item.get("user") or {}).get("login", ""))[:40], "draft": bool(item.get("draft"))})
        return {"count": int(data.get("total_count", 0)), "items": items}

    # PRTG v2 API: GET {base}/api/v2/sensors?limit=1[&filter=status=UP] with "Authorization: Bearer <API key>"
    #   -> JSON list of sensors; X-Total-Count is the number of sensors matching the filter. One filter value per request.
    def prtg_v2_query(self, base, token, verify, deadline, status=None):
        """(http status, X-Total-Count or None, first sensor or None); None for the sensor when the reply is not v2 JSON."""
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise PrtgError("timeout")
        params = {"limit": 1, **({"filter": f"status={status}"} if status else {})}
        with self.session.get(base + "/api/v2/sensors", timeout=min(8, remaining), verify=verify, stream=True, allow_redirects=False,
                              params=params, headers={"Authorization": f"Bearer {token}", "Accept": "application/json"}) as response:
            code = response.status_code
            kind = response.headers.get("Content-Type", "")
            total = response.headers.get("X-Total-Count")
            body = self.prtg_read(response, 256 * 1024)
        if not isinstance(kind, str) or not kind.lower().startswith("application/json"):
            return code, None, None
        try:
            items = json.loads(body)
            total = int(total) if total is not None else None
        except ValueError:
            return code, None, None
        return code, total, items

    def prtg_fetch_v2(self, base, token, verify):
        """Status counts via the v2 API, or None when the server does not speak it (HTML page, 404, ...)."""
        deadline = time.monotonic() + 20
        code, total, items = self.prtg_v2_query(base, token, verify, deadline)
        if code in (401, 403):
            raise PrtgError("access denied")
        if code == 400 and items is not None:
            raise PrtgError("invalid API key")
        if code != 200 or not isinstance(items, list) or total is None:
            return None
        found, worst = {}, {}
        for state in self.PRTG_V2_STATES:
            code, count, items = self.prtg_v2_query(base, token, verify, deadline, state)
            if code != 200 or not isinstance(items, list) or count is None:
                raise PrtgError("unexpected response")
            found[state] = max(0, count)
            if items and isinstance(items[0], dict):
                worst[state] = items[0]
        total = max(0, total)
        counted = sum(found.values())
        for state in ("DOWN", "ACKNOWLEDGED", "WARNING", "UNUSUAL"):
            if state in worst:
                sensor = worst[state]
                path = sensor.get("path") if isinstance(sensor.get("path"), list) else []
                device = next((e.get("name", "") for e in reversed(path) if isinstance(e, dict)
                               and e.get("type") in ("DEVICE", "REFERENCED_DEVICE")), "")
                label = f"{device} · {sensor.get('name', '')}".strip(" ·")[:80]
                break
        else:
            label = ""
        return {"up": found["UP"], "warning": found["WARNING"], "down": found["DOWN"] + found["ACKNOWLEDGED"],
                "paused": max(0, total - counted), "unusual": found["UNUSUAL"], "worst": label}

    def prtg_fetch_v1(self, base, token, verify):
        with self.session.get(base + "/api/table.json", timeout=8, verify=verify,
                              stream=True, allow_redirects=False, params={"content": "sensors", "count": 5000, "apitoken": token,
                                                   "columns": "objid,device,sensor,status_raw"}) as response:
            response.raise_for_status()
            body = self.prtg_read(response, 2 * 1024**2)
        if body.lstrip()[:1] == b"<":
            raise PrtgError(PRTG_NOT_API)  # the PRTG web page answers every unknown path with HTTP 200
        sensors = json.loads(body)["sensors"]
        counts = {"up": 0, "warning": 0, "down": 0, "paused": 0, "unusual": 0}
        worst = (0, "")
        for item in sensors:
            status = int(item["status_raw"])
            key = ("up" if status == 3 else "warning" if status == 4 else "down" if status in self.PRTG_DOWN
                   else "unusual" if status == 10 else "paused" if status in self.PRTG_PAUSED else None)
            if key is None:
                continue
            counts[key] += 1
            rank = {"down": 3, "warning": 2, "unusual": 1}.get(key, 0)
            if rank > worst[0]:
                worst = (rank, f"{item.get('device', '')} · {item.get('sensor', '')}".strip(" ·")[:80])
        return {**counts, "worst": worst[1]}

    def pc(self):
        if self.demo:
            values = {"cpu": 24, "ram": 62, "disk": 48, "gpu": 37, "cpu_temp": 52, "gpu_temp": 46,
                      "download": 2.4 * 1024**2, "upload": .35 * 1024**2}
            if not self.pc_history:
                import math
                for i in range(30):
                    self.pc_history.append({**values, "time": i * 5,
                        "cpu": 24 + 15 * math.sin(i / 2), "gpu": 37 + 25 * math.sin(i / 3),
                        "download": values["download"] * (1 + .5 * math.sin(i / 3))})
            return values

        def sample():
            cpu = psutil.cpu_percent(interval=.15 if not self.cpu_primed else None)
            self.cpu_primed = True
            result = {"cpu": cpu, "ram": psutil.virtual_memory().percent,
                      "disk": self.disk()["percent"], "gpu": None, "cpu_temp": None, "gpu_temp": None,
                      "download": None, "upload": None}
            now = time.monotonic()
            try:
                counters = psutil.net_io_counters()
                if counters is not None:
                    if self.network_previous is not None:
                        stamp, received, sent = self.network_previous
                        elapsed = now - stamp
                        if elapsed > 0 and counters.bytes_recv >= received and counters.bytes_sent >= sent:
                            result["download"] = (counters.bytes_recv - received) / elapsed
                            result["upload"] = (counters.bytes_sent - sent) / elapsed
                    self.network_previous = (now, counters.bytes_recv, counters.bytes_sent)
                else:
                    self.network_previous = None
            except OSError:
                self.network_previous = None
            if hasattr(psutil, "sensors_temperatures"):
                try:
                    groups = psutil.sensors_temperatures()
                except (OSError, RuntimeError):
                    groups = {}
                for name in ("coretemp", "k10temp", "cpu_thermal"):
                    if groups.get(name):
                        result["cpu_temp"] = groups[name][0].current
                        break
            if self.nvidia:
                try:
                    output = subprocess.run([self.nvidia, "--query-gpu=utilization.gpu,temperature.gpu",
                                             "--format=csv,noheader,nounits"], capture_output=True,
                                            text=True, timeout=3,
                                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                    values = output.stdout.splitlines()[0].split(",")
                    result["gpu"], result["gpu_temp"] = [float(x.strip()) for x in values]
                except (OSError, ValueError, IndexError, subprocess.TimeoutExpired):
                    pass
            for sensor in self.extra.hardware():
                identifier = sensor.get("Identifier", "").lower()
                if sensor.get("SensorType") == "Temperature" and sensor.get("Value") is not None:
                    if "cpu" in identifier and result["cpu_temp"] is None:
                        result["cpu_temp"] = float(sensor["Value"])
                    elif "gpu" in identifier and result["gpu_temp"] is None:
                        result["gpu_temp"] = float(sensor["Value"])
            self.pc_history.append({**result, "time": now})
            return result
        return self.cached("pc", 5, sample)

    def disk(self, path=""):
        if self.demo:
            return {"percent": 48, "free": 260 * 1024**3, "total": 500 * 1024**3}
        path = path or Path.home().anchor
        def sample():
            try:
                usage = psutil.disk_usage(path)
                return {"percent": usage.percent, "free": usage.free, "total": usage.total}
            except (OSError, ValueError):
                return {"percent": None, "free": None, "total": None}
        return self.cached(("disk", path), 5, sample)

    def weather(self, latitude, longitude):
        if self.demo:
            return {"temperature_2m": 23, "relative_humidity_2m": 48, "weather_code": 1}
        lat, lon = float(latitude), float(longitude)
        if not -90 <= lat <= 90 or not -180 <= lon <= 180:
            raise ValueError("Invalid coordinates")

        def fetch():
            response = self.session.get("https://api.open-meteo.com/v1/forecast", params={
                "latitude": lat, "longitude": lon,
                "current": "temperature_2m,relative_humidity_2m,weather_code"}, timeout=8)
            response.raise_for_status()
            return response.json()["current"]
        return self.cached(("weather", lat, lon), 600, fetch)

    def service(self, url):
        if self.demo:
            return True, 42
        http_url(url)

        def fetch():
            start = time.monotonic()
            try:
                response = self.session.get(url, timeout=4, stream=True)
                with response:
                    return response.status_code < 400, round((time.monotonic() - start) * 1000)
            except requests.RequestException:
                return False, 0
        return self.cached(("service", url), 15, fetch)

    def calendar(self, source):
        if self.demo:
            return "Project review", "16:30"

        def fetch():
            if source.startswith(("http://", "https://")):
                response = self.session.get(http_url(source), timeout=8)
                response.raise_for_status()
                return response.content
            return Path(source).read_bytes()
        blob = self.cached(("calendar", source), 300, fetch)
        from icalendar import Calendar
        import recurring_ical_events
        now = timesource.now()
        events = recurring_ical_events.of(Calendar.from_ical(blob)).between(now, now + timedelta(days=7))
        candidates = []
        for event in events:
            if str(event.get("STATUS", "")) == "CANCELLED":
                continue
            start = event.decoded("DTSTART")
            all_day = not isinstance(start, datetime)
            if all_day:
                start = datetime.combine(start, dt_time(), tzinfo=now.tzinfo)
            elif start.tzinfo is None:
                start = start.replace(tzinfo=now.tzinfo)
            if start >= now or (all_day and start.date() == now.date()):
                candidates.append((start, str(event.get("SUMMARY", "Event")), all_day))
        if not candidates:
            return "No events", "7 days"
        start, title, all_day = min(candidates, key=lambda x: x[0])
        when = "All day" if all_day else start.astimezone().strftime("%H:%M")
        if start.date() != now.date():
            when = start.strftime("%d/%m ") + when
        return title, when


class Renderer:
    def __init__(self, demo=False):
        self.providers = Providers(demo)

    def render(self, slot):
        from .content import EXTRA_KINDS
        if slot["kind"] in {k for k, _, _ in EXTRA_KINDS}:
            from .extensions import render_extra
            return render_extra(slot, self.providers)
        accent = ImageColor.getrgb(slot.get("color", "#64e6ca"))
        image = Image.new("RGB", (128, 128), slot.get("background", "#101b2b"))
        draw = ImageDraw.Draw(image)
        title = slot.get("title", "").strip()
        kind = slot["kind"]

        def label(text, y, size=12, color="#b8c4d5", center=False, bold=False):
            f = font(size, bold)
            while draw.textlength(str(text), font=f) > 112 and size > 10:
                size -= 1
                f = font(size, bold)
            x = (128 - draw.textlength(str(text), font=f)) / 2 if center else 8
            draw.text((x, y), str(text), font=f, fill=color)

        label(title or {"pc": "SYSTEM", "clock": "LOCAL TIME", "text": "NOTE", "weather": "WEATHER",
                        "countdown": "COUNTDOWN", "calendar": "CALENDAR", "service": "STATUS"}.get(kind, "KEEPER"),
              5, 13, accent, center=True, bold=True)
        if kind == "clock":
            now = timesource.now(ZoneInfo(slot.get("timezone", "Europe/Madrid")))
            label(now.strftime("%H:%M"), 41, 34, "white", center=True, bold=True)
            label(now.strftime("%d / %m / %Y"), 88, 13, center=True)
        elif kind == "text":
            size = max(10, min(40, int(slot.get("font_size", 24))))
            f = font(size, True)
            lines = wrap_text(draw, slot.get("text", ""), f, 112)
            while len(lines) * (size + 2) > 85 and size > 10:
                size -= 1
                f = font(size, True)
                lines = wrap_text(draw, slot.get("text", ""), f, 112)
            for i, line in enumerate(lines[:85 // (size + 2)]):
                draw.text((8, 35 + i * (size + 2)), line, font=f, fill="white")
            if slot.get("border"):
                draw.rectangle((0, 0, 127, 127), outline=accent, width=4)
        elif kind in {"pc", "pc_native"}:
            values = self.providers.pc()
            view = slot.get("pc_view", "usage")
            def graph(key, y, height=11, maximum=100):
                samples = list(self.providers.pc_history)[-60:]
                draw.line((8, y + height, 119, y + height), fill="#26334b")
                if len(samples) < 2:
                    return
                start, end = samples[0]["time"], samples[-1]["time"]
                maximum = max(1, maximum)
                previous = None
                for sample in samples:
                    value = sample.get(key)
                    if value is None:
                        previous = None
                        continue
                    point = (8 + 111 * (sample["time"] - start) / max(.001, end - start),
                             y + height - max(0, min(1, value / maximum)) * height)
                    if previous:
                        draw.line((previous, point), fill=accent, width=1)
                    previous = point

            if view == "network":
                for i, (key, title) in enumerate([("download", "RX / DOWNLOAD"), ("upload", "TX / UPLOAD")]):
                    y = 35 + i * 44
                    value = values.get(key)
                    label(title, y, 12)
                    label(format_rate(value), y + 13, 18, "white", bold=True)
                    peak = max((s.get(key) or 0 for s in self.providers.pc_history), default=1)
                    graph(key, y + 36, 6, peak)
                return image
            if view == "storage":
                disk = self.providers.disk(slot.get("pc_disk", ""))
                values = {**values, "disk": disk["percent"]}
                drive = slot.get("pc_disk", "") or Path.home().anchor
                label(str(drive) + " · FREE", 35, 12)
                free = disk["free"]
                label("N/A" if free is None else f"{free / 1024**3:.1f} GiB", 49, 22, "white", bold=True)
            keys = ["cpu_temp", "gpu_temp"] if view == "temperature" else ["disk", "ram"] if view == "storage" else ["cpu", "ram", "gpu"]
            for i, key in enumerate(keys):
                value = values[key]
                y = (75 if view == "storage" else 37) + i * 27
                label(key.replace("_temp", "").upper(), y, 13, bold=True)
                suffix = "°C" if key.endswith("_temp") else "%"
                label("N/A" if value is None else f"{value:.0f}{suffix}", y, 12, "white", center=True, bold=True)
                if view == "history":
                    graph(key, y + 14)
                    continue
                draw.rounded_rectangle((8, y + 19, 119, y + 22), radius=1, fill="#26334b")
                if value is not None and value > 0:
                    draw.rectangle((8, y + 19, 8 + max(1, min(111, int(value * 1.11))), y + 22), fill=accent)
        elif kind == "weather":
            data = self.providers.weather(slot["latitude"], slot["longitude"])
            label(f"{data['temperature_2m']:.0f}°", 35, 40, "white", center=True, bold=True)
            code = data["weather_code"]
            state = "CLEAR" if code == 0 else "CLOUDY" if code < 4 else "FOG" if code < 50 else "RAIN / SNOW"
            label(state, 85, 13, center=True)
            label(f"Humidity {data['relative_humidity_2m']}%", 104, 12, center=True)
        elif kind == "countdown":
            target = datetime.fromisoformat(slot["target"])
            if target.tzinfo is None:
                target = target.astimezone()
            seconds = max(0, int((target - timesource.now(timezone.utc)).total_seconds()))
            days, rem = divmod(seconds, 86400)
            hours, rem = divmod(rem, 3600)
            minutes, secs = divmod(rem, 60)
            value = f"{days}d {hours}h" if days else f"{hours:02}:{minutes:02}" if hours else f"{minutes:02}:{secs:02}"
            label(value, 43, 32, "white", center=True, bold=True)
            label("FINISHED" if seconds == 0 else "TIME LEFT", 94, 12, center=True)
        elif kind == "service":
            ok, latency = self.providers.service(slot["url"])
            color = "#64e6ca" if ok else "#ff8091"
            draw.ellipse((54, 37, 74, 57), fill=color)
            label("ONLINE" if ok else "OFFLINE", 67, 22, color, center=True, bold=True)
            label(f"{latency} ms" if ok else "No response", 103, 12, center=True)
        elif kind == "calendar":
            summary, when = self.providers.calendar(slot.get("url") or slot.get("path"))
            label(when, 35, 19, "white", bold=True)
            for i, line in enumerate(wrap_text(draw, summary, font(14), 112)[:3]):
                label(line, 65 + i * 17, 14)
        else:
            label("DIVOOM", 43, 23, "white", center=True, bold=True)
            label("KEEPER STUDIO", 81, 13, center=True)
        return image


def format_rate(value):
    if value is None:
        return "Measuring…"
    if value >= 1024**2:
        return f"{value / 1024**2:.1f} MiB/s"
    if value >= 1024:
        return f"{value / 1024:.1f} KiB/s"
    return f"{value:.0f} B/s"

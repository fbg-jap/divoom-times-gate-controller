from __future__ import annotations

import base64
from concurrent.futures import ThreadPoolExecutor, as_completed
import io
import ipaddress
import socket
import time

from PIL import Image, ImageOps, ImageSequence
import requests


def valid_ip(value):
    ip = ipaddress.ip_address(value.strip())
    if ip.version != 4:
        raise ValueError("Enter an IPv4 address")
    return str(ip)


class DeviceError(RuntimeError):
    pass


# Hardware 400 serves POST /post on port 80; hardware 402 serves POST /divoom_api on port 9000.
ENDPOINTS = ((80, "/post"), (9000, "/divoom_api"))


def endpoint_candidates(port=0):
    port = int(port or 0)
    if not port:
        return list(ENDPOINTS)
    return [(port, dict(ENDPOINTS).get(port, "/post"))]


def reply_ok(body):
    if not isinstance(body, dict):
        return False
    code = body["error_code"] if "error_code" in body else body.get("ReturnCode")
    return code in (0, "0")


CONNECT_TIMEOUT = 2          # seconds to establish the TCP connection; a device that is up accepts at once
RETRY_BACKOFF = (0.3, 1.0)   # waits before the 1st and 2nd retry of a command that did not connect or answer


class Client:
    def __init__(self, ip, session=None, timeout=10, port=0, token="", retries=len(RETRY_BACKOFF), sleep=time.sleep):
        self.ip = valid_ip(ip)
        self.candidates = endpoint_candidates(port)
        self.token = str(token or "").strip()
        # Keep the original sender's one-request-per-connection transport.
        # Device acceptance alone does not guarantee that a frame was displayed.
        self.session = session if session is not None else requests
        self.timeout = timeout
        self.retries = max(0, int(retries))
        self.sleep = sleep
        self.last_pic_id = 0

    def command(self, payload):
        selecting_panel = payload.get("Command") == "Channel/SetClockSelectId" and "LcdIndex" in payload
        selecting_group = payload.get("Command") == "Channel/Set5LcdChannelType" and payload.get("ChannelType") == 1
        if (selecting_panel or selecting_group) and int(payload.get("LcdIndependence", 0)) <= 0:
            raise DeviceError("A valid native group is missing. Group 0 alters other screens. "
                              "Select PC Monitor from Divoom and use the data-only sending mode.")
        if self.token and "LocalToken" not in payload:
            payload = {**payload, "LocalToken": self.token}
        body = self._post(payload)
        if not reply_ok(body):
            raise DeviceError(f"{payload.get('Command')}: {body}")
        return body

    def _post(self, payload):
        # A command that neither connects nor answers is repeated (every command here is safe to repeat: a frame
        # upload carries its own PicID and offset), waiting a little longer each time.
        for attempt in range(self.retries + 1):
            try:
                return self._post_once(payload)
            except (requests.ConnectionError, requests.Timeout):
                if attempt >= self.retries:
                    raise
                self.sleep(RETRY_BACKOFF[min(attempt, len(RETRY_BACKOFF) - 1)])

    def _post_once(self, payload):
        # Try each endpoint until one connects; remember it for later commands.
        last_error = None
        timeout = (min(CONNECT_TIMEOUT, self.timeout), self.timeout)
        for index, (port, path) in enumerate(self.candidates):
            try:
                host = self.ip if port == 80 else f"{self.ip}:{port}"
                response = self.session.post(f"http://{host}{path}", json=payload, timeout=timeout)
                response.raise_for_status()
                body = response.json()
            except (requests.ConnectionError, requests.Timeout) as error:
                last_error = error
                continue
            if len(self.candidates) > 1:
                self.candidates = [self.candidates[index]]
            return body
        raise last_error

    def send_frames(self, frames, panel, quality=85, speed=100, stop=None):
        if panel not in range(5) or not frames:
            raise ValueError("Invalid screen or animation")
        # The working legacy app uses Unix seconds, not a wrapped microsecond ID.
        # Multiple uploads within one second must still have increasing IDs.
        pic_id = max(int(time.time()), self.last_pic_id + 1)
        self.last_pic_id = pic_id
        for offset, frame in enumerate(frames):
            if stop is not None and stop.is_set():
                raise InterruptedError("Send cancelled")
            buf = io.BytesIO()
            frame.convert("RGB").save(buf, "JPEG", quality=max(30, min(100, int(quality))))
            self.command({"Command": "Draw/SendHttpGif", "LcdArray": [int(i == panel) for i in range(5)],
                          "PicNum": len(frames), "PicOffset": offset, "PicID": pic_id,
                          "PicSpeed": max(1, int(speed)), "PicWidth": 128,
                          "PicData": base64.b64encode(buf.getvalue()).decode("ascii")})
            # Still images and the final GIF frame also need the legacy pacing.
            if stop is not None:
                stop.wait(0.1)
            else:
                time.sleep(0.1)


def resize(image, fit="contain"):
    if fit == "stretch":
        # Byte-for-byte compatible preprocessing for migrated legacy profiles.
        return image.convert("RGB").resize((128, 128), Image.Resampling.LANCZOS)
    image = ImageOps.exif_transpose(image)
    if image.mode in ("RGBA", "LA") or "transparency" in image.info:
        rgba = image.convert("RGBA")
        base = Image.new("RGBA", rgba.size, "black")
        image = Image.alpha_composite(base, rgba).convert("RGB")
    image = image.convert("RGB")
    if fit == "cover":
        return ImageOps.fit(image, (128, 128), method=Image.Resampling.LANCZOS)
    return ImageOps.pad(image, (128, 128), method=Image.Resampling.LANCZOS, color="black")


def media_frames(path, fit="contain", frame_step=1):
    frames = []
    with Image.open(path) as image:
        count = getattr(image, "n_frames", 1)
        step = max(1, int(frame_step))
        if (count + step - 1) // step > 600:
            raise ValueError("Maximum 600 frames per send. Increase the frame step.")
        for i, frame in enumerate(ImageSequence.Iterator(image)):
            if i % step == 0:
                frames.append(resize(frame.copy(), fit))
    return frames


def _mac(value):
    return "".join(c for c in str(value or "").lower() if c in "0123456789abcdef")


def locate(device):
    """Current LAN address of a known device according to Divoom's cloud list (matched by MAC, else device id), or ''."""
    mac, device_id = _mac(device.get("mac")), int(device.get("device_id") or 0)
    if not mac and not device_id:
        return ""
    for item in discover(cloud=True):
        same = (mac and _mac(item.get("mac")) == mac) or (device_id and int(item.get("device_id") or 0) == device_id)
        if same:
            try:
                return valid_ip(item.get("ip", ""))
            except ValueError:
                return ""
    return ""


def probe(ip, timeout=.5, port=0, token=""):
    try:
        return Client(ip, timeout=timeout, port=port, token=token, retries=0).command({"Command": "Channel/GetAllConf"})
    except Exception:
        return None


def discover(seed="", cloud=False):
    if cloud:
        response = requests.post("https://app.divoom-gz.com/Device/ReturnSameLANDevice", timeout=10)
        response.raise_for_status()
        body = response.json()
        if body.get("ReturnCode") not in (0, "0"):
            raise DeviceError("Divoom did not return the device list")
        return [{"ip": d.get("DevicePrivateIP", ""), "name": d.get("DeviceName", "Divoom"),
                 "mac": d.get("DeviceMac", ""), "device_id": d.get("DeviceId", 0)}
                for d in body.get("DeviceList", [])]
    addresses = [seed] if seed else []
    try:
        addresses.extend(x[4][0] for x in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET))
    except OSError:
        pass
    prefixes = set()
    for address in addresses:
        try:
            ip = ipaddress.ip_address(address)
            if ip.version == 4 and ip.is_private and not ip.is_loopback and not ip.is_link_local:
                prefixes.add(".".join(address.split(".")[:3]))
        except ValueError:
            pass
    if not prefixes:
        raise ValueError("No local subnet found. Enter the device IP.")
    found = []
    with ThreadPoolExecutor(max_workers=32) as pool:
        futures = {pool.submit(probe, f"{prefix}.{i}"): f"{prefix}.{i}"
                   for prefix in prefixes for i in range(1, 255)}
        for f in as_completed(futures):
            if f.result() is not None:
                found.append({"ip": futures[f], "name": "Compatible Divoom"})
    return sorted(found, key=lambda d: tuple(map(int, d["ip"].split("."))))

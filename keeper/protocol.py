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
        raise ValueError("Introduce una dirección IPv4")
    return str(ip)


class DeviceError(RuntimeError):
    pass


class Client:
    def __init__(self, ip, session=None, timeout=10):
        self.ip = valid_ip(ip)
        # Keep the original sender's one-request-per-connection transport.
        # Device acceptance alone does not guarantee that a frame was displayed.
        self.session = session if session is not None else requests
        self.timeout = timeout
        self.last_pic_id = 0

    def command(self, payload):
        selecting_panel = payload.get("Command") == "Channel/SetClockSelectId" and "LcdIndex" in payload
        selecting_group = payload.get("Command") == "Channel/Set5LcdChannelType" and payload.get("ChannelType") == 1
        if (selecting_panel or selecting_group) and int(payload.get("LcdIndependence", 0)) <= 0:
            raise DeviceError("Falta un grupo nativo válido. El grupo 0 altera otras pantallas. "
                              "Selecciona PC Monitor desde Divoom y usa el modo de solo envío de datos.")
        response = self.session.post(f"http://{self.ip}/post", json=payload, timeout=self.timeout)
        response.raise_for_status()
        body = response.json()
        if not isinstance(body, dict) or body.get("error_code") not in (0, "0"):
            raise DeviceError(f"{payload.get('Command')}: {body}")
        return body

    def send_frames(self, frames, panel, quality=85, speed=100, stop=None):
        if panel not in range(5) or not frames:
            raise ValueError("Pantalla o animación inválida")
        # The working legacy app uses Unix seconds, not a wrapped microsecond ID.
        # Multiple uploads within one second must still have increasing IDs.
        pic_id = max(int(time.time()), self.last_pic_id + 1)
        self.last_pic_id = pic_id
        for offset, frame in enumerate(frames):
            if stop is not None and stop.is_set():
                raise InterruptedError("Envío cancelado")
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
            raise ValueError("Máximo 600 fotogramas por envío. Aumenta el salto de fotogramas.")
        for i, frame in enumerate(ImageSequence.Iterator(image)):
            if i % step == 0:
                frames.append(resize(frame.copy(), fit))
    return frames


def probe(ip, timeout=.5):
    try:
        return Client(ip, timeout=timeout).command({"Command": "Channel/GetAllConf"})
    except Exception:
        return None


def discover(seed="", cloud=False):
    if cloud:
        response = requests.post("https://app.divoom-gz.com/Device/ReturnSameLANDevice", timeout=10)
        response.raise_for_status()
        body = response.json()
        if body.get("ReturnCode") not in (0, "0"):
            raise DeviceError("Divoom no devolvió la lista de dispositivos")
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
        raise ValueError("No se encontró una subred local. Introduce la IP del dispositivo.")
    found = []
    with ThreadPoolExecutor(max_workers=32) as pool:
        futures = {pool.submit(probe, f"{prefix}.{i}"): f"{prefix}.{i}"
                   for prefix in prefixes for i in range(1, 255)}
        for f in as_completed(futures):
            if f.result() is not None:
                found.append({"ip": futures[f], "name": "Divoom compatible"})
    return sorted(found, key=lambda d: tuple(map(int, d["ip"].split("."))))

"""Online time: an SNTP (RFC 4330) client with an HTTPS Date-header fallback, and the shared TimeSource.

Everything is opt-in (integrations.timesync.enabled) and stdlib-only except the HTTPS fallback, which uses requests.
The offset is only ever applied to wall-clock reads (TimeSource.time/now); time.monotonic is never touched.
No function here raises into its caller: failures become a status error and the last good offset is kept.
"""
from __future__ import annotations

import email.utils
import os
import socket
import struct
import threading
import time
from datetime import datetime, timezone

NTP_EPOCH = 2208988800          # seconds between 1900-01-01 and 1970-01-01
MAX_DELAY = 2.0                 # a round trip slower than this gives an unreliable offset
MAX_OFFSET = 86400.0            # more than a day away is a bad sample, not a clock correction
STALE_AFTER = 6 * 3600          # without a successful sync for this long the offset is ignored
ATTEMPT_BUDGET = 8.0            # whole NTP attempt
PACKET_TIMEOUT = 2.5
HTTPS_TIMEOUT = 5.0
RETRY_FIRST, RETRY_MAX = 60.0, 900.0


class TimeSyncError(Exception):
    """A failure whose text is short and safe to show in the UI."""


def _to_ntp(value):
    seconds = int(value)
    return ((seconds + NTP_EPOCH) << 32) | int((value - seconds) * (1 << 32))


def _from_ntp(raw):
    return (raw >> 32) - NTP_EPOCH + (raw & 0xFFFFFFFF) / float(1 << 32)


def sntp_query(address, timeout=PACKET_TIMEOUT, clock=time.time, nonce=None):
    """One SNTP exchange with a resolved getaddrinfo tuple. Returns {offset, delay, stratum} in seconds."""
    family, kind, proto, _name, sockaddr = address
    nonce = int.from_bytes(os.urandom(8), "big") if nonce is None else nonce
    packet = bytes([(0 << 6) | (4 << 3) | 3]) + bytes(39) + struct.pack(">Q", nonce)
    try:
        sock = socket.socket(family, socket.SOCK_DGRAM)
    except OSError as error:
        raise TimeSyncError("socket: " + type(error).__name__) from None
    try:
        sock.settimeout(timeout)
        end = time.monotonic() + timeout
        t1 = clock()
        try:
            sock.sendto(packet, sockaddr)
            while True:
                data, sender = sock.recvfrom(1024)
                t4 = clock()
                if sender[0] == sockaddr[0]:
                    break
                sock.settimeout(max(0.01, end - time.monotonic()))   # a stray datagram from someone else
        except socket.timeout:
            raise TimeSyncError("no reply (UDP 123 may be blocked)") from None
        except OSError as error:
            raise TimeSyncError("network: " + type(error).__name__) from None
    finally:
        sock.close()
    if len(data) < 48:
        raise TimeSyncError("truncated reply")
    flags, stratum = data[0], data[1]
    leap, version, mode = flags >> 6, (flags >> 3) & 7, flags & 7
    originate, receive, transmit = struct.unpack(">QQQ", data[24:48])
    if originate != nonce:
        raise TimeSyncError("reply does not match the request")
    if mode != 4:
        raise TimeSyncError("not a server reply")
    if version not in (3, 4):
        raise TimeSyncError("unsupported NTP version")
    if stratum == 0:
        code = "".join(chr(b) if 32 <= b < 127 else "?" for b in data[12:16]).strip()
        raise TimeSyncError(f"server refused (Kiss-o'-Death {code})")
    if leap == 3:
        raise TimeSyncError("server clock is unsynchronised")
    if not 1 <= stratum <= 15:
        raise TimeSyncError("invalid stratum")
    if transmit == 0:
        raise TimeSyncError("reply without a transmit timestamp")
    t2, t3 = _from_ntp(receive), _from_ntp(transmit)
    delay = (t4 - t1) - (t3 - t2)
    if delay < 0 or delay >= MAX_DELAY:
        raise TimeSyncError("unusable round-trip delay")
    return {"offset": ((t2 - t1) + (t3 - t4)) / 2, "delay": delay, "stratum": stratum}


def combine(samples):
    """Median offset when there are 3+ good samples, otherwise the sample with the lowest delay."""
    if len(samples) >= 3:
        ordered = sorted(samples, key=lambda s: s["offset"])
        return ordered[len(ordered) // 2]
    return min(samples, key=lambda s: s["delay"])


def sntp_sample(servers, budget=ATTEMPT_BUDGET, clock=time.time, query=sntp_query, resolve=socket.getaddrinfo):
    """Query up to 3 addresses (over all servers, IPv4/IPv6) within the budget; returns the combined sample."""
    deadline = time.monotonic() + budget
    good, errors, tried = [], [], 0
    for server in servers:
        if len(good) >= 3 or tried >= 6 or time.monotonic() >= deadline:
            break
        try:
            infos = resolve(server, 123, type=socket.SOCK_DGRAM)
        except OSError:
            errors.append(f"{server}: name not found")
            continue
        seen = set()
        for info in infos:
            if info[4][0] in seen:
                continue
            seen.add(info[4][0])
            remaining = deadline - time.monotonic()
            if len(good) >= 3 or tried >= 6 or remaining <= 0.05:
                break
            tried += 1
            try:
                sample = query(info, min(PACKET_TIMEOUT, remaining), clock)
                sample["server"] = server
                good.append(sample)
            except TimeSyncError as error:
                errors.append(f"{server}: {error}")
            except Exception as error:   # defensive: never raise into the refresher
                errors.append(f"{server}: {type(error).__name__}")
    if not good:
        raise TimeSyncError("; ".join(errors[:3]) or "no time server reachable")
    return combine(good)


def https_sample(url, session=None, clock=time.time, timeout=HTTPS_TIMEOUT):
    """Offset from the Date header of an https URL (1 s resolution, so +0.5 s is assumed)."""
    if not str(url).lower().startswith("https://"):
        raise TimeSyncError("the time URL must be https")
    if session is None:
        import requests
        session = requests.Session()
    t1 = clock()
    try:
        response = session.get(url, timeout=timeout, allow_redirects=False, verify=True, stream=True)
    except Exception as error:
        raise TimeSyncError("https: " + type(error).__name__) from None
    t4 = clock()
    try:
        header = response.headers.get("Date")
    finally:
        try:
            response.close()
        except Exception:
            pass
    if not header:
        raise TimeSyncError("no Date header")
    try:
        moment = email.utils.parsedate_to_datetime(header)
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=timezone.utc)
        server = moment.timestamp()
    except (TypeError, ValueError, IndexError, OverflowError):
        raise TimeSyncError("invalid Date header") from None
    delay = t4 - t1
    if delay < 0 or delay > timeout:
        raise TimeSyncError("unusable round-trip delay")
    return {"offset": server + 0.5 - (t1 + t4) / 2, "delay": delay, "server": url}


class TimeSource:
    DEFAULTS = {"enabled": False, "source": "ntp", "servers": ["pool.ntp.org"], "https_url": "https://www.cloudflare.com/",
                "interval_minutes": 60, "fallback_https": True, "sync_device": False}

    def __init__(self, clock=time.time, mono=time.monotonic):
        self._clock, self._mono = clock, mono
        self._lock = threading.RLock()
        self._sync_lock = threading.Lock()
        self._conf = dict(self.DEFAULTS)
        self._offset = 0.0
        self._good_mono = None
        self._info = {"server": None, "delay": None, "synced_at": None, "source": None}
        self._error = None
        self._failures = 0
        self._count = 0
        self._thread = None
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._ntp = sntp_sample
        self._https = https_sample

    monotonic_unchanged = True      # only wall-clock reads are corrected; time.monotonic is never adjusted

    @property
    def sync_count(self):
        return self._count

    @property
    def sync_device(self):
        return bool(self._conf.get("sync_device"))

    def _live_offset(self):
        with self._lock:
            if not self._conf["enabled"] or self._good_mono is None or self._mono() - self._good_mono > STALE_AFTER:
                return 0.0
            return self._offset

    def time(self):
        try:
            return self._clock() + self._live_offset()
        except Exception:
            return time.time()

    def now(self, tz=None):
        moment = datetime.fromtimestamp(self.time(), timezone.utc)
        return moment.astimezone(tz) if tz is not None else moment.astimezone()

    def synced(self):
        """True when an offset is currently being applied (enabled, synced, not stale)."""
        with self._lock:
            return bool(self._conf["enabled"] and self._good_mono is not None and self._mono() - self._good_mono <= STALE_AFTER)

    def status(self):
        with self._lock:
            have = self._good_mono is not None
            stale = bool(self._conf["enabled"] and have and self._mono() - self._good_mono > STALE_AFTER)
            return {"enabled": bool(self._conf["enabled"]), "source": self._info["source"] or self._conf["source"],
                    "server": self._info["server"], "offset_ms": round(self._offset * 1000, 1) if have else None,
                    "delay_ms": round(self._info["delay"] * 1000, 1) if have and self._info["delay"] is not None else None,
                    "synced_at": self._info["synced_at"], "error": self._error, "stale": stale}

    # configuration -----------------------------------------------------------------------------------------------
    def configure(self, conf):
        try:
            new = {**self.DEFAULTS, **(conf if isinstance(conf, dict) else {})}
            new["servers"] = [s for s in new["servers"] if isinstance(s, str) and s.strip()] if isinstance(new["servers"], list) else []
            new["servers"] = new["servers"] or list(self.DEFAULTS["servers"])
            new["enabled"], new["fallback_https"], new["sync_device"] = bool(new["enabled"]), bool(new["fallback_https"]), bool(new["sync_device"])
            new["source"] = "https" if new["source"] == "https" else "ntp"
            new["interval_minutes"] = max(5, min(1440, int(new["interval_minutes"])))
            with self._lock:
                old = self._conf
                self._conf = new
                changed = {k: old.get(k) for k in ("enabled", "source", "servers", "https_url", "fallback_https")} != \
                          {k: new[k] for k in ("enabled", "source", "servers", "https_url", "fallback_https")}
                if changed and not new["enabled"]:
                    self._offset, self._good_mono, self._error = 0.0, None, None
                    self._info = {"server": None, "delay": None, "synced_at": None, "source": None}
                    self._failures = 0
            if not new["enabled"]:
                self.stop()
            elif self._thread and self._thread.is_alive():
                if changed:
                    self._failures = 0
                    self._wake.set()        # resync right away with the new settings
            else:
                self._failures = 0
                self.start()
        except Exception as error:
            self._error = "invalid settings: " + type(error).__name__

    # syncing -----------------------------------------------------------------------------------------------------
    def sync_now(self):
        """One synchronisation attempt (any thread). Never raises; returns True when a good offset was applied."""
        try:
            with self._sync_lock:
                return self._sync_once()
        except Exception as error:
            with self._lock:
                self._error = "unexpected: " + type(error).__name__
            return False

    def _sync_once(self):
        with self._lock:
            conf = dict(self._conf)
        errors, sample, used = [], None, None
        if conf["source"] == "ntp":
            try:
                sample, used = self._ntp(conf["servers"], clock=self._clock), "ntp"
            except TimeSyncError as error:
                errors.append("NTP " + str(error))
            except Exception as error:
                errors.append("NTP " + type(error).__name__)
        if sample is None and (conf["source"] == "https" or conf["fallback_https"]):
            try:
                sample, used = self._https(conf["https_url"], clock=self._clock), "https"
            except TimeSyncError as error:
                errors.append("HTTPS " + str(error))
            except Exception as error:
                errors.append("HTTPS " + type(error).__name__)
        with self._lock:
            if sample is not None and abs(sample["offset"]) > MAX_OFFSET:
                errors.append(f"offset of {sample['offset']:.0f} s rejected")
                sample = None
            if sample is None:
                self._error = "; ".join(errors) or "no result"
                return False
            self._offset, self._good_mono, self._error = float(sample["offset"]), self._mono(), None
            self._info = {"server": sample.get("server"), "delay": sample.get("delay"), "source": used,
                          "synced_at": self._clock() + self._offset}
            self._count += 1
            return True

    @staticmethod
    def retry_delay(failures):
        """Seconds to wait after the Nth consecutive failure (1-based): 60, 120, 240, ... capped at 15 min."""
        return min(RETRY_MAX, RETRY_FIRST * 2 ** max(0, failures - 1))

    def _run(self, stop, wake):
        while not stop.is_set():
            wake.clear()
            if self.sync_now():
                self._failures, wait = 0, self._conf["interval_minutes"] * 60
            else:
                self._failures += 1
                wait = self.retry_delay(self._failures)
            wake.wait(wait)

    def start(self):
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            self._stop, self._wake = threading.Event(), threading.Event()
            self._thread = threading.Thread(target=self._run, args=(self._stop, self._wake), name="keeper-timesync", daemon=True)
            self._thread.start()

    def stop(self, wait=False):
        with self._lock:
            thread, stop, wake = self._thread, self._stop, self._wake
            self._thread = None
        stop.set()
        wake.set()
        if wait and thread and thread is not threading.current_thread():
            thread.join(timeout=2)


timesource = TimeSource()

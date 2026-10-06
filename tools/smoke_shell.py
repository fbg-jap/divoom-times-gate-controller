#!/usr/bin/env python3
"""Smoke test for the browser shell (a built binary or `python app.py --ui web`). Needs only the stdlib and requests.

    tools/smoke_shell.py dist/DivoomKeeperStudioWeb-3.1.1-x86_64.AppImage --appimage-extract-and-run
    tools/smoke_shell.py python app.py --ui web

The command is started with --demo --minimized --config-dir <tmp> --port <free> --print-launch-url; the script
reads the one-time launch URL, redeems it, checks the portal and quits the app through /api/quit.
"""
import argparse
import os
import queue
import re
import socket
import subprocess
import sys
import tempfile
import threading
import time

import requests

LAUNCH_URL = re.compile(r"http://127\.0\.0\.1:(\d+)/#launch=(\S+)")


class SmokeError(Exception):
    pass


def build_command(command, config_dir, port):
    return [*command, "--demo", "--minimized", "--config-dir", str(config_dir), "--port", str(port), "--print-launch-url"]


def parse_launch_url(line):
    """(port, code) from a printed launch URL line, else None."""
    match = LAUNCH_URL.search(line)
    return (int(match.group(1)), match.group(2)) if match else None


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def check(condition, message):
    if not condition:
        raise SmokeError(message)


def run(command, startup_timeout=60, quit_timeout=15):
    with tempfile.TemporaryDirectory(prefix="keeper-smoke-") as config_dir:
        port = free_port()
        # The shell only prints a live launch URL to a pipe when this test-only variable is set.
        env = {**os.environ, "KEEPER_ALLOW_PIPED_LAUNCH_URL": "1"}
        proc = subprocess.Popen(build_command(command, config_dir, port), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, text=True, env=env)
        lines = queue.Queue()
        seen = []

        def pump():
            for line in proc.stdout:
                seen.append(line)
                lines.put(line)
            lines.put(None)

        threading.Thread(target=pump, daemon=True).start()
        try:
            return exercise(proc, lines, port, startup_timeout, quit_timeout)
        except SmokeError as error:
            raise SmokeError(f"{error}\n--- process output ---\n{''.join(seen)[-2000:]}")
        finally:
            if proc.poll() is None:
                proc.kill()
            proc.wait()


def exercise(proc, lines, port, startup_timeout, quit_timeout):
    deadline = time.monotonic() + startup_timeout
    found = None
    while found is None:
        try:
            line = lines.get(timeout=max(0.1, deadline - time.monotonic()))
        except queue.Empty:
            line = ""
        check(line is not None, f"the app exited before printing a launch URL (code {proc.poll()})")
        found = parse_launch_url(line) if line else None
        check(found or time.monotonic() < deadline, f"no launch URL within {startup_timeout} s")
    printed_port, code = found
    check(printed_port == port, f"launch URL uses port {printed_port}, expected {port}")
    base = f"http://127.0.0.1:{port}"
    while True:
        try:
            if requests.get(base + "/healthz", timeout=2).status_code == 200:
                break
        except requests.RequestException:
            pass
        check(proc.poll() is None, f"the app exited during startup (code {proc.poll()})")
        check(time.monotonic() < deadline, "/healthz did not answer in time")
        time.sleep(0.2)
    first = requests.post(base + "/api/launch", json={"code": code}, timeout=5)
    check(first.status_code == 200 and first.json().get("token"), f"POST /api/launch failed: {first.status_code} {first.text[:200]}")
    token = first.json()["token"]
    second = requests.post(base + "/api/launch", json={"code": code}, timeout=5)
    check(second.status_code == 401, f"second redemption of the launch code returned {second.status_code}, expected 401")
    state = requests.get(base + "/api/state", headers={"Authorization": "Bearer " + token}, timeout=10)
    check(state.status_code == 200, f"GET /api/state returned {state.status_code}")
    check(state.json().get("desktop") is True, "/api/state does not report desktop=true")
    page = requests.get(base + "/", timeout=5)
    check(page.status_code == 200 and '<div id="app"' in page.text, "GET / did not serve the web UI (missing '<div id=\"app\"')")
    quit_response = requests.post(base + "/api/quit", headers={"Authorization": "Bearer " + token}, timeout=5)
    check(quit_response.status_code == 200, f"POST /api/quit returned {quit_response.status_code}")
    try:
        code = proc.wait(quit_timeout)
    except subprocess.TimeoutExpired:
        raise SmokeError(f"the app did not exit within {quit_timeout} s after /api/quit")
    check(code == 0, f"the app exited with code {code}, expected 0")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--startup-timeout", type=float, default=60)
    parser.add_argument("command", nargs=argparse.REMAINDER, help="binary or interpreter command to start")
    args = parser.parse_args(argv)
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command:
        parser.error("give the binary path (or `python app.py --ui web`) to test")
    try:
        run(command, args.startup_timeout)
    except SmokeError as error:
        print(f"SMOKE FAIL: {error}", file=sys.stderr)
        return 1
    print("SMOKE OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())

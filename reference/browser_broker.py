#!/usr/bin/python3 -I
"""Open approved HTTPS login URLs outside the sandbox without general Win32 access."""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import pathlib
import signal
import socket
import stat
import subprocess
import sys
import threading
import urllib.parse


PR_SET_PDEATHSIG = 1
MAX_REQUEST = 16384
SOCKET_ENV = "BWRAP_BROWSER_SOCKET"
ALLOWED_DOMAINS = (
    "anthropic.com",
    "claude.ai",
    "openai.com",
    "chatgpt.com",
    "github.com",
    "accounts.google.com",
    "appleid.apple.com",
)


def die_with_parent() -> None:
    parent = os.getppid()
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(PR_SET_PDEATHSIG, signal.SIGTERM, 0, 0, 0) != 0:
        raise OSError(ctypes.get_errno(), "prctl failed")
    if os.getppid() != parent:
        raise RuntimeError("parent exited during broker startup")


def approved_url(raw_url: str) -> str:
    if not raw_url or len(raw_url) > 8192:
        raise ValueError("invalid URL length")
    if any(ord(character) < 0x20 or ord(character) == 0x7F for character in raw_url):
        raise ValueError("URL contains a control character")
    parsed = urllib.parse.urlsplit(raw_url)
    if parsed.scheme.lower() != "https" or not parsed.hostname:
        raise ValueError("only HTTPS URLs are allowed")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("URL credentials are not allowed")
    if parsed.port not in (None, 443):
        raise ValueError("non-default HTTPS ports are not allowed")
    hostname = parsed.hostname.rstrip(".").lower()
    if not any(
        hostname == domain or hostname.endswith("." + domain)
        for domain in ALLOWED_DOMAINS
    ):
        raise ValueError("URL host is not approved")
    return raw_url


def receive_request(client: socket.socket) -> dict[str, object]:
    with client.makefile("rb") as stream:
        line = stream.readline(MAX_REQUEST + 1)
    if not line or len(line) > MAX_REQUEST or not line.endswith(b"\n"):
        raise ValueError("invalid broker request")
    request = json.loads(line)
    if not isinstance(request, dict):
        raise ValueError("invalid broker request")
    return request


def launch_browser(url: str) -> None:
    home = pathlib.Path.home()
    launcher = home / ".local/bin/claude-guard-browser"
    expected = home / ".local/lib/claude-clash-guard/claude_guard.py"
    if launcher.resolve(strict=True) != expected or not expected.is_file():
        raise RuntimeError("dedicated browser launcher target changed")
    for path in (expected, *[p for p in expected.parents if p.is_relative_to(home)]):
        metadata = path.stat()
        if metadata.st_uid != os.getuid() or metadata.st_mode & 0o022:
            raise RuntimeError("dedicated browser launcher ownership or mode changed")
    result = subprocess.run(
        ["/usr/bin/python3", "-I", str(launcher), url],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=50,
    )
    if result.returncode:
        raise RuntimeError("dedicated browser launcher failed")


def handle_client(client: socket.socket) -> None:
    with client:
        client.settimeout(55)
        allowed = False
        try:
            request = receive_request(client)
            if set(request) != {"action", "url"} or request.get("action") != "open_https":
                raise ValueError("unsupported broker action")
            raw_url = request.get("url")
            if not isinstance(raw_url, str):
                raise ValueError("invalid URL")
            launch_browser(approved_url(raw_url))
            allowed = True
        except Exception:
            pass
        try:
            client.sendall(b"OK\n" if allowed else b"NO\n")
        except OSError:
            pass


def serve(socket_path: str) -> None:
    parent = os.path.dirname(socket_path)
    if not parent or not os.path.isdir(parent):
        raise ValueError("broker socket directory is missing")
    parent_status = os.lstat(parent)
    if (
        not stat.S_ISDIR(parent_status.st_mode)
        or parent_status.st_uid != os.getuid()
        or parent_status.st_mode & 0o077
    ):
        raise ValueError("broker socket directory is not private")
    if os.path.lexists(socket_path):
        raise ValueError("broker socket path already exists")

    os.umask(0o077)
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    listener.bind(socket_path)
    listener.listen(8)
    stopping = threading.Event()
    slots = threading.BoundedSemaphore(2)

    def run_client(client_socket: socket.socket) -> None:
        try:
            handle_client(client_socket)
        finally:
            slots.release()

    def stop(_signum: int, _frame: object) -> None:
        stopping.set()
        listener.close()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    print("READY", flush=True)
    try:
        while not stopping.is_set():
            try:
                client, _ = listener.accept()
            except OSError:
                break
            if not slots.acquire(blocking=False):
                client.close()
                continue
            threading.Thread(target=run_client, args=(client,), daemon=True).start()
    finally:
        listener.close()
        try:
            os.unlink(socket_path)
        except FileNotFoundError:
            pass


def client(url: str) -> int:
    socket_path = os.environ.get(SOCKET_ENV, "/run/agent-guard/browser.sock")
    request = json.dumps(
        {"action": "open_https", "url": url}, separators=(",", ":")
    ).encode() + b"\n"
    connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    connection.settimeout(60)
    try:
        connection.connect(socket_path)
        connection.sendall(request)
        with connection.makefile("rb") as stream:
            response = stream.readline(17)
    except OSError:
        response = b""
    finally:
        connection.close()
    if response == b"OK\n":
        return 0
    print("[browser-broker] URL was not opened", file=sys.stderr)
    return 1


def main() -> int:
    if len(sys.argv) >= 2 and sys.argv[1] == "host":
        parser = argparse.ArgumentParser()
        parser.add_argument("mode", choices=("host",))
        parser.add_argument("--socket", required=True)
        args = parser.parse_args()
        die_with_parent()
        serve(args.socket)
        return 0
    if len(sys.argv) != 2:
        print("[browser-broker] expected one HTTPS URL", file=sys.stderr)
        return 2
    return client(sys.argv[1])


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError, subprocess.SubprocessError):
        print("[browser-broker] unavailable", file=sys.stderr)
        raise SystemExit(1)

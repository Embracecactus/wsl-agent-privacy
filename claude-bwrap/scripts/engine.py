"""Route gating, native Claude release verification, and foreground process lifetime."""
from __future__ import annotations

import fcntl
import hashlib
import http.client
import json
import os
import pathlib
import re
import secrets
import selectors
import signal
import socket
import ssl
import stat
import subprocess
import sys
import threading
import time
from collections.abc import Callable

RELEASE_HOST = "downloads.claude.ai"
RELEASE_SIGNER = "31DDDE24DDFAB679F42D7BD2BAA929FF1A7ECACE"


class RouteGate:
    """Require a recent successful fixed-route attestation for relay connections."""

    def __init__(
        self,
        path: pathlib.Path,
        verifier: Callable[[], object],
        approval_ttl: float = 15.0,
        approved_at: float | None = None,
    ) -> None:
        self.path = path
        self.verifier = verifier
        self.approval_ttl = approval_ttl
        self.approved_until = approved_at + approval_ttl if approved_at is not None else 0.0
        self.listener: socket.socket | None = None
        self.stopping = threading.Event()
        self.thread: threading.Thread | None = None

    def start(self) -> None:
        if os.path.lexists(self.path):
            raise RuntimeError("route gate path already exists")
        listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        listener.bind(str(self.path))
        os.chmod(self.path, 0o600)
        listener.listen(8)
        listener.settimeout(0.5)
        self.listener = listener
        self.thread = threading.Thread(target=self._serve, daemon=True)
        self.thread.start()

    def _serve(self) -> None:
        assert self.listener is not None
        while not self.stopping.is_set():
            try:
                client, _ = self.listener.accept()
            except TimeoutError:
                continue
            except OSError:
                break
            with client:
                client.settimeout(20)
                allowed = False
                try:
                    with client.makefile("rb") as stream:
                        request = stream.readline(17)
                    if request == b"CHECK\n":
                        if time.monotonic() >= self.approved_until:
                            self.verifier()
                            self.approved_until = time.monotonic() + self.approval_ttl
                        allowed = True
                except Exception:
                    self.approved_until = 0.0
                    pass
                try:
                    client.sendall(b"OK\n" if allowed else b"NO\n")
                except OSError:
                    pass

    def close(self) -> None:
        self.stopping.set()
        if self.listener is not None:
            try:
                self.listener.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass  # A listener already closed by startup failure needs no wakeup.
            self.listener.close()
        if self.thread is not None:
            self.thread.join(timeout=1)
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass


def wait_ready(process: subprocess.Popen[str], timeout: float = 5.0) -> None:
    if process.stdout is None:
        raise RuntimeError("host relay readiness pipe is unavailable")
    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ)
    deadline = time.monotonic() + timeout
    try:
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError("host relay stopped during startup")
            events = selector.select(max(0.0, deadline - time.monotonic()))
            if events and process.stdout.readline().strip() == "READY":
                return
    finally:
        selector.close()
    raise RuntimeError("host relay did not become ready")


def native_release_target(entry: pathlib.Path, link_text: str | pathlib.Path) -> pathlib.Path:
    versions = entry.parents[1] / "share/claude/versions"
    # Relative native links are relative to the real bin directory, also in the staged view.
    target = pathlib.Path(os.path.abspath(entry.parent / link_text))
    if (
        target.parent != versions
        or versions.resolve(strict=True) != versions
        or not re.fullmatch(r"[0-9]{1,6}\.[0-9]{1,6}\.[0-9]{1,6}", target.name)
    ):
        raise RuntimeError("expected a managed native Claude release link")
    return target


def release_metadata(relay: pathlib.Path, path: str) -> bytes:
    # Even the host-side signature check can only reach the existing route-gated relay.
    host = RELEASE_HOST
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as stream:
        stream.settimeout(30)
        stream.connect(str(relay))
        connect = f"CONNECT {host}:443 HTTP/1.1\r\nHost: {host}:443\r\n\r\n"
        stream.sendall(connect.encode("ascii"))
        with http.client.HTTPResponse(stream, method="CONNECT") as response:
            response.begin()
            if response.status != 200:
                raise RuntimeError(f"release proxy returned HTTP {response.status}")
        context = ssl.create_default_context(cafile="/etc/ssl/certs/ca-certificates.crt")
        with context.wrap_socket(stream, server_hostname=host) as tls:
            request = f"GET {path} HTTP/1.1\r\nHost: {host}\r\nConnection: close\r\n\r\n"
            tls.sendall(request.encode("ascii"))
            with http.client.HTTPResponse(tls) as response:
                response.begin()
                if response.status != 200:
                    raise RuntimeError(f"release metadata {path} returned HTTP {response.status}")
                data = response.read(65537)
                if not 0 < len(data) <= 65536:
                    raise RuntimeError("invalid release metadata size")
                return data


def signed_release_checksum(runtime: pathlib.Path, relay: pathlib.Path, version: str) -> str:
    verify_dir = runtime / "verify"
    verify_dir.mkdir(mode=0o700)
    manifest = verify_dir / "manifest.json"
    signature = verify_dir / "manifest.json.sig"
    keyring = verify_dir / "release.gpg"
    prefix = f"/claude-code-releases/{version}"
    manifest.write_bytes(release_metadata(relay, f"{prefix}/manifest.json"))
    signature.write_bytes(release_metadata(relay, f"{prefix}/manifest.json.sig"))
    public_key = release_metadata(relay, "/keys/claude-code.asc")
    env = {"PATH": "/usr/bin:/bin", "LC_ALL": "C"}
    subprocess.run(
        [
            "/usr/bin/gpg", "--no-options", "--homedir", str(verify_dir),
            "--batch", "--output", str(keyring), "--dearmor",
        ],
        input=public_key, check=True, capture_output=True, env=env, timeout=10,
    )
    result = subprocess.run(
        [
            "/usr/bin/gpgv", "--homedir", str(verify_dir), "--keyring", str(keyring),
            "--status-fd", "1", str(signature), str(manifest),
        ],
        capture_output=True, text=True, env=env, timeout=10,
    )
    if result.returncode or not any(
        line.startswith("[GNUPG:] VALIDSIG ") and line.split()[-1] == RELEASE_SIGNER
        for line in result.stdout.splitlines()
    ):
        raise RuntimeError("Claude release manifest signature verification failed")
    release = json.loads(manifest.read_bytes())
    platform = {"x86_64": "linux-x64", "aarch64": "linux-arm64"}.get(os.uname().machine)
    if release["version"] != version or platform is None:
        raise RuntimeError("Claude release manifest does not match this installation")
    checksum = release["platforms"][platform]["checksum"]
    if not isinstance(checksum, str) or not re.fullmatch(r"[a-f0-9]{64}", checksum):
        raise RuntimeError("Claude release manifest has an invalid checksum")
    return checksum


def verify_release_file(selected: pathlib.Path, expected: str) -> os.stat_result:
    fd = os.open(selected, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as binary:
        status = os.fstat(fd)
        if (
            not stat.S_ISREG(status.st_mode)
            or status.st_uid != os.getuid()
            or not status.st_mode & stat.S_IXUSR
            or status.st_mode & 0o022
        ):
            raise RuntimeError("Claude update selected an unsafe executable")
        digest = hashlib.sha256()
        for chunk in iter(lambda: binary.read(1024 * 1024), b""):
            digest.update(chunk)
        if digest.hexdigest() != expected:
            raise RuntimeError("Claude executable failed its signed release checksum")
        return status


def activate_claude_update(
    entry: pathlib.Path,
    previous: pathlib.Path,
    staged: pathlib.Path,
    runtime: pathlib.Path,
    relay: pathlib.Path,
) -> pathlib.Path:
    selected = native_release_target(entry, staged.readlink())
    if tuple(map(int, selected.name.split("."))) < tuple(map(int, previous.name.split("."))):
        raise RuntimeError("Claude update selected an older release")
    verified = None
    if selected != previous:
        checksum = signed_release_checksum(runtime, relay, selected.name)
        verified = verify_release_file(selected, checksum)
    directory = os.open(entry.parent, os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        fcntl.flock(directory, fcntl.LOCK_EX)
        active = native_release_target(entry, os.readlink(entry.name, dir_fd=directory))
        if active not in (previous, selected):
            raise RuntimeError("Claude entry changed during update; retry from the active version")
        if verified is not None:
            current = selected.lstat()
            if not os.path.samestat(verified, current) or verified.st_ctime_ns != current.st_ctime_ns:
                raise RuntimeError("Claude executable changed after release verification")
        if active == selected:
            return active
        temporary = ".claude-update-" + secrets.token_hex(12)
        os.symlink(selected, temporary, dir_fd=directory)
        try:
            os.replace(temporary, entry.name, src_dir_fd=directory, dst_dir_fd=directory)
        finally:
            try:
                os.unlink(temporary, dir_fd=directory)
            except FileNotFoundError:
                pass
        return selected
    finally:
        os.close(directory)


def run_bwrap(command: list[str], env: dict[str, str]) -> int:
    previous_sigint = signal.signal(signal.SIGINT, signal.SIG_IGN)
    previous_sigquit = signal.signal(signal.SIGQUIT, signal.SIG_IGN)
    process: subprocess.Popen[bytes] | None = None
    termination_requested = False

    def terminate_child(_signum: int, _frame: object) -> None:
        nonlocal termination_requested
        termination_requested = True
        if process is not None and process.poll() is None:
            process.terminate()

    previous_sigterm = signal.signal(signal.SIGTERM, terminate_child)
    previous_sighup = signal.signal(signal.SIGHUP, terminate_child)
    try:
        process = subprocess.Popen(command, env=env)
        if termination_requested:
            process.terminate()
        return process.wait()
    finally:
        signal.signal(signal.SIGINT, previous_sigint)
        signal.signal(signal.SIGQUIT, previous_sigquit)
        signal.signal(signal.SIGTERM, previous_sigterm)
        signal.signal(signal.SIGHUP, previous_sighup)


def stop_broker(process: subprocess.Popen[str]) -> None:
    process.terminate()
    try:
        process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=2)

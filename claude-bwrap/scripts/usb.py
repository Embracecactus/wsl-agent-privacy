#!/usr/bin/python3 -I
"""Expose a narrow USB-only subset of Windows ADB to the isolated agent."""

from __future__ import annotations

import argparse
import base64
import ctypes
import hashlib
import json
import os
import pathlib
import re
import signal
import socket
import stat
import subprocess
import sys
import threading


PR_SET_PDEATHSIG = 1
SOCKET_ENV = "BWRAP_ADB_SOCKET"
ADB_PATH = pathlib.Path(os.environ.get("GUARD_ADB_EXE", "/unconfigured/adb.exe"))
ADB_RUNTIME_FILES = (
    ADB_PATH,
    ADB_PATH.with_name("AdbWinApi.dll"),
    ADB_PATH.with_name("AdbWinUsbApi.dll"),
)
MAX_REQUEST = 65536
MAX_OUTPUT = 16 * 1024 * 1024
MAX_RESPONSE = 24 * 1024 * 1024
COMMAND_TIMEOUT = 180

SERIAL_RE = re.compile(r"[A-Za-z0-9._-]{1,128}")
APPROVED_PROPERTIES = {
    "ro.build.flavor",
    "ro.build.version.sdk",
    "ro.debuggable",
    "sys.boot_completed",
}


class PolicyError(RuntimeError):
    pass


def die_with_parent() -> None:
    parent = os.getppid()
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(PR_SET_PDEATHSIG, signal.SIGTERM, 0, 0, 0) != 0:
        raise OSError(ctypes.get_errno(), "prctl failed")
    if os.getppid() != parent:
        raise RuntimeError("parent exited during broker startup")


def file_sha256(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def adb_runtime_hashes() -> dict[pathlib.Path, str]:
    try:
        return {path: file_sha256(path) for path in ADB_RUNTIME_FILES}
    except OSError as exc:
        raise RuntimeError("Windows ADB runtime is incomplete") from exc


def verify_adb_runtime(expected: dict[pathlib.Path, str]) -> None:
    if set(expected) != set(ADB_RUNTIME_FILES):
        raise PolicyError("ADB runtime manifest is invalid")
    for path, expected_hash in expected.items():
        if file_sha256(path) != expected_hash:
            raise PolicyError("ADB runtime changed during the session")


def windows_environment(proxy_port: int) -> dict[str, str]:
    proxy = f"http://127.0.0.1:{proxy_port}"
    env = dict(os.environ)
    for name in (
        "ANDROID_SERIAL",
        "ADB_VENDOR_KEYS",
        "ADB_TRACE",
        "ANDROID_LOG_TAGS",
        "ADB_LOCAL_TRANSPORT_MAX_PORT",
        "ADB_MDNS_OPENSCREEN",
    ):
        env.pop(name, None)
    overrides = {
        "HTTP_PROXY": proxy,
        "HTTPS_PROXY": proxy,
        "ALL_PROXY": proxy,
        "NO_PROXY": "localhost,127.0.0.1,::1",
        "ADB_SERVER_SOCKET": "tcp:127.0.0.1:5037",
        "ADB_MDNS_AUTO_CONNECT": "",
        "ADB_LIBUSB": "0",
    }
    env.update(overrides)
    forwarded = set(overrides)
    retained = [
        item
        for item in env.get("WSLENV", "").split(":")
        if item and item.split("/", 1)[0].upper() not in forwarded
    ]
    env["WSLENV"] = ":".join(
        [*retained, *(name + "/w" for name in sorted(forwarded))]
    )
    return env


def parse_selector(argv: list[str]) -> tuple[list[str], list[str]]:
    if not argv:
        raise PolicyError("ADB command is missing")
    if argv[0] == "-d":
        return ["-d"], argv[1:]
    if argv[0] == "-s":
        if len(argv) < 3 or not SERIAL_RE.fullmatch(argv[1]):
            raise PolicyError("invalid ADB serial")
        serial = argv[1]
        if ":" in serial or serial.lower().startswith("emulator-"):
            raise PolicyError("only USB serials are allowed")
        return ["-s", serial], argv[2:]
    if argv[0].startswith("-"):
        raise PolicyError("unsupported global ADB option")
    return [], argv


def approved_apk(raw: str, cwd: str) -> pathlib.Path:
    if not raw or "\x00" in raw or len(raw) > 4096:
        raise PolicyError("invalid APK path")
    candidate = pathlib.Path(raw)
    if not candidate.is_absolute():
        candidate = pathlib.Path(cwd) / candidate
    try:
        resolved = candidate.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise PolicyError("APK is unavailable") from exc
    root = pathlib.Path(os.environ["GUARD_APK_PROJECT"]).resolve(strict=True)
    if not resolved.is_relative_to(root):
        raise PolicyError("APK is outside approved roots")
    if not resolved.is_file() or resolved.suffix.lower() != ".apk":
        raise PolicyError("file is not an APK")
    return resolved


def windows_path(path: pathlib.Path) -> str:
    result = subprocess.run(
        ["/usr/bin/wslpath", "-w", str(path)],
        check=True,
        capture_output=True,
        text=True,
        timeout=5,
    )
    value = result.stdout.strip()
    if not value:
        raise PolicyError("Windows path conversion failed")
    return value


def validate_command(argv: list[str], cwd: str) -> tuple[list[str], str]:
    if (
        len(argv) > 40
        or any(not isinstance(value, str) for value in argv)
        or not isinstance(cwd, str)
        or len(cwd) > 4096
    ):
        raise PolicyError("ADB argument list is invalid")
    selector, command = parse_selector(argv)
    if not command:
        raise PolicyError("ADB command is missing")
    name, args = command[0], command[1:]
    if name == "version" and not selector and not args:
        return ["version"], "text"
    if name == "devices" and not selector and args in ([], ["-l"]):
        return ["devices", "-l"], "devices"

    selector = selector or ["-d"]
    if name == "install" and os.environ.get("GUARD_ALLOW_APK_INSTALL") == "1":
        options: list[str] = []
        while args and args[0] in {"-r", "-t"}:
            options.append(args.pop(0))
        if len(args) != 1:
            raise PolicyError("install requires one APK")
        return [*selector, "install", *options, windows_path(approved_apk(args[0], cwd))], "text"
    if name == "exec-out" and args == ["screencap", "-p"]:
        return [*selector, "exec-out", *args], "binary"
    if name == "shell" and len(args) == 2 and args[0] == "getprop" and args[1] in APPROVED_PROPERTIES:
        return [*selector, "shell", *args], "text"
    raise PolicyError("ADB subcommand is not approved")


def usb_device_map(
    runtime_hashes: dict[pathlib.Path, str], env: dict[str, str]
) -> dict[str, str]:
    verify_adb_runtime(runtime_hashes)
    result = subprocess.run(
        [str(ADB_PATH), "devices", "-l"],
        env=env,
        cwd=ADB_PATH.parent,
        capture_output=True,
        timeout=15,
    )
    serials: list[str] = []
    for raw_line in result.stdout.decode(errors="replace").splitlines()[1:]:
        fields = raw_line.split()
        if len(fields) >= 2 and fields[1] == "device" and any(
            field.startswith("usb:") for field in fields[2:]
        ):
            serials.append(fields[0])
    return {f"usb-{index}": serial for index, serial in enumerate(sorted(serials), 1)}


def filter_usb_devices(output: bytes) -> bytes:
    lines = output.decode(errors="replace").splitlines()
    kept = [lines[0] if lines else "List of devices attached"]
    rows: list[tuple[str, str]] = []
    for line in lines[1:]:
        fields = line.split()
        if len(fields) >= 2 and any(field.startswith("usb:") for field in fields[2:]):
            rows.append((fields[0], fields[1]))
    for index, (_serial, state) in enumerate(sorted(rows), 1):
        kept.append(f"usb-{index}\t{state}")
    return ("\n".join(kept) + "\n").encode()


def run_adb(
    argv: list[str],
    cwd: str,
    runtime_hashes: dict[pathlib.Path, str],
    env: dict[str, str],
) -> dict[str, object]:
    command, output_kind = validate_command(list(argv), cwd)
    if command[:1] == ["-s"]:
        devices = usb_device_map(runtime_hashes, env)
        selected = command[1]
        if selected in devices:
            command[1] = devices[selected]
        elif selected not in devices.values():
            raise PolicyError("selected serial is not a current USB device")
    else:
        verify_adb_runtime(runtime_hashes)
    process = subprocess.Popen(
        [str(ADB_PATH), *command],
        env=env,
        cwd=ADB_PATH.parent,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        stdout, stderr = process.communicate(timeout=COMMAND_TIMEOUT)
    except subprocess.TimeoutExpired:
        process.kill()
        process.communicate()
        return {"returncode": 124, "stdout": "", "stderr": "command timed out\n"}
    if output_kind == "devices":
        stdout = filter_usb_devices(stdout)
    elif command == ["version"]:
        # The rest of adb version includes the host installation path and OS.
        stdout = b"".join(line + b"\n" for line in stdout.splitlines()
                          if re.fullmatch(rb"(Android Debug Bridge version|Version) [0-9A-Za-z.+-]+", line))
    if stderr:
        stderr = b"Windows ADB returned diagnostics; inspect the host privately if needed.\n"
    if len(stdout) + len(stderr) > MAX_OUTPUT:
        return {"returncode": 125, "stdout": "", "stderr": "output limit exceeded\n"}
    return {
        "returncode": process.returncode,
        "stdout": base64.b64encode(stdout).decode(),
        "stderr": base64.b64encode(stderr).decode(),
        "encoding": "base64",
    }


def receive_request(client_socket: socket.socket) -> dict[str, object]:
    with client_socket.makefile("rb") as stream:
        line = stream.readline(MAX_REQUEST + 1)
    if not line or len(line) > MAX_REQUEST or not line.endswith(b"\n"):
        raise PolicyError("invalid broker request")
    value = json.loads(line)
    if not isinstance(value, dict):
        raise PolicyError("invalid broker request")
    return value


def handle_client(
    client_socket: socket.socket,
    runtime_hashes: dict[pathlib.Path, str],
    env: dict[str, str],
) -> None:
    with client_socket:
        client_socket.settimeout(COMMAND_TIMEOUT + 15)
        try:
            request = receive_request(client_socket)
            if set(request) != {"action", "argv", "cwd"} or request.get("action") != "adb":
                raise PolicyError("unsupported broker action")
            argv, cwd = request.get("argv"), request.get("cwd")
            if not isinstance(argv, list) or not isinstance(cwd, str):
                raise PolicyError("invalid broker request")
            response = run_adb(argv, cwd, runtime_hashes, env)
        except Exception:
            response = {"returncode": 126, "stdout": "", "stderr": "ADB request denied\n"}
        payload = json.dumps(response, separators=(",", ":")).encode() + b"\n"
        if len(payload) > MAX_RESPONSE:
            payload = b'{"returncode":125,"stdout":"","stderr":"response limit exceeded\\n"}\n'
        try:
            client_socket.sendall(payload)
        except OSError:
            pass


def serve(socket_path: str, proxy_port: int) -> None:
    runtime_hashes = adb_runtime_hashes()
    pinned = json.loads(os.environ["GUARD_ADB_HASHES"])
    if {p.name: h for p, h in runtime_hashes.items()} != pinned:
        raise PolicyError("ADB executable or DLL does not match configured hashes")
    env = windows_environment(proxy_port)
    parent = os.path.dirname(socket_path)
    if not parent or not os.path.isdir(parent):
        raise ValueError("ADB broker socket directory is missing")
    parent_status = os.lstat(parent)
    if (
        not stat.S_ISDIR(parent_status.st_mode)
        or parent_status.st_uid != os.getuid()
        or parent_status.st_mode & 0o077
    ):
        raise ValueError("ADB broker socket directory is not private")
    if os.path.lexists(socket_path):
        raise ValueError("ADB broker socket path already exists")

    os.umask(0o077)
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    listener.bind(socket_path)
    listener.listen(4)
    stopping = threading.Event()
    slots = threading.BoundedSemaphore(1)

    def stop(_signum: int, _frame: object) -> None:
        stopping.set()
        listener.close()

    def run_client(client_socket: socket.socket) -> None:
        try:
            handle_client(client_socket, runtime_hashes, env)
        finally:
            slots.release()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    print("READY", flush=True)
    try:
        while not stopping.is_set():
            try:
                client_socket, _ = listener.accept()
            except OSError:
                break
            if not slots.acquire(blocking=False):
                client_socket.close()
                continue
            threading.Thread(target=run_client, args=(client_socket,), daemon=True).start()
    finally:
        listener.close()
        try:
            os.unlink(socket_path)
        except FileNotFoundError:
            pass


def client(argv: list[str]) -> int:
    socket_path = os.environ.get(SOCKET_ENV, "/run/agent-guard/adb.sock")
    request = json.dumps(
        {"action": "adb", "argv": argv, "cwd": os.getcwd()}, separators=(",", ":")
    ).encode() + b"\n"
    if len(request) > MAX_REQUEST:
        print("adb-safe: argument list is too large", file=sys.stderr)
        return 126
    connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    connection.settimeout(COMMAND_TIMEOUT + 20)
    try:
        connection.connect(socket_path)
        connection.sendall(request)
        with connection.makefile("rb") as stream:
            line = stream.readline(MAX_RESPONSE + 1)
    except OSError:
        print("adb-safe: broker unavailable", file=sys.stderr)
        return 126
    finally:
        connection.close()
    try:
        response = json.loads(line)
        returncode = int(response["returncode"])
        if response.get("encoding") == "base64":
            stdout = base64.b64decode(response.get("stdout", ""), validate=True)
            stderr = base64.b64decode(response.get("stderr", ""), validate=True)
        else:
            stdout = str(response.get("stdout", "")).encode()
            stderr = str(response.get("stderr", "")).encode()
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        print("adb-safe: invalid broker response", file=sys.stderr)
        return 126
    sys.stdout.buffer.write(stdout)
    sys.stdout.buffer.flush()
    sys.stderr.buffer.write(stderr)
    sys.stderr.buffer.flush()
    return returncode if 0 <= returncode <= 125 else 1


def main() -> int:
    if len(sys.argv) >= 2 and sys.argv[1] == "host":
        parser = argparse.ArgumentParser()
        parser.add_argument("mode", choices=("host",))
        parser.add_argument("--socket", required=True)
        parser.add_argument("--proxy-port", required=True, type=int)
        args = parser.parse_args()
        if not 1024 <= args.proxy_port <= 65535:
            raise ValueError("invalid proxy port")
        die_with_parent()
        serve(args.socket, args.proxy_port)
        return 0
    return client(sys.argv[1:])


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError, subprocess.SubprocessError):
        print("adb-safe: unavailable", file=sys.stderr)
        raise SystemExit(126)

#!/usr/bin/python3 -I
"""Verify the isolated namespace, start its proxy endpoint, and run a tool."""

from __future__ import annotations

import argparse
import os
import pathlib
import selectors
import signal
import subprocess
import sys
import time
from datetime import datetime
from zoneinfo import ZoneInfo


TRUSTED_PYTHON = "/usr/bin/python3"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--relay", required=True)
    parser.add_argument("--socket", required=True)
    parser.add_argument("--port", required=True, type=int)
    parser.add_argument("--timezone", required=True)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if args.command and args.command[0] == "--":
        args.command = args.command[1:]
    if not args.command:
        parser.error("a command is required")
    if not 1024 <= args.port <= 65535:
        parser.error("invalid proxy port")
    return args


def verify_timezone(expected: str) -> None:
    failure = "isolated timezone check failed"
    localtime = pathlib.Path("/etc/localtime")
    try:
        if (os.environ.get("TZ") != expected
                or pathlib.Path("/etc/timezone").read_bytes().strip() != expected.encode("ascii")
                or localtime.readlink() != pathlib.Path("/usr/share/zoneinfo") / expected):
            raise RuntimeError(failure)
        with localtime.open("rb") as stream:
            default_zone = ZoneInfo.from_file(stream)
        # Check winter and summer so a single matching UTC offset is insufficient.
        for instant in (1_705_320_000, 1_721_044_800):
            expected_time = datetime.fromtimestamp(instant, default_zone).replace(tzinfo=None)
            if datetime.fromtimestamp(instant) != expected_time:
                raise RuntimeError(failure)
    except (OSError, ValueError, EOFError) as exc:
        raise RuntimeError(failure) from exc


def verify_confinement() -> None:
    status: dict[str, str] = {}
    for line in pathlib.Path("/proc/self/status").read_text().splitlines():
        key, _, value = line.partition(":")
        status[key] = value.strip()
    if status.get("CapEff") != "0000000000000000":
        raise RuntimeError("effective capabilities were not dropped")
    if status.get("CapPrm") != "0000000000000000":
        raise RuntimeError("permitted capabilities were not dropped")
    if status.get("CapBnd") != "0000000000000000":
        raise RuntimeError("capability bounding set is not empty")
    if status.get("NoNewPrivs") != "1":
        raise RuntimeError("no-new-privileges is not active")

    ip = "/usr/sbin/ip"
    if not os.path.isfile(ip):
        raise RuntimeError("route inspection is unavailable")
    for family in ([], ["-6"]):
        try:
            result = subprocess.run(
                [ip, *family, "route", "show"],
                check=True,
                capture_output=True,
                text=True,
                timeout=3,
            )
        except subprocess.CalledProcessError as exc:
            raise RuntimeError("failed to inspect sandbox routes") from exc
        if result.stdout.strip():
            raise RuntimeError("sandbox unexpectedly has a network route")


def wait_ready(process: subprocess.Popen[str], timeout: float = 5.0) -> None:
    if process.stdout is None:
        raise RuntimeError("relay readiness pipe is unavailable")
    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ)
    deadline = time.monotonic() + timeout
    try:
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError("sandbox relay stopped during startup")
            events = selector.select(max(0.0, deadline - time.monotonic()))
            if events and process.stdout.readline().strip() == "READY":
                return
    finally:
        selector.close()
    raise RuntimeError("sandbox relay did not become ready")


def run() -> None:
    args = parse_args()
    verify_confinement()
    verify_timezone(args.timezone)
    relay = subprocess.Popen(
        [
            TRUSTED_PYTHON,
            "-I",
            args.relay,
            "sandbox",
            "--socket",
            args.socket,
            "--port",
            str(args.port),
        ],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        start_new_session=True,
    )
    try:
        wait_ready(relay)
        signal.signal(signal.SIGINT, signal.SIG_DFL)
        signal.signal(signal.SIGQUIT, signal.SIG_DFL)
        os.execvpe(args.command[0], args.command, os.environ)
    finally:
        relay.terminate()
        try:
            relay.wait(timeout=2)
        except subprocess.TimeoutExpired:
            relay.kill()


if __name__ == "__main__":
    try:
        run()
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        message = str(exc) if isinstance(exc, RuntimeError) else type(exc).__name__
        print(f"[bwrap-entry] {message}", file=sys.stderr)
        raise SystemExit(1)

#!/usr/bin/python3 -I
"""Bridge a sandbox TCP proxy endpoint to the host proxy through AF_UNIX."""

from __future__ import annotations

import argparse
import ctypes
import os
import signal
import socket
import stat
import sys
import threading
from collections.abc import Callable


Connector = Callable[[], socket.socket]
PR_SET_PDEATHSIG = 1


def die_with_parent() -> None:
    parent = os.getppid()
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(PR_SET_PDEATHSIG, signal.SIGTERM, 0, 0, 0) != 0:
        raise OSError(ctypes.get_errno(), "prctl failed")
    if os.getppid() != parent:
        raise RuntimeError("parent exited during relay startup")


def copy_stream(source: socket.socket, destination: socket.socket) -> None:
    try:
        while True:
            chunk = source.recv(65536)
            if not chunk:
                break
            destination.sendall(chunk)
    except OSError:
        pass
    finally:
        try:
            destination.shutdown(socket.SHUT_WR)
        except OSError:
            pass


def bridge(client: socket.socket, connector: Connector) -> None:
    upstream = None
    try:
        upstream = connector()
        upstream.settimeout(None)
        client.settimeout(None)
        outgoing = threading.Thread(
            target=copy_stream, args=(client, upstream), daemon=True
        )
        incoming = threading.Thread(
            target=copy_stream, args=(upstream, client), daemon=True
        )
        outgoing.start()
        incoming.start()
        outgoing.join()
        incoming.join()
    except OSError:
        pass
    finally:
        client.close()
        if upstream is not None:
            upstream.close()


def serve(listener: socket.socket, connector: Connector) -> None:
    stopping = threading.Event()
    slots = threading.BoundedSemaphore(32)

    def run_bridge(client: socket.socket) -> None:
        try:
            bridge(client, connector)
        finally:
            slots.release()

    def stop(_signum: int, _frame: object) -> None:
        stopping.set()
        listener.close()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    print("READY", flush=True)
    while not stopping.is_set():
        try:
            client, _ = listener.accept()
        except OSError:
            break
        if not slots.acquire(blocking=False):
            client.close()
            continue
        threading.Thread(target=run_bridge, args=(client,), daemon=True).start()


def authorize(gate_socket_path: str) -> None:
    gate = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    gate.settimeout(20)
    try:
        gate.connect(gate_socket_path)
        gate.sendall(b"CHECK\n")
        with gate.makefile("rb") as stream:
            if stream.readline(17) != b"OK\n":
                raise OSError("route gate denied the connection")
    finally:
        gate.close()


def host_mode(socket_path: str, target_port: int, gate_socket_path: str) -> None:
    if not 1024 <= target_port <= 65535:
        raise ValueError("invalid target port")
    parent = os.path.dirname(socket_path)
    if not parent or not os.path.isdir(parent):
        raise ValueError("socket directory is missing")
    parent_status = os.lstat(parent)
    if (
        not stat.S_ISDIR(parent_status.st_mode)
        or parent_status.st_uid != os.getuid()
        or parent_status.st_mode & 0o077
    ):
        raise ValueError("socket directory is not private")
    if os.path.lexists(socket_path):
        raise ValueError("socket path already exists")

    os.umask(0o077)
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    listener.bind(socket_path)
    listener.listen(32)

    def connector() -> socket.socket:
        authorize(gate_socket_path)
        return socket.create_connection(("127.0.0.1", target_port), timeout=8)

    try:
        serve(listener, connector)
    finally:
        listener.close()
        try:
            os.unlink(socket_path)
        except FileNotFoundError:
            pass


def sandbox_mode(socket_path: str, listen_port: int) -> None:
    if not 1024 <= listen_port <= 65535:
        raise ValueError("invalid listen port")
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", listen_port))
    listener.listen(32)

    def connector() -> socket.socket:
        upstream = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        upstream.settimeout(8)
        upstream.connect(socket_path)
        return upstream

    serve(listener, connector)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("host", "sandbox"))
    parser.add_argument("--socket", required=True)
    parser.add_argument("--port", required=True, type=int)
    parser.add_argument("--gate-socket")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        die_with_parent()
        if args.mode == "host":
            if not args.gate_socket:
                raise ValueError("route gate is required in host mode")
            host_mode(args.socket, args.port, args.gate_socket)
        else:
            sandbox_mode(args.socket, args.port)
    except (OSError, RuntimeError, ValueError):
        print("proxy-relay: unavailable", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

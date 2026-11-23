"""Connectivity checks to run only inside the guard's fresh network namespace."""
import errno
import http.client
import json
import os
import pathlib
import shutil
import socket
import ssl
import subprocess
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from sandbox_entry import verify_confinement


def blocked(family, address, kind=socket.SOCK_STREAM, port=443):
    with socket.socket(family, kind) as s:
        s.settimeout(2)
        try:
            s.connect((address, port))
        except OSError as exc:
            if exc.errno in (errno.ENETUNREACH, errno.EHOSTUNREACH):
                return
            raise RuntimeError("direct probe did not give a definitive no-route result") from exc
        raise RuntimeError("unexpected direct route")


def run(port, host):
    verify_confinement()
    if host not in {"api.anthropic.com", "chatgpt.com"}:
        raise ValueError("unsupported anonymous TLS probe")
    intl_ok = None
    if node := shutil.which("node"):
        zone = pathlib.Path("/etc/timezone").read_text().strip()
        expression = ("const expected = new Intl.DateTimeFormat('en', {timeZone: process.argv[1]});"
                      "process.exitCode = Intl.DateTimeFormat().resolvedOptions().timeZone "
                      "=== expected.resolvedOptions().timeZone ? 0 : 1;")
        fallback = os.environ.copy()
        fallback.pop("TZ", None)
        for env in (None, fallback):
            if subprocess.run([node, "-e", expression, zone], env=env, timeout=5, capture_output=True).returncode:
                raise RuntimeError("child Intl timezone check failed")
        intl_ok = True
    blocked(socket.AF_INET, "192.0.2.1")
    blocked(socket.AF_INET6, "2001:db8::1")
    blocked(socket.AF_INET, "192.0.2.1", socket.SOCK_DGRAM, 53)
    proxy = http.client.HTTPSConnection("127.0.0.1", port, timeout=12,
                                        context=ssl.create_default_context())
    try:
        proxy.set_tunnel(host, 443)
        proxy.connect()
    finally:
        proxy.close()
    # Reserve a local port without listening; simulate an unavailable proxy without touching the real one.
    with socket.socket() as stopped:
        stopped.bind(("127.0.0.1", 0))
        try:
            with socket.create_connection(stopped.getsockname(), timeout=2):
                raise RuntimeError("unexpected connection to unavailable proxy")
        except ConnectionRefusedError:
            pass
        blocked(socket.AF_INET, "192.0.2.1")
        blocked(socket.AF_INET6, "2001:db8::1")
    print(json.dumps({"direct_v4": "no route", "direct_v6": "no route", "direct_dns_udp": "no route",
                      "proxy_tls": "verified", "closed_test_listener": "refused",
                      "direct_after_refusal": "no route", "intl_timezone_with_and_without_TZ": intl_ok,
                      "scope": "this Linux network namespace"}))


if __name__ == "__main__":
    run(int(sys.argv[1]), sys.argv[2])

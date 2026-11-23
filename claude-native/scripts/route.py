"""Fail-closed Mihomo route validation for the native WSL Claude launcher."""

from __future__ import annotations

import http.client
import ipaddress
import json
import os
import pathlib
import re
import socket
import ssl
import subprocess
import urllib.parse
from typing import Any


PROBES = {"claude": "api.anthropic.com"}
PIPE_NAME = re.compile(r"^[A-Za-z0-9_.-]{1,128}$")
NODE_NAME = re.compile(r"^[^\x00-\x1f\x7f]{1,256}$")
ALLOWED_TYPES = {
    "anytls", "http", "hysteria", "hysteria2", "mieru", "shadowsocks",
    "shadowsocksr", "snell", "socks", "socks5", "ssh", "ss", "ssr",
    "trojan", "tuic", "vless", "vmess", "wireguard",
}
FORBIDDEN_TYPES = {
    "direct", "reject", "rejectdrop", "pass", "compatible", "selector",
    "urltest", "fallback", "loadbalance", "relay",
}
TRANSIENT = (ConnectionResetError, TimeoutError, ssl.SSLEOFError, socket.timeout)


def private_secret(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise RuntimeError("route configuration is invalid")
    path = pathlib.Path(value)
    if not path.is_absolute() or path.is_symlink():
        raise RuntimeError("route configuration is invalid")
    try:
        status = path.stat()
        if not path.is_file() or status.st_uid != os.getuid() or status.st_mode & 0o077:
            raise RuntimeError("route configuration is invalid")
        secret = path.read_text(encoding="utf-8").strip()
    except OSError as error:
        raise RuntimeError("route controller is unavailable") from error
    if not secret or "\r" in secret or "\n" in secret:
        raise RuntimeError("route configuration is invalid")
    try:
        secret.encode("ascii")
    except UnicodeEncodeError as error:
        raise RuntimeError("route configuration is invalid") from error
    return secret


def safe_port(value: object) -> int:
    if not isinstance(value, int) or not 1024 <= value <= 65535:
        raise RuntimeError("route configuration is invalid")
    return value


def safe_node(value: object) -> str:
    if not isinstance(value, str) or not NODE_NAME.fullmatch(value):
        raise RuntimeError("route configuration is invalid")
    return value


class Controller:
    def verify_listener(self, port: int, owner: str | None) -> None:
        raise NotImplementedError

    def proxy(self, node: str) -> dict[str, Any]:
        raise NotImplementedError

    def connections(self, source_port: int, host: str) -> list[dict[str, Any]]:
        raise NotImplementedError


class HttpController(Controller):
    # This controller is for a loopback HTTP API visible in the current Linux
    # network namespace. A Windows-host controller must use windows_pipe.
    def __init__(self, port: int, secret: str | None) -> None:
        self.port = safe_port(port)
        self.secret = secret

    def get(self, endpoint: str) -> Any:
        headers = {"Accept": "application/json"}
        if self.secret is not None:
            headers["Authorization"] = "Bearer " + self.secret
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        try:
            connection.request("GET", endpoint, headers=headers)
            response = connection.getresponse()
            if response.status != 200:
                raise RuntimeError("route controller rejected the check")
            payload = response.read(2 * 1024 * 1024 + 1)
            if len(payload) > 2 * 1024 * 1024:
                raise RuntimeError("route controller response is invalid")
            return json.loads(payload)
        except (OSError, http.client.HTTPException, json.JSONDecodeError) as error:
            raise RuntimeError("route controller is unavailable") from error
        finally:
            connection.close()

    def verify_listener(self, port: int, owner: str | None) -> None:
        if owner is not None:
            raise RuntimeError("route configuration is invalid")
        verify_linux_loopback_listener(port)

    def proxy(self, node: str) -> dict[str, Any]:
        value = self.get("/proxies/" + urllib.parse.quote(node, safe=""))
        if not isinstance(value, dict):
            raise RuntimeError("route controller response is invalid")
        return value

    def connections(self, source_port: int, host: str) -> list[dict[str, Any]]:
        value = self.get("/connections")
        if not isinstance(value, dict) or not isinstance(value.get("connections"), list):
            raise RuntimeError("route controller response is invalid")
        return matched_connections(value["connections"], source_port, host)


class UnixController(HttpController):
    def __init__(self, socket_path: str, secret: str | None) -> None:
        path = pathlib.Path(socket_path)
        if not path.is_absolute():
            raise RuntimeError("route configuration is invalid")
        self.socket_path = str(path)
        self.secret = secret

    def get(self, endpoint: str) -> Any:
        headers = ["GET " + endpoint + " HTTP/1.1", "Host: localhost", "Accept: application/json"]
        if self.secret is not None:
            headers.append("Authorization: Bearer " + self.secret)
        headers.extend(("Connection: close", "", ""))
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as stream:
                stream.settimeout(5)
                stream.connect(self.socket_path)
                stream.sendall("\r\n".join(headers).encode("ascii"))
                response = http.client.HTTPResponse(stream)
                response.begin()
                if response.status != 200:
                    raise RuntimeError("route controller rejected the check")
                payload = response.read(2 * 1024 * 1024 + 1)
                if len(payload) > 2 * 1024 * 1024:
                    raise RuntimeError("route controller response is invalid")
                return json.loads(payload)
        except (OSError, http.client.HTTPException, UnicodeEncodeError, json.JSONDecodeError) as error:
            raise RuntimeError("route controller is unavailable") from error


class WindowsPipeController(Controller):
    def __init__(self, pipe: str, secret: str | None) -> None:
        if not PIPE_NAME.fullmatch(pipe):
            raise RuntimeError("route configuration is invalid")
        self.pipe = pipe
        self.secret = secret
        self.script = pathlib.Path(__file__).with_name("controller.ps1")
        if not self.script.is_file():
            raise RuntimeError("route controller is unavailable")

    def request(self, data: dict[str, Any]) -> Any:
        wslpath = "/usr/bin/wslpath"
        powershell = "/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe"
        if not pathlib.Path(wslpath).is_file() or not pathlib.Path(powershell).is_file():
            raise RuntimeError("route controller is unavailable")
        try:
            script_path = subprocess.check_output(
                [wslpath, "-w", str(self.script)], text=True, timeout=3
            ).strip()
            request = dict(data, pipe=self.pipe)
            if self.secret is not None:
                request["secret"] = self.secret
            result = subprocess.run(
                [
                    powershell, "-NoLogo", "-NoProfile", "-NonInteractive",
                    "-ExecutionPolicy", "Bypass", "-File", script_path,
                ],
                input=json.dumps(request, separators=(",", ":")).encode(),
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                timeout=10,
                check=False,
            )
            if result.returncode != 0:
                raise RuntimeError("route controller is unavailable")
            return json.loads(result.stdout.decode("utf-8-sig"))
        except (OSError, subprocess.SubprocessError, UnicodeError, json.JSONDecodeError) as error:
            raise RuntimeError("route controller is unavailable") from error

    def verify_listener(self, port: int, owner: str | None) -> None:
        value = self.request(
            {"action": "listener", "port": port, "listener_owner": owner}
        )
        if not isinstance(value, dict) or value.get("ok") is not True:
            raise RuntimeError("dedicated listener check failed")

    def proxy(self, node: str) -> dict[str, Any]:
        value = self.request({"action": "proxy", "node": node})
        if not isinstance(value, dict):
            raise RuntimeError("route controller response is invalid")
        return value

    def connections(self, source_port: int, host: str) -> list[dict[str, Any]]:
        value = self.request({"action": "connections", "source_port": source_port, "host": host})
        if not isinstance(value, dict) or not isinstance(value.get("matches"), list):
            raise RuntimeError("route controller response is invalid")
        return value["matches"]


def matched_connections(rows: list[Any], source_port: int, host: str) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("metadata"), dict):
            continue
        metadata = row["metadata"]
        if str(metadata.get("sourcePort")) != str(source_port) or metadata.get("host") != host:
            continue
        filtered: dict[str, Any] = {
            "chains": row.get("chains"), "specialProxy": metadata.get("specialProxy"),
            "inboundPort": metadata.get("inboundPort"),
        }
        for field in ("inbound", "inboundName", "inboundTag"):
            if field in row:
                filtered[field] = row[field]
            elif field in metadata:
                filtered[field] = metadata[field]
        matches.append(filtered)
    return matches


def proc_listener_address(raw: str, family: int) -> tuple[str, int]:
    host_hex, port_hex = raw.split(":")
    packed = bytes.fromhex(host_hex)
    if family == 4:
        host = str(socket.inet_ntop(socket.AF_INET, packed[::-1]))
    else:
        host = str(
            socket.inet_ntop(
                socket.AF_INET6,
                b"".join(packed[index:index + 4][::-1] for index in range(0, 16, 4)),
            )
        )
    return host, int(port_hex, 16)


def verify_linux_loopback_listener(port: int) -> None:
    """Check the current Linux network namespace without touching the proxy."""
    listeners: list[str] = []
    for filename, family in (("/proc/net/tcp", 4), ("/proc/net/tcp6", 6)):
        try:
            rows = pathlib.Path(filename).read_text(encoding="ascii").splitlines()[1:]
        except OSError as error:
            raise RuntimeError("dedicated listener check unavailable") from error
        for row in rows:
            fields = row.split()
            if len(fields) < 4 or fields[3] != "0A":
                continue
            try:
                host, row_port = proc_listener_address(fields[1], family)
            except (OSError, ValueError):
                continue
            if row_port == port:
                listeners.append(host)
    if listeners != ["127.0.0.1"]:
        raise RuntimeError("dedicated listener check failed")


def build_controller(config: dict[str, Any]) -> Controller:
    controller = config.get("controller")
    if not isinstance(controller, dict):
        raise RuntimeError("route configuration is invalid")
    secret = private_secret(controller.get("secret_file"))
    listener_owner = controller.get("listener_owner")
    if listener_owner is not None and (
        not isinstance(listener_owner, str) or not PIPE_NAME.fullmatch(listener_owner)
    ):
        raise RuntimeError("route configuration is invalid")
    keys = set(controller) - {"secret_file", "listener_owner"}
    if keys == {"http_port"}:
        if secret is None:
            raise RuntimeError("route configuration is invalid")
        if listener_owner is not None:
            raise RuntimeError("route configuration is invalid")
        return HttpController(safe_port(controller["http_port"]), secret)
    if keys == {"unix_socket"} and isinstance(controller["unix_socket"], str):
        if listener_owner is not None:
            raise RuntimeError("route configuration is invalid")
        return UnixController(controller["unix_socket"], secret)
    if keys == {"windows_pipe"} and isinstance(controller["windows_pipe"], str):
        return WindowsPipeController(controller["windows_pipe"], secret)
    raise RuntimeError("route configuration is invalid")


def validate_proxy(proxy: dict[str, Any], config: dict[str, Any], tool: str) -> None:
    proxy_type = proxy.get("type")
    if not isinstance(proxy_type, str):
        raise RuntimeError("route controller response is invalid")
    normalized = proxy_type.replace("-", "").replace("_", "").casefold()
    if normalized in FORBIDDEN_TYPES or normalized not in ALLOWED_TYPES:
        raise RuntimeError("configured route is not a concrete outbound proxy")
    selected = config.get("node_types", {})
    expected = selected.get(tool) if isinstance(selected, dict) else None
    if expected is not None and (
        not isinstance(expected, str)
        or normalized != expected.replace("-", "").replace("_", "").casefold()
    ):
        raise RuntimeError("configured proxy type does not match")


def verify_rendered(config: dict, tool: str, port: int, node: str) -> None:
    """Check the active generated profile before making the external TLS probe."""
    try:
        import yaml
    except ImportError:
        raise RuntimeError("system Python needs PyYAML to verify the active profile") from None
    try:
        path = pathlib.Path(config["rendered_profile"]).expanduser()
        if not path.is_absolute():
            raise ValueError
        profile = yaml.safe_load(path.read_text(encoding="utf-8-sig"))
        listeners = [v for v in profile["listeners"] if str(v.get("port")) == str(port)]
        if len(listeners) != 1 or (listeners[0].get("type"), listeners[0].get("listen"),
                                    listeners[0].get("proxy")) != ("http", "127.0.0.1", node):
            raise ValueError
        peers = [v for v in profile["proxies"] if v.get("name") == node]
        if len(peers) != 1 or peers[0].get("dialer-proxy") or not isinstance(peers[0].get("server"), str):
            raise ValueError
        ipaddress.ip_address(peers[0]["server"])
        validate_proxy(peers[0], config, tool)
    except (KeyError, TypeError, ValueError, AttributeError, OSError, yaml.YAMLError):
        # Parser diagnostics can contain credentials from the original profile.
        raise RuntimeError("active profile does not attest the fixed local listener and IP node") from None


def validate_match(matches: list[dict[str, Any]], node: str, port: int, expected_inbound: object) -> None:
    if (len(matches) != 1 or matches[0].get("chains") != [node]
            or matches[0].get("specialProxy") != node or str(matches[0].get("inboundPort")) != str(port)):
        raise RuntimeError("probe route does not match the configured node")
    inbound_values = [matches[0].get(k) for k in ("inbound", "inboundName", "inboundTag")]
    if expected_inbound is not None and expected_inbound not in inbound_values:
        raise RuntimeError("probe route does not match the configured inbound")


def open_probe(port: int, host: str) -> tuple[http.client.HTTPSConnection, int]:
    connection = http.client.HTTPSConnection(
        "127.0.0.1", port, timeout=8, context=ssl.create_default_context()
    )
    connection.set_tunnel(host, 443)
    try:
        connection.connect()
        if connection.sock is None:
            raise RuntimeError("proxy tunnel did not open")
        return connection, int(connection.sock.getsockname()[1])
    except BaseException:
        connection.close()
        raise


def _check(config: dict, tool: str) -> None:
    if tool not in PROBES or not isinstance(config, dict):
        raise RuntimeError("route configuration is invalid")
    ports, nodes = config.get("ports"), config.get("nodes")
    if not isinstance(ports, dict) or not isinstance(nodes, dict):
        raise RuntimeError("route configuration is invalid")
    port, node = safe_port(ports.get(tool)), safe_node(nodes.get(tool))
    verify_rendered(config, tool, port, node)
    controller = build_controller(config)
    owner = config["controller"].get("listener_owner")
    controller.verify_listener(port, owner)
    validate_proxy(controller.proxy(node), config, tool)
    inbounds = config.get("inbounds", {})
    expected_inbound = inbounds.get(tool) if isinstance(inbounds, dict) else None
    if expected_inbound is not None and not isinstance(expected_inbound, str):
        raise RuntimeError("route configuration is invalid")
    for attempt in range(3):
        try:
            connection, source_port = open_probe(port, PROBES[tool])
            try:
                validate_match(
                    controller.connections(source_port, PROBES[tool]),
                    node,
                    port,
                    expected_inbound,
                )
                return
            finally:
                connection.close()
        except TRANSIENT as error:
            if attempt == 2:
                raise RuntimeError("proxy transport check failed") from error
        except (OSError, http.client.HTTPException, ssl.SSLError) as error:
            raise RuntimeError("proxy transport check failed") from error
    raise RuntimeError("proxy transport check failed")


def check(config: dict, tool: str) -> None:
    """Raise RuntimeError unless the dedicated proxy route is cryptographically probed."""
    try:
        _check(config, tool)
    except Exception as error:
        raise RuntimeError("route check failed") from error

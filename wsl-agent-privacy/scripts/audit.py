#!/usr/bin/env python3
"""Read-only, redacted diagnostics for Claude Code and Codex on Linux or WSL2."""

from __future__ import annotations

import argparse
import collections
import ipaddress
import json
import math
import os
import pathlib
import re
import signal
import sys
import threading
import time
from typing import Any, Iterable


IP_CANDIDATE = re.compile(
    r"(?<![0-9A-Za-z_.:-])"
    r"(?:(?:\d{1,3}\.){3}\d{1,3}|"
    r"[0-9A-Fa-f:]*:[0-9A-Fa-f:]+)"
    r"(?![0-9A-Za-z_.:-])"
)
TIMEZONE = re.compile(
    r"\b(?:Asia|America|Europe|Africa|Australia|Pacific|Etc)/[A-Za-z_+-]+\b|"
    r"(?<![\w])(?:UTC|GMT)?[+-](?:0\d|1[0-4])(?::?\d{2})\b"
)
WINDOWS_MARKERS = (
    re.compile(r"(?i)(?:^|[^\w])(?:cmd|powershell|wsl|chrome|adb)\.exe\b"),
    re.compile(r"(?i)(?:^|[^\w])(?:[a-z]:[\\/]|\\\\|/mnt/[a-z]/)"),
    re.compile(r"(?i)(?:^|[\\/])platform-tools[\\/]adb(?:\.exe)?\b"),
)
TOOL_TYPES = {
    "tool_use", "tool_result", "function_call", "function_call_output",
    "custom_tool_call", "custom_tool_call_output", "shell", "bash",
}


def emit(data: dict[str, Any]) -> None:
    if data.get("mode", "").startswith("watch"):
        data["observed_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    print(json.dumps(data, ensure_ascii=False, sort_keys=True, indent=2), flush=True)


def text_flags(value: str, result: collections.Counter[str]) -> None:
    """Count sensitive-looking categories without retaining the matched value."""
    for candidate in IP_CANDIDATE.findall(value):
        try:
            address = ipaddress.ip_address(candidate)
        except ValueError:
            continue
        if address.is_global:
            result["possible_public_ip"] += 1
    result["timezone_or_offset"] += len(TIMEZONE.findall(value))
    lowered = value.lower()
    for marker in WINDOWS_MARKERS:
        if marker.search(value):
            result["windows_interop_marker"] += 1
            break
    if "github.com" in lowered or "api.github.com" in lowered:
        result["github_marker"] += 1
    if "anthropic" in lowered or "openai" in lowered or "chatgpt" in lowered:
        result["provider_marker"] += 1
    if "proxy" in lowered or "clash" in lowered or "mihomo" in lowered:
        result["proxy_marker"] += 1


def event_type(item: dict[str, Any]) -> str | None:
    values = (
        item.get("type"),
        item.get("event_type"),
        item.get("kind"),
        item.get("name") if "arguments" in item or "input" in item else None,
    )
    for value in values:
        if isinstance(value, str) and value.lower() in TOOL_TYPES:
            return value.lower()
    if "tool_use" in item or "tool_result" in item:
        return "tool"
    return None


def strings(node: Any) -> Iterable[str]:
    if isinstance(node, str):
        yield node
    elif isinstance(node, dict):
        for value in node.values():
            yield from strings(value)
    elif isinstance(node, list):
        for value in node:
            yield from strings(value)


def tool_event_nodes(node: Any) -> Iterable[tuple[str, dict[str, Any]]]:
    if isinstance(node, dict):
        kind = event_type(node)
        if kind is not None:
            yield kind, node
            return
        for value in node.values():
            yield from tool_event_nodes(value)
    elif isinstance(node, list):
        for value in node:
            yield from tool_event_nodes(value)


def session(path: pathlib.Path) -> int:
    if not path.is_file():
        raise RuntimeError("会话文件不存在或不是普通文件")
    counts: collections.Counter[str] = collections.Counter()
    tools: collections.Counter[str] = collections.Counter()
    records = invalid = tool_events = 0
    with path.open("r", encoding="utf-8", errors="replace") as stream:
        for line in stream:
            if not line.strip():
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                invalid += 1
                continue
            records += 1
            if not isinstance(item, dict):
                continue
            for kind, event in tool_event_nodes(item):
                tool_events += 1
                tools[kind] += 1
                for value in strings(event):
                    text_flags(value, counts)
    emit(
        {
            "mode": "session",
            "records": records,
            "invalid_json_lines": invalid,
            "tool_events": tool_events,
            "tool_event_types": dict(sorted(tools.items())),
            "sensitive_categories_in_tool_events": dict(sorted(counts.items())),
            "scope": (
                "只扫描工具事件中的类别，不输出会话正文、路径、账号、会话标识、IP 或令牌。"
                "历史记录不能证明网络请求实际走过哪条链路。"
            ),
        }
    )
    return 0


def read_text(path: pathlib.Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def optional_text(path: pathlib.Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def tcp_table(network_pid: int | None = None) -> tuple[dict[str, tuple[str, int, str, int, str]], bool]:
    result: dict[str, tuple[str, int, str, int, str]] = {}
    root = pathlib.Path("/proc/net") if network_pid is None else pathlib.Path("/proc") / str(network_pid) / "net"
    for filename, family in (("tcp", 4), ("tcp6", 6)):
        contents = optional_text(root / filename)
        if contents is None:
            return {}, False
        for line in contents.splitlines()[1:]:
            fields = line.split()
            if len(fields) < 10:
                continue
            local, remote, state, inode = fields[1], fields[2], fields[3], fields[9]
            try:
                local_host, local_port = decode_endpoint(local, family)
                remote_host, remote_port = decode_endpoint(remote, family)
            except (ValueError, OSError):
                continue
            result[inode] = (local_host, local_port, remote_host, remote_port, state)
    return result, True


def readonly_mount(target: pathlib.Path) -> bool:
    target_text = str(target)
    for line in read_text(pathlib.Path("/proc/self/mountinfo")).splitlines():
        before_separator = line.split(" - ", 1)[0].split()
        if len(before_separator) >= 6 and before_separator[4] == target_text:
            return "ro" in before_separator[5].split(",")
    return False


def decode_endpoint(raw: str, family: int) -> tuple[str, int]:
    host_hex, port_hex = raw.split(":")
    packed = bytes.fromhex(host_hex)
    if family == 4:
        host = str(ipaddress.IPv4Address(packed[::-1]))
    else:
        host = str(ipaddress.IPv6Address(
            b"".join(packed[index:index + 4][::-1] for index in range(0, 16, 4))
        ))
    return host, int(port_hex, 16)


def is_loopback(address: str) -> bool:
    return ipaddress.ip_address(address).is_loopback


def process_tree(root: int) -> set[int]:
    parents: dict[int, list[int]] = collections.defaultdict(list)
    for proc in pathlib.Path("/proc").iterdir():
        if not proc.name.isdigit():
            continue
        fields = read_text(proc / "stat").rsplit(")", 1)
        if len(fields) != 2:
            continue
        after = fields[1].split()
        if len(after) >= 2 and after[1].isdigit():
            parents[int(after[1])].append(int(proc.name))
    found, pending = {root}, [root]
    while pending:
        current = pending.pop()
        for child in parents.get(current, []):
            if child not in found:
                found.add(child)
                pending.append(child)
    return found


def network_namespace(pid: int) -> str | None:
    try:
        return os.readlink(pathlib.Path("/proc") / str(pid) / "ns/net")
    except OSError:
        return None


def process_socket_inodes(
    pids: set[int],
) -> tuple[dict[str, tuple[int, set[str]]], set[int]]:
    groups: dict[str, tuple[int, set[str]]] = {}
    unreadable: set[int] = set()
    for pid in pids:
        namespace = network_namespace(pid)
        if namespace is None:
            unreadable.add(pid)
            continue
        try:
            descriptors = list((pathlib.Path("/proc") / str(pid) / "fd").iterdir())
        except OSError:
            unreadable.add(pid)
            continue
        representative, inodes = groups.setdefault(namespace, (pid, set()))
        for descriptor in descriptors:
            try:
                target = os.readlink(descriptor)
            except OSError:
                continue
            match = re.fullmatch(r"socket:\[(\d+)\]", target)
            if match:
                inodes.add(match.group(1))
    return groups, unreadable


def process_identity(pid: int) -> tuple[int, str] | None:
    fields = read_text(pathlib.Path("/proc") / str(pid) / "stat").rsplit(")", 1)
    if len(fields) != 2:
        return None
    after = fields[1].split()
    if len(after) < 20:
        return None
    return pid, after[19]


def classify_sockets(
    inodes: set[str],
    proxy_ports: set[int],
    table: dict[str, tuple[str, int, str, int, str]],
) -> collections.Counter[str]:
    counts: collections.Counter[str] = collections.Counter()
    for inode in inodes:
        entry = table.get(inode)
        if entry is None:
            counts["unresolved_udp_or_unix"] += 1
            continue
        local_host, _local_port, remote_host, remote_port, state = entry
        if state == "0A":
            counts["listening"] += 1
        elif is_loopback(remote_host) and remote_port in proxy_ports:
            counts["local_proxy"] += 1
        elif is_loopback(remote_host):
            counts["loopback_other"] += 1
        elif remote_host in ("0.0.0.0", "::"):
            counts["unconnected"] += 1
        else:
            counts["external_endpoint"] += 1
    return counts


def watch(pid: int, interval: float, seconds: float | None, proxy_ports: set[int]) -> int:
    identity = process_identity(pid)
    if pid <= 0 or identity is None:
        raise RuntimeError("目标 PID 不存在或不可读取")
    deadline = None if seconds is None else time.monotonic() + seconds
    samples = 0
    previous = None
    stopped = threading.Event()
    next_heartbeat = 0.0

    def stop(_signum: int, _frame: object) -> None:
        stopped.set()

    old_int = signal.signal(signal.SIGINT, stop)
    try:
        while not stopped.is_set() and (deadline is None or time.monotonic() < deadline):
            if process_identity(pid) != identity:
                emit({"mode": "watch_complete", "samples": samples, "target_exited_or_reused": True})
                return 0
            pids = process_tree(pid)
            groups, unreadable = process_socket_inodes(pids)
            if process_identity(pid) != identity:
                emit({"mode": "watch_complete", "samples": samples, "target_exited_or_reused": True})
                return 0
            counts: collections.Counter[str] = collections.Counter()
            unresolved_namespaces = 0
            for representative, inodes in groups.values():
                table, readable = tcp_table(representative)
                if readable:
                    counts.update(classify_sockets(inodes, proxy_ports, table))
                else:
                    unresolved_namespaces += 1
            snapshot = {
                "socket_categories": dict(sorted(counts.items())),
                "unreadable_processes": len(unreadable),
                "unreadable_network_namespaces": unresolved_namespaces,
            }
            if snapshot != previous or time.monotonic() >= next_heartbeat:
                emit(
                    {
                        "mode": "watch",
                        "process_count": len(pids),
                        **snapshot,
                        "scope": (
                            "按 PID 及其 Linux 子进程的当前 socket inode 归因。"
                            "UDP 和 Unix socket 归为 unresolved_udp_or_unix。"
                            "unreadable_processes 或 unreadable_network_namespaces 非零时不能把缺少 socket 类别视为没有连接。"
                            "外部端点类别不能说明归属、代理链或服务端看到的 IP。"
                        ),
                    }
                )
                previous = snapshot
                next_heartbeat = time.monotonic() + 30
            samples += 1
            if deadline is None:
                stopped.wait(interval)
            else:
                stopped.wait(min(interval, max(0.0, deadline - time.monotonic())))
    finally:
        signal.signal(signal.SIGINT, old_int)
    emit({"mode": "watch_complete", "samples": samples, "interrupted": stopped.is_set()})
    return 0


def local_environment_markers(path: pathlib.Path) -> bool:
    contents = optional_text(path)
    return contents is not None and "TZ" in contents and "LANG" in contents


def host(proxy_ports: set[int]) -> int:
    version = read_text(pathlib.Path("/proc/version")).lower()
    is_wsl = "microsoft" in version or "wsl" in version
    bwrap = "bwrap" in read_text(pathlib.Path("/proc/1/cmdline"))
    bin_dir = pathlib.Path.home() / ".local/bin"
    guards = pathlib.Path.home() / ".local/lib"
    listening = collections.Counter()
    table, readable = tcp_table()
    for _inode, (host, port, _remote, _remote_port, state) in table.items():
        if state == "0A" and is_loopback(host) and port in proxy_ports:
            listening[str(port)] += 1
    emit(
        {
            "mode": "host",
            "environment": {
                "wsl_detected": is_wsl,
                "current_process_is_bwrap_namespace": bwrap,
                "home_bin_readonly_mount_seen": readonly_mount(bin_dir),
            },
            "installation_evidence": {
                "claude_command_exists": (bin_dir / "claude").exists(),
                "codex_command_exists": (bin_dir / "codex").exists(),
                "claude_guard_present": (guards / "claude-clash-guard").is_dir(),
                "codex_guard_present": (guards / "codex-clash-guard").is_dir(),
                "bwrap_guard_present": (guards / "bwrap-agent-guard").is_dir(),
                "claude_guard_config_present": (guards / "claude-clash-guard/guard.json").is_file(),
                "codex_guard_config_present": (guards / "codex-clash-guard/guard.json").is_file(),
                "claude_guard_declares_tz_locale": local_environment_markers(
                    guards / "claude-clash-guard/claude_guard.py"
                ),
                "codex_guard_declares_tz_locale": local_environment_markers(
                    guards / "codex-clash-guard/codex_guard.py"
                ),
                "current_namespace_tcp_table_readable": readable,
                "dedicated_loopback_listener_count": dict(sorted(listening.items())),
            },
            "scope": (
                "本机只读快照。它不读取代理控制器、账号或网络凭据，"
                "也不能证明某次历史会话、Windows 程序或 DNS 请求的实际出口。"
            ),
        }
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="WSL2 Claude/Codex privacy audit")
    subparsers = parser.add_subparsers(dest="command", required=True)
    host_parser = subparsers.add_parser("host", help="脱敏检查当前主机与安装证据")
    host_parser.add_argument("--proxy-port", type=int, action="append")
    session_parser = subparsers.add_parser("session", help="脱敏汇总一个 JSONL 会话")
    session_parser.add_argument("file", type=pathlib.Path)
    watch_parser = subparsers.add_parser("watch", help="只读监看指定 Linux 进程")
    watch_parser.add_argument("--pid", type=int, required=True)
    watch_parser.add_argument("--interval", type=float, default=2.0)
    watch_parser.add_argument("--seconds", type=float)
    watch_parser.add_argument("--proxy-port", type=int, action="append")
    args = parser.parse_args()
    interval = getattr(args, "interval", 1.0)
    seconds = getattr(args, "seconds", None)
    specified_ports = getattr(args, "proxy_port", None)
    proxy_ports = [17897, 17898] if specified_ports is None else specified_ports
    if (
        not math.isfinite(interval)
        or not 0.05 <= interval <= 3600
        or seconds is not None and (
            not math.isfinite(seconds) or not 0.05 <= seconds <= 86400
        )
        or any(not 1024 <= port <= 65535 for port in proxy_ports)
    ):
        raise RuntimeError("interval 和 seconds 必须为正数")
    if args.command == "host":
        return host(set(proxy_ports))
    if args.command == "session":
        return session(args.file)
    return watch(args.pid, args.interval, args.seconds, set(proxy_ports))


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as error:
        print(json.dumps({"error": str(error), "scope": "未执行任何网络或配置修改。"}, ensure_ascii=False))
        raise SystemExit(2)

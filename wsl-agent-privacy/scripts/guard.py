#!/usr/bin/python3 -I
"""Run the native CLIs against a private home and a route-checked local proxy."""
from __future__ import annotations

import json
import fcntl
import os
import pathlib
import re
import shlex
import signal
import socket
import stat
import subprocess
import sys
import tempfile
import time
from contextlib import ExitStack

P = pathlib.Path
HERE = P(__file__).resolve().parent
sys.dont_write_bytecode = True
sys.path.insert(0, str(HERE))
import engine
import route

TOOLS = ("claude", "codex")
HOME_DIR = P.home()
CONFIG_DIR = HOME_DIR / ".config/wsl-agent-privacy"
STATE_DIR = HOME_DIR / ".local/state/wsl-agent-privacy"
BIN_DIR = HOME_DIR / ".local/share/wsl-agent-privacy/bin"
CONFIG = CONFIG_DIR / "config.json"
INSIDE = P("/opt/wsl-agent-privacy")
PYTHON = "/usr/bin/python3"
SIDE_BY_SIDE = P("/usr/local/libexec/wsl-agent-guard/bwrap")
BWRAP = str(SIDE_BY_SIDE if SIDE_BY_SIDE.is_file() else P("/usr/bin/bwrap"))


def check_bubblewrap() -> None:
    binary = P(BWRAP).resolve(strict=True)
    st = binary.stat()
    if (not stat.S_ISREG(st.st_mode) or st.st_uid != 0 or st.st_mode & 0o6022
            or any(p.stat().st_uid != 0 or p.stat().st_mode & 0o022 for p in binary.parents)):
        raise RuntimeError("bubblewrap must be root-owned, non-setuid and protected from user writes")
    version = subprocess.check_output([str(binary), "--version"], text=True, timeout=3).strip()
    match = re.fullmatch(r"bubblewrap (\d+)\.(\d+)\.(\d+)", version)
    if not match or tuple(map(int, match.groups())) < (0, 12, 0):
        raise RuntimeError("install a patched upstream bubblewrap (0.12.0 or newer)")


def private_dir(path: P) -> P:
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise RuntimeError(f"expected a private directory (mode 0700): {path}")
    return path


def create_config() -> None:
    private_dir(CONFIG_DIR)
    sample = {
        "ports": {"claude": 17897, "codex": 17898},
        "nodes": {tool: "REPLACE_WITH_FIXED_NODE" for tool in TOOLS},
        "controller": {"windows_pipe": "verge-mihomo"},
        "rendered_profile": "/replace/with/active/generated/mihomo.yaml",
        "executables": {tool: str(HOME_DIR / ".local/bin" / tool) for tool in TOOLS},
        "timezone": "Etc/UTC", "locale": "C.UTF-8", "wayland": False,
        "codex_no_daemon": True,
    }
    with os.fdopen(os.open(CONFIG, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w") as f:
        json.dump(sample, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(f"Edit the two fixed listeners and controller in {CONFIG}")


def load_config() -> dict:
    info = CONFIG.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise RuntimeError("config.json must be an owner-only regular file (mode 0600)")
    cfg = json.loads(CONFIG.read_text())
    ports = [cfg["ports"][tool] for tool in TOOLS]
    if any(type(p) is not int or not 1024 <= p <= 65535 for p in ports) or ports[0] == ports[1]:
        raise ValueError("choose two distinct unprivileged listener ports")
    return cfg


def shell_entries(claude_mode: str | None = None) -> None:
    """Preserve an existing selection unless the user explicitly switches modes."""
    private_dir(BIN_DIR)
    def wrapper(action, tool):
        cmd = shlex.join([PYTHON, "-I", str(HERE / "guard.py"), action, tool])
        return '#!/bin/sh\nexec ' + cmd + ' "$@"\n'

    native = wrapper("native", "claude")
    strict = wrapper("run", "claude")
    entries = {"claude-local": native, "claude-bwrap": strict, "codex": wrapper("run", "codex"),
               "claude": strict if claude_mode == "bwrap" else native}
    directory = os.open(BIN_DIR, os.O_NOFOLLOW | os.O_DIRECTORY)
    try:
        fcntl.flock(directory, fcntl.LOCK_EX)
        changes = {}
        for name, content in entries.items():
            path = BIN_DIR / name
            prior = None
            if os.path.lexists(path):
                allowed = (native, strict) if name == "claude" else (content,)
                if path.is_symlink() or not path.is_file() or (prior := path.read_text()) not in allowed:
                    raise RuntimeError(f"existing entry differs: {path}")
                if prior == content or (name == "claude" and claude_mode is None):
                    continue
            changes[path] = (prior, content)
        with tempfile.TemporaryDirectory(dir=BIN_DIR) as temp:
            for path, (prior, content) in changes.items():
                staged = P(temp) / path.name
                staged.write_text(content)
                staged.chmod(0o700)
                if prior is None:
                    os.link(staged, path)
                else:
                    if path.is_symlink() or not path.is_file() or path.read_text() != prior:
                        raise RuntimeError(f"entry changed during installation: {path}")
                    staged.replace(path)
    finally:
        os.close(directory)
    print('export PATH=' + shlex.quote(str(BIN_DIR)) + ':"$PATH"')


def tool_binary(cfg: dict, tool: str) -> tuple[P, P]:
    entry = P(cfg["executables"][tool]).expanduser()
    if not entry.is_absolute():
        raise ValueError("select an absolute native executable")
    real = entry.resolve(strict=True)
    if not real.is_file() or not os.access(real, os.X_OK):
        raise RuntimeError("native CLI is not executable")
    with real.open("rb") as f:
        if f.read(4) != b"\x7fELF":
            raise RuntimeError("select the Linux native ELF, not a shell, Node or Windows wrapper")
    return entry, real


def proxy_environment(port: int) -> dict[str, str]:
    proxy = f"http://127.0.0.1:{port}"
    env = {"NODE_USE_ENV_PROXY": "1", "NO_PROXY": "localhost,127.0.0.1,::1",
           "no_proxy": "localhost,127.0.0.1,::1"}
    for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "WS_PROXY", "WSS_PROXY"):
        env[key] = env[key.lower()] = proxy
    return env


def run_native_claude(args: list[str]) -> int:
    if args in (["--self-test"], ["update"], ["upgrade"]):
        return run_tool("claude", args)
    cfg = load_config()
    _, real = tool_binary(cfg, "claude")
    route.check(cfg, "claude")
    if args == ["--guard-check"]:
        print("claude: native entry fixed-node probe passed")
        return 0
    overrides = proxy_environment(cfg["ports"]["claude"])
    # WSL passes these variables to new Win32 children only when WSLENV lists them.
    forwarded = [key for key in overrides if key.isupper()]
    retained = [item for item in os.environ.get("WSLENV", "").split(":")
                if item and item.split("/", 1)[0].upper() not in forwarded]
    env = {**os.environ, **overrides, "WSLENV": ":".join([*retained, *(key + "/w" for key in forwarded)])}
    os.execve(real, [str(real), *args], env)


def mount(cmd: list[str], source: P, destination: P, *, write: bool = False) -> None:
    cmd.extend(("--bind" if write else "--ro-bind", str(source), str(destination)))


def prepare_namespace(cfg: dict, tool: str, args: list[str], runtime: P, relay: P,
                      entry: P, real: P, self_test: bool) -> tuple[list[str], dict, P | None]:
    tool_home = private_dir(private_dir(STATE_DIR) / tool)
    uid, gid = os.getuid(), os.getgid()
    cmd = [BWRAP, "--unshare-user", "--uid", str(uid), "--gid", str(gid),
           "--unshare-net", "--unshare-pid", "--unshare-ipc", "--unshare-uts",
           "--unshare-cgroup-try", "--cap-drop", "ALL", "--die-with-parent",
           "--hostname", "agent", "--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp",
           "--dir", "/var/tmp", "--dir", "/run/agent-guard", "--dir", f"/run/user/{uid}"]
    for name in ("usr", "bin", "sbin", "lib", "lib64"):
        path = P("/") / name
        if path.is_symlink():
            cmd.extend(("--symlink", os.readlink(path), str(path)))
        elif path.is_dir():
            mount(cmd, path, path)
    zone_name = cfg.get("timezone", "Etc/UTC")
    zone_root = P("/usr/share/zoneinfo")
    if not isinstance(zone_name, str) or P(zone_name).is_absolute() or ".." in P(zone_name).parts:
        raise ValueError("invalid IANA time zone")
    zone = (zone_root / zone_name).resolve(strict=True)
    if not zone.is_relative_to(zone_root) or not zone.is_file():
        raise ValueError("invalid IANA time zone")
    locale = cfg.get("locale", "C.UTF-8")
    if not re.fullmatch(r"[A-Za-z0-9_.@-]{1,48}", locale):
        raise ValueError("invalid locale")
    etc = runtime / "etc"
    etc.mkdir()
    for name, data in {
        "hosts": "127.0.0.1 localhost agent\n::1 localhost\n",
        "hostname": "agent\n", "resolv.conf": "nameserver 127.0.0.1\noptions attempts:1 timeout:1\n",
        "nsswitch.conf": "passwd: files\ngroup: files\nhosts: files dns\n",
        "passwd": f"agent:x:{uid}:{gid}::" + str(HOME_DIR) + ":/bin/sh\n",
        "group": f"agent:x:{gid}:\n", "timezone": zone_name + "\n",
    }.items():
        (etc / name).write_text(data)
    # Create destinations before binding the private /etc read-only.
    (etc / "localtime").symlink_to(zone_root / zone_name)
    for path in (P("/etc/alternatives"), P("/etc/ssl"), P("/etc/ld.so.cache")):
        if path.exists():
            dest = etc / path.name
            dest.mkdir() if path.is_dir() else dest.touch()
    mount(cmd, etc, P("/etc"))
    for path in (P("/etc/ssl"), P("/etc/alternatives"), P("/etc/ld.so.cache")):
        if path.exists():
            mount(cmd, path, path)
    mount(cmd, tool_home, HOME_DIR, write=True)
    mount(cmd, HERE, INSIDE)
    skill_path = ".claude/skills" if tool == "claude" else ".agents/skills"
    mount(cmd, HERE.parent, HOME_DIR / skill_path / "wsl-agent-privacy")
    mount(cmd, relay, P("/run/agent-guard/relay.sock"))
    # The real bin directory never becomes writable. Both CLIs see a temporary native entry.
    native_bin = runtime / "bin"
    native_bin.mkdir()
    native_entry = HOME_DIR / ".local/bin" / tool
    (native_bin / tool).symlink_to(real)
    is_update = not self_test and (args == ["update"] or (tool == "claude" and args == ["upgrade"]))
    staged = None
    if tool == "claude":
        managed = HOME_DIR / ".local/share/claude/versions"
        if is_update and (entry != native_entry or engine.native_release_target(entry, entry.readlink()) != real):
            raise RuntimeError("manual update requires the official native Claude link and versions directory")
        if real.parent == managed:
            mount(cmd, managed, managed, write=is_update)
        mount(cmd, real, real)
        if is_update:
            staged = native_bin / tool
    else:
        store = HOME_DIR / ".codex/packages/standalone"
        if real.is_relative_to(store / "releases"):
            if is_update and (not entry.is_symlink() or
                               P(os.path.abspath(entry.parent / entry.readlink())) != store / "current/bin/codex"):
                raise RuntimeError("standalone Codex update needs its stable current/bin/codex link")
            mount(cmd, store, store, write=is_update)
        else:
            if is_update:
                raise RuntimeError("use this installation's package manager in a separately verified maintenance environment")
            mount(cmd, real, real)
    mount(cmd, native_bin, native_entry.parent, write=is_update)
    cwd = P.cwd().resolve()
    if not self_test and not is_update and cwd != HOME_DIR:
        roots = [HOME_DIR, *(P(root).expanduser().resolve() for root in cfg.get("project_roots", []))]
        if not any(cwd.is_relative_to(root) and root != P("/") for root in roots):
            raise RuntimeError("use a project in your Linux home, or configure its exact project_roots entry")
        protected = [HOME_DIR, HERE, STATE_DIR, CONFIG_DIR, BIN_DIR, entry, real,
                     P(cfg["rendered_profile"]).expanduser().resolve(strict=True)]
        for key in ("secret_file", "unix_socket"):
            item = cfg["controller"].get(key)
            if item:
                protected.append(P(item).expanduser().resolve())
        if any(p.is_relative_to(cwd) for p in protected) or any(
            cwd.is_relative_to(p) for p in protected[1:5]
        ):
            raise RuntimeError("select a business project separate from the launcher and its configuration")
        mount(cmd, cwd, cwd, write=True)
    else:
        cwd = HOME_DIR
    port = cfg["ports"][tool]
    env = {"HOME": str(HOME_DIR), "USER": "agent", "LOGNAME": "agent", "SHELL": "/bin/bash",
           "PATH": str(native_entry.parent) + ":/usr/local/bin:/usr/bin:/bin:/usr/sbin",
           "LANG": locale, "LC_ALL": locale, "TZ": zone_name, "TERM": os.environ.get("TERM", "xterm"),
           "XDG_RUNTIME_DIR": f"/run/user/{uid}", **proxy_environment(port)}
    if cfg.get("wayland", False) and not is_update:
        wayland = os.environ.get("WAYLAND_DISPLAY", "wayland-0")
        if not re.fullmatch(r"wayland-[0-9]+", wayland):
            raise ValueError("expected a local Wayland socket name")
        xdg = os.environ.get("XDG_RUNTIME_DIR")
        sock = P(xdg) / wayland if xdg else P("/mnt/wslg/runtime-dir") / wayland
        if not sock.is_socket():
            raise RuntimeError("configured Wayland socket unavailable")
        mount(cmd, sock, P(env["XDG_RUNTIME_DIR"]) / wayland)
        env.update(WAYLAND_DISPLAY=wayland, GDK_BACKEND="wayland", LIBGL_ALWAYS_SOFTWARE="1")
    if (runtime / "adb.sock").is_socket():
        clients = runtime / "clients"
        clients.mkdir()
        client = clients / "adb"
        client.write_text('#!/bin/sh\nexec /usr/bin/python3 -I /opt/wsl-agent-privacy/usb.py "$@"\n')
        client.chmod(0o755)
        (clients / "adb.exe").symlink_to("adb")
        mount(cmd, clients, P("/run/agent-tools"))
        mount(cmd, runtime / "adb.sock", P("/run/agent-guard/adb.sock"))
        env["PATH"] = "/run/agent-tools:" + env["PATH"]
    if self_test:
        command = [PYTHON, "-I", str(INSIDE / "probe.py"), str(port), route.PROBES[tool]]
    elif tool == "claude":
        if any(a == "--settings" or a.startswith("--settings=") for a in args):
            raise ValueError("guard reserves Claude --settings for its proxy")
        env.update(DISABLE_TELEMETRY="1", DISABLE_ERROR_REPORTING="1")
        overrides = {k: v for k, v in env.items() if "PROXY" in k.upper()
                     or k in {"TZ", "DISABLE_TELEMETRY", "DISABLE_ERROR_REPORTING"}}
        command = [str(real), "--settings", json.dumps({"env": overrides}), *args]
    else:
        flags = ["--no-daemon"] if cfg.get("codex_no_daemon", True) and "--no-daemon" not in args else []
        command = [str(real), *flags, *args]
    cmd.extend(("--remount-ro", "/", "--chdir", str(cwd), "--", PYTHON, "-I", str(INSIDE / "sandbox_entry.py"),
                "--relay", str(INSIDE / "proxy_relay.py"), "--socket", "/run/agent-guard/relay.sock",
                "--port", str(port), "--timezone", zone_name, "--", *command))
    return cmd, env, staged


def run_tool(tool: str, args: list[str]) -> int:
    cfg = load_config()
    entry, real = tool_binary(cfg, tool)
    check_bubblewrap()
    tty_guard = P("/proc/sys/dev/tty/legacy_tiocsti")
    if not tty_guard.is_file() or tty_guard.read_text().strip() != "0":
        raise RuntimeError("safe interactive terminal isolation unavailable on this kernel")
    route.check(cfg, tool)
    approved_at = time.monotonic()
    base = P(f"/run/user/{os.getuid()}")
    if not base.is_dir() or base.lstat().st_uid != os.getuid() or base.stat().st_mode & 0o077:
        base = P("/tmp")
    with ExitStack() as restore, tempfile.TemporaryDirectory(prefix="agent-net.", dir=base) as temp, ExitStack() as services:
        runtime = P(temp)
        gate = engine.RouteGate(runtime / "gate", lambda: route.check(cfg, tool), approved_at=approved_at)
        gate.start()
        services.callback(gate.close)
        try:
            relay_path = runtime / "proxy"
            relay = subprocess.Popen(
                [PYTHON, "-I", str(HERE / "proxy_relay.py"), "host", "--socket", str(relay_path),
                 "--port", str(cfg["ports"][tool]), "--gate-socket", str(gate.path)],
                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                env={"PATH": "/usr/bin:/bin"}, text=True, start_new_session=True,
            )
            services.callback(engine.stop_broker, relay)
            engine.wait_ready(relay)
            test = args == ["--self-test"]
            usb = cfg.get("usb_adb")
            if usb and not test and args not in (["update"], ["upgrade"], ["--version"]):
                exe = P(usb["exe"]).expanduser()
                hashes = usb["sha256"]
                if (not exe.is_absolute() or exe.name.lower() != "adb.exe" or
                        set(hashes) != {"adb.exe", "AdbWinApi.dll", "AdbWinUsbApi.dll"} or
                        not all(isinstance(v, str) and re.fullmatch(r"[0-9a-f]{64}", v)
                                for v in hashes.values())):
                    raise ValueError("select an installed Windows ADB and pin its three file hashes")
                usb_env = {"PATH": "/usr/bin:/bin", "GUARD_ADB_EXE": str(exe),
                           "GUARD_ADB_HASHES": json.dumps(hashes), "GUARD_APK_PROJECT": str(P.cwd()),
                           "GUARD_ALLOW_APK_INSTALL": "1" if usb.get("allow_project_apk_install") is True
                           and P.cwd().resolve() != HOME_DIR else "0"}
                if "WSL_INTEROP" in os.environ:
                    usb_env["WSL_INTEROP"] = os.environ["WSL_INTEROP"]
                adb = subprocess.Popen(
                    [PYTHON, "-I", str(HERE / "usb.py"), "host", "--socket", str(runtime / "adb.sock"),
                     "--proxy-port", str(cfg["ports"][tool])], stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
                    env=usb_env, start_new_session=True,
                )
                services.callback(engine.stop_broker, adb)
                engine.wait_ready(adb)
            cmd, env, staged = prepare_namespace(cfg, tool, args, runtime, relay_path, entry, real, test)
            print(f"[{tool}] fixed proxy verified; running inside bwrap", file=sys.stderr, flush=True)
            rc = engine.run_bwrap(cmd, env)
            if rc == 0 and staged is not None:
                active = engine.activate_claude_update(entry, real, staged, runtime, relay_path)
                print(f"[claude] active native version: {active.name}", file=sys.stderr)
            if rc == 0 and tool == "codex" and args == ["update"]:
                store = HOME_DIR / ".codex/packages/standalone"
                link = (runtime / "bin/codex").readlink()
                if P(os.path.abspath(entry.parent / link)) != store / "current/bin/codex":
                    raise RuntimeError("Codex updater selected an unexpected native entry")
                selected = entry.resolve(strict=True)
                if not selected.is_relative_to(store / "releases") or selected.name != "codex":
                    raise RuntimeError("could not confirm the standalone Codex entry after update")
                manifest = json.loads((selected.parent.parent / "codex-package.json").read_text())
                version = manifest.get("version")
                if not isinstance(version, str) or not re.fullmatch(r"[0-9A-Za-z.+-]{1,64}", version):
                    raise RuntimeError("Codex package did not report a valid version")
                print(f"[codex] selected package: {version}; verify with codex --version", file=sys.stderr)
            return rc if rc >= 0 else 128 - rc
        finally:
            for sig in (signal.SIGINT, signal.SIGQUIT):
                restore.callback(signal.signal, sig, signal.signal(sig, signal.SIG_IGN))


def main(args: list[str]) -> int:
    if not sys.flags.isolated or P(sys.executable).resolve() != P(PYTHON).resolve():
        raise RuntimeError("use /usr/bin/python3 -I to run the guard")
    if args == ["init"]:
        create_config()
    elif args in (["entries"], ["entries", "--claude-native"], ["entries", "--claude-bwrap"]):
        load_config()
        shell_entries(args[1].removeprefix("--claude-") if len(args) == 2 else None)
    elif len(args) == 2 and args[0] in {"check", "checked-port"} and args[1] in TOOLS:
        config = load_config()
        route.check(config, args[1])
        print(config["ports"][args[1]] if args[0] == "checked-port" else f"{args[1]}: fixed-node probe passed")
    elif len(args) >= 2 and args[0] == "run" and args[1] in TOOLS:
        return run_tool(args[1], args[2:])
    elif args[:2] == ["native", "claude"]:
        return run_native_claude(args[2:])
    else:
        print("Usage: guard.py init | entries [--claude-native | --claude-bwrap] | check TOOL | "
              "native claude [ARGS...] | run TOOL [--self-test | ARGS...]", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv[1:]))
    except KeyboardInterrupt:
        raise SystemExit(130)
    except (OSError, KeyError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        print(f"[agent-guard] {exc}", file=sys.stderr)
        raise SystemExit(1)

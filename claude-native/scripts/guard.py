#!/usr/bin/python3 -I
"""Start the official Claude CLI in the user's WSL environment after a fixed-route check."""
from __future__ import annotations

import fcntl
import json
import os
from pathlib import Path
import shlex
import stat
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
sys.dont_write_bytecode = True
sys.path.insert(0, str(HERE))
import route

HOME_DIR = Path.home()
CONFIG_DIR = HOME_DIR / ".config/claude-native"
CONFIG = CONFIG_DIR / "config.json"
BIN_DIR = HOME_DIR / ".local/share/claude-native/bin"
PYTHON = "/usr/bin/python3"


def private_dir(path: Path) -> Path:
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise RuntimeError(f"expected a private directory (mode 0700): {path}")
    return path


def create_config() -> None:
    private_dir(CONFIG_DIR)
    sample = {
        "ports": {"claude": 17897},
        "nodes": {"claude": "CLAUDE_FIXED_NODE"},
        "controller": {"windows_pipe": "verge-mihomo"},
        "rendered_profile": "/replace/with/active/generated/mihomo.yaml",
        "executables": {"claude": str(HOME_DIR / ".local/bin/claude")},
    }
    with os.fdopen(os.open(CONFIG, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w") as f:
        json.dump(sample, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(f"Edit the Claude listener, node, controller and executable in {CONFIG}")


def load_config() -> dict:
    info = CONFIG.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise RuntimeError("config.json must be an owner-only regular file (mode 0600)")
    return json.loads(CONFIG.read_text())


def shell_entries() -> None:
    private_dir(BIN_DIR)
    cmd = shlex.join([PYTHON, "-I", str(HERE / "guard.py"), "native", "claude"])
    content = '#!/bin/sh\nexec ' + cmd + ' "$@"\n'
    directory = os.open(BIN_DIR, os.O_NOFOLLOW | os.O_DIRECTORY)
    try:
        fcntl.flock(directory, fcntl.LOCK_EX)
        paths = [BIN_DIR / name for name in ("claude", "claude-local")]
        missing = []
        for path in paths:
            if not os.path.lexists(path):
                missing.append(path)
            elif path.is_symlink() or not path.is_file() or path.read_text() != content:
                raise RuntimeError(f"existing entry differs: {path}")
        if missing:
            with tempfile.NamedTemporaryFile(mode="w", dir=BIN_DIR) as tmp:
                tmp.write(content)
                tmp.flush()
                os.fchmod(tmp.fileno(), 0o700)
                for path in missing:
                    os.link(tmp.name, path)
    finally:
        os.close(directory)
    print('export PATH=' + shlex.quote(str(BIN_DIR)) + ':"$PATH"')


def tool_binary(cfg: dict) -> Path:
    entry = Path(cfg["executables"]["claude"]).expanduser()
    if not entry.is_absolute():
        raise ValueError("select an absolute native executable")
    real = entry.resolve(strict=True)
    if not real.is_file() or not os.access(real, os.X_OK):
        raise RuntimeError("native CLI is not executable")
    with real.open("rb") as f:
        if f.read(4) != b"\x7fELF":
            raise RuntimeError("select the Linux native ELF, not a shell, Node or Windows wrapper")
    return real


def proxy_environment(port: int) -> dict[str, str]:
    proxy = f"http://127.0.0.1:{port}"
    env = {"NODE_USE_ENV_PROXY": "1", "NO_PROXY": "localhost,127.0.0.1,::1",
           "no_proxy": "localhost,127.0.0.1,::1"}
    for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "WS_PROXY", "WSS_PROXY"):
        env[key] = env[key.lower()] = proxy
    return env


def run_native_claude(args: list[str]) -> int:
    cfg = load_config()
    real = tool_binary(cfg)
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


def main(args: list[str]) -> int:
    if not sys.flags.isolated or Path(sys.executable).resolve() != Path(PYTHON).resolve():
        raise RuntimeError("use /usr/bin/python3 -I to run the guard")
    if args == ["init"]:
        create_config()
    elif args in (["entries"], ["entries", "--claude-native"]):
        load_config()
        shell_entries()
    elif args == ["check", "claude"]:
        route.check(load_config(), "claude")
        print("claude: fixed-node probe passed")
    elif args[:2] == ["native", "claude"]:
        return run_native_claude(args[2:])
    else:
        print("Usage: guard.py init | entries | check claude | native claude [CLI_ARGS...]", file=sys.stderr)
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

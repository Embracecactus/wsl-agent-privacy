#!/usr/bin/python3 -I
"""Claude entry for an existing WSL host with the Clash and bwrap guards installed."""
import json
import os
from pathlib import Path
import runpy
import sys


def main(name, args):
    home = Path.home()
    strict = home / ".local/lib/bwrap-agent-guard/bwrap_guard.py"
    if name not in {"claude", "claude-local", "claude-bwrap", "codex"}:
        raise RuntimeError("unknown launcher name")
    # Administrative probes and signed upgrades belong to the existing isolated runtime.
    probes = {"--self-test", "--check-cuda", "--check-windows-port", "--check-windows-powershell"}
    wrapper_args = args[:args.index("--")] if "--" in args else args
    shares_session = any(a == "--share-session" or a.startswith("--share-session=") for a in wrapper_args)
    if (name in {"claude-bwrap", "codex"} or args in (["update"], ["upgrade"]) or args[:1] == ["install"]
            or (args and args[0] in probes) or shares_session):
        tool = "codex" if name == "codex" else "claude"
        os.execv("/usr/bin/python3", ["/usr/bin/python3", "-I", str(strict), tool, *args])

    guard_dir = home / ".local/lib/claude-clash-guard"
    guard = runpy.run_path(str(guard_dir / "claude_guard.py"))
    settings = json.loads((guard_dir / "guard.json").read_bytes())
    if args == ["--guard-check"]:
        guard["check"](settings, start_if_missing=False)
        print("Claude 本地原生入口的固定节点检查通过。")
        return
    if Path("/run/agent-guard/relay.sock").is_socket():
        raise SystemExit("请在普通 WSL 终端启动原生入口")
    native = (home / ".local/state/bwrap-agent-guard/native/claude").resolve(strict=True)
    if native.parent != home / ".local/share/claude/versions":
        raise RuntimeError("unrecognized native Claude release")
    guard["check"](settings)
    env = {**os.environ, **guard["launch_environment"](settings)}
    # The vendor updater would replace ~/.local/bin/claude, which this deployment manages.
    env["DISABLE_AUTOUPDATER"] = "1"
    os.execve(native, [str(native), *args], env)


if __name__ == "__main__":
    sys.dont_write_bytecode = True
    try:
        main(Path(sys.argv[0]).name, sys.argv[1:])
    except KeyboardInterrupt:
        sys.exit(130)
    except Exception as exc:
        # Bridge errors may contain local configuration or login URLs.
        sys.exit(f"Claude 启动失败，请核对固定节点及原生程序（{type(exc).__name__}）。")

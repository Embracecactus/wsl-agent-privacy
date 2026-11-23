"""Select the everyday Claude entry in an existing host-guard installation."""
import argparse
import fcntl
import os
from pathlib import Path
import sys


def install(rt, source, default):
    home = Path.home()
    entries = home / ".local/lib/bwrap-agent-guard/entrypoints"
    entry = entries / "claude"
    bin_dir = home / ".local/bin"
    local = bin_dir / "claude-local"
    packages = home / ".local/lib/claude-clash-guard/host-entries"
    helper = Path(__file__).with_name("claude_host.py").read_bytes()
    release = packages / (rt.digest(helper) + ".py")
    original = (source / "entrypoints/claude").read_bytes()
    original_spec = rt.file_spec(original, 0o755)
    if original_spec["hash"] != "80913e392db5b8b55907a55afde840f79f87d436d535a89205b735180adab496":
        raise RuntimeError("unrecognized original host entry")
    if rt.snapshot(bin_dir / "claude") != rt.link_spec(entry):
        raise RuntimeError("expected the managed ~/.local/bin/claude link")
    rt.native_target(home, "claude", home / ".local/state/bwrap-agent-guard/native/claude")
    if not (entries.parent / "bwrap_guard.py").is_file():
        raise RuntimeError("existing bwrap launcher is missing")
    rt.owned_dir(packages)
    pending = []

    def plan(path, desired, allowed, data=None):
        before = rt.snapshot(path)
        if before == desired:
            return
        if before not in allowed:
            raise RuntimeError(f"independent change in {path.name}; inspect before switching")
        pending.append((path, before, desired, data))

    absent = {"type": "absent"}
    plan(release, rt.file_spec(helper, 0o755), [absent], helper)
    known_local = [absent]
    if local.is_symlink():
        old = local.readlink()
        if old.parent == packages and old.is_file() and old.name == rt.digest(old.read_bytes()) + ".py":
            known_local.append(rt.link_spec(old))
    plan(local, rt.link_spec(release), known_local)
    plan(bin_dir / "claude-bwrap", rt.link_spec(local), [absent])
    bashrc = home / ".bashrc"
    if bashrc.is_file():
        before = rt.snapshot(bashrc)
        body = bashrc.read_bytes()
        old = b'claude() {\n    /usr/bin/python3 -I "$HOME/.local/lib/bwrap-agent-guard/bwrap_guard.py" claude "$@"\n}'
        new = b'claude() {\n    "$HOME/.local/bin/claude" "$@"\n}'
        if b'claude()' in body:
            if body.count(old) + body.count(new) != 1 or body.count(b'claude()') != 1:
                raise RuntimeError("review the existing Claude shell function")
            old_comment = b"# Start Claude with fixed-proxy, identity, Wayland and approved Windows brokers."
            new_comment = b"# Use the selected Claude entry with its verified proxy."
            selected = new if default == "native" else old
            body = body.replace(old if default == "native" else new, selected, 1)
            comment, replacement = ((old_comment, new_comment) if default == "native"
                                    else (new_comment, old_comment))
            body = body.replace(comment + b"\n" + selected, replacement + b"\n" + selected, 1)
            plan(bashrc, rt.file_spec(body, before["mode"]), [before], body)
    desired = rt.link_spec(local) if default == "native" else original_spec
    plan(entry, desired, [original_spec, rt.link_spec(local)], original)

    # Publish the default last. The old shell function and the shared PATH both
    # remain usable if a process exits between two atomic file replacements.
    applied = []
    try:
        for path, before, after, data in pending:
            if rt.snapshot(path) != before:
                raise RuntimeError(f"{path.name} changed during installation")
            prior_data = path.read_bytes() if before["type"] == "file" else None
            rt.replace(path, after, data)
            applied.append((path, before, after, prior_data))
    except BaseException:
        for path, before, after, data in reversed(applied):
            if rt.snapshot(path) == after:
                rt.replace(path, before, data)
        raise
    print(f"Claude default: {default} ({len(pending)} changed entries)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("runtime", type=Path, help="host runtime source directory containing install_runtime.py")
    parser.add_argument("default", choices=("native", "bwrap"))
    args = parser.parse_args()
    source = args.runtime.resolve(strict=True)
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(source))
    import install_runtime

    entries = Path.home() / ".local/lib/bwrap-agent-guard/entrypoints"
    descriptor = os.open(entries, os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        install(install_runtime, source, args.default)
    finally:
        os.close(descriptor)

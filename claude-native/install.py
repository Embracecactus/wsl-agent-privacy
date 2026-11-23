#!/usr/bin/env python3
"""Install this Skill into Claude Code and/or Codex user Skill locations."""

from __future__ import annotations

import argparse
import contextlib
import errno
import fcntl
import hashlib
import os
import pathlib
import shutil
import stat
import sys
import tempfile
from collections.abc import Iterator


SKILL = "claude-native"
ROOT = pathlib.Path(__file__).resolve().parent
TARGETS = {
    "claude": pathlib.Path.home() / ".claude" / "skills" / SKILL,
    "codex": pathlib.Path.home() / ".agents" / "skills" / SKILL,
}
DISTRIBUTED_FILES = (
    "SKILL.md", "install.py", "agents/openai.yaml",
    "scripts/guard.py", "scripts/route.py", "scripts/controller.ps1",
    "references/setup.md", "references/network.md",
    "network/mihomo.example.yaml", "network/clash-verge.js",
)


class InstallError(RuntimeError):
    pass


def regular_source(path: pathlib.Path) -> None:
    info = path.lstat()
    if path.is_symlink() or not stat.S_ISREG(info.st_mode):
        raise InstallError(f"distribution contains an unsafe file: {path.relative_to(ROOT)}")


def distribution() -> dict[pathlib.PurePosixPath, pathlib.Path]:
    files = {pathlib.PurePosixPath(name): ROOT / name for name in DISTRIBUTED_FILES}
    for base in {path.parent for path in files.values()}:
        if not base.is_dir() or base.is_symlink():
            raise InstallError("distribution folder is unavailable")
    for source in files.values():
        regular_source(source)
    return files


def digest(path: pathlib.Path) -> str:
    content = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            content.update(block)
    return content.hexdigest()


def destination_state(destination: pathlib.Path, files: dict[pathlib.PurePosixPath, pathlib.Path]) -> str:
    if not os.path.lexists(destination):
        return "absent"
    if destination.is_symlink() or not destination.is_dir():
        return "conflict"
    expected = set(files)
    expected_directories = {
        parent
        for relative in expected
        for parent in relative.parents
        if parent != pathlib.PurePosixPath(".")
    }
    found: set[pathlib.PurePosixPath] = set()
    for current in destination.rglob("*"):
        relative = pathlib.PurePosixPath(current.relative_to(destination).as_posix())
        if current.is_symlink() or not current.is_file():
            if current.is_dir() and not current.is_symlink():
                if relative not in expected_directories:
                    return "conflict"
                continue
            return "conflict"
        found.add(relative)
        source = files.get(relative)
        if source is None or digest(current) != digest(source):
            return "conflict"
    return "same" if found == expected else "conflict"


def prepare_stage(parent: pathlib.Path, files: dict[pathlib.PurePosixPath, pathlib.Path]) -> pathlib.Path:
    stage = pathlib.Path(tempfile.mkdtemp(prefix=f".{SKILL}.stage-", dir=parent))
    try:
        for relative, source in files.items():
            target = stage / relative
            target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            shutil.copyfile(source, target)
            target.chmod(0o644)
        if destination_state(stage, files) != "same":
            raise InstallError("staged distribution verification failed")
        return stage
    except BaseException:
        shutil.rmtree(stage, ignore_errors=True)
        raise


@contextlib.contextmanager
def install_lock(parents: list[pathlib.Path]) -> Iterator[None]:
    descriptors: list[int] = []
    try:
        for parent in sorted(set(parents)):
            parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            if parent.is_symlink() or not parent.is_dir():
                raise InstallError(f"unsafe Skill parent: {parent}")
            lock = parent / f".{SKILL}.install.lock"
            descriptor = os.open(lock, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
            descriptors.append(descriptor)
            fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        for descriptor in reversed(descriptors):
            try:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
            finally:
                os.close(descriptor)


def remove_exact(destination: pathlib.Path, files: dict[pathlib.PurePosixPath, pathlib.Path]) -> bool:
    state = destination_state(destination, files)
    if state == "absent":
        return False
    if state != "same":
        raise InstallError(f"will not remove changed or incomplete Skill: {destination}")
    shutil.rmtree(destination)
    return True


def selected_targets(name: str) -> dict[str, pathlib.Path]:
    if name == "both":
        return dict(TARGETS)
    return {name: TARGETS[name]}


def install(targets: dict[str, pathlib.Path], files: dict[pathlib.PurePosixPath, pathlib.Path]) -> None:
    parents = [path.parent for path in targets.values()]
    with install_lock(parents):
        state = {name: destination_state(path, files) for name, path in targets.items()}
        conflicts = [name for name, value in state.items() if value == "conflict"]
        if conflicts:
            raise InstallError("existing Skill differs at: " + ", ".join(conflicts))
        stages = {
            name: prepare_stage(targets[name].parent, files)
            for name, value in state.items()
            if value == "absent"
        }
        created: list[str] = []
        try:
            for name, stage in stages.items():
                os.replace(stage, targets[name])
                created.append(name)
        except BaseException:
            for name in reversed(created):
                if destination_state(targets[name], files) == "same":
                    shutil.rmtree(targets[name])
            raise
        finally:
            for stage in stages.values():
                if stage.exists():
                    shutil.rmtree(stage, ignore_errors=True)
    for name, value in state.items():
        outcome = "already current" if value == "same" else "installed"
        print(f"{name}: {outcome}")


def remove(targets: dict[str, pathlib.Path], files: dict[pathlib.PurePosixPath, pathlib.Path]) -> None:
    with install_lock([path.parent for path in targets.values()]):
        states = {name: destination_state(path, files) for name, path in targets.items()}
        conflicts = [name for name, value in states.items() if value == "conflict"]
        if conflicts:
            raise InstallError("will not remove changed or incomplete Skill at: " + ", ".join(conflicts))
        for name, destination in targets.items():
            print(f"{name}: {'removed' if remove_exact(destination, files) else 'not installed'}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Install the native Claude launcher Skill in a user Skill directory."
    )
    parser.add_argument("--target", choices=("both", "claude", "codex"))
    parser.add_argument("--remove", action="store_true", help="remove only an unmodified installed copy")
    args = parser.parse_args()
    if args.target is None:
        parser.print_help()
    return args


def main() -> int:
    args = parse_args()
    if args.target is None:
        return 0
    try:
        files = distribution()
        targets = selected_targets(args.target)
        if args.remove:
            remove(targets, files)
        else:
            install(targets, files)
    except (InstallError, OSError, shutil.Error) as exc:
        print(f"install.py: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

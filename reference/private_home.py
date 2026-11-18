"""Mount the current tool's existing account and selected work into a private home."""

import contextlib
import os
from pathlib import Path
import re
import shutil
import sqlite3
import stat
import tempfile


CODE = Path("/run/agent-code")
SHARED = Path("/run/shared-sessions")


def bind(command, source, destination=None, *, write=False):
    command.extend(("--bind" if write else "--ro-bind", str(source), str(destination or source)))


def private_dir(path):
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = path.lstat()
    if path.resolve() != path or not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
        raise RuntimeError("private agent state is not an owned directory")
    path.chmod(0o700)
    return path


def private_home(home, state, tool):
    folder = private_dir(private_dir(state / "homes") / tool)
    # The native Claude CLI atomically replaces this top-level file. A bind-mounted
    # file would break rename. Seed it once, without copying login files or histories.
    target, existing = folder / ".claude.json", home / ".claude.json"
    if tool == "claude" and not os.path.lexists(target) and existing.is_file():
        with tempfile.NamedTemporaryFile(dir=folder) as staged:
            with existing.open("rb") as source:
                shutil.copyfileobj(source, staged)
            staged.flush()
            with contextlib.suppress(FileExistsError):
                os.link(staged.name, target)
    return folder


def session_arguments(args, tool, home):
    """Consume wrapper options before --, pin canonical transcript files at launch."""
    forwarded, selected = [], []
    other = "codex" if tool == "claude" else "claude"
    base = home / ("." + other)
    roots = [base / "projects"] if other == "claude" else [base / "sessions", base / "archived_sessions"]
    it = iter(args)
    for arg in it:
        if arg == "--":
            forwarded.extend((arg, *it))
            break
        if arg != "--share-session" and not arg.startswith("--share-session="):
            forwarded.append(arg)
            continue
        value = next(it, "") if arg == "--share-session" else arg.partition("=")[2]
        if re.fullmatch(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}", value):
            matches = []
            if other == "codex":
                for db in sorted(base.glob("state_*.sqlite"), reverse=True):
                    try:
                        with contextlib.closing(sqlite3.connect(db.as_uri() + "?mode=ro", uri=True)) as conn:
                            row = conn.execute("SELECT rollout_path FROM threads WHERE id=?", (value,)).fetchone()
                    except sqlite3.OperationalError:
                        # Older Codex metadata can lack the current threads schema.
                        continue
                    if row and row[0] and Path(row[0]).is_file():
                        matches = [Path(row[0])]
                        break
            if not matches:
                matches = [p for root in roots if root.is_dir() for p in root.rglob("*" + value + ".jsonl")]
            if len(matches) != 1:
                raise ValueError("specify the exact transcript filename for --share-session")
            path = matches[0]
        else:
            path = Path(value).expanduser()
        path = path.resolve(strict=True)
        if (path.suffix != ".jsonl" or not path.is_file()
                or not any(path.is_relative_to(r) and r.resolve() == r for r in roots)):
            raise ValueError("--share-session accepts only the other tool's local transcript")
        if any(p.name == path.name and p != path for p in selected):
            raise ValueError("selected transcripts would have the same visible name")
        if path not in selected:
            selected.append(path)
    return forwarded, selected


def business_root(home, path):
    project = home / "project"
    if path.is_relative_to(project) and project.resolve() == project:
        return project
    # Windows interoperability is opt-in at the working-directory or --add-dir
    # boundary. A single business project never grants the whole drive/profile.
    parts = path.parts
    if len(parts) >= 5 and parts[1] == "mnt" and re.fullmatch(r"[a-z]", parts[2]):
        drive = Path(*parts[:3])
        if parts[3].lower() in {"projects", "project", "workspace", "repos"}:
            return drive / parts[3]
        if parts[3].lower() == "users" and len(parts) >= 7:
            profile = Path(*parts[:5])
            if parts[5].lower() in {"documents", "desktop", "videos", "pictures", "downloads"}:
                return profile / parts[5]
            drafts = "appdata/local/jianyingpro/user data/projects/com.lveditor.draft"
            if "/".join(parts[5:11]).lower() == drafts and len(parts) > 11:
                return Path(*parts[:11])
    raise ValueError("select a project under ~/project or a specific Windows business directory")


def work_paths(home, cwd, args, tool=None):
    result = []
    def add(path):
        resolved = path.expanduser().resolve(strict=True)
        if resolved == home:
            return resolved
        if not resolved.is_dir():
            raise ValueError("selected work path must be a directory")
        business_root(home, resolved)
        if resolved not in result:
            result.append(resolved)
        return resolved
    add(cwd)
    position = 0
    while position < len(args):
        arg = args[position]
        position += 1
        if arg == "--":
            break
        if arg in ("-C", "--cd", "--add-dir"):
            if position == len(args) or not args[position]:
                raise ValueError(f"{arg} needs a directory")
            value = args[position]
            position += 1
        elif arg.startswith(("--cd=", "--add-dir=")):
            value = arg.split("=", 1)[1]
        elif arg.startswith("-C") and len(arg) > 2:
            value = arg[2:]
        else:
            continue
        add(cwd / Path(value).expanduser())
        if tool == "claude" and arg == "--add-dir":
            while position < len(args) and not args[position].startswith("-"):
                extra = cwd / Path(args[position]).expanduser()
                if not extra.is_dir():
                    break
                add(extra)
                position += 1
    # A checkout entered through a subdirectory still needs its index and build root.
    for path in list(result):
        project = business_root(home, path)
        for parent in (path, *path.parents):
            if not parent.is_relative_to(project):
                break
            if parent == project and project != home / "project" and parent != path:
                break
            if (parent / ".git").exists():
                result.append(parent)
                break
    return sorted({p for p in result if not any(q != p and p.is_relative_to(q) for q in result)})


def mount_home(command, home, state, tool, work, selected, current_binary, bin_view, updating):
    folder = private_home(home, state, tool)
    bind(command, folder, home, write=True)
    for p in work:
        bind(command, p, write=True)
        dotgit = p / ".git"
        if dotgit.is_file() and dotgit.stat().st_size < 8192:
            spec = dotgit.read_text().strip()
            if spec.startswith("gitdir: "):
                gitdir = (p / spec[8:]).resolve(strict=True)
                if business_root(home, gitdir) != business_root(home, p):
                    raise ValueError("worktree metadata is outside the business directory")
                if (gitdir / "commondir").is_file():
                    common = (gitdir / (gitdir / "commondir").read_text().strip()).resolve(strict=True)
                    if common.name != ".git" or not common.is_relative_to(business_root(home, p)):
                        raise ValueError("unexpected worktree common directory")
                    bind(command, common, write=True)
    own = home / ("." + tool)
    if not own.is_dir() or own.resolve() != own:
        raise RuntimeError("existing tool account directory is unavailable")
    bind(command, own, write=True)
    protected = [own / "hooks", own / "skills", own / "hooks.json"]
    if tool == "codex":
        protected += [own / "packages", own / "plugins"]
    # These are shared tool binaries, Python packages or hook code, never the sibling's account.
    protected += [home / ".agents/skills",
                  home / ".local/lib/node_modules",
                  home / ".local/share/uv/python", home / ".nvm/versions/node",
                  home / ".gitconfig"]
    if os.environ.get("WSL_AGENT_SHARE_GH_AUTH") == "1":
        protected.append(home / ".config/gh")
    protected.extend(sorted((home / ".local/lib").glob("python*/site-packages")))
    for path in protected:
        if path.exists() and path.resolve() == path:
            bind(command, path)
    # Keep host daemon/control sockets out of the application state mount.
    for leaf in (("app-server-control", "app-server-daemon", "tmp") if tool == "codex" else ("daemon",)):
        if (own / leaf).is_dir():
            command.extend(("--tmpfs", str(own / leaf)))
    if tool == "codex":
        store = own / "packages/standalone"
        if not current_binary.is_relative_to(store / "releases"):
            raise RuntimeError("expected the native standalone Codex installation")
        bind(command, store, write=updating)
    else:
        store = home / ".local/share/claude/versions"
        if current_binary.parent != store:
            raise RuntimeError("expected the official versioned Claude installation")
        bind(command, store, write=updating)
    bind(command, current_binary)
    bind(command, bin_view, home / ".local/bin", write=updating)
    for name in ("ninja", "meson", "cmake", "ctest", "cpack", "uv", "uvx",
                 "manim", "pytest", "ruff", "west", "ffmpeg", "ffprobe"):
        program = home / ".local/bin" / name
        if program.is_file():
            bind(command, program.resolve(), Path("/run/agent-tools") / name)
    command.extend(("--dir", str(SHARED)))
    for file in selected:
        bind(command, file, SHARED / file.name)

    # Some native daemons leave filesystem sockets below their state or a checkout.
    # Hide existing host sockets in these grants without touching their underlying files.
    granted = (own, *work, *protected)
    for row in Path("/proc/net/unix").read_text().splitlines()[1:]:
        columns = row.split(maxsplit=7)
        if len(columns) != 8 or not columns[7].startswith("/"):
            continue
        path = Path(columns[7])
        if (any(path.is_relative_to(root) for root in granted) and path.is_socket()
                and path.resolve() == path and not any(path.is_relative_to(own / leaf) for leaf in
                          ("app-server-control", "app-server-daemon", "tmp", "daemon"))):
            bind(command, Path("/dev/null"), path)

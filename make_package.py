"""Build a shareable ZIP from the installer's explicit distribution manifest."""
import argparse
import ast
import hashlib
import os
from pathlib import Path
import stat
import tempfile
import zipfile


def build(source: Path, destination: Path) -> str:
    source = source.resolve(strict=True)
    tree = ast.parse((source / "install.py").read_bytes())
    manifest, = [ast.literal_eval(node.value) for node in tree.body if isinstance(node, ast.Assign)
                 and any(isinstance(t, ast.Name) and t.id == "DISTRIBUTED_FILES" for t in node.targets)]
    with tempfile.NamedTemporaryFile(dir=destination.parent, delete=False) as staged:
        tmp = Path(staged.name)
    try:
        with zipfile.ZipFile(tmp, "w") as archive:
            for name in sorted(manifest):
                path = source / name
                if path != path.resolve(strict=True) or not path.is_relative_to(source) or not path.is_file():
                    raise ValueError("unsafe package member")
                entry = zipfile.ZipInfo("claude-native/" + name, (1980, 1, 1, 0, 0, 0))
                entry.create_system = 3
                entry.external_attr = (stat.S_IFREG | 0o644) << 16
                archive.writestr(entry, path.read_bytes(), compress_type=zipfile.ZIP_DEFLATED)
        with zipfile.ZipFile(tmp) as archive:
            if archive.testzip() or len(archive.infolist()) != len(set(manifest)):
                raise ValueError("archive verification failed")
        tmp.chmod(0o644)
        os.replace(tmp, destination)
    finally:
        tmp.unlink(missing_ok=True)
    return hashlib.sha256(destination.read_bytes()).hexdigest()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("zip", type=Path)
    args = parser.parse_args()
    print(build(args.source, args.zip))

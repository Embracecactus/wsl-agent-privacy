"""Exercise the generated entries and host/native dispatch without an account or network."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "wsl-agent-privacy/scripts"))
import guard


class ClaudeModes(unittest.TestCase):
    def test_portable_entries_and_explicit_switch(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(guard, "BIN_DIR", Path(temp)):
            root = Path(temp)
            guard.shell_entries()
            self.assertEqual((root/"claude").read_bytes(), (root/"claude-local").read_bytes())
            guard.shell_entries("bwrap")
            strict = (root/"claude-bwrap").read_bytes()
            self.assertEqual((root/"claude").read_bytes(), strict)
            guard.shell_entries()
            self.assertEqual((root/"claude").read_bytes(), strict)
            (root/"codex").write_text("user entry\n")
            with self.assertRaisesRegex(RuntimeError, "existing entry differs"):
                guard.shell_entries("native")
            self.assertEqual((root/"claude").read_bytes(), strict)
            (root/"codex").unlink()
            guard.shell_entries("native")
            self.assertEqual((root/"claude").read_bytes(), (root/"claude-local").read_bytes())

    def test_portable_native_checks_before_exec_and_keeps_arguments(self):
        cfg = {"ports": {"claude": 17897}, "executables": {"claude": "/bin/true"}}
        args = ["--resume", "name with spaces", "--settings", "settings.json"]
        with (patch.object(guard, "load_config", return_value=cfg),
              patch.object(guard.route, "check", side_effect=RuntimeError("no route")) as check,
              patch.dict(os.environ, WSLENV="KEEP/p:HTTP_PROXY/p"),
              patch.object(os, "execve") as execute):
            with self.assertRaisesRegex(RuntimeError, "no route"):
                guard.run_native_claude(args)
            execute.assert_not_called()
            check.side_effect = None
            guard.run_native_claude(args)
            real, argv, env = execute.call_args.args
            self.assertEqual(argv, [str(real), *args])
            self.assertEqual(env["HOME"], os.environ["HOME"])
            self.assertEqual(env["PATH"], os.environ["PATH"])
            self.assertEqual(env["https_proxy"], "http://127.0.0.1:17897")
            self.assertEqual(env["no_proxy"], "localhost,127.0.0.1,::1")
            self.assertIn("KEEP/p", env["WSLENV"].split(":"))
            self.assertIn("HTTP_PROXY/w", env["WSLENV"].split(":"))
            self.assertNotIn("HTTP_PROXY/p", env["WSLENV"].split(":"))

    def test_host_runs_native_and_selects_existing_strict_runtime(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            entries = home/".local/bin"
            guard_dir = home/".local/lib/claude-clash-guard"
            strict = home/".local/lib/bwrap-agent-guard/bwrap_guard.py"
            native = home/".local/state/bwrap-agent-guard/native/claude"
            version = home/".local/share/claude/versions/1.0.0"
            for directory in (entries, guard_dir, strict.parent, native.parent, version.parent):
                directory.mkdir(parents=True)
            shutil.copy2(Path("/usr/bin/python3").resolve(), version)
            native.symlink_to(version)
            (guard_dir/"guard.json").write_text("{}")
            (guard_dir/"claude_guard.py").write_text(
                "def check(settings, start_if_missing=True):\n"
                "    if settings.get('blocked'): raise RuntimeError('route blocked')\n"
                "def launch_environment(settings): return {'https_proxy':'http://127.0.0.1:17897'}\n")
            strict.write_text("import json,sys\nprint(json.dumps(sys.argv[1:]))\n")
            for name in ("claude", "claude-local", "claude-bwrap", "codex"):
                (entries/name).symlink_to(ROOT/"integrations/claude_host.py")
            def run(name, *args, check=True):
                return subprocess.run(["/usr/bin/python3", "-I", str(entries/name), *args], cwd=temp,
                                      env={**os.environ, "HOME": temp}, capture_output=True,
                                      text=True, check=check)
            probe = ("import os,sys,json; print(json.dumps([os.getcwd(),os.environ['HOME'],"
                     "os.readlink('/proc/self/ns/net'),os.environ['https_proxy'],"
                     "os.environ['DISABLE_AUTOUPDATER'],sys.argv[1:]]))")
            for name in ("claude", "claude-local"):
                data = json.loads(run(name, "-c", probe, "--", "--share-session", "a b").stdout)
                self.assertEqual(data, [temp, temp, os.readlink("/proc/self/ns/net"),
                                        "http://127.0.0.1:17897", "1", ["--", "--share-session", "a b"]])
            for name, args, tool in (("claude-bwrap", ["--version"], "claude"),
                                     ("codex", ["--version"], "codex"),
                                     ("claude", ["--share-session=example"], "claude"),
                                     ("claude", ["update"], "claude")):
                self.assertEqual(json.loads(run(name, *args).stdout), [tool, *args])
            (guard_dir/"guard.json").write_text('{"blocked":true}')
            result = run("claude", "-c", "print('client started')", check=False)
            self.assertNotEqual(result.returncode, 0)
            self.assertNotIn("client started", result.stdout)


if __name__ == "__main__":
    unittest.main()

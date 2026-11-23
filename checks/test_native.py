"""Exercise the native branch entry points without using an account or a remote service."""
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / "claude-native/scripts"
sys.path.insert(0, str(SCRIPTS))
import guard


class NativeTests(unittest.TestCase):
    def test_new_home_creates_only_native_entries(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            env = {**os.environ, "HOME": temp}
            def invoke(*args, check=True):
                return subprocess.run(["/usr/bin/python3", "-I", str(SCRIPTS / "guard.py"), *args],
                                      env=env, capture_output=True, text=True, check=check)
            invoke("init")
            config = home / ".config/claude-native/config.json"
            self.assertEqual(stat.S_IMODE(config.stat().st_mode), 0o600)
            self.assertEqual(set(json.loads(config.read_text())["ports"]), {"claude"})
            self.assertNotEqual(invoke("init", check=False).returncode, 0)
            invoke("entries")
            invoke("entries")
            folder = home / ".local/share/claude-native/bin"
            self.assertEqual({entry.name for entry in folder.iterdir()}, {"claude", "claude-local"})
            self.assertEqual((folder / "claude").read_bytes(), (folder / "claude-local").read_bytes())
            self.assertTrue(os.access(folder / "claude", os.X_OK))

    def test_conflicting_alias_is_preserved(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(guard, "BIN_DIR", Path(temp)):
            folder = Path(temp)
            original = folder / "user-command"
            original.write_text("user content")
            (folder / "claude-local").symlink_to(original)
            with self.assertRaisesRegex(RuntimeError, "existing entry differs"):
                guard.shell_entries()
            self.assertFalse((folder / "claude").exists())
            self.assertEqual(original.read_text(), "user content")

    def test_native_checks_before_exec_and_keeps_arguments(self):
        cfg = {"ports": {"claude": 17897}, "executables": {"claude": "/bin/true"}}
        with (patch.object(guard, "load_config", return_value=cfg),
              patch.object(guard.route, "check", side_effect=RuntimeError("no route")) as check,
              patch.dict(os.environ, WSLENV="KEEP/p:HTTP_PROXY/p", TZ="Etc/UTC"),
              patch.object(os, "execve") as execute):
            with self.assertRaisesRegex(RuntimeError, "no route"):
                guard.run_native_claude(["--version"])
            execute.assert_not_called()
            check.side_effect = None
            self.assertEqual(guard.run_native_claude(["--guard-check"]), 0)
            execute.assert_not_called()
            for args in (["--resume", "name with spaces", "--settings", "settings.json"], ["update"], ["upgrade"]):
                with self.subTest(args=args):
                    guard.run_native_claude(args)
                    real, argv, env = execute.call_args.args
                    self.assertEqual(real, Path("/bin/true").resolve())
                    self.assertEqual(argv, [str(real), *args])
                    for key in ("HOME", "PATH", "TZ"):
                        self.assertEqual(env[key], os.environ[key])
                    self.assertEqual(env["https_proxy"], "http://127.0.0.1:17897")
                    self.assertEqual(env["HTTPS_PROXY"], env["https_proxy"])
                    self.assertEqual(env["no_proxy"], "localhost,127.0.0.1,::1")
                    fields = env["WSLENV"].split(":")
                    self.assertIn("KEEP/p", fields)
                    self.assertIn("HTTP_PROXY/w", fields)
                    self.assertNotIn("HTTP_PROXY/p", fields)
            self.assertEqual(check.call_count, 5)

    def test_same_chain_from_ordinary_listener_is_rejected(self):
        match = {"chains": ["fixture"], "specialProxy": "fixture", "inboundPort": 17897}
        guard.route.validate_match([match], "fixture", 17897, None)
        for key, value in (("specialProxy", ""), ("inboundPort", 7890)):
            with self.subTest(key=key), self.assertRaises(RuntimeError):
                guard.route.validate_match([{**match, key: value}], "fixture", 17897, None)


if __name__ == "__main__":
    unittest.main()

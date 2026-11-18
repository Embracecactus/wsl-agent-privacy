"""Offline regressions using temporary configuration, a synthetic client and no account."""
import contextlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "wsl-agent-privacy/scripts"))
import engine
import guard
import route


class GuardTests(unittest.TestCase):
    def test_listener_and_live_route(self):
        with tempfile.TemporaryDirectory() as folder:
            profile = Path(folder) / "active.yaml"
            config = {"rendered_profile": str(profile)}
            inbound = {"type": "http", "port": 17897, "listen": "127.0.0.1", "proxy": "fixture"}
            peer = {"type": "vless", "name": "fixture", "server": "192.0.2.1"}
            def write():
                profile.write_text(json.dumps({"listeners": [inbound], "proxies": [peer]}))
            write()
            route.verify_rendered(config, "claude", 17897, "fixture")
            inbound["proxy"] = "DIRECT"
            write()
            with self.assertRaises(RuntimeError):
                route.verify_rendered(config, "claude", 17897, "fixture")
            inbound["proxy"] = "fixture"
            peer["server"] = "fixture.test"
            write()
            with self.assertRaises(RuntimeError):
                route.verify_rendered(config, "claude", 17897, "fixture")
        metadata = {"inboundPort": "17897", "specialProxy": "fixture",
                    "sourcePort": 50000, "host": "fixture.test"}
        rows = [{"chains": ["fixture"], "metadata": metadata}]
        def verify():
            route.validate_match(route.matched_connections(rows, 50000, "fixture.test"),
                                 "fixture", 17897, None)
        verify()
        for field, value in (("specialProxy", ""), ("inboundPort", "17898")):
            with patch.dict(metadata, {field: value}), self.assertRaises(RuntimeError):
                verify()

    def test_gate_freshness(self):
        approved = engine.RouteGate(Path("unused"), lambda: None, approved_at=10.0)
        self.assertEqual(approved.approved_until, 25.0)
        self.assertEqual(engine.RouteGate(Path("unused"), lambda: None).approved_until, 0.0)

    def test_private_timezone_and_failed_start(self):
        # This fixture tests the namespace itself. A nested WSL user namespace
        # maps host root to nobody; the real launcher validates ownership outside it.
        self.assertTrue(Path(guard.BWRAP).is_file(), "install a patched bubblewrap first")
        with tempfile.TemporaryDirectory() as temp, contextlib.ExitStack() as cleanup:
            base = Path(temp)
            home = base / "home"
            home.mkdir(mode=0o700)
            for key, value in {"HOME_DIR": home, "STATE_DIR": base / "state"}.items():
                cleanup.enter_context(patch.object(guard, key, value))
            previous = Path.cwd()
            cleanup.callback(os.chdir, previous)
            os.chdir(home)
            runtime = base / "runtime"
            runtime.mkdir()
            proxy = cleanup.enter_context(socket.socket(socket.AF_UNIX))
            relay = runtime / "fixture.sock"
            proxy.bind(str(relay))
            config = {"ports": {"codex": 17898}, "timezone": "Etc/UTC", "codex_no_daemon": False}
            native = Path("/usr/bin/python3").resolve()
            child = ("import os,time; from pathlib import Path; "
                     "assert Path('/proc/net/dev').read_text().count(':') == 1; "
                     "os.environ.pop('TZ'); time.tzset(); assert time.timezone == 0; "
                     "print('client ran')")
            cmd, env, _ = guard.prepare_namespace(config, "codex", ["-I", "-c", child], runtime,
                                                   relay, native, native, False)
            def invoke():
                return subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=12)
            ok = invoke()
            self.assertEqual(ok.returncode, 0, ok.stderr)
            self.assertEqual(ok.stdout.strip(), "client ran")
            for field in ("env", "name", "link"):
                with self.subTest(field=field):
                    if field == "env":
                        env["TZ"] = "Etc/GMT+3"
                    elif field == "name":
                        (runtime / "etc/timezone").write_text("Etc/GMT+3\n")
                    else:
                        link = runtime / "etc/localtime"
                        link.unlink()
                        link.symlink_to("/usr/share/zoneinfo/Etc/GMT+3")
                    failed = invoke()
                    self.assertNotEqual(failed.returncode, 0)
                    self.assertNotIn("client ran", failed.stdout)
                    self.assertIn("isolated timezone check failed", failed.stderr)
                    self.assertNotIn("Etc/GMT+3", failed.stderr)
                    env["TZ"] = "Etc/UTC"
                    (runtime / "etc/timezone").write_text("Etc/UTC\n")


if __name__ == "__main__":
    unittest.main()

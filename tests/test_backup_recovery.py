from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest


ROOT = Path(__file__).resolve().parents[1]


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


WATCH = load_module("backup_watch", ROOT / "scripts/run-restic-backup.py")
MOUNT = load_module("backup_mount", ROOT / "rack-pi/scripts/check-rest-server-mount.py")


class RepositoryWatchTests(unittest.TestCase):
    def test_success_and_failure_codes_are_preserved(self):
        for code in (0, 7):
            self.assertEqual(
                WATCH.run_backup([sys.executable, "-c", f"raise SystemExit({code})"], interval=5),
                code,
            )

    def test_healthy_slow_backup_is_allowed_to_complete(self):
        probes = []

        def healthy():
            probes.append(True)
            return True

        self.assertEqual(
            WATCH.run_backup(
                [sys.executable, "-c", "import time; time.sleep(0.15)"],
                probe=healthy,
                interval=0.02,
            ),
            0,
        )
        self.assertTrue(probes)

    def test_failed_repository_stops_transfer_promptly(self):
        started = time.monotonic()
        result = WATCH.run_backup(
            [sys.executable, "-c", "import time; time.sleep(60)"],
            probe=lambda: False,
            interval=0.02,
        )
        self.assertEqual(result, 1)
        self.assertLess(time.monotonic() - started, 5)

    @unittest.skipUnless(os.name == "posix", "POSIX signal handling")
    def test_termination_does_not_leave_transfer_running(self):
        with tempfile.TemporaryDirectory() as directory:
            pidfile = Path(directory) / "pid"
            child = (
                "import os,time,pathlib; "
                f"pathlib.Path({str(pidfile)!r}).write_text(str(os.getpid())); "
                "time.sleep(60)"
            )
            process = subprocess.Popen(
                [sys.executable, str(ROOT / "scripts/run-restic-backup.py"),
                 sys.executable, "-c", child]
            )
            try:
                deadline = time.monotonic() + 5
                while not pidfile.exists() and time.monotonic() < deadline:
                    time.sleep(0.02)
                self.assertTrue(pidfile.exists())
                child_pid = int(pidfile.read_text())
                process.send_signal(signal.SIGTERM)
                self.assertEqual(process.wait(timeout=5), 143)
                with self.assertRaises(ProcessLookupError):
                    os.kill(child_pid, 0)
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait()


class MountIdentityTests(unittest.TestCase):
    def test_same_live_repository_is_accepted(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / "config"
            config.write_text('{"version": 2}')
            MOUNT.verify_mount(root, root, [config])

    def test_same_contents_on_different_mount_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            current, stale = root / "current", root / "stale"
            current.mkdir()
            stale.mkdir()
            for target in (current, stale):
                (target / "config").write_text('{"version": 2}')
            with self.assertRaises(ValueError):
                MOUNT.verify_mount(current, stale, [current / "config"])

    def test_repository_outside_mount_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repository = root / "repositories"
            repository.mkdir()
            config = root / "other-config"
            config.write_text("{}")
            with self.assertRaises(ValueError):
                MOUNT.verify_mount(repository, repository, [config])


@unittest.skipUnless(os.name == "posix" and os.geteuid() == 0, "isolated Linux/root shell tests")
class BackupPreflightTests(unittest.TestCase):
    def test_installer_preserves_systemd_escaped_mount_unit(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            rack = root / "rack-pi"
            (rack / "scripts").mkdir(parents=True)
            shutil.copytree(ROOT / "rack-pi/systemd", rack / "systemd")
            units, binaries = root / "units", root / "bin"
            units.mkdir()
            binaries.mkdir()
            fake_systemctl = binaries / "systemctl"
            fake_systemctl.write_text("#!/bin/sh\nexit 0\n")
            fake_systemctl.chmod(0o755)
            envfile = root / "backup.env"
            envfile.write_text("BACKUP_MOUNTPOINT=/mnt/rack-backup\n")
            installer = rack / "scripts/install-systemd.sh"
            installer.write_text(
                (ROOT / "rack-pi/scripts/install-systemd.sh").read_text()
                .replace("/etc/rack-pi/backup.env", str(envfile))
                .replace("/etc/systemd/system", str(units))
            )
            result = subprocess.run(
                ["bash", str(installer)], capture_output=True, text=True, timeout=10,
                env=dict(os.environ, PATH=f"{binaries}:{os.environ['PATH']}"),
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            service = (units / "rack-rest-server.service").read_text()
            self.assertIn(r"BindsTo=mnt-rack\x2dbackup.mount", service)
            self.assertIn("RequiresMountsFor=/mnt/rack-backup", service)
            self.assertNotIn("__BACKUP_", service)

    def test_unreadable_remote_repository_does_not_touch_docker(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            scripts, binaries = root / "scripts", root / "bin"
            scripts.mkdir()
            binaries.mkdir()
            backup_env = root / "backup.env"
            backup_env.write_text(
                "RESTIC_REPOSITORY=rest:http://127.0.0.1:1/minipc/state\n"
                "RESTIC_PASSWORD_FILE=/unused\n"
                f"XDG_CACHE_HOME={root}/cache\n"
            )
            (root / ".env").write_text(f"DATA_DIR={root}/data\nSTAGING_DIR={root}/staging\n")
            for name in ("backup.sh", "check-backup-target.sh", "read-stack-path.sh"):
                text = (ROOT / "scripts" / name).read_text()
                text = text.replace("/etc/raspberry-server/backup.env", str(backup_env))
                text = text.replace("/run/lock/raspberry-server-backup.lock", str(root / "lock"))
                (scripts / name).write_text(text)
            (scripts / "refresh-backup-status.sh").write_text("#!/bin/sh\nexit 0\n")
            calls = root / "docker-calls"
            for name, content in {
                "restic": "#!/bin/sh\nexit 1\n",
                "docker": f"#!/bin/sh\necho called >> '{calls}'\nexit 99\n",
            }.items():
                path = binaries / name
                path.write_text(content)
                path.chmod(0o755)
            env = dict(os.environ, PATH=f"{binaries}:{os.environ['PATH']}")
            result = subprocess.run(
                ["bash", str(scripts / "backup.sh")], env=env,
                capture_output=True, text=True, timeout=10,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("applications will remain online", result.stderr)
            self.assertFalse(calls.exists(), result.stdout + result.stderr)

    def test_wrong_uuid_is_rejected_even_with_identity_marker(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            mount = root / "disk"
            mount.mkdir()
            (mount / ".rack-pi-restic").touch()
            backup_env = root / "backup.env"
            backup_env.write_text(f"BACKUP_MOUNTPOINT={mount}\n")
            script = root / "check.sh"
            script.write_text((ROOT / "rack-pi/scripts/check-backup-disk.sh").read_text()
                              .replace("/etc/rack-pi/backup.env", str(backup_env)))
            binaries = root / "bin"
            binaries.mkdir()
            findmnt = binaries / "findmnt"
            findmnt.write_text(
                '#!/bin/sh\ncase "$*" in\n'
                ' *--fstab*) echo UUID=expected;;\n'
                ' *"-o UUID"*) echo unexpected;;\n'
                f' *) echo "{mount} ext4 /dev/sdz1";;\nesac\n'
            )
            findmnt.chmod(0o755)
            result = subprocess.run(
                ["bash", str(script)], capture_output=True, text=True, timeout=10,
                env=dict(os.environ, PATH=f"{binaries}:{os.environ['PATH']}"),
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("must match its UUID", result.stderr)


if __name__ == "__main__":
    unittest.main()

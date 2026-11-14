from pathlib import Path
import plistlib
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import install_macos


class MacOSInstallerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.source = root / "source"
        self.runtime = root / "runtime"
        self.plist = root / "LaunchAgents" / "bot.plist"
        self.source.mkdir()
        (self.source / "bot.py").write_text("print('bot')\n")
        (self.source / ".env").write_text("TELEGRAM_BOT_TOKEN=private-token\n")
        self.patches = [
            patch.object(install_macos, "SOURCE", self.source),
            patch.object(install_macos, "RUNTIME", self.runtime),
            patch.object(install_macos, "PLIST", self.plist),
            patch.object(install_macos, "TARGET", "gui/501/com.test.bot"),
            patch.object(install_macos.os, "getuid", return_value=501),
            patch.object(install_macos.sys, "platform", "darwin"),
        ]
        for item in self.patches:
            item.start()
            self.addCleanup(item.stop)

    def test_install_copies_private_files_and_registers_launch_agent(self):
        def run(command, **_kwargs):
            if command[1] == "bootstrap":
                return subprocess.CompletedProcess(command, 0, "", "")
            return subprocess.CompletedProcess(command, 0, "state = running\npid = 123\n", "")

        with patch.object(sys, "argv", ["install_macos.py"]), patch.object(
            install_macos.subprocess, "run", side_effect=run
        ) as run_command:
            install_macos.main()

        self.assertEqual((self.runtime / "bot.py").read_text(), "print('bot')\n")
        self.assertEqual((self.runtime / ".env").read_text(), "TELEGRAM_BOT_TOKEN=private-token\n")
        self.assertEqual(stat.S_IMODE(self.runtime.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE((self.runtime / ".env").stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(self.plist.stat().st_mode), 0o600)
        with self.plist.open("rb") as stream:
            job = plistlib.load(stream)
        self.assertEqual(job["ProgramArguments"][0], sys.executable)
        self.assertEqual(job["ProgramArguments"][-1], "--commands-only")
        self.assertTrue(job["RunAtLoad"])
        self.assertTrue(job["KeepAlive"])
        self.assertTrue(any(call.args[0][1] == "bootstrap" for call in run_command.call_args_list))

    def test_status_only_inspects_service(self):
        completed = subprocess.CompletedProcess([], 0, "state = running\n", "")
        with patch.object(sys, "argv", ["install_macos.py", "--status"]), patch.object(
            install_macos.subprocess, "run", return_value=completed
        ) as run_command:
            install_macos.main()
        run_command.assert_called_once_with(
            ["/bin/launchctl", "print", "gui/501/com.test.bot"],
            text=True,
            capture_output=True,
        )

    def test_stop_removes_launch_agent_but_keeps_runtime_config(self):
        self.plist.parent.mkdir(parents=True)
        self.plist.write_text("agent")
        self.runtime.mkdir()
        (self.runtime / ".env").write_text("preserve")
        with patch.object(sys, "argv", ["install_macos.py", "--stop"]), patch.object(
            install_macos.subprocess, "run"
        ) as run_command:
            install_macos.main()
        run_command.assert_called_once_with(
            ["/bin/launchctl", "bootout", "gui/501/com.test.bot"], capture_output=True
        )
        self.assertFalse(self.plist.exists())
        self.assertEqual((self.runtime / ".env").read_text(), "preserve")

    def test_install_requires_private_configuration(self):
        (self.source / ".env").unlink()
        with patch.object(sys, "argv", ["install_macos.py"]), self.assertRaises(SystemExit) as raised:
            install_macos.main()
        self.assertEqual(raised.exception.code, 1)

    def test_rejects_non_macos_platform(self):
        with patch.object(install_macos.sys, "platform", "linux"), patch.object(
            sys, "argv", ["install_macos.py"]
        ), self.assertRaises(SystemExit) as raised:
            install_macos.main()
        self.assertEqual(raised.exception.code, 1)


if __name__ == "__main__":
    unittest.main()

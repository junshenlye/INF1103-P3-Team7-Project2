"""Install and manage the Telegram command bot as a per-user macOS service."""
import argparse
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys

SOURCE = Path(__file__).resolve().parent
LABEL = "com.junshenlye.team-pr-bot"
RUNTIME = Path.home() / "Library" / "Application Support" / "TeamPRBot"
PLIST = Path.home() / "Library" / "LaunchAgents" / (LABEL + ".plist")
TARGET = "gui/%s/%s" % (os.getuid(), LABEL)


def service_status() -> bool:
    """Print the launch-agent state and return whether it is loaded."""
    result = subprocess.run(
        ["/bin/launchctl", "print", TARGET], text=True, capture_output=True
    )
    if result.returncode:
        print("The command listener is not loaded.")
        return False
    for line in result.stdout.splitlines():
        stripped = line.strip()
        if stripped.startswith(("state =", "pid =", "runs =", "last exit code =")):
            print(stripped)
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--stop", action="store_true", help="Stop and disable the login service")
    group.add_argument("--status", action="store_true", help="Show whether the login service is loaded")
    args = parser.parse_args()

    if sys.platform != "darwin":
        parser.exit(1, "This installer is for macOS.\n")
    if args.status:
        service_status()
        return
    if args.stop:
        subprocess.run(["/bin/launchctl", "bootout", TARGET], capture_output=True)
        if PLIST.exists():
            PLIST.unlink()
        print("Stopped the command listener and disabled login startup. Configuration and state are preserved.")
        return

    config = SOURCE / ".env"
    bot_source = SOURCE / "bot.py"
    if not config.is_file():
        parser.exit(1, "Configure integrations/telegram_bot/.env before installing.\n")
    if not bot_source.is_file():
        parser.exit(1, "The Telegram bot source file is missing.\n")

    RUNTIME.mkdir(parents=True, exist_ok=True, mode=0o700)
    RUNTIME.chmod(0o700)
    PLIST.parent.mkdir(parents=True, exist_ok=True)

    # Stop only this service before replacing its installed code or configuration.
    subprocess.run(["/bin/launchctl", "bootout", TARGET], capture_output=True)
    shutil.copyfile(bot_source, RUNTIME / "bot.py")

    runtime_config = RUNTIME / ".env"
    runtime_config.touch(mode=0o600, exist_ok=True)
    runtime_config.chmod(0o600)
    runtime_config.write_bytes(config.read_bytes())

    for name in ("stdout.log", "stderr.log"):
        log = RUNTIME / name
        log.touch(mode=0o600, exist_ok=True)
        log.chmod(0o600)

    job = {
        "Label": LABEL,
        "ProgramArguments": [
            sys.executable,
            "-u",
            str(RUNTIME / "bot.py"),
            "--commands-only",
        ],
        "WorkingDirectory": str(RUNTIME),
        "RunAtLoad": True,
        "KeepAlive": True,
        "ThrottleInterval": 30,
        "ProcessType": "Background",
        "EnvironmentVariables": {"PYTHONDONTWRITEBYTECODE": "1"},
        "StandardOutPath": str(RUNTIME / "stdout.log"),
        "StandardErrorPath": str(RUNTIME / "stderr.log"),
    }
    PLIST.write_bytes(plistlib.dumps(job))
    PLIST.chmod(0o600)

    result = subprocess.run(
        ["/bin/launchctl", "bootstrap", "gui/%s" % os.getuid(), str(PLIST)],
        capture_output=True,
    )
    if result.returncode:
        parser.exit(1, "macOS could not start the login service (exit %s).\n" % result.returncode)

    print("Installed the background command listener with automatic login startup.")
    print("Runtime and private configuration: " + str(RUNTIME))
    service_status()


if __name__ == "__main__":
    main()

"""Run the repository's Python and frontend verification checks locally."""

from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


def run(label: str, *command: str) -> None:
    """Run one check from the repository root and stop on its first failure."""
    print(f"\n== {label} ==", flush=True)
    try:
        subprocess.run(command, cwd=ROOT, check=True)
    except FileNotFoundError as error:
        raise SystemExit(
            f"Required command '{command[0]}' was not found. "
            "Install Python, Ruff, Node.js, and npm before running the checks."
        ) from error


def main() -> int:
    """Execute the same core checks used by the repository CI workflow."""
    run("Compile Python source and tests", sys.executable, "-m", "compileall", "-q", "src", "tests")
    run("Lint Python source and tests", "ruff", "check", "src", "tests")
    run(
        "Run Python unit tests",
        sys.executable,
        "-m",
        "unittest",
        "discover",
        "-s",
        "tests",
        "-v",
    )
    run("Run frontend checks", "npm", "run", "check", "--prefix", "frontend")
    run("Run processing/loading browser regression", "npm", "run", "test:loading", "--prefix", "frontend")
    run("Run calendar browser regression", "npm", "run", "test:calendar", "--prefix", "frontend")
    run("Run submission recovery browser regression", "npm", "run", "test:recovery", "--prefix", "frontend")
    print("\nAll local verification checks passed.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

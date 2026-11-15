"""Run isolated SQL, recovery, API, worker and browser checks; clean up on exit."""
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]


def run(*args, env=None, capture=False):
    return subprocess.run(args, cwd=ROOT, env=env, check=True, text=True,
                          stdout=subprocess.PIPE if capture else None)


def available_port():
    with socket.socket() as stream:
        stream.bind(("127.0.0.1", 0))
        return stream.getsockname()[1]


def main():
    name = "stackplan-rebuild-test-" + uuid4().hex[:10]
    server = None
    env = dict(os.environ)
    try:
        run("docker", "run", "--detach", "--name", name,
            "-e", "POSTGRES_USER=stackplan_test", "-e", "POSTGRES_PASSWORD=stackplan_test",
            "-e", "POSTGRES_DB=stackplan_rebuild_test", "-p", "127.0.0.1::5432",
            "postgres:16-alpine", capture=True)
        for _ in range(60):
            result = subprocess.run(["docker", "exec", name, "pg_isready", "-U", "stackplan_test"],
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if result.returncode == 0:
                break
            time.sleep(0.5)
        else:
            raise RuntimeError("Disposable database did not become ready.")
        port = run("docker", "port", name, "5432", capture=True).stdout.strip().rsplit(":", 1)[1]
        env["STACKPLAN_TEST_DATABASE_URL"] = (
            f"postgresql://stackplan_test:stackplan_test@127.0.0.1:{port}/stackplan_rebuild_test")
        env["STACKPLAN_TEST_CONTAINER"] = name
        run(sys.executable, "-m", "pytest", "-q", env=env)
        run("npm", "run", "check", "--prefix", "frontend", env=env)
        api_port = available_port()
        env["STACKPLAN_BROWSER_API_PORT"] = str(api_port)
        env["BROWSER_API_URL"] = f"http://127.0.0.1:{api_port}"
        with tempfile.TemporaryFile(mode="w+") as log:
            server = subprocess.Popen([sys.executable, "tests/frontend/server.py"],
                                      cwd=ROOT, env=env, stdout=log, stderr=log)
            for _ in range(300):
                log.seek(0)
                output = log.read()
                if "BROWSER_TEST_STACK_READY" in output:
                    break
                if server.poll() is not None:
                    raise RuntimeError(output)
                time.sleep(0.1)
            else:
                raise RuntimeError("Browser test stack did not become ready.\n" + output)
            run("npm", "run", "test:browser", "--prefix", "frontend", env=env)
    finally:
        if server is not None and server.poll() is None:
            server.terminate()
            try:
                server.wait(timeout=10)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait()
        subprocess.run(["docker", "rm", "--force", name], stdout=subprocess.DEVNULL)


if __name__ == "__main__":
    main()

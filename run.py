"""One-command launcher for the local MCP service and Streamlit UI."""

from __future__ import annotations

import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parent


def wait_for_server(timeout: float = 15) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen("http://127.0.0.1:8000/health", timeout=0.5) as response:
                if response.status == 200:
                    return
        except (urllib.error.URLError, TimeoutError):
            time.sleep(0.2)
    raise RuntimeError("Local MCP server did not become ready on port 8000")


def main() -> None:
    server = subprocess.Popen([sys.executable, "-m", "psy_consilium.servers.http_server"], cwd=ROOT)
    try:
        wait_for_server()
        if server.poll() is not None:
            raise RuntimeError("Не удалось запустить MCP на порту 8000: вероятно, порт уже занят другим процессом")
        try:
            subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "streamlit",
                    "run",
                    "app.py",
                    "--server.address=127.0.0.1",
                    "--server.port=8501",
                ],
                cwd=ROOT,
                check=True,
            )
        except KeyboardInterrupt:
            pass
    finally:
        server.terminate()
        try:
            server.wait(timeout=5)
        except subprocess.TimeoutExpired:
            server.kill()


if __name__ == "__main__":
    main()

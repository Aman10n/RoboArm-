"""Launch the RoboArm AI API and web development server together."""

from __future__ import annotations

import argparse
import shutil
import socket
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
FRONTEND_DIR = ROOT / "frontend"
BACKEND_PORT = 8000
FRONTEND_PORT = 5173


def port_is_open(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as connection:
        connection.settimeout(0.3)
        return connection.connect_ex(("127.0.0.1", port)) == 0


def check_prerequisites() -> None:
    missing = []
    for module in ("fastapi", "numpy", "pydantic", "uvicorn"):
        try:
            __import__(module)
        except ImportError:
            missing.append(module)

    if missing:
        raise RuntimeError(
            "Missing Python dependencies. Run: python -m pip install -r requirements.txt"
        )
    if not shutil.which("npm"):
        raise RuntimeError("Node.js and npm are required. Install Node.js 20 or newer.")
    if not (FRONTEND_DIR / "node_modules").exists():
        raise RuntimeError("Frontend dependencies are missing. Run: cd frontend && npm install")


def stream_output(process: subprocess.Popen, label: str) -> None:
    if process.stdout is None:
        return
    for line in process.stdout:
        output_encoding = sys.stdout.encoding or "utf-8"
        safe_line = line.encode(output_encoding, errors="replace").decode(output_encoding)
        print(f"[{label}] {safe_line}", end="", flush=True)


def start_process(command: list[str], cwd: Path) -> subprocess.Popen:
    return subprocess.Popen(
        command,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def stop_process_tree(process: subprocess.Popen) -> None:
    """Terminate a service and any child processes it launched."""
    if process.poll() is not None:
        return
    if sys.platform == "win32":
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            capture_output=True,
            check=False,
        )
    else:
        process.terminate()


def main() -> int:
    parser = argparse.ArgumentParser(description="Run RoboArm AI locally")
    parser.add_argument("--no-browser", action="store_true", help="Do not open the UI")
    parser.add_argument("--no-reload", action="store_true", help="Disable API auto-reload")
    args = parser.parse_args()

    try:
        check_prerequisites()
    except RuntimeError as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1

    if port_is_open(FRONTEND_PORT):
        print(f"Error: frontend port {FRONTEND_PORT} is already in use.", file=sys.stderr)
        return 1

    processes: list[subprocess.Popen] = []
    backend_owned = not port_is_open(BACKEND_PORT)
    try:
        if backend_owned:
            backend_command = [
                sys.executable,
                "-m",
                "uvicorn",
                "backend.main:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(BACKEND_PORT),
            ]
            if not args.no_reload:
                backend_command.append("--reload")
            backend = start_process(backend_command, ROOT)
            processes.append(backend)
            threading.Thread(
                target=stream_output, args=(backend, "api"), daemon=True
            ).start()
        else:
            print(f"Using the API already running on port {BACKEND_PORT}.")

        node_executable = shutil.which("node")
        vite_cli = FRONTEND_DIR / "node_modules" / "vite" / "bin" / "vite.js"
        frontend = start_process(
            [node_executable, str(vite_cli), "--host", "127.0.0.1", "--strictPort"],
            FRONTEND_DIR,
        )
        processes.append(frontend)
        threading.Thread(
            target=stream_output, args=(frontend, "web"), daemon=True
        ).start()

        url = f"http://localhost:{FRONTEND_PORT}"
        print(f"RoboArm AI is starting at {url}")
        print("Press Ctrl+C to stop all services.")
        if not args.no_browser:
            threading.Timer(2.5, lambda: webbrowser.open(url)).start()

        while all(process.poll() is None for process in processes):
            time.sleep(0.25)
        return next((process.returncode for process in processes if process.poll() is not None), 0)
    except KeyboardInterrupt:
        return 0
    finally:
        for process in reversed(processes):
            stop_process_tree(process)
        for process in processes:
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()


if __name__ == "__main__":
    raise SystemExit(main())

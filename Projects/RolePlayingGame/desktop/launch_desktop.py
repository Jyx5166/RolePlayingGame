from __future__ import annotations

import subprocess
import os
import sys
import time
import urllib.request
import webbrowser
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HOST = os.getenv("APP_HOST", "127.0.0.1")
PORT = int(os.getenv("APP_PORT", "8000"))
URL = f"http://{HOST}:{PORT}"


def wait_until_ready(timeout_seconds: float = 20.0) -> bool:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"{URL}/health", timeout=1.0) as response:
                return response.status == 200
        except OSError:
            time.sleep(0.3)
    return False


def main() -> int:
    command = [
        sys.executable,
        "-m",
        "uvicorn",
        "main:app",
        "--app-dir",
        "backend/app",
        "--host",
        HOST,
        "--port",
        str(PORT),
    ]
    process = subprocess.Popen(command, cwd=ROOT)
    if not wait_until_ready():
        process.terminate()
        print("服务启动失败，请在终端运行 python -m uvicorn main:app --app-dir backend/app 查看错误。")
        return 1

    webbrowser.open(URL)
    print(f"AI 剧本杀引擎已启动：{URL}")
    print("关闭此窗口将停止本地服务。")
    try:
        process.wait()
    except KeyboardInterrupt:
        process.terminate()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

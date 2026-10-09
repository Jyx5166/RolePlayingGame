from __future__ import annotations

import threading
import os
import sys
import time
import urllib.request
import webbrowser

import uvicorn

from paths import frontend_dir, scripts_dir


HOST = os.getenv("APP_HOST", "127.0.0.1")
PORT = int(os.getenv("APP_PORT", "8000"))
URL = f"http://{HOST}:{PORT}"


def is_ready() -> bool:
    try:
        with urllib.request.urlopen(f"{URL}/health", timeout=1.0) as response:
            return response.status == 200
    except OSError:
        return False


def wait_until_ready(timeout_seconds: float = 20.0) -> bool:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        if is_ready():
            return True
        time.sleep(0.3)
    return False


def run_server() -> None:
    from main import app

    uvicorn.run(app, host=HOST, port=PORT, log_level="warning")


def self_test() -> int:
    checks = [
        frontend_dir() / "index.html",
        frontend_dir() / "styles.css",
        frontend_dir() / "app.js",
        scripts_dir() / "flame_mountain.json",
    ]
    missing = [path for path in checks if not path.exists()]
    if missing:
        for path in missing:
            print(f"MISSING {path}")
        return 1
    print("SELF_TEST_OK")
    return 0


def main() -> int:
    if "--self-test" in sys.argv:
        return self_test()

    if not is_ready():
        server_thread = threading.Thread(target=run_server, daemon=True)
        server_thread.start()
        if not wait_until_ready():
            print("服务启动失败。")
            return 1

    if "--no-browser" not in sys.argv:
        webbrowser.open(URL)
    print(f"AI 剧本杀引擎已启动：{URL}")
    print("保持此窗口开启以维持本地服务。按 Ctrl+C 退出。")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())

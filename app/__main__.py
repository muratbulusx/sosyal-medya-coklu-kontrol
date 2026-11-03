"""Programı başlatır: python -m app"""

import argparse
import json
import logging
import os
import shutil
import socket
import subprocess
import sys
import threading
import webbrowser
from pathlib import Path

from werkzeug.serving import make_server

from .engine import Engine
from .platforms import create_platforms
from .server import create_app

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
SETTINGS_PATH = DATA_DIR / "ayarlar.json"
DEFAULT_SETTINGS = {"facebookUrl": "https://www.facebook.com/", "kapanmaSuresiSn": 30, "hesaplar": {}}
DEFAULT_PORT = 3579


def load_settings():
    try:
        return {**DEFAULT_SETTINGS, **json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))}
    except (OSError, ValueError):
        return dict(DEFAULT_SETTINGS)


def already_running(port):
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=1):
            return True
    except OSError:
        return False


def windows_chrome_paths(env):
    for variable in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA"):
        base = env.get(variable)
        if base:
            yield Path(base) / "Google" / "Chrome" / "Application" / "chrome.exe"


def open_in_chrome(url):
    """Hesapların açık olduğu Chrome'da açar; Chrome bulunamazsa varsayılan tarayıcıyı kullanır."""
    try:
        if sys.platform == "win32":
            chrome = next((path for path in windows_chrome_paths(os.environ) if path.exists()), None)
            if chrome:
                subprocess.Popen([str(chrome), url])
                return
        elif sys.platform == "darwin":
            if subprocess.run(["open", "-a", "Google Chrome", url], capture_output=True).returncode == 0:
                return
    except OSError:
        pass
    webbrowser.open(url)


def main():
    parser = argparse.ArgumentParser(description="Sosyal Medya Çoklu Kontrol")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--no-browser", action="store_true", help="Siteyi Chrome'da otomatik açma")
    args = parser.parse_args()
    url = f"http://localhost:{args.port}"

    # İkinci kez çift tıklanırsa yeni kopya başlatmak yerine açık olanı gösterir.
    if already_running(args.port):
        print(f"Program zaten açık: {url}")
        if not args.no_browser:
            open_in_chrome(url)
        return

    # Sayfa her saniye durum sorar; bu istekler pencereyi doldurmasın.
    logging.getLogger("werkzeug").setLevel(logging.ERROR)

    settings = load_settings()
    engine = Engine(
        create_platforms({"facebook": settings["facebookUrl"]}),
        error_dir=DATA_DIR / "hatalar",
        accounts=dict(settings["hesaplar"]),
        close_delay=float(settings["kapanmaSuresiSn"]),
    )

    def save_accounts(accounts):
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        SETTINGS_PATH.write_text(
            json.dumps({**settings, "hesaplar": accounts}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )

    temp_dir = DATA_DIR / "gecici"
    app = create_app(engine, temp_dir, save_accounts)
    try:
        server = make_server("127.0.0.1", args.port, app, threaded=True)
    except (OSError, SystemExit):
        print(f"{args.port} numaralı port başka bir program tarafından kullanılıyor.")
        sys.exit(1)

    shutil.rmtree(temp_dir, ignore_errors=True)
    print(f"Sosyal Medya Çoklu Kontrol hazır: {url}")
    print("Kullanırken bu pencereyi kapatma. Kapatınca program durur.", flush=True)
    if not args.no_browser:
        threading.Timer(0.5, open_in_chrome, [url]).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        if not engine.state["running"]:
            try:
                engine.shutdown()
            except Exception:
                pass


if __name__ == "__main__":
    main()

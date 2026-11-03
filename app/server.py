"""Yerel web sitesi: arayüzü sunar ve isteği motora iletir."""

import shutil
import tempfile
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory
from werkzeug.exceptions import RequestEntityTooLarge

from .engine import CONNECT_HELP, first_line

EXTENSIONS = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}
MAX_IMAGES = 4
MAX_UPLOAD_BYTES = MAX_IMAGES * 30 * 1024 * 1024 + 1024 * 1024
STATIC_DIR = Path(__file__).parent / "static"


def create_app(engine, temp_dir, save_accounts=lambda accounts: None):
    app = Flask(__name__, static_folder=None)
    app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_BYTES
    temp_dir = Path(temp_dir)

    # Yalnızca bu bilgisayardaki kendi sayfamız istek atabilir. Böylece gezilen
    # başka bir site, açık oturumlar üzerinden paylaşım başlatamaz.
    @app.before_request
    def only_local_page():
        port = request.environ.get("SERVER_PORT")
        host = request.headers.get("Host")
        host_ok = host in (f"127.0.0.1:{port}", f"localhost:{port}")
        origin_ok = request.method == "GET" or request.headers.get("Origin") == f"http://{host}"
        if not host_ok or not origin_ok:
            return jsonify(error="İzin verilmeyen istek"), 403
        return None

    def busy():
        return jsonify(error="Devam eden bir paylaşım var"), 409

    @app.get("/")
    def index():
        return send_from_directory(STATIC_DIR, "index.html")

    @app.get("/api/durum")
    def status():
        return jsonify(
            {
                **engine.state,
                "accounts": engine.accounts,
                "platforms": [{"id": p.id, "name": p.name, "accountHint": p.account_hint} for p in engine.platforms],
            }
        )

    @app.post("/api/hesaplar")
    def accounts():
        if engine.state["running"]:
            return busy()
        body = request.get_json(silent=True) or {}
        for platform in engine.platforms:
            name = body.get(platform.id)
            if isinstance(name, str):
                engine.accounts[platform.id] = name.strip()[:100]
        try:
            save_accounts(engine.accounts)
        except OSError as error:
            return jsonify(error=f"Hesaplar kaydedilemedi: {error}"), 500
        return jsonify(ok=True)

    @app.post("/api/paylas")
    def share():
        if engine.state["running"]:
            return busy()
        images = request.files.getlist("images")
        if not images:
            return jsonify(error="En az bir görsel ekle"), 400
        if len(images) > MAX_IMAGES:
            return jsonify(error=f"En fazla {MAX_IMAGES} görsel eklenebilir"), 400
        if any(image.mimetype not in EXTENSIONS for image in images):
            return jsonify(error="Yalnızca JPEG, PNG veya WebP yüklenebilir"), 400

        # Tarayıcı dosyayı paylaşım anında okuyabilir; bu yüzden önceki işin
        # dosyaları ancak yeni iş başlarken silinir.
        shutil.rmtree(temp_dir, ignore_errors=True)
        temp_dir.mkdir(parents=True, exist_ok=True)
        job_dir = Path(tempfile.mkdtemp(prefix="is-", dir=temp_dir))
        files = []
        for number, image in enumerate(images, start=1):
            path = job_dir / f"gorsel-{number}{EXTENSIONS[image.mimetype]}"
            image.save(path)
            files.append(str(path))

        try:
            engine.start(
                {"files": files, "caption": request.form.get("caption", "")},
                request.form.getlist("platforms"),
                request.form.get("live") == "true",
            )
        except ValueError as error:
            return jsonify(error=str(error)), 400
        return jsonify(ok=True), 202

    @app.post("/api/baglan")
    def connect():
        try:
            engine.connect()
        except Exception as error:
            print(f"Chrome bağlantı hatası: {first_line(error)}", flush=True)
            return jsonify(error=CONNECT_HELP), 502
        return jsonify(ok=True)

    @app.errorhandler(RequestEntityTooLarge)
    def too_large(_):
        return jsonify(error="Görseller çok büyük. Görsel başına en fazla 30 MB olmalı."), 413

    return app

"""Gerçek platformlara hiç dokunmadan motoru sınamak için, platforms.py'nin
beklediği düğme ve alanları taşıyan sahte sayfalar."""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

PIXEL = "data:image/gif;base64,R0lGODlhAQABAAAAACH5BAEKAAEALAAAAAABAAEAAAICTAEAOw=="
ACCOUNTS = f"""
  <div data-testid="SideNav_AccountSwitcher_Button">Resmi @resmi_x</div>
  <a href="/resmi_ig/"><img alt="resmi_ig'in profil resmi" src="{PIXEL}" width="10" height="10"></a>
  <div role="navigation"><a href="/">&nbsp;</a><a href="/profile.php?id=1">Resmi Sayfa</a></div>
  <div aria-haspopup="dialog"><img alt="Resmi NSosyal" src="{PIXEL}" width="10" height="10"></div>"""


def page(body):
    return f"""<!doctype html><meta charset="utf-8"><body>{ACCOUNTS}{body}
<script>
  const report = (site, extra = {{}}) => {{
    const input = document.querySelector('input[type=file]');
    const cap = document.querySelector('.cap');
    return fetch('/kayit', {{ method: 'POST', body: JSON.stringify({{
      site, files: input ? input.files.length : 0, caption: cap.value ?? cap.innerText, ...extra }}) }});
  }};
</script>"""


X_FIELDS = """
    <input data-testid="fileInput" type="file" multiple>
    <textarea class="cap" data-testid="tweetTextarea_0"></textarea>"""

PAGES = {
    "x": page(
        X_FIELDS
        + """<button data-testid="tweetButton" onclick="report('x').then(() => history.pushState({}, '', '/home'))">Post</button>"""
    ),
    "instagram": page("""
    <svg aria-label="Yeni Gönderi" width="30" height="30" onclick="document.getElementById('d').hidden=false"><rect width="30" height="30"/></svg>
    <div id="d" role="dialog" hidden>
      <input type="file" multiple>
      <button id="n" onclick="this.hidden=true;document.getElementById('n2').hidden=false">İleri</button>
      <button id="n2" hidden onclick="this.hidden=true;document.getElementById('s').hidden=false;document.getElementById('c').hidden=false">İleri</button>
      <div id="c" hidden class="cap" role="textbox" contenteditable="true"></div>
      <button id="s" hidden onclick="report('instagram').then(() => { document.getElementById('ok').hidden = false })">Paylaş</button>
      <div id="ok" hidden>Gönderin paylaşıldı</div>
    </div>"""),
    "facebook": page("""
    <button onclick="document.getElementById('d').hidden=false">Ne düşünüyorsun, Sayfa?</button>
    <div id="d" role="dialog" hidden>
      <div class="cap" role="textbox" contenteditable="true"></div>
      <button aria-label="Fotoğraf/video" onclick="this.insertAdjacentHTML('afterend','<input type=file multiple>')"></button>
      <button onclick="report('facebook').then(() => document.getElementById('d').remove())">Paylaş</button>
    </div>"""),
    "nsosyal": page("""
    <button onclick="document.getElementById('d').hidden=false">Gönderi Oluştur</button>
    <div id="d" hidden>
      <input type="file" multiple>
      <textarea class="cap"></textarea>
      <button onclick="report('nsosyal').then(() => { document.querySelector('.cap').value = '' })">Gönder</button>
    </div>
    <article><p>Bu haber paylaşıldı</p><button onclick="report('baskasinin-gonderisi')">Paylaş</button></article>"""),
    # Paylaş düğmesi hiç olmayan bozuk sayfa
    "bozuk": page(X_FIELDS),
    # Düğmeye basılıyor ama hiçbir sonuç görünmüyor
    "sessiz": page(X_FIELDS + """<button data-testid="tweetButton" onclick="report('sessiz')">Post</button>"""),
    "kullanici-sekmesi": page("<p>Kullanıcının kendi sekmesi</p>"),
}

LOGIN = page("""
  <input name="email">
  <button onclick="document.cookie='oturum=1;path=/';location.href=new URLSearchParams(location.search).get('geri')">Giriş</button>""")


class FakeSites:
    def __init__(self):
        self.posts = []
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def _html(self, html, status=200, location=None):
                data = html.encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                if location:
                    self.send_header("Location", location)
                self.end_headers()
                self.wfile.write(data)

            def do_POST(self):
                length = int(self.headers.get("Content-Length", 0))
                owner.posts.append(json.loads(self.rfile.read(length)))
                self._html("ok")

            def do_GET(self):
                path = urlparse(self.path).path
                if path == "/login":
                    return self._html(LOGIN)
                if path == "/korumali-x":
                    if "oturum=1" not in self.headers.get("Cookie", ""):
                        return self._html("", 302, "/login?geri=/korumali-x")
                    return self._html(PAGES["x"])
                return self._html(PAGES.get(path.strip("/"), "yok"))

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.origin = f"http://127.0.0.1:{self._server.server_address[1]}"
        threading.Thread(target=self._server.serve_forever, daemon=True).start()

    def close(self):
        self._server.shutdown()
        self._server.server_close()

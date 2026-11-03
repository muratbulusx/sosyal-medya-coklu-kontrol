"""Uçtan uca testler. Gerçek platformlara dokunmaz: geçici profilli ayrı bir Chrome
ve sahte siteler kullanır, kullanıcının kendi Chrome'una bağlanmaz."""

import base64
import io
import shutil
import socket
import tempfile
import threading
import time
import unittest
from pathlib import Path

from playwright.sync_api import sync_playwright
from werkzeug.serving import make_server

from app.__main__ import windows_chrome_paths
from app.engine import CONNECT_HELP, Engine, normalize_account
from app.platforms import create_platforms
from app.server import create_app
from tests.fake_sites import FakeSites

PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
)
ACCOUNTS = {"x": "resmi_x", "instagram": "resmi_ig", "facebook": "Resmi Sayfa", "nsosyal": "Resmi NSosyal"}
CAPTION = "Merhaba dünya\nİkinci satır"
ROOT = Path(__file__).resolve().parent.parent


def free_port():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sites = FakeSites()
        cls.dir = Path(tempfile.mkdtemp(prefix="smck-test-"))
        cls.files = []
        for name in ("a.png", "b.png"):
            path = cls.dir / name
            path.write_bytes(PNG)
            cls.files.append(str(path))
        cls.playwright = sync_playwright().start()

    @classmethod
    def tearDownClass(cls):
        cls.playwright.stop()
        cls.sites.close()
        shutil.rmtree(cls.dir, ignore_errors=True)

    def setUp(self):
        self.sites.posts.clear()
        self.engines = []
        self.chromes = []

    def tearDown(self):
        for engine in self.engines:
            engine.shutdown()
        for chrome in self.chromes:
            chrome.close()

    def real_platforms(self):
        return create_platforms({name: f"{self.sites.origin}/{name}" for name in ACCOUNTS})

    def only_x(self, path="x"):
        return create_platforms({"x": f"{self.sites.origin}/{path}"})[3]

    def open_chrome(self):
        """Kullanıcının zaten açık olan Chrome'unu, içindeki kendi sekmesiyle taklit eder."""
        port = free_port()
        chrome = self.playwright.chromium.launch_persistent_context(
            str(tempfile.mkdtemp(prefix="chrome-", dir=self.dir)),
            channel="chrome",
            headless=True,
            args=[f"--remote-debugging-port={port}"],
        )
        self.chromes.append(chrome)
        user_tab = chrome.new_page()
        user_tab.goto(f"{self.sites.origin}/kullanici-sekmesi")
        return chrome, user_tab, f"http://127.0.0.1:{port}"

    def engine_for(self, endpoint, platforms, accounts=None, **options):
        async def connect(playwright):
            return await playwright.chromium.connect_over_cdp(endpoint)

        settings = {"close_delay": 0.3, "unknown_page_timeout": 3.0, "account_timeout": 1.0, "poll": 0.1, **options}
        engine = Engine(
            platforms,
            error_dir=self.dir / "hatalar",
            accounts=dict(ACCOUNTS if accounts is None else accounts),
            connect=connect,
            **settings,
        )
        self.engines.append(engine)
        return engine

    def engine_with(self, platforms, accounts=None, **options):
        _, _, endpoint = self.open_chrome()
        return self.engine_for(endpoint, platforms, accounts, **options)

    def job(self):
        return {"files": self.files, "caption": CAPTION}

    def run_job(self, engine, ids, live):
        engine.start(self.job(), ids, live)
        engine.wait(timeout=90)

    @staticmethod
    def open_urls(engine):
        async def urls():
            context = await engine.get_context()
            return [page.url for page in context.pages if not page.url.endswith("/kullanici-sekmesi")]

        return engine.call(urls(), timeout=20)

    @staticmethod
    def statuses(engine):
        return {result["id"]: result["status"] for result in engine.state["results"]}


class EngineTests(Base):
    def test_dry_run_never_posts_and_keeps_tabs_open(self):
        engine = self.engine_with(self.real_platforms())
        self.run_job(engine, list(ACCOUNTS), False)
        self.assertEqual(self.statuses(engine), {key: "hazir" for key in ACCOUNTS})
        self.assertEqual(self.sites.posts, [])
        self.assertEqual(len([u for u in self.open_urls(engine) if u.startswith(self.sites.origin)]), 4)

    def test_live_posts_once_everywhere_and_closes_tabs(self):
        engine = self.engine_with(self.real_platforms())
        self.run_job(engine, list(ACCOUNTS), True)
        self.assertEqual(self.statuses(engine), {key: "paylasildi" for key in ACCOUNTS})
        self.assertEqual(sorted(post["site"] for post in self.sites.posts), sorted(ACCOUNTS))
        for post in self.sites.posts:
            self.assertEqual(post["files"], 2, post["site"])
            self.assertRegex(post["caption"], r"Merhaba dünya\s+İkinci satır", post["site"])
        time.sleep(0.7)
        self.assertEqual([u for u in self.open_urls(engine) if u.startswith(self.sites.origin)], [])

    def test_unselected_platform_is_not_touched(self):
        engine = self.engine_with(self.real_platforms())
        self.run_job(engine, ["x"], True)
        self.assertEqual([post["site"] for post in self.sites.posts], ["x"])

    def test_waits_for_login_then_posts(self):
        chrome, user_tab, endpoint = self.open_chrome()
        engine = self.engine_for(endpoint, [self.only_x("korumali-x")], unknown_page_timeout=15.0)
        engine.start(self.job(), ["x"], True)
        deadline = time.monotonic() + 30
        while engine.state["results"][0]["status"] != "giris-bekleniyor":
            self.assertLess(time.monotonic(), deadline, engine.state["results"][0])
            user_tab.wait_for_timeout(50)
        self.assertEqual(self.sites.posts, [])
        login = next(page for page in chrome.pages if "/login" in page.url)
        login.get_by_role("button", name="Giriş").click()
        engine.wait(timeout=60)
        self.assertEqual(engine.state["results"][0]["status"], "paylasildi", engine.state["results"][0])
        self.assertEqual(len(self.sites.posts), 1)

    def test_broken_platform_does_not_stop_others_and_tab_stays(self):
        broken = self.only_x("bozuk")

        async def quick_share(page):
            await page.locator('[data-testid="tweetButton"]').click(timeout=500)

        broken.share = quick_share
        facebook = create_platforms({"facebook": f"{self.sites.origin}/facebook"})[1]
        engine = self.engine_with([broken, facebook])
        self.run_job(engine, ["x", "facebook"], True)
        self.assertEqual(self.statuses(engine), {"x": "hata", "facebook": "paylasildi"})
        self.assertEqual([post["site"] for post in self.sites.posts], ["facebook"])
        self.assertTrue(any(u.endswith("/bozuk") for u in self.open_urls(engine)))
        self.assertTrue(list((self.dir / "hatalar").glob("*-x.png")))

    def test_unconfirmed_share_is_not_retried_and_tab_stays(self):
        silent = self.only_x("sessiz")

        async def never_confirmed(page):
            return False

        silent.confirm = never_confirmed
        engine = self.engine_with([silent])
        self.run_job(engine, ["x"], True)
        self.assertEqual(engine.state["results"][0]["status"], "kontrol-et")
        self.assertEqual(len(self.sites.posts), 1)
        self.assertTrue(any(u.endswith("/sessiz") for u in self.open_urls(engine)))

    def test_nsosyal_does_not_click_other_peoples_share_buttons(self):
        nsosyal = create_platforms({"nsosyal": f"{self.sites.origin}/nsosyal"})[2]
        engine = self.engine_with([nsosyal])
        self.run_job(engine, ["nsosyal"], True)
        self.assertEqual([post["site"] for post in self.sites.posts], ["nsosyal"])

    def test_leaves_user_tab_and_chrome_alone(self):
        chrome, user_tab, endpoint = self.open_chrome()
        engine = self.engine_for(endpoint, [self.only_x()], close_delay=0.1)
        seen = []
        chrome.on("page", lambda page: seen.append(page))
        self.run_job(engine, ["x"], True)
        self.assertEqual(engine.state["results"][0]["status"], "paylasildi")
        self.assertEqual(len(self.sites.posts), 1)
        user_tab.wait_for_timeout(500)
        self.assertEqual(len(seen), 1, "gönderi sekmesi aynı Chrome içinde açılmalı")
        self.assertTrue(seen[0].is_closed(), "kendi sekmesini kapatmalı")
        self.assertFalse(user_tab.is_closed(), "kullanıcının sekmesi açık kalmalı")
        self.assertRegex(user_tab.url, r"kullanici-sekmesi$")

        self.engines.remove(engine)
        engine.shutdown()
        self.assertEqual(user_tab.evaluate("1 + 1"), 2, "bağlantı kesilince Chrome açık kalmalı")

    def test_connection_failure_gives_clear_help(self):
        async def refuse(playwright):
            raise RuntimeError("reddedildi")

        engine = Engine(self.real_platforms(), self.dir / "hatalar", dict(ACCOUNTS), connect=refuse)
        self.engines.append(engine)
        self.run_job(engine, ["x", "facebook"], True)
        self.assertEqual(self.statuses(engine), {"facebook": "hata", "x": "hata"})
        self.assertEqual(engine.state["results"][0]["message"], CONNECT_HELP)
        self.assertFalse(engine.state["running"])
        self.assertEqual(self.sites.posts, [])

    def test_wrong_account_stops_before_attaching_others_continue(self):
        engine = self.engine_with(self.real_platforms(), {**ACCOUNTS, "x": "resmi_x2"})
        self.run_job(engine, ["x", "facebook"], True)
        self.assertEqual(self.statuses(engine), {"facebook": "paylasildi", "x": "hata"})
        self.assertEqual([post["site"] for post in self.sites.posts], ["facebook"])
        result = next(r for r in engine.state["results"] if r["id"] == "x")
        self.assertEqual(result["account"], "resmi_x")
        self.assertFalse(result["accountOk"])
        self.assertRegex(result["message"], r"Yanlış hesap açık.*resmi_x.*resmi_x2")

        async def attached_files():
            context = await engine.get_context()
            tab = next(page for page in context.pages if page.url.endswith("/x"))
            return await tab.locator('input[data-testid="fileInput"]').evaluate("i => i.files.length")

        self.assertEqual(engine.call(attached_files(), timeout=20), 0)

    def test_unreadable_account_stops_live_share(self):
        blind = self.only_x()

        async def no_account(page):
            return None

        blind.current_account = no_account
        engine = self.engine_with([blind])
        self.run_job(engine, ["x"], True)
        self.assertEqual(engine.state["results"][0]["status"], "hata")
        self.assertIn("okunamadı", engine.state["results"][0]["message"])
        self.assertEqual(self.sites.posts, [])

    def test_live_refuses_without_saved_accounts(self):
        async def must_not_connect(playwright):
            self.fail("tarayıcıya bağlanmamalı")

        engine = Engine(
            self.real_platforms(), self.dir / "hatalar", {"x": "resmi_x", "instagram": "  "}, connect=must_not_connect
        )
        self.engines.append(engine)
        with self.assertRaisesRegex(ValueError, "Önce paylaşılacak hesabı yaz: Instagram, Facebook"):
            engine.start(self.job(), ["x", "instagram", "facebook"], True)
        self.assertFalse(engine.state["running"])
        self.assertEqual(self.sites.posts, [])

    def test_dry_run_reports_open_accounts_without_saved_names(self):
        engine = self.engine_with(self.real_platforms(), {})
        self.run_job(engine, list(ACCOUNTS), False)
        self.assertEqual(self.statuses(engine), {key: "hazir" for key in ACCOUNTS})
        self.assertEqual({r["id"]: r["account"] for r in engine.state["results"]}, ACCOUNTS)
        self.assertEqual(self.sites.posts, [])


class ServerTests(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="smck-server-"))
        self.calls = []
        self.saved = []
        tester = self

        class FakePlatform:
            id = "x"
            name = "X"
            account_hint = ""

        class FakeEngine:
            state = {"running": False, "live": False, "connected": False, "results": []}
            platforms = [FakePlatform()]
            accounts = {}

            def start(self, job, ids, live):
                tester.calls.append((job, ids, live))

        self.engine = FakeEngine()
        self.engine.accounts = {}
        self.port = free_port()
        app = create_app(self.engine, self.dir / "gecici", lambda accounts: self.saved.append(dict(accounts)))
        self.server = make_server("127.0.0.1", self.port, app, threaded=True)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.port}"
        self.client = app.test_client()
        self.host = {"Host": f"127.0.0.1:{self.port}", "Origin": self.base}

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        shutil.rmtree(self.dir, ignore_errors=True)

    def post_share(self, headers, files=1, mimetype="image/png", **fields):
        data = {"images": [(io.BytesIO(PNG), f"{i}.png", mimetype) for i in range(files)], "platforms": "x", **fields}
        return self.client.post(
            "/api/paylas",
            data=data,
            content_type="multipart/form-data",
            headers=headers,
            environ_overrides={"SERVER_PORT": str(self.port)},
        )

    def request_json(self, path, headers, body=None):
        return self.client.post(path, json=body, headers=headers, environ_overrides={"SERVER_PORT": str(self.port)})

    def test_rejects_other_sites(self):
        evil = {"Host": f"127.0.0.1:{self.port}", "Origin": "https://kotu-site.example"}
        self.assertEqual(self.post_share(evil).status_code, 403)
        no_origin = {"Host": f"127.0.0.1:{self.port}"}
        self.assertEqual(self.request_json("/api/baglan", no_origin).status_code, 403)
        rebinding = {"Host": "kotu-site.example", "Origin": "http://kotu-site.example"}
        self.assertEqual(self.post_share(rebinding).status_code, 403)
        self.assertEqual(self.request_json("/api/hesaplar", evil, {"x": "kotu"}).status_code, 403)
        self.assertEqual(self.calls, [])
        self.assertEqual(self.saved, [])

    def test_share_defaults_to_not_posting(self):
        response = self.post_share(self.host)
        self.assertEqual(response.status_code, 202)
        self.assertFalse(self.calls[0][2], "live belirtilmezse gerçek paylaşım olmamalı")

    def test_share_keeps_image_order_and_checks_limits(self):
        response = self.post_share(self.host, files=4, live="true", caption="merhaba")
        self.assertEqual(response.status_code, 202)
        job, ids, live = self.calls[0]
        self.assertTrue(live)
        self.assertEqual(ids, ["x"])
        self.assertEqual(job["caption"], "merhaba")
        self.assertEqual([Path(path).name for path in job["files"]], [f"gorsel-{i}.png" for i in range(1, 5)])
        self.assertTrue(all(Path(path).exists() for path in job["files"]))
        self.assertEqual(self.post_share(self.host, files=5).status_code, 400)
        self.assertEqual(self.post_share(self.host, mimetype="image/heic").status_code, 400)

    def test_saves_only_known_accounts_trimmed(self):
        response = self.request_json("/api/hesaplar", self.host, {"x": "  resmi_x ", "bilinmeyen": "kotu"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.saved, [{"x": "resmi_x"}])

    def test_refuses_while_running(self):
        self.engine.state = {**self.engine.state, "running": True}
        self.assertEqual(self.post_share(self.host).status_code, 409)
        self.assertEqual(self.request_json("/api/hesaplar", self.host, {"x": "y"}).status_code, 409)

    def test_serves_page(self):
        response = self.client.get("/", headers={"Host": f"127.0.0.1:{self.port}"},
                                   environ_overrides={"SERVER_PORT": str(self.port)})
        self.assertIn("Sosyal Medya Çoklu Kontrol", response.get_data(as_text=True))
        response.close()


class SmallTests(unittest.TestCase):
    def test_account_names_ignore_only_case_at_sign_and_spaces(self):
        self.assertEqual(normalize_account("  @RESMİ_x "), normalize_account("resmi_x"))
        self.assertEqual(normalize_account("Resmi   Sayfa"), normalize_account("resmi sayfa"))
        self.assertEqual(normalize_account("MURAT"), normalize_account("murat".replace("i", "ı")))
        self.assertNotEqual(normalize_account("resmi_x2"), normalize_account("resmi_x"))
        self.assertNotEqual(normalize_account("Resmi Sayfa Yedek"), normalize_account("Resmi Sayfa"))
        self.assertNotEqual(normalize_account(""), normalize_account("x"))

    def test_finds_chrome_in_windows_locations(self):
        env = {"ProgramFiles": r"C:\Program Files", "LOCALAPPDATA": r"C:\Users\kisi\AppData\Local"}
        paths = [str(path) for path in windows_chrome_paths(env)]
        self.assertEqual(len(paths), 2)
        self.assertTrue(all(path.endswith("chrome.exe") for path in paths))

    def test_windows_launcher_is_safe_for_cmd(self):
        data = (ROOT / "baslat.bat").read_bytes()
        self.assertEqual(data.count(b"\n"), data.count(b"\r\n"), "cmd.exe için tüm satırlar CRLF olmalı")
        self.assertTrue(all(byte < 128 for byte in data), "bat dosyası yalnızca ASCII olmalı")
        text = data.decode("ascii")
        for target in ("deps", "run", "nopython", "venvfail", "pipfail", "appfail", "stop"):
            self.assertIn(f"\r\n:{target}\r\n", text, f"{target} etiketi eksik")

    def test_mac_launcher_is_executable_with_unix_lines(self):
        path = ROOT / "baslat.command"
        self.assertNotIn(b"\r", path.read_bytes())
        self.assertTrue(path.stat().st_mode & 0o111)


if __name__ == "__main__":
    unittest.main()

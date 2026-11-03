"""Açık Chrome'a bağlanıp paylaşım adımlarını sırayla çalıştıran motor."""

import asyncio
import os
import re
import sys
import threading
import time
import unicodedata
from datetime import datetime
from pathlib import Path

from playwright.async_api import async_playwright

CONNECT_HELP = (
    "Chrome'a bağlanılamadı. Chrome açık olmalı. Adres çubuğuna chrome://inspect/#remote-debugging yaz, "
    '"Allow remote debugging for this browser instance" kutusunu işaretle, sonra tekrar dene ve çıkan '
    "pencerede izin ver."
)


def normalize_account(name):
    """'@Resmi Hesap' ile 'resmi  hesap' aynı hesaptır; bunun dışında birebir eşleşme aranır."""
    text = unicodedata.normalize("NFC", name or "").strip()
    if text.startswith("@"):
        text = text[1:]
    text = re.sub(r"\s+", " ", text)
    return text.replace("İ", "i").replace("I", "ı").lower()


def chrome_profile_dirs():
    if sys.platform == "win32":
        return [Path(os.environ.get("LOCALAPPDATA", "")) / "Google" / "Chrome" / "User Data"]
    if sys.platform == "darwin":
        return [Path.home() / "Library" / "Application Support" / "Google" / "Chrome"]
    return [Path.home() / ".config" / "google-chrome"]


def debug_port():
    """Chrome'un bildirdiği portu okur. macOS bu okumayı engelleyebilir; o zaman varsayılan kullanılır."""
    for directory in chrome_profile_dirs():
        try:
            return int((directory / "DevToolsActivePort").read_text().split()[0])
        except (OSError, ValueError, IndexError):
            continue
    return 9222


async def connect_to_open_chrome(playwright):
    # Chrome ilk bağlantıda izin penceresi gösterir; süre "İzin ver"e basmaya yetecek kadar uzundur.
    return await playwright.chromium.connect_over_cdp(
        f"ws://127.0.0.1:{debug_port()}/devtools/browser", timeout=60_000
    )


def first_line(error):
    return str(error).split("\n")[0]


class Engine:
    def __init__(
        self,
        platforms,
        error_dir,
        accounts=None,
        close_delay=30.0,
        login_timeout=600.0,
        unknown_page_timeout=45.0,
        account_timeout=15.0,
        poll=1.0,
        connect=connect_to_open_chrome,
    ):
        self.platforms = platforms
        self.accounts = accounts if accounts is not None else {}
        self.state = {"running": False, "live": False, "connected": False, "results": []}
        self._error_dir = Path(error_dir)
        self._close_delay = close_delay
        self._login_timeout = login_timeout
        self._unknown_page_timeout = unknown_page_timeout
        self._account_timeout = account_timeout
        self._poll = poll
        self._connect = connect
        self._playwright = None
        self._browser = None
        self._close_handles = set()
        self._finished = None

        # Playwright'ın olayları kesintisiz işlemesi için tüm tarayıcı işleri tek bir arka plan döngüsünde yürür.
        self._loop = asyncio.new_event_loop()
        self._ready = threading.Event()
        threading.Thread(target=self._run_loop, daemon=True).start()
        self._ready.wait()

    def _run_loop(self):
        asyncio.set_event_loop(self._loop)
        self._lock = asyncio.Lock()
        self._loop.call_soon(self._ready.set)
        self._loop.run_forever()

    def call(self, coroutine, timeout=None):
        """Bir eşyordamı motor döngüsünde çalıştırır ve sonucunu bekler."""
        return asyncio.run_coroutine_threadsafe(coroutine, self._loop).result(timeout)

    # Her bağlantı Chrome'da izin sorar; eşzamanlı çağrılar aynı bağlantıyı paylaşır.
    async def get_browser(self):
        async with self._lock:
            if self._browser and self._browser.is_connected():
                return self._browser
            if not self._playwright:
                self._playwright = await async_playwright().start()
            browser = await self._connect(self._playwright)
            self._browser = browser
            self.state["connected"] = True

            def on_disconnected(_):
                if self._browser is browser:
                    self._browser = None
                    self.state["connected"] = False

            browser.on("disconnected", on_disconnected)
            return browser

    async def get_context(self):
        # Kullanıcının oturumları Chrome'un varsayılan bağlamındadır.
        return (await self.get_browser()).contexts[0]

    def connect(self):
        self.call(self.get_browser(), timeout=75)

    def _close_later(self, page):
        async def close():
            try:
                await page.close()
            except Exception:
                pass

        def fire():
            self._close_handles.discard(handle)
            asyncio.ensure_future(close())

        handle = self._loop.call_later(self._close_delay, fire)
        self._close_handles.add(handle)

    async def _save_screenshot(self, page, platform):
        try:
            self._error_dir.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            await page.screenshot(path=str(self._error_dir / f"{stamp}-{platform.id}.png"))
        except Exception:
            # Ekran görüntüsü alınamaması asıl sonucu değiştirmez.
            pass

    # Oturum düştüyse giriş ekranını öne getirir ve kullanıcının girmesini bekler.
    async def _wait_until_ready(self, page, platform, result):
        deadline = time.monotonic() + self._unknown_page_timeout
        waiting_for_login = False
        while True:
            if page.is_closed():
                raise RuntimeError("Sekme kapatıldı")
            if await platform.is_ready(page):
                return
            logged_out = await platform.is_logged_out(page)
            if logged_out and not waiting_for_login:
                waiting_for_login = True
                deadline = time.monotonic() + self._login_timeout
                result["status"] = "giris-bekleniyor"
                result["message"] = "Oturum kapalı. Açılan sekmede giriş yap, sonra kendiliğinden devam eder."
                await page.bring_to_front()
            elif not logged_out and waiting_for_login:
                waiting_for_login = False
                deadline = time.monotonic() + self._unknown_page_timeout
                result["status"] = "calisiyor"
                result["message"] = "Giriş yapıldı, devam ediliyor."
                await page.goto(platform.url, wait_until="domcontentloaded", timeout=60_000)
            if time.monotonic() > deadline:
                raise RuntimeError("Giriş için süre doldu" if waiting_for_login else "Paylaşım ekranı bulunamadı")
            await asyncio.sleep(self._poll)

    async def _read_account(self, page, platform):
        deadline = time.monotonic() + self._account_timeout
        while True:
            try:
                account = await platform.current_account(page)
            except Exception:
                account = None
            if account or time.monotonic() > deadline:
                return account
            await asyncio.sleep(self._poll)

    # Yanlış hesaba hiçbir şey eklenmesin diye görsellerden önce çalışır.
    async def _check_account(self, page, platform, result, live):
        expected = self.accounts.get(platform.id)
        result["account"] = await self._read_account(page, platform)
        result["accountOk"] = bool(
            result["account"] and expected and normalize_account(result["account"]) == normalize_account(expected)
        )
        if result["accountOk"]:
            return
        if result["account"] and expected:
            raise RuntimeError(f'Yanlış hesap açık: "{result["account"]}". Beklenen: "{expected}"')
        if not result["account"] and live:
            raise RuntimeError("Açık hesap okunamadı, güvenlik için durduruldu. Pencereyi büyütüp tekrar dene")

    async def _run_one(self, context, platform, job, result, live):
        page = None
        try:
            result["status"] = "calisiyor"
            result["message"] = "Sekme açılıyor."
            page = await context.new_page()
            await page.goto(platform.url, wait_until="domcontentloaded", timeout=60_000)
            await self._wait_until_ready(page, platform, result)

            result["status"] = "calisiyor"
            result["message"] = "Açık hesap kontrol ediliyor."
            await self._check_account(page, platform, result, live)

            result["message"] = "Görseller ve açıklama ekleniyor."
            await page.bring_to_front()
            await platform.prepare(page, job["files"], job["caption"])
            if not live:
                result["status"] = "hazir"
                if result["accountOk"]:
                    result["message"] = "Hazır, paylaşılmadı. Sekme açık kaldı."
                elif result["account"]:
                    result["message"] = "Hazır, paylaşılmadı. Paylaşmak için bu hesabı doğruysa kaydet."
                else:
                    result["message"] = "Hazır, paylaşılmadı. Ama açık hesap okunamadı, gerçek paylaşım durur."
                return

            result["message"] = "Paylaş düğmesine basılıyor."
            await platform.share(page)
            result["message"] = "Sonuç bekleniyor."
            if await platform.confirm(page):
                result["status"] = "paylasildi"
                result["message"] = "Paylaşıldı."
                self._close_later(page)
            else:
                # Paylaşılmış olabilir: yinelenen gönderi olmasın diye tekrar denemiyoruz.
                result["status"] = "kontrol-et"
                result["message"] = (
                    "Düğmeye basıldı ama sonuç doğrulanamadı. Sekmeyi kontrol et, tekrar paylaşmadan önce bak."
                )
                await self._save_screenshot(page, platform)
        except Exception as error:
            result["status"] = "hata"
            result["message"] = f"Paylaşılmadı: {first_line(error)}"
            if page:
                await self._save_screenshot(page, platform)

    async def _run(self, job, selected, live):
        try:
            context = await self.get_context()
            for platform in selected:
                result = next(r for r in self.state["results"] if r["id"] == platform.id)
                await self._run_one(context, platform, job, result, live)
        except Exception as error:
            print(f"Chrome bağlantı hatası: {first_line(error)}", file=sys.stderr)
            for result in self.state["results"]:
                if result["status"] == "bekliyor":
                    result["status"] = "hata"
                    result["message"] = CONNECT_HELP
        finally:
            self.state["running"] = False

    def start(self, job, platform_ids, live):
        if self.state["running"]:
            raise ValueError("Devam eden bir paylaşım var")
        selected = [p for p in self.platforms if p.id in platform_ids]
        if not selected:
            raise ValueError("En az bir platform seç")
        missing = [p.name for p in selected if not (self.accounts.get(p.id) or "").strip()]
        if live and missing:
            raise ValueError(f"Önce paylaşılacak hesabı yaz: {', '.join(missing)}")
        self.state["running"] = True
        self.state["live"] = live
        self.state["results"] = [
            {"id": p.id, "name": p.name, "status": "bekliyor", "message": "", "account": None, "accountOk": False}
            for p in selected
        ]
        self._finished = asyncio.run_coroutine_threadsafe(self._run(job, selected, live), self._loop)

    def wait(self, timeout=None):
        if self._finished:
            self._finished.result(timeout)

    # Yalnızca bağlantıyı keser; kullanıcının Chrome'u ve sekmeleri açık kalır.
    def shutdown(self):
        async def stop():
            for handle in self._close_handles:
                handle.cancel()
            self._close_handles.clear()
            if self._browser:
                await self._browser.close()
            if self._playwright:
                await self._playwright.stop()

        self.wait()
        self.call(stop(), timeout=15)
        self._loop.call_soon_threadsafe(self._loop.stop)

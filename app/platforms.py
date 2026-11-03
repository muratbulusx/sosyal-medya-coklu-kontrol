"""Her platformun web arayüzündeki adımları.

Siteler arayüzünü değiştirirse düzeltilecek tek yer burasıdır.
Arayüz Türkçe veya İngilizce olabilir.
"""

import asyncio
import re
from urllib.parse import urlparse

from playwright.async_api import Error as PlaywrightError

from .messages import Problem

STEP_TIMEOUT = 20_000
UPLOAD_TIMEOUT = 120_000
CONFIRM_TIMEOUT = 120_000


async def visible(locator):
    try:
        return await locator.first.is_visible()
    except PlaywrightError:
        return False


async def first_of(*waits):
    """Herhangi biri başarılı olunca True döner; hiçbiri olmazsa hata atmadan False."""
    pending = {asyncio.ensure_future(wait) for wait in waits}
    try:
        while pending:
            done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
            if any(not task.cancelled() and task.exception() is None for task in done):
                return True
        return False
    finally:
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)


async def attach_files(page, file_input, files, open_uploader=None):
    if not await file_input.count() and open_uploader:
        chooser_task = asyncio.ensure_future(page.wait_for_event("filechooser", timeout=STEP_TIMEOUT))
        await open_uploader()
        if not await file_input.count():
            try:
                chooser = await chooser_task
            except PlaywrightError:
                chooser = None
            if chooser:
                await chooser.set_files(files)
                return
        else:
            chooser_task.cancel()
            await asyncio.gather(chooser_task, return_exceptions=True)
    await file_input.first.wait_for(state="attached", timeout=STEP_TIMEOUT)
    await file_input.first.set_input_files(files)


async def type_caption(page, box, caption):
    if not caption.strip():
        return
    await box.click(timeout=STEP_TIMEOUT)
    lines = re.split(r"\r?\n", caption)
    for index, line in enumerate(lines):
        if line:
            await page.keyboard.insert_text(line)
        if index < len(lines) - 1:
            await page.keyboard.press("Enter")
    first_line = next(line for line in lines if line.strip()).strip()
    written = await box.evaluate("el => el.value ?? el.innerText")
    if first_line not in written:
        raise Problem("error.captionFailed")


class X:
    id = "x"
    name = "X"
    account_hint = "account.hintUsername"

    def __init__(self, url="https://x.com/compose/post"):
        self.url = url

    @staticmethod
    def _box(page):
        return page.locator('[data-testid="tweetTextarea_0"]')

    async def is_logged_out(self, page):
        if re.search(r"/(i/flow/login|login)", urlparse(page.url).path):
            return True
        return await visible(page.locator('[data-testid="loginButton"]'))

    async def is_ready(self, page):
        return await visible(self._box(page))

    async def current_account(self, page):
        text = await (
            page.locator('[data-testid="SideNav_AccountSwitcher_Button"]').first.inner_text(timeout=1_000)
        )
        match = re.search(r"@(\S+)", text)
        return match.group(1) if match else None

    async def prepare(self, page, files, caption):
        await attach_files(page, page.locator('input[data-testid="fileInput"]'), files)
        await type_caption(page, self._box(page).first, caption)

    async def share(self, page):
        await page.locator('[data-testid="tweetButton"]').click(timeout=UPLOAD_TIMEOUT)

    async def confirm(self, page):
        return await first_of(
            page.wait_for_url(
                lambda url: "/compose/" not in urlparse(url).path,
                timeout=CONFIRM_TIMEOUT,
                wait_until="commit",
            ),
            page.locator('[data-testid="toast"]').first.wait_for(timeout=CONFIRM_TIMEOUT),
        )


class Instagram:
    id = "instagram"
    name = "Instagram"
    account_hint = "account.hintUsername"

    def __init__(self, url="https://www.instagram.com/"):
        self.url = url

    @staticmethod
    def _create(page):
        return page.locator(
            'svg[aria-label="New post" i], svg[aria-label="Yeni gönderi" i], '
            'svg[aria-label="Create" i], svg[aria-label="Oluştur" i]'
        )

    @staticmethod
    def _next(page):
        return page.get_by_role("button", name=re.compile(r"^(Next|İleri)$"))

    async def is_logged_out(self, page):
        if "/accounts/login" in urlparse(page.url).path:
            return True
        return await visible(page.locator('input[name="username"]'))

    async def is_ready(self, page):
        return await visible(self._create(page))

    async def current_account(self, page):
        # Soldaki menüde yalnızca açık hesabın profil resmi vardır; akıştaki resimler daha sağdadır.
        return await page.evaluate(
            """() => {
              const image = [...document.querySelectorAll('a[href] img[alt]')].find((img) => {
                const box = img.getBoundingClientRect();
                return box.width > 0 && box.left < 120 && /profil/i.test(img.alt);
              });
              return image?.closest('a').getAttribute('href').replaceAll('/', '') ?? null;
            }"""
        )

    async def prepare(self, page, files, caption):
        await self._create(page).first.click(timeout=STEP_TIMEOUT)
        file_input = page.locator('[role="dialog"] input[type="file"], form input[type="file"]')
        # Pencere yavaş açılabilir; bazı hesaplarda önce "Gönderi" menüsü çıkar.
        post_item = page.get_by_text(re.compile(r"^(Post|Gönderi)$"))
        await file_input.or_(post_item).first.wait_for(state="attached", timeout=STEP_TIMEOUT)
        if not await file_input.count():
            await post_item.first.click(timeout=STEP_TIMEOUT)
        await attach_files(page, file_input, files)

        # Varsayılan kare kırpma yerine özgün oranı seçmeyi dener; bulamazsa devam eder.
        try:
            await page.locator('svg[aria-label="Select crop"], svg[aria-label="Kırpmayı seç"]').first.click(
                timeout=5_000
            )
            await page.get_by_text(re.compile(r"^(Original|Orijinal|Özgün)$")).first.click(timeout=3_000)
        except PlaywrightError:
            pass

        await self._next(page).first.click(timeout=UPLOAD_TIMEOUT)
        await self._next(page).first.click(timeout=STEP_TIMEOUT)
        await type_caption(page, page.locator('[role="dialog"] [role="textbox"]').first, caption)

    async def share(self, page):
        await (
            page.locator('[role="dialog"]')
            .get_by_role("button", name=re.compile(r"^(Share|Paylaş)$"))
            .first.click(timeout=STEP_TIMEOUT)
        )

    async def confirm(self, page):
        return await first_of(
            page.locator('[role="dialog"]')
            .get_by_text(
                re.compile(
                    r"(post|reel) has been shared|Gönderin paylaşıldı|Gönderi paylaşıldı|Post shared",
                    re.IGNORECASE,
                )
            )
            .first.wait_for(timeout=CONFIRM_TIMEOUT),
        )


class Facebook:
    id = "facebook"
    name = "Facebook"
    account_hint = "account.hintPage"

    def __init__(self, url="https://www.facebook.com/"):
        self.url = url

    @staticmethod
    def _trigger(page):
        return page.get_by_role("button", name=re.compile(r"Ne düşünüyorsun|What's on your mind"))

    @staticmethod
    def _dialog(page):
        return page.get_by_role("dialog").filter(has=page.locator('[role="textbox"]'))

    async def is_logged_out(self, page):
        if urlparse(page.url).path.startswith("/login"):
            return True
        return await visible(page.locator('input[name="email"]'))

    async def is_ready(self, page):
        return await visible(self._trigger(page))

    async def current_account(self, page):
        # Sol menüdeki yazılı ilk bağlantı o an kullanılan profil veya Sayfa'dır.
        return await page.evaluate(
            """() => {
              const link = [...document.querySelectorAll('[role="navigation"] a[href]')].find(
                (a) => a.getBoundingClientRect().width > 0 && a.innerText.trim(),
              );
              return link?.innerText.trim() ?? null;
            }"""
        )

    async def prepare(self, page, files, caption):
        await self._trigger(page).first.click(timeout=STEP_TIMEOUT)
        composer = self._dialog(page).first
        await composer.wait_for(timeout=STEP_TIMEOUT)

        async def open_uploader():
            await (
                composer.get_by_role("button", name=re.compile(r"Fotoğraf\/video|Photo\/video"))
                .first.click(timeout=STEP_TIMEOUT)
            )

        await attach_files(page, composer.locator('input[type="file"]'), files, open_uploader)
        await type_caption(page, composer.locator('[role="textbox"]').first, caption)

    async def share(self, page):
        next_button = self._dialog(page).first.get_by_role("button", name=re.compile(r"^(Next|İleri)$"))
        if await visible(next_button):
            await next_button.first.click(timeout=UPLOAD_TIMEOUT)
        await (
            page.get_by_role("dialog")
            .get_by_role("button", name=re.compile(r"^(Post|Paylaş|Gönder)$"))
            .first.click(timeout=UPLOAD_TIMEOUT)
        )

    async def confirm(self, page):
        return await first_of(self._dialog(page).first.wait_for(state="hidden", timeout=CONFIRM_TIMEOUT))


class NSosyal:
    id = "nsosyal"
    name = "NSosyal"
    account_hint = "account.hintName"

    def __init__(self, url="https://nsosyal.com/"):
        self.url = url

    @staticmethod
    def _box(page):
        return page.locator('textarea, [role="textbox"], [contenteditable="true"]')

    @staticmethod
    def _create(page):
        return page.get_by_role("button", name=re.compile(r"Gönderi Oluştur|Yeni gönderi", re.IGNORECASE))

    async def is_logged_out(self, page):
        return await visible(page.get_by_text(re.compile(r"^Giriş Yap$")))

    async def is_ready(self, page):
        return await visible(self._box(page)) or await visible(self._create(page))

    async def current_account(self, page):
        # Sağ üstteki hesap menüsünün resmi; gönderi kutusundaki resmin adı yoktur.
        return await page.evaluate(
            """() => {
              const image = [...document.querySelectorAll('[aria-haspopup="dialog"] img[alt]')].find((img) => {
                const box = img.getBoundingClientRect();
                return box.width > 0 && box.top < 120;
              });
              return image?.alt.trim() || null;
            }"""
        )

    async def prepare(self, page, files, caption):
        if not await visible(self._box(page)):
            await self._create(page).first.click(timeout=STEP_TIMEOUT)
        await self._box(page).first.wait_for(timeout=STEP_TIMEOUT)
        await attach_files(page, page.locator('input[type="file"]'), files)
        await type_caption(page, self._box(page).first, caption)

    async def share(self, page):
        # Akıştaki başkalarının gönderilerine değil, yalnızca gönderi kutusuna bakılır.
        await (
            self._box(page)
            .first.locator('xpath=ancestor::div[.//button[normalize-space()="Gönder"]][1]')
            .get_by_role("button", name="Gönder", exact=True)
            .click(timeout=UPLOAD_TIMEOUT)
        )

    async def confirm(self, page):
        # Akışta "paylaşıldı" yazan gönderiler olabileceği için sayfa metnine bakılmaz.
        box = self._box(page).first
        return await first_of(
            box.wait_for(state="hidden", timeout=CONFIRM_TIMEOUT),
            box.evaluate(
                """(el) => new Promise((resolve) => {
                  const timer = setInterval(() => {
                    if (!(el.value ?? el.innerText).trim()) {
                      clearInterval(timer);
                      resolve();
                    }
                  }, 500);
                })""",
                timeout=CONFIRM_TIMEOUT,
            ),
        )


def create_platforms(urls=None):
    urls = {key: value for key, value in (urls or {}).items() if value}
    return [
        Instagram(**({"url": urls["instagram"]} if "instagram" in urls else {})),
        Facebook(**({"url": urls["facebook"]} if "facebook" in urls else {})),
        NSosyal(**({"url": urls["nsosyal"]} if "nsosyal" in urls else {})),
        X(**({"url": urls["x"]} if "x" in urls else {})),
    ]

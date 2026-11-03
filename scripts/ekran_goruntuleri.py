"""README ekran görüntülerini her dil için docs/ekran klasörüne yazar.

Tamamen sahte verilerle, ayrı başsız bir Chrome'da çalışır; gerçek hesaplara dokunmaz.
Önce programı başlat: python -m app --no-browser
"""

import json
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

OUT = Path(__file__).resolve().parent.parent / "docs" / "ekran"
URL = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:3579"
CAPTIONS = {
    "en": "Photos from our weekend event. Thanks to everyone who came!",
    "tr": "Hafta sonu etkinliğimizden kareler. Katılan herkese teşekkürler!",
    "es": "Fotos de nuestro evento del fin de semana. ¡Gracias a todos los que vinieron!",
    "pt": "Fotos do nosso evento do fim de semana. Obrigado a todos que vieram!",
    "fr": "Photos de notre événement du week-end. Merci à tous ceux qui sont venus !",
    "de": "Fotos von unserer Veranstaltung am Wochenende. Danke an alle, die da waren!",
    "ru": "Фото с нашего мероприятия на выходных. Спасибо всем, кто пришёл!",
    "ar": "صور من فعاليتنا في نهاية الأسبوع. شكرًا لكل من حضر!",
    "zh": "周末活动的照片。感谢所有到场的朋友！",
    "ja": "週末のイベントの写真です。ご参加のみなさん、ありがとうございました！",
}
ACCOUNTS = {"instagram": "demo_account", "facebook": "Demo Page", "nsosyal": "Demo Account", "x": "demo_account"}
NAMES = {"instagram": "Instagram", "facebook": "Facebook", "nsosyal": "NSosyal", "x": "X"}
HINTS = {"instagram": "account.hintUsername", "facebook": "account.hintPage", "nsosyal": "account.hintName", "x": "account.hintUsername"}


def result(id, status, key):
    message = {"key": key, "params": {}} if key else None
    account = ACCOUNTS[id] if key else None
    return {"id": id, "name": NAMES[id], "status": status, "message": message, "account": account, "accountOk": bool(key)}


DEMO = {
    "running": False,
    "live": True,
    "connected": True,
    "accounts": ACCOUNTS,
    "platforms": [{"id": id, "name": NAMES[id], "accountHint": HINTS[id]} for id in NAMES],
    "results": [
        result("instagram", "paylasildi", "run.shared"),
        result("facebook", "paylasildi", "run.shared"),
        result("nsosyal", "calisiyor", "run.preparing"),
        result("x", "bekliyor", None),
    ],
}
FILL = """async (text) => {
  const paint = async (a, b, n) => {
    const c = document.createElement('canvas'); c.width = c.height = 600;
    const g = c.getContext('2d'); const f = g.createLinearGradient(0, 0, 600, 600);
    f.addColorStop(0, a); f.addColorStop(1, b); g.fillStyle = f; g.fillRect(0, 0, 600, 600);
    g.fillStyle = 'rgba(255,255,255,.22)'; g.beginPath(); g.arc(420, 190, 95, 0, 7); g.fill();
    g.fillStyle = 'rgba(0,0,0,.14)'; g.beginPath(); g.moveTo(0, 600); g.lineTo(230, 280); g.lineTo(600, 600); g.fill();
    const blob = await new Promise((r) => c.toBlob(r, 'image/png'));
    return new File([blob], `${n}.png`, { type: 'image/png' });
  };
  const pairs = [['#ff9a62', '#d83a6b'], ['#37c5d8', '#2b55e0'], ['#7bd88f', '#16794a'], ['#f5c451', '#d9792b']];
  const files = await Promise.all(pairs.map(([a, b], i) => paint(a, b, i)));
  const dt = new DataTransfer(); files.forEach((f) => dt.items.add(f));
  const input = document.getElementById('images'); input.files = dt.files; input.dispatchEvent(new Event('change'));
  const caption = document.getElementById('caption');
  caption.value = text; caption.dispatchEvent(new Event('input'));
}"""

OUT.mkdir(parents=True, exist_ok=True)
with sync_playwright() as playwright:
    browser = playwright.chromium.launch(channel="chrome", headless=True)
    for code, caption in CAPTIONS.items():
        context = browser.new_context(
            locale=code, viewport={"width": 1120, "height": 820}, device_scale_factor=1.5, color_scheme="light"
        )
        page = context.new_page()
        page.route("**/api/durum", lambda route: route.fulfill(content_type="application/json", body=json.dumps(DEMO)))
        page.goto(URL)
        page.wait_for_selector("#status li")
        page.evaluate(FILL, caption)
        page.wait_for_timeout(500)
        page.screenshot(path=str(OUT / f"{code}.png"), full_page=True)
        context.close()
    browser.close()

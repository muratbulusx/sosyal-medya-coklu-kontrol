"""Windows ve Mac için dağıtım zip'lerini dist/ klasörüne yazar.

Yalnızca aşağıda listelenen dosyalar pakete girer; hesap adları, hata görüntüleri
ve sanal ortam bu sayede hiçbir zaman pakete karışmaz.
"""

import stat
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"
FOLDER = "SosyalMedyaCokluKontrol"
COMMON = ["KULLANIM.txt", "LICENSE", "README.md", "requirements.txt", "docs/ekran-goruntusu.png"]
LAUNCHERS = {"Windows": "baslat.bat", "Mac": "baslat.command"}


def app_files():
    return sorted(
        path.relative_to(ROOT).as_posix()
        for path in (ROOT / "app").rglob("*")
        if path.is_file() and "__pycache__" not in path.parts
    )


def add(archive, relative, executable=False):
    info = zipfile.ZipInfo(f"{FOLDER}/{relative}", date_time=(2026, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    mode = 0o755 if executable else 0o644
    info.external_attr = (stat.S_IFREG | mode) << 16
    data = (ROOT / relative).read_bytes()
    # Windows'ta Not Defteri'nin Türkçe karakterleri doğru göstermesi için.
    if relative == "KULLANIM.txt":
        data = b"\xef\xbb\xbf" + data.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
    archive.writestr(info, data)


def main():
    DIST.mkdir(exist_ok=True)
    for system, launcher in LAUNCHERS.items():
        target = DIST / f"{FOLDER}-{system}.zip"
        with zipfile.ZipFile(target, "w") as archive:
            add(archive, launcher, executable=True)
            for relative in COMMON + app_files():
                add(archive, relative)
        print(f"{target.name}: {target.stat().st_size // 1024} KB")


if __name__ == "__main__":
    main()

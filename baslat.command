#!/bin/zsh
# Çift tıklayınca gerekli parçaları kurar, siteyi başlatır ve Chrome'da açar.
# Kapatmak için bu pencereyi kapat.
cd "$(dirname "$0")" || exit 1
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
export PYTHONUTF8=1

fail() {
  echo
  echo "$1"
  read -r "?Kapatmak icin Enter'a bas / Press Enter to close..."
  exit 1
}

if [[ ! -x .venv/bin/python ]]; then
  PY=""
  for candidate in python3 python3.14 python3.13 python3.12 python3.11 python3.10; do
    if "$candidate" -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >/dev/null 2>&1; then
      PY="$candidate"
      break
    fi
  done
  [[ -n "$PY" ]] || fail "Python 3.10 veya daha yenisi bulunamadi. https://www.python.org adresinden kurup tekrar dene.

Python 3.10 or newer was not found. Install it from https://www.python.org and try again."
  echo "Ilk acilis: hazirlik yapiliyor, bir iki dakika surebilir..."
  echo "First launch: setting up, this may take a minute or two..."
  "$PY" -m venv .venv || fail "Python ortami olusturulamadi. / Could not create the Python environment."
fi

if ! cmp -s requirements.txt .venv/kurulu.txt; then
  echo "Gerekli parcalar yukleniyor..."
  echo "Installing required packages..."
  .venv/bin/python -m pip install --disable-pip-version-check -q -r requirements.txt \
    || fail "Yukleme basarisiz oldu. Internet baglantisini kontrol edip tekrar dene.

Installation failed. Check your internet connection and try again."
  cp requirements.txt .venv/kurulu.txt
fi

.venv/bin/python -m app || fail "Program beklenmedik sekilde kapandi. / The program closed unexpectedly."

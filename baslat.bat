@echo off
setlocal
rem Cift tiklayinca gerekli parcalari kurar, siteyi baslatir ve Chrome'da acar.
rem Kapatmak icin bu pencereyi kapat.
chcp 65001 >nul
title Sosyal Medya Coklu Kontrol
cd /d "%~dp0"
set "PYTHONUTF8=1"
set "VENV_PY=.venv\Scripts\python.exe"
set "VERSION_CHECK=import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)"

if exist "%VENV_PY%" goto deps

set "PY="
py -3 -c "%VERSION_CHECK%" >nul 2>nul && set "PY=py -3"
if not defined PY python -c "%VERSION_CHECK%" >nul 2>nul && set "PY=python"
if not defined PY python3 -c "%VERSION_CHECK%" >nul 2>nul && set "PY=python3"
if not defined PY goto nopython

echo Ilk acilis: hazirlik yapiliyor, bir iki dakika surebilir...
%PY% -m venv .venv
if errorlevel 1 goto venvfail

:deps
fc /b requirements.txt .venv\kurulu.txt >nul 2>nul
if not errorlevel 1 goto run
echo Gerekli parcalar yukleniyor...
"%VENV_PY%" -m pip install --disable-pip-version-check -q -r requirements.txt
if errorlevel 1 goto pipfail
copy /y requirements.txt .venv\kurulu.txt >nul

:run
"%VENV_PY%" -m app
if errorlevel 1 goto appfail
exit /b 0

:nopython
echo.
echo Python 3.10 veya daha yenisi bulunamadi.
echo https://www.python.org adresinden kurarken "Add python.exe to PATH" kutusunu isaretle, sonra tekrar dene.
goto stop

:venvfail
echo.
echo Python ortami olusturulamadi. Klasoru Masaustu gibi normal bir yere cikardigindan emin ol.
goto stop

:pipfail
echo.
echo Yukleme basarisiz oldu. Internet baglantisini kontrol edip tekrar dene.
goto stop

:appfail
echo.
echo Program beklenmedik sekilde kapandi. Yukaridaki mesaji kontrol et.

:stop
echo.
pause
exit /b 1

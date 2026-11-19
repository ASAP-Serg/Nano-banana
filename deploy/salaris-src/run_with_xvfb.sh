#!/bin/sh
# Запуск с виртуальным дисплеем (для HEADLESS=false). Chrome без headless на сервере требует Xvfb.
# x11vnc — подключайся по VNC к порту 5900 и смотри, что делает Selenium.

export DISPLAY=:99
DISPLAY_WIDTH="${DISPLAY_WIDTH:-1920}"
DISPLAY_HEIGHT="${DISPLAY_HEIGHT:-1080}"
DISPLAY_DEPTH="${DISPLAY_DEPTH:-24}"
# Запускаем Xvfb в фоне, если ещё не запущен (порт 99 свободен)
if ! pgrep -x Xvfb > /dev/null 2>&1; then
    Xvfb :99 -screen 0 "${DISPLAY_WIDTH}x${DISPLAY_HEIGHT}x${DISPLAY_DEPTH}" &
    sleep 2
fi
# VNC: подключайся с ПК к серверу:5900 (TightVNC, TigerVNC и т.д.), пароль по желанию через -passwd
x11vnc -display :99 -forever -shared -rfbport 5900 -noxdamage -bg 2>/dev/null || true
# Один воркер для Selenium: избегаем гонок за Chrome-профиль и лишних Google-челленджей
exec gunicorn -w 1 -b 0.0.0.0:5000 --timeout 300 api_server:app

FROM python:3.11-slim

WORKDIR /app

# Установка системных зависимостей: Selenium, Xvfb, x11vnc (смотреть сессию Chrome по VNC)
RUN apt-get update && apt-get install -y \
    chromium \
    chromium-driver \
    curl \
    xvfb \
    x11vnc \
    procps \
    && rm -rf /var/lib/apt/lists/*

# Копируем requirements и устанавливаем зависимости
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копируем код
COPY . .

# Переменные окружения
ENV PYTHONUNBUFFERED=1
ENV CHROME_BIN=/usr/bin/chromium
ENV CHROMEDRIVER_PATH=/usr/bin/chromedriver

# Порты: 5000 — API, 5900 — VNC (подключиться и смотреть, что делает Chrome)
EXPOSE 5000 5900

# run_with_xvfb.sh уже в /app через COPY . . При HEADLESS=false Chrome использует виртуальный дисплей.
RUN chmod +x /app/run_with_xvfb.sh
ENV DISPLAY=:99
CMD ["/app/run_with_xvfb.sh"]


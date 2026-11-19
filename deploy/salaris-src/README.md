# Salaris Disabled — сервер (второй этап)

API для кнопки в Google Таблице: принимает строки с **item_ids** (заполнены пользователем на ПК через run.vbs + VPN) и проставляет статусы в Mosaica через Selenium.

**На сервере:** только `api_server.py` и `process_items_no_status.py` (логин в Mosaica и навигация встроены в скрипт, Fast-track не нужен).

## Деплой

**Автоматически (при пуше в GitHub):** настроен workflow `.github/workflows/deploy.yml`. При пуше в `master` или `main` сервер получает по SSH команды: `cd ~/salaris-api`, `git pull`, `docker-compose up -d --build`.

В репозитории GitHub → Settings → Secrets and variables → Actions должны быть секреты:
- **SERVER_HOST** — IP или хост сервера (например `155.212.147.137`)
- **SERVER_USER** — пользователь SSH (например `root`)
- **SSH_PRIVATE_KEY** — приватный ключ SSH (содержимое ключа, которым сервер разрешает логин; соответствующий публичный ключ должен быть в `~/.ssh/authorized_keys` на сервере)

На сервере репозиторий должен быть клонирован в `~/salaris-api` (внутри — этот же проект с `docker-compose.yml`).

**Вручную на сервере:** `cd ~/salaris-api && git pull && docker-compose up -d --build`. Убедись, что порт 5000 открыт в файрволе (см. ниже).

## Ошибка «Адрес недоступен» при нажатии кнопки в таблице

Запрос идёт **с серверов Google** (Apps Script), не с твоего ПК. Если в таблице появляется «Адрес недоступен: http://IP:5000/process», до сервера не доходят входящие запросы.

**На сервере по SSH:**

1. Открой порт 5000 в файрволе:
   ```bash
   sudo ufw allow 5000/tcp
   sudo ufw reload
   sudo ufw status
   ```
2. Проверь, что контейнер слушает порт: `docker-compose ps` (должен быть 0.0.0.0:5000->5000).

**С любого ПК в интернете (или с телефона без Wi‑Fi):**

```bash
curl http://155.212.147.137:5000/health
```

Если ответ `{"status":"ok",...}` — сервер доступен снаружи. Если в логах Gunicorn появляется **Invalid HTTP Version: (2, 0)** — запросы от Google идут по HTTP/2, а Gunicorn понимает только HTTP/1.1. **Решение:** проксировать Salaris через уже стоящий на сервере nginx (порты 80/443): nginx примет HTTP/2 и отправит на `127.0.0.1:5000` по HTTP/1.1. Пример конфига — в файле `nginx-salaris.conf.example`.

## Переменные окружения (сервер)

- **API_KEY** — секретный ключ для запросов из Google Sheets.
- **PROCESS_API_URL** — URL этого сервера (например `http://155.212.147.137:5000`).
- **PORT** — порт (по умолчанию 5000).
- **MOSAICA_EMAIL**, **MOSAICA_PASSWORD** — креды для входа в Mosaica (использует `process_items_no_status`).
- **HEADLESS=false** — запуск Chrome без headless (как в Bot-otchet); логин в Google реже блокируется. В Docker контейнер уже поднимает Xvfb (`run_with_xvfb.sh`: виртуальный дисплей `:99`), достаточно выставить `HEADLESS=false` в `.env` и пересобрать/перезапустить.
- **SELENIUM_DEBUG=true** — сохранять диагностические дампы Selenium (PNG + HTML) в контейнере.
- **SELENIUM_DEBUG_DIR=/tmp/salaris-debug** — каталог для дампов (по умолчанию `/tmp/salaris-debug`).

Креды BigQuery на сервере не нужны — шаг 1 (item_ids) пользователь делает на своём ПК.

## Как посмотреть, что реально происходит в Selenium на сервере

1. Включи в `.env`: `HEADLESS=false`, `SELENIUM_DEBUG=true`, затем `docker-compose up -d --build`.
2. Подключись к VNC на сервер (`<server-ip>:5900`) — `x11vnc` уже запускается в `run_with_xvfb.sh`.
3. Смотреть живые логи:
   ```bash
   docker-compose logs -f salaris-api
   ```
4. Смотреть скриншоты/HTML после падения:
   ```bash
   docker exec -it salaris-api sh -lc "ls -lah /tmp/salaris-debug | tail -n 30"
   docker exec -it salaris-api sh -lc "sed -n '1,80p' /tmp/salaris-debug/*.html"
   ```
   (проверь последний `*.png` и соответствующий `*.html` — это снимок прямо в точке сбоя).

## Лимит времени Google Apps Script (6 мин)

При большом числе айтемов (100–200) обработка на сервере может занимать десятки минут. Запрос из таблицы не должен ждать: скрипт должен сразу завершиться и показать сообщение.

**Вариант 1 — асинхронный запуск (рекомендуется)**  
- В Google Apps Script кнопка вызывает **POST /process-async** (тело как у `/process`).  
- Сервер сразу возвращает **202** и `job_id`, в теле: `job_id`, `message`, `total_items`, `estimated_minutes`.  
- Показать пользователю: «Обрабатывается N айтемов, ориентировочно ~X мин. Идентификатор задачи: \<job_id\>. Позже нажмите „Проверить результат“.»  
- Отдельная кнопка или функция «Проверить результат»: запрос **GET /job/\<job_id\>** (job_id можно хранить в ячейке или PropertiesService). Если `status === "done"` — взять `results` и `summary`, записать в лист и запустить раскраску. Если `status === "running"` или `"pending"` — показать «Ещё обрабатывается».

**Вариант 2** — по-прежнему вызывать **POST /process** и ждать ответ (подходит только для малого числа айтемов, иначе возможна ошибка по таймауту).

## Сервер сам управляет таблицей (рекомендуется для 100+ айтемов)

Если добавить **креды бота** (service account Google), сервер сам читает лист, гоняет Selenium и пишет обратно статус и раскраску. Скрипт в таблице только один раз вызывает API и сразу завершается — в лимит не упираемся.

1. Создай service account в Google Cloud (JSON ключ), расшарь таблицу на `client_email` из ключа.
2. На сервере задай в `.env`: **GOOGLE_SHEETS_CREDENTIALS** (путь к JSON) или **GOOGLE_SHEETS_CREDENTIALS_JSON** (строка JSON). Это креды бота для таблиц; для BigQuery используется GOOGLE_APPLICATION_CREDENTIALS отдельно.
3. В таблице: кнопка/триггер вызывает **POST /process-from-sheet** с телом:
   ```json
   { "spreadsheet_id": "id_таблицы_из_URL", "sheet_name": "Лист1" }
   ```
   Колонку с item_id сервер найдёт сам (заголовок содержит "item" и "id"); при необходимости можно передать `id_column` и `status_column` (буква или номер).
4. Сервер сразу возвращает 202: «Обработка запущена, лист обновится по окончании».
5. По окончании сервер пишет в таблицу: в колонку статуса — «Готово» или «Ошибка: …», раскрашивает строки (зелёный/красный), в A1 — «Всё готово · Salaris».

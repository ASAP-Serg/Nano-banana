# Nano Banana

Сервис генерации изображений: React-сайт, HTTP API и worker очереди. Провайдеры — Moonez, Replicate и OpenRouter.

## Как устроено

```
apps/web        UI (Vite + React)
apps/api        FastAPI: логин, ключи, создать задачу, список, админка
apps/worker     очередь Redis → провайдер → S3
packages/core   общее ядро: модели, провайдеры, хранилище, очередь
deploy/compose  локальный стек
deploy/k8s      манифесты для Kubernetes (Yandex)
```

Браузер ходит в web. Web/API принимают запрос и кладут job в Redis. Worker один (или несколько с lock) обрабатывает генерацию. Postgres и Object Storage снаружи процесса приложения.

## Локальный запуск

```bash
cp env.example .env
docker compose -f deploy/compose/docker-compose.yml up --build
```

- сайт: http://localhost:8080
- API: http://localhost:8000
- MinIO console: http://localhost:9001

Миграции БД: `alembic upgrade head` (compose делает это сам сервисом `migrate`).

Фронт отдельно для разработки:

```bash
cd apps/web
npm install
npm run dev
```

Vite проксирует `/api` на `localhost:8000`.

## Тесты

```bash
pip install -r requirements.txt
python -m pytest tests -q
```

CI гоняет pytest, `npm ci && npm run build` и сборку Docker-образов. На Beget код уезжает только если тесты зелёные.

## Деплой

Пока куб не готов, прод живёт на Beget. Push в `master`/`main` снова выкатывает туда по SSH (те же secrets: `SERVER_HOST`, `SERVER_USER`, `SERVER_SSH_KEY`, `DEPLOY_PATH`).

На сервере `docker compose up` поднимает web + api + worker + Redis. Хостовый nginx как раньше смотрит на `127.0.0.1:8000` — это теперь контейнер web, `/api` внутри проксируется в FastAPI. Postgres и MinIO volumes не трогаем. `.env` на сервере git не перезаписывает: `SECRET_KEY` оставь как был, `DATA_ENCRYPTION_KEY` можно не задавать (ключи пользователей расшифруются старым SECRET_KEY).

Локально:

```bash
docker compose -f deploy/compose/docker-compose.yml up --build
```

Прод в Kubernetes — когда девопс будет готов: манифесты в `deploy/k8s/`, образы в Container Registry.

## Kubernetes

Манифесты в `deploy/k8s/`. Подставьте registry, домен, Managed PostgreSQL, Redis и Object Storage в ConfigMap/Secret. Секреты не хранятся в git (`secret.example.yaml`).

Образы:

- `deploy/docker/Dockerfile.backend` — API и worker (разная команда)
- `deploy/docker/Dockerfile.web` — статика nginx

Рекомендуемый rollout: Job `migrate` → Deployment api / worker / web.

`SECRET_KEY` — JWT. `DATA_ENCRYPTION_KEY` — шифрование ключей пользователей в БД. Их нужно задавать разными; JWT можно ротировать без поломки сохранённых ключей.

## Переменные

См. `env.example`. Для прода:

- `CORS_ORIGINS` — конкретные https-домены, не `*`
- `SECURITY_DISABLE_OPENAPI=true`
- `MINIO_ENDPOINT` — S3 endpoint (Yandex Object Storage)
- `REDIS_URL` — очередь

# Lead Finder

Мультиарендный SaaS для поиска **свежего спроса**: сообщения людей, которым прямо сейчас нужна услуга клиента.
Источники (VK API, SearXNG, RSS, DuckDuckGo) → фильтры (стоп-лист, свежесть, признаки запроса) →
оценка LLM по описанию идеального клиента → входящие лиды с воронкой статусов, Telegram/webhook.

## Архитектура

```
web (React, nginx :3000) ──/api──▶ api (FastAPI :8000) ──▶ PostgreSQL
                                        ▲  SSE live-лог           ▲
                                   worker (очередь runs в Postgres, cron) ─┘
                                     ├─ sources: vk · searxng · rss · ddg
                                     └─ LLM: любой OpenAI-совместимый (MTPLX/Qwen на Mac, Groq, …)
searxng — свой метапоиск внутри compose
```

- Организация = клиент SaaS. Все данные изолированы по `organization_id`, роли: владелец / администратор / менеджер / наблюдатель, плюс суперадмин.
- Безопасность: argon2, JWT в httpOnly-cookie, CSRF double-submit, ограничение частоты входа, секреты интеграций зашифрованы (Fernet), журнал действий.
- Проект = ниша: что продаём, идеальный клиент (ICP), примеры, источники, расписание. Импорт/экспорт шаблонов в YAML (`niches/`).

## Запуск локально (Mac)

```bash
cp .env.example .env                                   # и заполните ключи:
docker compose run --rm api python manage.py gen-key    # → SECRET_KEY, FERNET_KEY
docker compose up -d --build
docker compose exec api python manage.py create-superadmin --email you@example.com
docker compose exec api python manage.py create-org --name "Demo Land Agency" --slug demo --owner you@example.com
docker compose exec api python manage.py import-niche --org demo --file /seed/niches/land_agency_demo.yaml
```

Интерфейс: http://localhost:3000 · API-документация: http://localhost:8000/api/docs (в `ENV=dev`).

### Модель
Локально (на хосте, не в Docker):

```bash
mtplx serve --model Youssofal/Qwen3.8-27B-MTPLX-Optimized-Speed --port 8080 --reasoning off --no-auth
```

Или облако: Настройки → Модель → адрес `https://api.groq.com/openai/v1`, модель, API-ключ.
Проверить качество модели на размеченных примерах:

```bash
docker compose exec worker python -m app.eval --org demo --project land_agency_demo
```

### VK-токен
Источнику «ВКонтакте» нужен **пользовательский** access token (метод `newsfeed.search`).
Добавляется в Настройки → Интеграции → VK-токен (хранится зашифрованным).

## Эксплуатация

| Задача | Команда |
|---|---|
| Логи worker | `docker compose logs -f worker` |
| Бэкап БД (с ротацией 14 дней) | `./deploy/backup.sh` |
| Восстановление | `gunzip -c backups/<file>.sql.gz \| docker compose exec -T db psql -U leadgen leadgen` |
| Миграция схемы после изменения моделей | `docker compose run --rm -v "$PWD/backend:/app" api alembic revision --autogenerate -m "..."` |
| Тесты | `cd backend && .venv/bin/python -m pytest` (SQLite) или с `TEST_DATABASE_URL` на Postgres |

## Перед продакшеном (VPS)
- `ENV=prod`, `COOKIE_SECURE=true`, HTTPS-прокси (Caddy/Traefik) перед `web`.
- LLM — облачный API или отдельный GPU-сервер (27B на обычном VPS не потянет).
- Ограничение частоты входа хранится в памяти процесса — при нескольких экземплярах API вынести в Redis.
- `FERNET_KEY` не менять: без него не расшифровать сохранённые токены.

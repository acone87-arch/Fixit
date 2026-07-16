# Service & Warehouse Management API (FastAPI)

Бэкенд по ТЗ «Учёт ремонтов, сервисной истории оборудования и управления
складом запчастей». Реализует REST API из `database_schema.sql`, плюс
механизмы, перенесённые из прототипа Codex: идемпотентный офлайн-синк,
optimistic concurrency (`version`), блокировки остатков и гостевые заявки
через публичный QR.

## Быстрый старт через Docker (рекомендуется)

У тебя уже настроен Docker Desktop — этот способ проще всего.

1. Распакуй `backend.zip` в отдельную папку (не поверх проекта Codex —
   схемы разные, лучше не мешать данные в одном volume).
2. В этой папке:

   ```bash
   docker compose up --build
   ```

   Поднимутся два контейнера: `api` (на `localhost:8000`) и `db` (Postgres,
   `localhost:5432`). Первый запуск соберёт образ — займёт минуту-другую.

3. В новом терминале создай таблицы и наполни тестовыми данными:

   ```bash
   docker compose exec api python scripts/bootstrap_db.py
   docker compose exec api python scripts/seed.py
   ```

   Второй скрипт выведет логин/пароль admin и техника — тестовое оборудование
   и склад с одной запчастью уже будут созданы.

4. Открой **http://localhost:8000/** — это веб-панель администратора на
   русском (не Swagger). Войди под admin или technician из seed. Swagger
   по-прежнему доступен на `/docs`, если понадобится подёргать API напрямую.

Остановить: `docker compose down` (данные останутся в volume `postgres_data`,
следующий `up` не потеряет БД). Полный сброс: `docker compose down -v`.

## Альтернатива без Docker

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env   # и поправить DATABASE_URL/SECRET_KEY под себя
```

Нужен Postgres (можно поднять только `db` из docker-compose.yml этого проекта:
`docker compose up db`).

Таблицы: быстрее всего через `python scripts/bootstrap_db.py` (см. описание в
разделе Docker выше — та же логика, просто без `docker compose exec`). Для
реального проекта источник правды — Alembic-миграции:

```bash
alembic init alembic
# в alembic/env.py: target_metadata = Base.metadata (импорт из app.database + app.models)
alembic revision --autogenerate -m "init"
alembic upgrade head
```

Запуск:

```bash
uvicorn app.main:app --reload --port 8000
python scripts/seed.py   # тестовые admin/техник/оборудование
```

Swagger: `http://localhost:8000/docs`.

## Веб-панель администратора

`app/static/` — небольшой vanilla-JS SPA (без сборки), который FastAPI отдаёт
напрямую на `/`. Разделы: Оборудование (паспорт + лента истории + QR),
Наряды, Заявки от гостей, Склад и запчасти (остатки/приёмка/перемещение),
Пользователи. Видимость разделов зависит от роли — у техника только «Мои
наряды» и «Мой склад» (полный офлайн-флоу техника — в мобильном приложении,
см. отдельный мокап, тут только просмотр для теста API).

## Карта эндпоинтов

| Группа | Метод/путь | Доступ |
|---|---|---|
| Auth | `POST /api/auth/login` | публично |
| Пользователи | `GET /api/users/me` | любой авторизованный |
| | `GET/POST /api/users` | admin (создание — только admin) |
| Оборудование | `GET/POST /api/equipment` | список — любой; создание — admin/dispatcher |
| | `PATCH /api/equipment/{id}` | admin/dispatcher |
| | `GET /api/equipment/{id}/passport` | любой (лента истории для карточки) |
| | `GET /api/equipment/{id}/qr` | любой (SVG для печати/показа) |
| Наряды | `GET/POST /api/tasks` | список — свои для техника, все для admin/dispatcher; создание — admin/dispatcher |
| | `PATCH /api/tasks/{id}/assign` | admin/dispatcher |
| Гостевые заявки | `GET /api/public/equipment/{qr_token}` | публично, без авторизации |
| | `POST /api/public/equipment/{qr_token}/tickets` | публично, идемпотентно |
| | `GET /api/tickets`, `PATCH /api/tickets/{id}/assign` | admin/dispatcher |
| Склад | `GET /api/warehouses`, `GET /api/warehouses/{id}/stock` | техник — только свой мобильный склад |
| | `POST /api/warehouses/movements/receive` | admin/dispatcher |
| | `POST /api/warehouses/movements/transfer` | admin/dispatcher |
| | `GET/POST /api/parts` | список — любой; создание — admin/dispatcher |
| Офлайн-синк | `POST /api/v1/sync/repairs` | technician (JWT) |

## Ключевые механизмы (перенесены из прототипа Codex, адаптированы)

- **Идемпотентность синка** — `services/sync_service.py` проверяет
  `sync_operations` по `local_uuid` до любых записей; повторная отправка
  пакета возвращает тот же результат, не создавая дублей.
- **Optimistic concurrency** — `equipment.version` + `base_equipment_version`
  в payload ремонта. Расхождение не роняет запрос, а помечает ремонт
  `sync_status = conflict` для ручной проверки диспетчером.
- **Блокировки остатков** — `services/stock_service.py` берёт
  `SELECT ... FOR UPDATE` на строку `warehouse_stock` перед списанием/
  перемещением; при переводе между двумя складами строки блокируются в
  стабильном порядке (по id), чтобы избежать deadlock при встречных операциях.
- **Гостевые заявки** — публичный QR ведёт на `public_qr_token` (не на
  внутренний `id`), создание заявки идемпотентно по ключу с гостевой
  страницы. Это расширение сверх исходных ролей ТЗ (админ/техник) — обсудить
  с заказчиком, нужно ли это в проде, или оставить только техников.

## Что осознанно не сделано (для MVP-скелета)

- **Обработка фотографий к акту ремонта** — модель `repair_attachments` есть
  в схеме, но нет эндпоинта загрузки файлов (нужно решить, куда класть файлы:
  S3-совместимое хранилище/локальный диск).
- **Alembic-миграции не сгенерированы** — только зависимость в
  `requirements.txt`, см. «Быстрый старт» выше.
- **Rate limiting / brute-force защита на `/api/auth/login`** — не реализована.
- **CORS открыт на `*`** в `main.py` — сузить под реальные origin перед продом.

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

## SaaS foundation

Новые бизнес-данные принадлежат `Organization`, а доступ пользователя к
организации и его роль хранятся в `OrganizationMembership`. Активная
организация записывается в JWT (`org`) и определяется сервером; API не доверяет
`organization_id`, присланному клиентом. Один пользователь может состоять в
нескольких организациях, выбрав нужную через `organization_slug` при входе.

Для обновления существующей production-базы используется Alembic:

```bash
alembic upgrade head
```

Первая миграция создаёт организацию `Fixit Default`, добавляет в неё текущих
пользователей и переносит существующее оборудование, заявки, ремонты и склад,
не удаляя данные.

Клиенты и объекты обслуживания образуют следующий уровень tenant-модели:
`Organization → Client → Site → Equipment`. Миграция `20260826_0002`
преобразует существующие текстовые расположения оборудования в объекты и
привязывает их к импортированному клиенту соответствующей организации.

## Автодеплой на VPS

Workflow `.github/workflows/deploy.yml` запускается после каждого push в
`main` (или вручную через **Actions → Deploy to VPS → Run workflow**). Он
подключается к серверу по SSH, обновляет `/opt/fixit`, собирает новый образ,
применяет `alembic upgrade head`, затем обновляет контейнеры и ждёт успешного
ответа `/health`. Если миграция не прошла, работающий API не перезапускается.

В GitHub Environment `production` должны быть настроены Secrets:

- `VPS_HOST` — IP или DNS-имя сервера;
- `VPS_USER` — SSH-пользователь с доступом к `/opt/fixit` и Docker;
- `VPS_SSH_KEY` — приватный SSH-ключ без passphrase;
- `VPS_KNOWN_HOSTS` — строка сервера из `ssh-keyscan`.

Файл `/opt/fixit/.env` хранится только на сервере и при деплое не
перезаписывается. Данные PostgreSQL остаются в Docker volume
`postgres_data`. При ошибке health-check workflow завершается с ошибкой и
выводит последние 100 строк лога API.

## Веб-панель администратора

`app/static/` — небольшой vanilla-JS SPA (без сборки), который FastAPI отдаёт
напрямую на `/`. Разделы: Оборудование (паспорт + лента истории + QR),
Наряды, Заявки от гостей, Склад и запчасти (остатки/приёмка/перемещение),
Пользователи. Видимость разделов зависит от роли — у техника только «Мои
наряды» и «Мой склад» (это read-only просмотр для проверки API; полный
рабочий процесс техника — в PWA ниже).

## PWA техника (офлайн-first)

`app/static-tech/` — отдельное приложение на `/tech/`, реализует п. 3.2 ТЗ.
Устанавливается на телефон как приложение (manifest.json + service worker).

- **Офлайн-хранилище** — `db.js`, обёртка над IndexedDB: кэш назначенных
  заявок, паспортов оборудования (включая ленту истории) и остатков на
  складе техника. При открытии заявки без сети данные берутся из кэша.
- **Закрытие ремонта офлайн** — акт сохраняется в IndexedDB
  (`pendingRepairs`) с локально сгенерированным `local_uuid` и версией
  оборудования на момент открытия карточки. Индикатор связи вверху экрана
  показывает, сколько актов ждут отправки.
- **Синхронизация** — при восстановлении сети (`online`-событие) сразу
  пробует отправить очередь на `/api/v1/sync/repairs`. Если приложение в
  этот момент закрыто — за это отвечает **Background Sync API**
  (`sw.js`, событие `sync`), поддержан в Chrome/Edge (desktop и Android).
  В Safari/iOS Background Sync недоступен — синк тогда произойдёт при
  следующем открытии приложения с сетью.
- **Скан QR** — через `BarcodeDetector` (нативный API браузера, без внешних
  библиотек — сети для их загрузки может не быть). Поддержан в Chrome/Edge;
  там, где недоступен (Safari), всегда есть ручной ввод серийного номера.

## Гостевая заявка по QR

`app/static-guest/` — страница на `/guest/`, куда ведёт редирект `/e/{token}`
(именно этот URL закодирован в самой QR-наклейке на оборудовании). Гость
сканирует обычной камерой телефона, без входа в систему, отмечает
серьёзность/симптомы и отправляет — заявка попадает в раздел «Заявки от
гостей» админ-панели.

## Карта эндпоинтов

| Группа | Метод/путь | Доступ |
|---|---|---|
| Auth | `POST /api/auth/login` | публично |
| Пользователи | `GET /api/users/me` | любой авторизованный |
| | `GET/POST /api/users` | admin (создание — только admin) |
| Клиенты | `GET/POST /api/clients` | список — любой; создание — admin/dispatcher |
| Объекты | `GET/POST /api/sites` | список — любой; создание — admin/dispatcher |
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
| QR | `GET /api/equipment/by-qr/{qr_token}` | авторизован (техник — паспорт по сканy) |
| | `GET /e/{qr_token}` | публично, редирект на гостевую страницу |

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

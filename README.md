# Fixit 2.0 / Fixit Pulse

Fixit — SaaS/PWA для сервисных компаний: клиенты и объекты, оборудование с QR,
заявки, назначение техников, ремонт, работы и запчасти, фотографии, сервисные
акты, история оборудования, клиентский кабинет и офлайн-работа техника.

Backend: FastAPI + PostgreSQL + SQLAlchemy + Alembic. Интерфейсы находятся в
`app/static/` и `app/static-guest/`; отдельной frontend-сборки нет.

## Для Codex и AI-агентов

Не использовать README как журнал текущего этапа разработки.

Перед работой читать в таком порядке:

1. `AGENTS.md` — постоянные правила, инварианты и порядок работы.
2. `AI_CONTEXT.md` — краткое текущее состояние, baseline и следующая задача.
3. Только затем — код и тесты, относящиеся к текущей задаче.

Полный аудит репозитория перед каждой правкой не нужен. README описывает
стабильную архитектуру и эксплуатацию, а не историю всех предыдущих этапов.

## Архитектура

Tenant-модель:

```text
Organization
  -> Client
      -> Site
          -> Equipment
              -> ServiceRequest
                  -> Repair
```

Ключевые правила:

- `ServiceRequest` — основная рабочая сущность жизненного цикла заявки.
- `Repair` канонически связан с `ServiceRequest`; для одной заявки не должно
  появляться несколько независимых ремонтов.
- `Task` оставлен только для чтения исторических данных и не должен становиться
  источником нового workflow.
- `Ticket` хранит происхождение публичного QR-обращения и его idempotency, но
  не управляет назначением и состояниями работы.
- Сервер определяет организацию и доступ; клиентскому `organization_id` нельзя
  доверять как источнику авторизации.
- Изоляция Organization / Client / Site обязательна для всех новых изменений.

Основные backend-модули находятся в `app/routers/`, `app/services/`,
`app/models/` и `app/schemas/`.

## Fixit Pulse

`app/static/` — основной интерфейс Fixit, включая рабочее место техника.
Fixit Pulse — устанавливаемая PWA, а не отдельное APK.

Старый `/tech` больше не является отдельным продуктовым интерфейсом:
`/tech` и `/tech/*` перенаправляются в текущий Pulse. Каталог
`app/static-tech/` пока остаётся в репозитории только как rollback-артефакт и
не монтируется в production.

Единый service worker доступен по `/sw.js` со scope `/`.

## Офлайн-работа техника

Pulse использует IndexedDB для локального кэша и очередей незавершённой
синхронизации. Критические свойства:

- офлайн-операции ремонта имеют локальный idempotency key;
- повторная отправка не должна создавать дубль ремонта;
- версия оборудования участвует в optimistic concurrency;
- вложения имеют отдельную durable-очередь и могут повторно отправляться после
  восстановления сети;
- Background Sync используется там, где браузер его поддерживает; на iOS
  отправка может происходить при следующем открытии приложения с сетью.

Ключевой endpoint синхронизации ремонта: `POST /api/v1/sync/repairs`.

## QR и публичные обращения

Физический QR оборудования использует публичный token, а не внутренний ID.

```text
/e/{qr_token}
  -> /guest/?token=...
  -> публичная карточка / обращение
  -> ServiceRequest workflow
```

Гостевой интерфейс находится в `app/static-guest/`. Публичные загрузки фото и
повторные попытки должны сохранять tenant-isolation и idempotency.

## Клиентский доступ

В проекте есть Client Portal и pilot onboarding для пользователей клиента.
Доступ выдаётся к существующему `Client`/`Site`, а не путём создания новой
Organization для каждого приглашённого пользователя.

Site Manager ограничивается назначенным объектом. Director работает в рамках
разрешённого клиента. Любое изменение onboarding/access должно проверять
невозможность доступа к чужому Client или Site.

## Оборудование и история сервиса

Оборудование принадлежит конкретному Site и имеет публичный QR token. Паспорт
оборудования включает фото и сервисную историю.

История строится вокруг `ServiceRequest`: проблема, выполненные работы,
использованные детали, фотографии, статус, номер заявки, даты и техник должны
оставаться согласованными с каноническим Repair.

## Медиа

Загрузка фотографий оборудования, заявки и ремонта реализована. При изменениях
медиа необходимо сохранять:

- проверку доступа на сервере;
- принадлежность Client/Site/Equipment;
- безопасное чтение вложений завершённых ремонтов;
- корректную повторную отправку офлайн-вложений;
- совместимость существующих записей и URL.

Не добавлять в документацию старое утверждение, что endpoints ремонта для
фотографий отсутствуют: это уже не соответствует текущему коду.

## База данных и миграции

Alembic — единственный источник правды для схемы production и обычной
разработки.

Применить текущую цепочку:

```bash
alembic upgrade head
```

Миграции уже находятся в `alembic/versions/`; повторно выполнять
`alembic init` нельзя.

`scripts/bootstrap_db.py` создаёт таблицы напрямую из моделей и предназначен
только для быстрого локального dev-бутстрапа. Его не использовать как замену
Alembic для production или проверки миграционной совместимости.

## Быстрый локальный запуск через Docker

```bash
docker compose up --build
```

Compose поднимает API на `http://localhost:8000` и PostgreSQL на локальном
порту `5432`. После запуска примените миграции:

```bash
docker compose exec api alembic upgrade head
```

При необходимости наполнить локальную базу тестовыми данными:

```bash
docker compose exec api python scripts/seed.py
```

Остановить контейнеры без удаления данных:

```bash
docker compose down
```

Полный локальный сброс volume:

```bash
docker compose down -v
```

## Запуск без Docker

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
cp .env.example .env
alembic upgrade head
uvicorn app.main:app --reload --port 8000
```

Нужен доступный PostgreSQL и корректные значения в `.env`.

Основные настройки:

```text
DATABASE_URL
SECRET_KEY
PUBLIC_APP_URL
ALLOWED_ORIGINS
ALLOWED_HOSTS
VAPID_PUBLIC_KEY
VAPID_PRIVATE_KEY
VAPID_SUBJECT
```

CORS и Host allowlist задаются через `ALLOWED_ORIGINS` и `ALLOWED_HOSTS`;
приложение не использует безусловный production CORS `*`.

## Web Push

Web Push использует VAPID-ключи. Private key хранится только в окружении
сервера и не должен попадать в git или frontend.

Пользователь включает уведомления явным действием. Push применяется, в
частности, для событий назначения заявки и рабочего lifecycle. Web Push для
установленной PWA требует HTTPS в production.

## Тесты

Python regression suite:

```bash
pytest -q
```

CI дополнительно выполняет runtime-проверки offline/PWA:

```bash
node tests/pulse_offline_engine_runtime_test.js
node tests/technician_workflow_runtime_test.js
node tests/offline_attachment_sync_runtime_test.js
```

Для локальной правки сначала запускайте тесты затронутой подсистемы, а полный
suite — когда изменение пересекает границы нескольких подсистем или перед
production-приёмкой.

В `tests/` уже есть отдельные regression/security тесты для canonical Repair,
Client Portal/access, equipment history, media, pilot onboarding, guest photos,
public URL и offline workflow. Не нужно заново исследовать весь suite перед
каждой небольшой задачей.

## Production deploy

`.github/workflows/deploy.yml` запускается при push в `main` и вручную через
`workflow_dispatch`.

Перед deploy workflow:

1. устанавливает Python-зависимости;
2. запускает `pytest -q`;
3. запускает основные offline runtime tests;
4. только после успешных тестов обновляет VPS;
5. собирает production image;
6. выполняет `alembic upgrade head`;
7. пересоздаёт API;
8. проверяет `/health`;
9. валидирует nginx/HTTPS-конфигурацию.

Production checkout расположен в `/opt/fixit`. Production `.env` хранится на
сервере и не должен заменяться файлом из репозитория.

Основной публичный URL новых ссылок — `https://fixitpulse.ru`.

## Критические инварианты

При разработке нельзя незаметно ломать следующие свойства:

- Organization / Client / Site isolation;
- один канонический Repair на ServiceRequest;
- согласованный workflow ServiceRequest и Repair;
- безопасный публичный QR без раскрытия внутренних ID;
- idempotent offline sync и отсутствие дублей;
- сохранность существующих media/history;
- транзакционная корректность складских остатков;
- обратную совместимость production-данных и миграций.

Актуальные рабочие ограничения и следующий этап держать в `AI_CONTEXT.md`, а
постоянные правила для Codex/Astra — в `AGENTS.md`.

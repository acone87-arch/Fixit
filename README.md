# Fixit 2.0 / Fixit Pulse

Система обслуживания оборудования на объектах заказчиков: заявки, работа
техников, история ремонтов, сервисные акты, склад запчастей и QR-инвентаризация.
Fixit Pulse — единое веб-приложение для сотрудников и клиентского кабинета,
с установкой как PWA и общей офлайн-очередью ремонтов и фотографий.

Описание сверено с кодом и Git-историей до `7d3bf18` (08.10.2026).
Это состояние исходного кода, а не подтверждение текущего SHA production.

## Возможности и модель данных

- Иерархия обслуживания: `Organization → Client → Site → Equipment`.
  Доступ к организации задаётся через `OrganizationMembership`, активная
  организация определяется сервером из авторизации, а не из произвольного ID
  в клиентском запросе.
- Роли: `owner`, `admin`, `dispatcher`, `technician`, `client_admin`,
  `client_site_user`. Доступ дополнительно ограничивается организацией,
  клиентом, объектом и назначением техника; роль не даёт доступа ко всем данным.
- `ServiceRequest` — единственная активная рабочая сущность для диспетчера,
  техника, клиента и гостевого QR-обращения. Есть назначение, статусы,
  согласования, приоритетная очередь и фильтры по клиенту/объекту.
- Результат ремонта: диагностика и работы, использованные детали, фотографии,
  история оборудования и PDF сервисного акта, связанные с заявкой.
- Клиентский кабинет: оборудование и паспорта, обращения, согласования,
  документы, пользователи и одноразовые приглашения, список и отзыв приглашений.
  Для сотрудников доступно редактирование объектов в рамках серверных прав.
- Склад: центральные и мобильные склады техников, остатки, приход,
  перемещения и списание деталей при ремонте. Сервер использует блокировки,
  ограничения остатков и идемпотентные операции.
- QR-инвентаризация: создание партии пустых карточек оборудования на объекте,
  печать PDF, заполнение карточек после сканирования и пакетная перепечатка
  наклеек существующего оборудования без смены QR-идентификаторов.
- Единый шаблон QR-этикетки для одиночной и массовой печати. Публичная ссылка
  имеет вид `{PUBLIC_APP_URL}/e/{public_qr_token}` и ведёт к гостевой заявке.
- Профиль и настройки: тема, размер текста, смена и восстановление пароля,
  установка PWA, управление Web Push.

`Task` и административный `Ticket` API сохранены только для чтения истории.
`Ticket` хранит происхождение QR-обращения, но не управляет жизненным циклом
работы. Исторические связи и данные не удалены. `/tech` перенаправляет в Pulse;
`app/static-tech/` остаётся для совместимости и rollback, а не как отдельное
действующее приложение. Подробнее: [Task retirement](TASK_DEPRECATION_TODO.md).

## Стек и структура

Python 3.12, FastAPI, SQLAlchemy async, PostgreSQL 16 и Alembic.
Интерфейс — HTML/CSS/vanilla JavaScript без отдельной сборки приложения.
PDF формируется через ReportLab; Web Push — через pywebpush.
Node.js нужен для JS/browser-проверок, в CI используется Node.js 22.

| Путь | Назначение |
|---|---|
| `app/routers/` | HTTP API, авторизация и границы доступа |
| `app/services/` | Workflow, синхронизация, склад, PDF, Push и почта |
| `app/models/`, `app/schemas/` | ORM-модели и API-схемы |
| `app/static/` | Pulse SPA, PWA и общий офлайн-движок |
| `app/static-guest/` | Гостевое обращение по QR |
| `alembic/versions/` | Версионированная схема БД |
| `scripts/` | Демо-данные, проверки, выпуск и backup/restore |
| `tests/` | Python, PostgreSQL, JS runtime и browser-проверки |

## Локальный запуск через Docker

Из корня клонированного репозитория, при работающем Docker Compose:

```bash
mkdir -p uploads
docker compose up --build -d
docker compose exec api alembic upgrade head
docker compose exec api python -m scripts.seed
```

Локальный Compose задаёт собственные параметры разработки: PostgreSQL
`fsm:fsm` в базе `fsm`, API на порту 8000, БД на порту 5432. Файл `.env`
для этого сценария не требуется. Каталог `uploads` нужен в том числе для
проверки readiness и хранения загружаемых файлов.

Открыть [Pulse](http://localhost:8000/), [Swagger](http://localhost:8000/docs)
или [readiness](http://localhost:8000/health). `/health` проверяет доступность
БД и возможность записи в `uploads`; при ошибке возвращает 503.

Демо-скрипт создаёт организацию `fixit-default`, клиента, объект, оборудование,
склады и запчасть. Локальные учётные записи по умолчанию:

| Email | Пароль | Роль в демо-организации |
|---|---|---|
| `admin@example.com` | `admin12345` | `owner` |
| `tech@example.com` | `tech12345` | `technician` |

Пароли новых демо-пользователей можно задать переменными
`INITIAL_ADMIN_PASSWORD` и `INITIAL_TECH_PASSWORD` при запуске seed.
Повторный seed не меняет пароль уже существующего пользователя.
Демо-данные и эти пароли предназначены для локальной разработки.

Остановка: `docker compose down`. Данные PostgreSQL остаются в volume
`postgres_data`, локальные файлы — в `uploads/`.
`docker compose down -v` удаляет volume с локальной БД.

## Запуск Python без контейнера API

Нужны Python 3.12, PostgreSQL 16 и системный шрифт DejaVu Sans для PDF.
В Docker-образе шрифт устанавливается автоматически.

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Настройте `.env` под локальную БД. Если используете БД из `docker compose up -d db`:

```env
DATABASE_URL=postgresql+asyncpg://fsm:fsm@127.0.0.1:5432/fsm
SECRET_KEY=replace-with-a-random-local-secret
PUBLIC_APP_URL=http://localhost:8000
ALLOWED_ORIGINS=http://localhost:8000,http://127.0.0.1:8000
ALLOWED_HOSTS=localhost,127.0.0.1
```

Затем:

```bash
mkdir -p uploads
alembic upgrade head
python -m scripts.seed
uvicorn app.main:app --reload --port 8000
```

В Windows активация окружения: `.venv\Scripts\activate`.

## Миграции БД

Существующая Alembic-цепочка — источник установки и обновления схемы.
Не запускайте `alembic init` и не генерируйте новую initial migration для
клонированного проекта. `scripts/bootstrap_db.py` — старый dev-helper с
`Base.metadata.create_all()`: он не записывает историю Alembic и не заменяет
миграции в описанном выше запуске.

```bash
alembic heads
alembic current
alembic upgrade head
```

Текущая линейная цепочка: `20260825_0000 → … → 20261002_0018`.
`0000` восстанавливает историческую pre-SaaS схему; далее идут tenant-модель,
клиенты/объекты, заявки, вложения, доступы, Push, приглашения, QR-инвентаризация
и склад. Последние изменения:

- `20260928_0017`: `equipment.location_details`.
- `20261002_0018`: версия авторизации пользователя и токены восстановления пароля.

На БД с revision `0016` обновление до текущего `head` применяет `0017` и `0018`;
оно уже не является no-op. Исторические утверждения о no-op относятся к выпуску
P0.7, когда head был `0016`. Stamp допустим только для проверенной точной
legacy-схемы по процедуре runbook, а не для пустой БД. Перед production upgrade
нужны проверенные backup/restore и совместимость нового кода со схемой.

## Офлайн-работа и PWA

Pulse использует общий движок `app/static/offline/engine.js`, IndexedDB
`fixit-tech-db` и очереди `pendingRepairs` / `pendingAttachments`.
Черновик заявки, включая выбранные фото, также сохраняется локально.
При завершении ремонта результат и фотографии ставятся в durable queue;
повторы синхронизации используют `local_uuid` и серверную идемпотентность.
Контроль версии оборудования позволяет отметить конфликт вместо незаметной
перезаписи. Очередь учитывает владельца и организацию, включая смену аккаунта.

Корневой Service Worker `/sw.js` имеет scope `/` и импортирует общий движок.
При наличии поддержки браузера применяется Background Sync
`fixit-sync-repairs`; иначе отправка продолжается при открытии приложения с
сетью. Существование очереди не означает, что каждый экран и любой первый
запуск доступны без сети. Физическая проверка Android/iOS остаётся отдельной
частью приёмки.

Установка доступна в «Профиль и настройки»: Chrome/Edge показывают кнопку после
`beforeinstallprompt`. На iPhone/iPad используется «Поделиться → На экран Домой».
Production PWA и Web Push требуют HTTPS.

## Настройки сервера, Web Push и почта

Полный пример переменных — [.env.example](.env.example). CORS и Host проверяются
по `ALLOWED_ORIGINS` и `ALLOWED_HOSTS` (списки через запятую).
`PUBLIC_APP_URL` должен указывать на внешний адрес сервиса: он используется
в QR и ссылках восстановления.

Для Web Push задайте одну согласованную пару ключей только на сервере:

```env
VAPID_PUBLIC_KEY=...
VAPID_PRIVATE_KEY=...
VAPID_SUBJECT=mailto:admin@example.com
```

Подключение уведомлений запускается пользователем из профиля. При logout
приложение снимает текущую browser subscription. Реализованы уведомления о
назначении, внутреннем и клиентском ожидании согласования, завершении ремонта.
Нажатие открывает безопасный внутренний адрес заявки. Реальную доставку на
устройство следует проверять отдельно от тестов с замоканным transport.

Для восстановления пароля:

```env
PASSWORD_RESET_EXPIRE_MINUTES=30
PASSWORD_RESET_DEBUG=false
SMTP_HOST=smtp.example.com
SMTP_PORT=587
SMTP_USERNAME=...
SMTP_PASSWORD=...
SMTP_FROM=no-reply@example.com
SMTP_STARTTLS=true
```

Имена параметров — именно `SMTP_FROM` и `SMTP_STARTTLS`, как в `app/config.py`.
В БД хранится SHA-256 одноразового токена. Смена и восстановление пароля
инвалидируют ранее выданные JWT через версию авторизации. Публичный ответ
запроса восстановления одинаков для известных и неизвестных email.
`PASSWORD_RESET_DEBUG=true` разрешает preview-ссылку для существующего
пользователя только в локальном сценарии без SMTP; в production оставьте false.

## Основные API

Точные схемы и методы доступны в `/docs`. Все защищённые маршруты дополнительно
проверяют tenant/client/site scope и права; таблица не заменяет ACL.

| Группа | Маршруты |
|---|---|
| Авторизация | `/api/auth/login`, `/api/auth/password/*` |
| Пользователи и организации | `/api/users`, `/api/organizations` |
| Клиенты и объекты | `/api/clients`, `/api/sites` |
| Оборудование | `/api/equipment`, `/api/equipment-types` |
| Паспорт и QR | `GET /api/equipment/{id}/passport`, `GET /api/equipment/{id}/qr` (PDF) |
| Инвентаризация | `/api/equipment-inventory/batches`, `/api/equipment-inventory/reprint/pdf`, `/api/equipment-inventory/{id}/complete` |
| Заявки | `/api/service-requests`, включая assignment, статусы, approval и вложения |
| Ремонты | `/api/repairs/{id}/attachments`, `/api/repairs/{id}/act.pdf` |
| Клиентский кабинет | `/api/client-portal/*` |
| Гостевой QR | `/e/{token}`, `/api/public/equipment/{token}`, `/api/public/equipment/{token}/tickets` |
| Склад | `/api/warehouses`, `/api/parts` |
| Офлайн-синк | `POST /api/v1/sync/repairs` |
| Push | `/api/push/*` |
| Исторические данные | `GET /api/tasks`, `GET /api/tickets` |

## Проверки

Для целевых локальных PostgreSQL/browser-тестов поднимите Compose БД и создайте
отдельную тестовую базу (один раз):

```bash
docker compose up -d db
docker compose exec db psql -U fsm -d fsm -c "CREATE ROLE pilot LOGIN PASSWORD 'pilot-ci-only';"
docker compose exec db psql -U fsm -d fsm -c "CREATE DATABASE fixit_test OWNER pilot;"
```

В Python-окружении:

```bash
pip install -r requirements-dev.txt
python -m playwright install chromium
python scripts/test_location_workflow.py
```

Этот helper сам задаёт изолированный DSN `fixit_test`, test host и browser-флаг.
Он запускает целевую подборку, а не весь release gate.

Полный gate задан в [.github/workflows/deploy.yml](.github/workflows/deploy.yml):
Python/PostgreSQL/Chromium, пять JS runtime suites, настоящий IndexedDB/Service
Worker, browser-тесты очереди и контраста, изолированный restore PostgreSQL и
media. JS-зависимости устанавливаются через `npm ci --prefix tests --ignore-scripts`.
Проверки должны использовать отдельную БД; количество passed/skipped зависит
от версии кода и включённых проверок, старые числа приёмки не являются текущим
результатом.

## Production и выпуск

`docker-compose.prod.yml` использует `.env`, отдельные volumes PostgreSQL и
media и публикует API только на `127.0.0.1:8000`. В `.env` production нужны
случайные `SECRET_KEY`, `POSTGRES_PASSWORD`, внешний `PUBLIC_APP_URL` и allowlists.
Compose формирует `DATABASE_URL` контейнера из `POSTGRES_PASSWORD`.

Workflow `Deploy to VPS` выполняет проверки для PR в `main`, push в `main`
или `codex/pilot-release-p0-5`, а также при ручном запуске. Но **job deploy
разрешён только для события `push` в `main`**, после успешного test job.
Push в старую release-ветку или ручной запуск сами по себе сейчас не деплоят.

В GitHub Environment `production` используются `VPS_HOST`, `VPS_USER`,
`VPS_SSH_KEY`, `VPS_KNOWN_HOSTS`. Серверный `.env` не перезаписывается выпуском.
Скрипт выпуска проверяет согласованный backup/restore DB+media, применяет
миграции, обновляет приложение и проверяет readiness, nginx, TLS и multipart.
При ошибке возвращается прежний код/image без удаления volumes и без Alembic
downgrade. Изменения схемы должны оставаться совместимыми с rollback приложения.

Процедуры восстановления: [PRODUCTION_RUNBOOK.md](docs/PRODUCTION_RUNBOOK.md).
Его исторические указания о head `0016` и выпуске через pilot release-ветку
нужно читать с учётом актуальных миграций и workflow, описанных выше.

## Основные изменения по Git-истории

| Дата / commit | Изменение |
|---|---|
| `672b812`, `45b13c5` | Вывод Task из активного workflow и общая durable offline queue |
| 15.09.2026, `4184d68`–`b72d287` | Восстановление legacy baseline, clean bootstrap, production acceptance и backup/restore |
| 16–24.09.2026, `f525bd7`–`494b107` | Frontend/backend parity и стабилизация проверок |
| 29.09.2026, `7c18bb7` | Расположение оборудования в workflow заявки |
| 02.10.2026, `9ed44d2` | Профиль, пароль, PWA/Push и единый QR-шаблон |
| 02–06.10.2026, `9606d7f`, `4d92d75`, `2853f21` | Светлая тема, контраст и мобильный интерфейс при крупном тексте |
| 06.10.2026, `b14ba15` | Приоритетная очередь заявок и фильтры по клиенту/объекту |
| 08.10.2026, `7d3bf18` | Пакетная перепечатка QR оборудования на объекте |

История P0 и старый parity backlog сохранены в
[PILOT_HARDENING_ROADMAP.md](docs/PILOT_HARDENING_ROADMAP.md).
Это журнал решений: его записи о недостающем UI после P0.7 не описывают
все последующие исправления. Аналогично `OFFLINE_TODO.md` и
`docs/client-portal-notification-todo.md` содержат исторические планы,
часть которых уже реализована. Профиль/PWA/Push/QR дополнительно описаны в
[документе приёмки](docs/PROFILE_PWA_PUSH_QR_ACCEPTANCE.md); для переменных SMTP
используйте актуальные имена из этого README и `.env.example`.

Ограничения: переназначение уже назначенной заявки требует отдельного правила
серверного workflow; сервисный акт генерируется из текущих данных и не является
криптографически подписанным неизменяемым snapshot. Исходную invite-ссылку
нельзя восстановить после создания, поскольку хранится только hash токена.

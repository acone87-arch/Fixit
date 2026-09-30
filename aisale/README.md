# AI-замерщик балконов

Вертикальный MVP для одной компании остекления: мобильный web-диалог использует общий backend, EstimateState, детерминированный demo PriceEngine и общее расписание. Подключение MAX отложено.

## Запуск локального демо

1. Скопируйте `.env.example` в `.env`; задайте собственный `ADMIN_PASSWORD`.
2. Запустите `docker compose up --build`.
3. Откройте [http://localhost:3000](http://localhost:3000). Админка — [http://localhost:3000/admin](http://localhost:3000/admin), demo-вход `admin` / `demo-change-me` (или значения из `.env`).
4. Demo-прайс и слоты на неделю создаются при первом старте. Через admin можно редактировать цены и добавлять интервалы.

Без Docker backend запускается из каталога `backend`: `pip install -r requirements.txt`, `alembic -c alembic.ini upgrade head`, `uvicorn main:app --reload`. При отсутствии `DATABASE_URL` используется SQLite для быстрой разработки; Compose подключает PostgreSQL.

## Интеграции

- **AI / Vision:** рекомендуемая стартовая конфигурация — Yandex AI Studio, модель `qwen3.6-35b-a3b`: она принимает текст и изображения через OpenAI-compatible Chat Completions API. Создайте платёжный аккаунт и сервисный аккаунт/API-ключ с ролью `ai.languageModels.user`; укажите ключ в `AI_API_KEY`, ID каталога в `AI_PROJECT_ID` и `AI_MODEL=gpt://<folder-id>/qwen3.6-35b-a3b`. Для Yandex используются `AI_BASE_URL=https://ai.api.cloud.yandex.net/v1` и `AI_AUTH_SCHEME=Api-Key`. Тариф на момент подготовки README: 0,20 ₽ за 1000 входящих и 0,30 ₽ за 1000 исходящих токенов, с НДС. Без ключа работает demo parser; цены всегда считает backend. Другой OpenAI-compatible endpoint можно настроить через те же переменные; для провайдеров с Bearer-токеном задайте `AI_AUTH_SCHEME=Bearer` и при необходимости оставьте `AI_PROJECT_ID` пустым.
- **Object Storage:** локальный filesystem по умолчанию; для S3-compatible endpoint задайте `STORAGE_ENDPOINT`, `STORAGE_BUCKET`, `STORAGE_ACCESS_KEY`, `STORAGE_SECRET_KEY` и регион.
- **Telegram:** в Telegram откройте `@BotFather`, выполните `/newbot`, выберите имя и username, оканчивающийся на `bot`. Сохраните выданный токен локально в `TELEGRAM_BOT_TOKEN` (не присылайте его в чат и не коммитьте). Напишите созданному боту `/start`, затем получите ID личного чата через официальный `getUpdates` и задайте `TELEGRAM_CHAT_ID`. При тестировании используйте `getMe`, чтобы проверить токен. Сервис уведомлений отправляет заявку владельцу; он не делает Telegram клиентским каналом. Сбой уведомления не отменяет Lead.
- **MAX:** интеграцию и подключение токена отложили; переменные `MAX_BOT_TOKEN` и `MAX_WEBHOOK_SECRET` оставлены как extension point.

Для production выберите инфраструктуру хранения и AI endpoint с учётом требований компании к персональным данным, настройте TLS, резервное копирование и ротацию секретов. Демонстрационные цены собраны как ориентир по опубликованным расценкам Уфимского оконного завода; это не прайс пилотного партнёра и не предложение этой компании. Источники и ограничения — в [DEMO_PRICE_BENCHMARK.md](DEMO_PRICE_BENCHMARK.md). Перед запуском на трафике замените их согласованным прайсом компании. `DATA_RETENTION_DAYS` задаёт срок хранения сессий/заявок/фото (по умолчанию 180 дней; `0` отключает автоочистку); очистка выполняется при старте backend. `BUSINESS_TIMEZONE` задаёт часовой пояс расписания. Текст согласия в `/privacy` является шаблоном; до пилота компания должна проверить его и опубликовать актуальную политику. Админка содержит удаление заявки, контакта, сообщений и фото.

## Проверки

Из каталога `backend`: `pytest`. Тесты покрывают нормализацию MAX-событий, телефон, фото, переходы сценария, demo-расчёт и атомарное резервирование. Для проверки реальной конкурентной записи запускайте integration tests с PostgreSQL; SQLite не моделирует блокировки PostgreSQL.

## Пилотный деплой aisale

Production-конфигурация изолирована от FixitPulse: собственные контейнеры и тома PostgreSQL/фото, frontend доступен на сервере только через `127.0.0.1:3100`, а Nginx обслуживает `https://aisale.fixitpulse.ru`. Workflow `.github/workflows/deploy-aisale.yml` разворачивает только каталог `aisale/` и получает TLS-сертификат через существующий Certbot.

Для запуска workflow в GitHub Actions Secrets должны быть заданы `VPS_HOST`, `VPS_USER`, `VPS_SSH_KEY`, `VPS_KNOWN_HOSTS` (секреты текущего Fixit-деплоя) и `AISALE_POSTGRES_PASSWORD`, `AISALE_ADMIN_USERNAME`, `AISALE_ADMIN_PASSWORD`, `AISALE_AI_API_KEY`, `AISALE_AI_PROJECT_ID`, `AISALE_TELEGRAM_BOT_TOKEN`, `AISALE_TELEGRAM_CHAT_ID`. Пароль админки должен быть уникальным; известный demo-пароль workflow отклонит.

Перед реальным трафиком замените demo-прайс согласованным прайсом компании и утвердите актуальную политику обработки персональных данных. Приложение не объявляет шаблон политики юридически проверенным.

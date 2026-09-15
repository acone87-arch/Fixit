# Fixit production release, backup restore and rollback

Этот runbook применяется только к SHA, который прошёл workflow `Pilot onboarding acceptance`.
Секреты и значения `.env` в журнал проверки не копируются.

## Исторический bootstrap схемы

Alembic graph начинается с `20260825_0000` — явного снимка legacy-схемы из
Git commit `77b37fc4f29eb6f568335815001848500aee39d3`. Это исторический предок
уже развёрнутой revision `20260914_0016`.

- Полностью пустая БД устанавливается только командой `alembic upgrade head`.
- БД, уже показывающую `20260914_0016`, нельзя stamp'ить или downgrade'ить:
  с новым graph команда `alembic upgrade head` является no-op.
- Неверсионированная БД с точной pre-SaaS legacy-схемой сначала требует
  проверенного backup и сравнения schema. Только для этого исторического
  случая выполняются `alembic stamp 20260825_0000`, затем
  `alembic upgrade head`.

Legacy stamp нельзя применять к пустой БД или к production на `0016`: stamp
только записывает историю и не создаёт и не валидирует таблицы.

## Выпуск точного SHA

1. Убедиться, что draft PR содержит требуемый SHA и его acceptance job завершён успешно.
2. Перевести release-ветку `codex/pilot-release-p0-5` на этот SHA обычным fast-forward без force.
3. Workflow `Deploy to VPS` повторно запускает полный PostgreSQL/Chromium/JS gate для того же `github.sha`.
4. Deployment script сохраняет прежний SHA и image, останавливает API, создаёт согласованный DB+media backup и восстанавливает его в одноразовый PostgreSQL-контейнер и временный каталог.
5. Только после успешного сравнения таблиц, файлов и checksum выполняется `alembic upgrade head` и запускается новый image.
6. Deployment считается успешным после readiness `/health`, nginx config test, TLS health и HTTPS multipart smoke test.

`main` не требуется перемещать для pilot release. Push в `main` также является production trigger и поэтому допустим только после отдельного решения о merge.

## Состав backup

Каталог, напечатанный строкой `Backup:` в deployment log, содержит:

- `database.dump` и читаемый список архива;
- `database.counts` с количеством строк каждой таблицы;
- `uploads.tar.gz`, список файлов и `uploads.sha256`;
- `SHA256SUMS` для DB и media архивов;
- прежние `code.sha`, `image.id` и копию environment с закрытыми правами.

Команда ниже не меняет production DB или volumes. Она создаёт одноразовый PostgreSQL 16 без опубликованных портов, восстанавливает DB и media, сравнивает manifests и удаляет временные ресурсы:

```bash
cd /opt/fixit
bash scripts/verify_pilot_backup.sh /opt/fixit/backups/<backup-directory>
```

Хранить не менее пяти последних подтверждённых backup и не менее 30 дней. Старые архивы удаляются только вручную после успешного restore и проверки свободного места; deployment ничего автоматически не удаляет.

## Автоматический rollback приложения

Если backup, restore drill, миграция или readiness завершаются ошибкой, release script возвращает checkout на `code.sha`, переназначает сохранённый image и пересоздаёт только API container. PostgreSQL и uploads не удаляются и Alembic downgrade не выполняется.

После автоматического rollback проверить:

```bash
cd /opt/fixit
git rev-parse HEAD
docker compose -f docker-compose.prod.yml ps
curl -fsS http://127.0.0.1:8000/health
docker compose -f docker-compose.prod.yml exec -T api alembic current
```

Новая схема должна оставаться обратно совместимой с сохранённым image. Если это условие для будущей миграции не доказано, rollout останавливается до миграции.

## Полное восстановление DB и media

Полное восстановление выполняется только при повреждении production данных, в maintenance window и после проверки выбранного backup через `verify_pilot_backup.sh`.

1. Остановить запись в API и сохранить текущие DB volume и uploads volume без удаления.
2. Создать новые, отдельно названные PostgreSQL и media volumes.
3. Восстановить `database.dump` командой `pg_restore --exit-on-error --no-owner --no-privileges` в пустую БД.
4. Распаковать `uploads.tar.gz` в новый media volume и проверить `uploads.sha256`.
5. Сравнить `database.counts`, проверить `alembic_version`, открыть сохранённое изображение и сформировать PDF акта.
6. Переключить API на восстановленные volumes только после этих проверок. Старые volumes оставить до отдельного решения об удалении.

## Проверка HTTPS uploads

Nginx принимает multipart body до 9 MiB, а приложение ограничивает изображения до 8 MiB и гостевые изображения до 6 MiB. Deployment smoke test отправляет безвредные запросы на несуществующие UUID: 2 MiB должен дойти до приложения и вернуть `404`, 10 MiB должен быть отклонён nginx с `413`. Повтор и частичная доставка реальных фотографий проверяются в изолированных PostgreSQL/browser тестах.

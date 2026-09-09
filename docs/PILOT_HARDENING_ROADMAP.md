# FIXIT PILOT READY — живой roadmap

Главный журнал доведения существующего Fixit 2.0 / Fixit Pulse до пилотной готовности. Обновлять этот файл, не создавать новый roadmap после каждого этапа. Историю решений и исправлений сохранять.

## Контрольная точка

- Репозиторий: `acone87-arch/Fixit`.
- Исходный документ: `Fixit_Audit_2026-09-07.md`, независимый аудит от 07.09.2026.
- Audit SHA: `80ec53e84402b24c3a8bb263d150e7bf7a0dd865`.
- Последняя сверенная main: `87e3044f30a40b6d0cff0306e71f9aee83aca329`.
- Последняя сверка: 08.09.2026; GitHub Compare `identical`, ahead/behind `0/0`, новых commits `0`, изменённых файлов `0`. GitHub commit lookup отдельно подтвердил HEAD.
- P0.1 выполнен и проверен в PR [№3](https://github.com/acone87-arch/Fixit/pull/3); проверенный SHA кода: `cde3d81a79b7f29efd17f65bac0538914a75ca1c`. Изменения ещё не в main и не в production.
- Текущий шаг: **P0.4 в работе по команде пользователя от 09.09.2026**. Ветка `codex/p0-3-workflow`, PR №5; проверенный SHA кода P0.3 `9ed18bb664c6fd82a024624ed83ce6e56ea8c489`. Сохранены P0.1/P0.2 и актуальный main; merge в main/deploy не выполнялись.
- **FIXIT PILOT READY не подтверждён.**

### Как читать доказательства

Аудит уже проверял этот же SHA. При неизменённом коде его выводы сохранены как baseline, а не выданы за новые воспроизведения. Дополнительно просмотрены три конкретных места P0.1: invite role conversion, dependency TechnicianClientAccess, загрузка Equipment Types в клиентском UI.

Результаты Verify при инициализации:

| Категория | Результат |
|---|---|
| Всё ещё воспроизводится | Воспроизведения аудита относятся к неизменённому текущему SHA; заново не запускались. Конкретные дефекты перечислены ниже |
| Уже исправлено после аудита | Таких изменений нет. Работающие ранее возможности сохраняются; повторно их не разрабатывать |
| Не подтверждено | Реальные PG concurrency/миграции, browser E2E, устройства/SW, HTTPS upload, backup/restore/rollback — доказательства получать на соответствующем этапе |
| Новая связанная проблема | При этой ограниченной сверке не установлена |

Исторические проверки аудита: Python **143 passed**, 4 предупреждения; четыре JS runtime-файла завершились успешно. Это не текущий повтор suite, не PG integration и не основание закрывать P0. Большая часть source assertions не исполняет реальный маршрут. Последний deployment, изученный аудитом: [run 34093690044](https://github.com/acone87-arch/Fixit/actions/runs/34093690044); runtime/backup на момент будущего выпуска нужно проверить заново.

## Правила и статусы

- ⬜ не начато
- 🟡 в работе
- 🟢 выполнено и проверено
- 🟠 исправлено, но не полностью подтверждено
- 🔴 blocker
- ⚫ legacy / отложено

🔴 означает известное препятствие приёмке, а не то, что уже начато исправление. ⬜ означает ещё не выполненную задачу/проверку. Статус этапа учитывает все обязательные условия его DoD.

🟢 допустим только при подтверждённой проблеме и причине, внесённом исправлении, regression test, который выявлял исходный дефект, и проходящем необходимом runtime/integration пути. Для уже работавшего сценария не создавать искусственное исправление: записать «исправление не требуется» и доказательство поведения. Source assertion сам по себе недостаточен. Исправление без требуемого runtime подтверждения — 🟠, с точным недостающим доказательством.

Для каждого этапа: **Verify → Reproduce → Fix → Regression → Test → Roadmap → остановка**. В начале получить текущий main и diff от последнего сверенного SHA; читать только diff, код этапа и связанные regression tests. SHA обновлять после фактически выполненной сверки, оставляя прежний в журнале. Связанные изменения других P0 отметить, не расширять самовольно этап. Полный повторный аудит — только перед финальной приёмкой либо при изменении архитектуры нескольких P0-блоков.

Тестирование исправлений: сначала связанные тесты, затем полный доступный suite. Failing/skipped и недоступные среды фиксировать отдельно. Для дефектов ORM/блокировок необходим PostgreSQL, для UI — реальный payload/браузер, для очереди — IndexedDB/SW runtime. Тестовые среды изолированы от production.

До завершения P0 не разрабатывать SLA, ТО, Health Score, TCO, billing, ERP, AI и другие крупные возможности. Архитектуру и Fixit Pulse сохранять. Legacy Task/Ticket и старые offline payload не удалять без доказательства безопасности.

## Карта этапов

| Этап | Статус | Основание / следующий критерий |
|---|---|---|
| P0.1 Onboarding | 🟢 выполнено и проверено | 186 Python passed, включая 18 PostgreSQL и 3 browser E2E; пять JS runtime-файлов прошли. PR №3, production не обновлён |
| P0.2 Security boundaries | 🟢 выполнено и проверено | 48 PostgreSQL security-сценариев; полный suite 234 passed, 0 skipped; browser P0.1 и 5 JS runtime-файлов проходят. PR №4, production не обновлён |
| P0.3 QR + ServiceRequest | 🟢 выполнено и проверено | 266 passed, 0 skipped: новые 28 PG workflow, 2 migration и 2 browser; все пять JS runtime-файлов прошли. PR №5, production не обновлён |
| P0.4 Technician result | 🟡 в работе | Исходные фото и клиентский результат не доведены; полный E2E не подтверждён |
| P0.5 Durable offline queue | 🔴 blocker | data_url, atomic queue, ownership, межконтекстные гонки |
| P0.6 Warehouse integrity | 🔴 blocker | Отрицательное количество, mobile warehouse, связь движения с Repair |
| P0.7 Production acceptance | ⬜ не начато | PG/browser E2E, HTTPS upload, backup restore и rollback предстоит доказать |

## P0.1 — Onboarding

**Статус: 🟢 выполнено и проверено.**

DoD подтверждён на PostgreSQL 16 и Chromium в Actions. 18 PG-сценариев и 3 browser E2E прошли без пропусков; точные результаты, SHA и ограничения — в записи приёмки от 08.09.2026 ниже.

**Definition of Done:** приглашённый Site Manager самостоятельно принимает invite и входит, видит только назначенный Site, создаёт Equipment с существующим типом; сервисная компания назначает техника клиенту, и тот получает корректный доступ. Director подключается к уже существующему Client без дубликата. Проверены новый/существующий User, expiry/reuse/revoke и недопустимые роли.

| ID | Статус | Задача и актуальное основание |
|---|---|---|
| ONB-01 | 🟢 выполнено и проверено | Исправить accept: `target_role` после ORM — str, audit events читают `.value`; AttributeError воспроизведён аудитом |
| ONB-02 | 🟢 выполнено и проверено | Исправить `replace_service_technicians`: пользователь попадает в параметр db, параметр user отсутствует; HTTP-ошибка воспроизведена |
| ONB-03 | 🟢 выполнено и проверено | Подготовить Equipment Types для свежего Site Manager: клиентская кнопка вызывает ensureCustomers, но не ensureEquipmentTypes; не предлагать недоступное создание типа |
| ONB-04 | 🟢 выполнено и проверено | Подтвердить новым PG/HTTP тестом новый User и существующий User с верным/неверным паролем, атомарность accept |
| ONB-05 | 🟢 выполнено и проверено | Подтвердить expiry, повтор использования, revoke, inactive User/org/site/client, неправильную роль, конкурирующее принятие; согласовать отзыв с P0.2 |
| ONB-06 | 🟢 выполнено и проверено | Site Manager: свой/чужой Site и Client, первое Equipment; Director: тот же Client и его Sites без расширения в чужой Client |
| ONB-07 | 🟢 выполнено и проверено | Назначить/отозвать TechnicianClientAccess; активность membership; доступ к парку отдельно от права менять назначенную заявку |

**Код:** `app/routers/invites.py:156–203`, `app/models/customer.py`, `app/routers/customers.py:229–242`, `app/routers/equipment.py`, `app/services/client_portal.py`, `app/services/access_policy.py`, `app/static/app.js:673–680,1552` и клиентский join UI.

**Сохранить:** hash/token/expiry, привязку роли и Site сервером, подключение Director к существующему Client, scope Equipment. Не заменять работающий invite новым механизмом.

**Доказательства для закрытия:** HTTP → router → service → ORM → PostgreSQL для accept и grants; browser свежей сессии Site Manager → выбор существующего типа → Equipment; отрицательные чужие IDs. Минимальную PG test fixture допустимо подготовить здесь как необходимый инструмент этапа, без запуска всей P0.7.

**Миграция:** не нужна для внесённых исправлений P0.1; схема и применённые Alembic revisions не изменены. Constraints/data cleanup пока не выполнялись. **Риск:** средний, особенно existing User, смена клиентской роли и восстановление отозванных доступов.

## P0.2 — Security boundaries

**Статус: 🟢 выполнено и проверено в PR №4.**

**Definition of Done:** Organization A и Client A не могут читать или менять данные Organization B / Client B через основные или legacy API. Отзыв доступа действует сервером; общая учётная запись не позволяет администратору одного tenant отключить другой tenant. Доступ на чтение не даёт права менять ремонт.

| ID | Статус | Задача и актуальное основание |
|---|---|---|
| SEC-01 | 🟢 выполнено и проверено | Разделить глобальный User и управление membership: текущий PATCH меняет глобальную активность; existing-email POST присоединяет аккаунт без согласия |
| SEC-02 | 🟢 выполнено и проверено | Ограничить client-role чтение `/tasks`, `/warehouses`, stock и внутреннего parts API; tenant-only filter недостаточен для Client/Site |
| SEC-03 | 🟢 выполнено и проверено | Разделить Repair media read/write; клиент и fleet-reader не должны дописывать чужой акт; delayed upload автора после completion сохранить |
| SEC-04 | 🟢 выполнено и проверено | Закрыть бесконтекстный legacy sync; валидировать tenant/equipment/назначение Task и Ticket; разрешённые старые payload сохранить |
| SEC-05 | 🟢 выполнено и проверено | Полная матрица cross-client/cross-tenant ACL, включая фото/PDF, arbitrary IDs, inactive/deleted memberships, pending invites после revoke |
| SEC-06 | 🟢 выполнено и проверено | Проверить fail-closed Client/Site grants и multi-client поведение; не менять модель ролей без необходимости |

**Код:** `app/routers/users.py`, `tasks.py`, `warehouses.py`, `repairs.py`, `invites.py`, `app/services/access_policy.py`, `client_portal.py`, `sync_service.py`, `app/core/deps.py`.

**Доказательства:** HTTP+PG с двумя Organization, двумя Client в одном tenant, несколькими Sites, общим User; чтение и запись каждым role; valid/invalid legacy sync; отзыв и повтор с прежним JWT; авторский post-completion upload. Ownership локальной очереди принадлежит P0.5, совместная регрессия обязательна.

**Миграция:** не требуется; модели и Alembic не менялись. **Совместимость:** авторский retry и delayed photo проверены; старые Task/Ticket принимаются только с действительным назначением. Бесконтекстный пакет возвращает failed и остаётся в существующей очереди. Подробные доказательства и ограничения — в записи приёмки ниже.

## P0.3 — QR + ServiceRequest

**Статус: 🟢 выполнено и проверено. Приёмка в PR №5; production не обновлялся.**

**Definition of Done:** повтор QR не падает и не создаёт некорректных дублей; одна бизнес-поломка проходит существующий ServiceRequest workflow. Approval и completion работают, время завершения фиксируется, повтор sync возвращает согласованный результат без нового canonical Repair.

| ID | Статус | Задача и актуальное основание |
|---|---|---|
| SR-01 | 🟢 выполнено и проверено | Повтор QR использует существующую ServiceRequest, в том числе без Ticket; 201 вместо NameError |
| SR-02 | 🟢 выполнено и проверено | QR/staff/client intake используют общий transaction advisory lock для номера; конкурентные HTTP-запросы проходят |
| SR-03 | 🟢 выполнено и проверено | Receipt сохраняет ключ повтора после completion; другой Equipment получает 409 без чужого ID. Guest partial/photo retry и legacy NULL client_id проверены, исправление их поведения не требовалось |
| SR-04 | 🟢 выполнено и проверено | Оба target, сохранённый proposal, клиентские фото и owner/internal решение проходят в Chromium. Получатель переживает добавление фото/reload, поздний dashboard не затирает заявку; прежний Pulse payload поддержан |
| SR-05 | 🟢 выполнено и проверено | FOR UPDATE OF ServiceRequest: client approve/reject, cross-site deny и конкурентные решения проходят на PostgreSQL |
| SR-06 | 🟢 выполнено и проверено | Сервер ставит completed_at при canonical completion; retry не меняет дату. Старые неоднозначные даты не заполнены |
| SR-07 | 🟢 выполнено и проверено | Повторная проверка SyncOperation после Equipment lock возвращает already_synced с проверкой ownership; один Repair и одно completion event |
| SR-08 | 🟢 выполнено и проверено | Без Repair / в waiting / чужим участником завершить нельзя; approval/reject/cancellation, версии и несколько активных SR проверены. Staff/client intake меняет status/version под Equipment lock |

**Код:** `app/routers/tickets.py`, `service_requests.py`, `client_portal.py`, `app/services/service_requests.py`, `service_request_workflow.py`, `sync_service.py`, guest upload/UI, Pulse approval payload.

**Доказательства:** реальные PG-транзакции двух обращений/двух sync; настоящий UI payload; полный переход с approve/reject; запрет status bypass; guest response loss и photo retry. Не приравнивать автоматически все разные неисправности одного Equipment к одной поломке — сохранять подтверждённую продуктовую семантику.

**Миграция:** `20260908_0014`, новая таблица guest_request_receipts. Upgrade/downgrade/upgrade на существующих данных и transaction rollback проверены на PG. Схема остальных сущностей и исторические completed_at не менялись. Нумерация без новой сущности. **Риск:** высокий — canonical lifecycle и старые данные.


## P0.4 — Technician result

**Статус: 🟡 в работе. Verify/Reproduce.**

**Definition of Done:** одна ServiceRequest создаёт один полный canonical Repair и одну понятную запись истории: проблема, исходные фото, диагностика, работы, детали, фото результата, статус и результат. Техник проходит назначение → начало → approval при необходимости → completion; акт и результат доступны нужному клиенту.

| ID | Статус | Задача и актуальное основание |
|---|---|---|
| RES-01 | 🔴 blocker | Показать исходные request_attachments технику: workspace сейчас показывает Repair attachments |
| RES-02 | 🔴 blocker | Довести клиентский просмотр результата/работ/деталей/фото и вход в паспорт: карточка client equipment сейчас открывает новую заявку |
| RES-03 | 🔴 blocker | Устранить пропадание legacy Repair в агрегированной истории при task/ticket mapping без canonical link; неоднозначные связи не назначать произвольно |
| RES-04 | ⬜ не начато | Проверить полный путь с деталями и фото, генерацией акта, одной строкой истории, корректным доступом техника к историческому результату |
| RES-05 | ⬜ не начато | Проверить обязательность результата на сервере, Equipment.version conflict и отображение состояния; акт должен соответствовать доступному результату |

**Код:** Pulse technician/client UI, `app/routers/equipment.py`, `service_requests.py`, `client_portal.py`, `repairs.py`, `app/services/service_act_pdf.py`, serializers/access policy.

**Доказательства:** browser → API → PG, контроль числа canonical Repair/history entries; сравнение UI/JSON/PDF результата; legacy fixtures; другой клиент получает отказ. Подпись и юридически неизменяемый snapshot акта не добавлять автоматически в пилотный scope: отдельно фиксировать ограничение динамического PDF.

**Миграция:** не определена; только доказанная необходимость согласования legacy данных. **Риск:** средний/высокий — представление истории и границы read/write. Зависимости: P0.1–P0.3; окончательная приёмка с P0.5/P0.6.

## P0.5 — Durable offline queue

**Статус: 🔴 blocker. Исполнение не начато.**

**Definition of Done:** уже введённый ремонт и фотографии переживают временную потерю сети/ответа и перезапуск, не отправляются от другого аккаунта; после восстановления сети корректно связаны с Repair. Сохранённые данные не уничтожаются автоматически при logout/ошибке.

| ID | Статус | Задача и актуальное основание |
|---|---|---|
| OFF-01 | 🔴 blocker | Поддержать Blob и старые data_url: текущий engine старые фото помечает повреждёнными |
| OFF-02 | 🔴 blocker | Атомарно записывать pendingRepairs/pendingAttachments, ожидать transaction completion, явно обрабатывать quota/abort |
| OFF-03 | 🔴 blocker | User/org ownership очереди; account switch не отправляет чужие pending записи текущим токеном |
| OFF-04 | 🔴 blocker | Согласовать SW/page/две вкладки: нет общей блокировки, возможны гонки repair/attachment |
| OFF-05 | ⬜ не начато | Lost response, restart, истечение JWT/повторный login, безопасный retry, delayed upload после completed Repair |
| OFF-06 | 🔴 blocker | Показать конкретные ошибки очереди и безопасный способ продолжить отправку, не обещая бесконечный успешный retry |

**Код:** `app/static/offline/engine.js`, Pulse drafts/queue UI, `app/static/sw.js`, legacy SW/payload adapters, sync/media contracts.

**Доказательства:** IndexedDB/SW runtime и browser с Blob/data_url; принудительный abort/quota; закрытие/перезапуск; два аккаунта/tenant; SW+две вкладки; потеря ответа после commit; один Repair и один attachment на client_id; own completed Repair upload. Android Chromium и iOS подтверждать отдельно; отсутствие Background Sync на iOS учитывать, foreground recovery обязателен.

**Миграция:** вероятна версия/миграция IndexedDB; старые pending данные сохранять. Серверная миграция — только при необходимости. **Риск:** высокий — риск потери невосстановимых локальных фото.

⚫ **Отдельно отложено:** full offline cold-start, кеш заявок/паспортов/склада и автономные переходы. Включать только при подтверждённой потребности первого пилота; текущий Pulse не объявлять offline-first. Старые origin/SW не отключать раньше завершения безопасной миграции очередей.

## P0.6 — Warehouse integrity

**Статус: 🔴 blocker. Исполнение не начато.**

**Definition of Done:** использованная деталь корректно уменьшает остаток, движение связано с Repair; повтор запроса, ошибка и конкурирующий расход не портят склад. Новый техник получает постоянный мобильный склад и может пройти приёмку/перемещение/списание.

| ID | Статус | Задача и актуальное основание |
|---|---|---|
| WH-01 | 🔴 blocker | quantity>0 в схемах и сервисах receive/transfer/consumption; аудит воспроизвёл увеличение 10→15 при расходе -5 |
| WH-02 | 🔴 blocker | Persistent mobile warehouse: GET /mine/stock создаёт через flush без commit |
| WH-03 | 🔴 blocker | StockMovement → Repair: sync списывает с repair_id=None, связь потом не заполняется |
| WH-04 | ⬜ не начато | Два списания последней детали, missing-row race, порядок блокировок, rollback всего ремонта |
| WH-05 | 🔴 blocker | Retry/idempotency receive/transfer; повтор POST сейчас создаёт новое движение |

**Код:** `app/schemas/warehouse.py`, `repair.py`, `app/services/stock_service.py`, `sync_service.py`, `app/core/deps.py`, `app/routers/warehouses.py`, warehouse UI.

**Доказательства:** PG receive→transfer→repair; negative/zero; недостаток; новый техник; concurrent consumption; отказ второй детали откатывает первую и Repair; повтор после потери ответа; проверка ledger repair_id. Существующие row locks и CHECK stock>=0 сохранять.

**Миграция:** возможны positive-quantity/owner uniqueness constraints и ключи идемпотентности; сначала проверить старые данные. **Риск:** средний/высокий — складская целостность. ERP/закупочную систему не строить.

## P0.7 — Production acceptance

**Статус: ⬜ не начато.**

**Definition of Done:** полный Pilot E2E проходит на production-like PostgreSQL; DB+media backup действительно восстановлен в изолированную среду; выпускается проверенный SHA, а предыдущую работоспособную версию можно восстановить по проверенному runbook. Не объявлять готовность только по зелёному CI или наличию volume.

| ID | Статус | Задача и актуальное основание |
|---|---|---|
| OPS-01 | ⬜ не начато | PG integration и browser E2E всей цепочки, включая отрицательные ACL и retries |
| OPS-02 | 🔴 blocker | CI без PG и PR gate; guest JS runtime не включён. Подключить доказательные проверки этапов |
| OPS-03 | 🔴 blocker | Deploy делает git pull main вместо exact tested SHA; автоматическое восстановление после failed rollout отсутствует |
| OPS-04 | ⬜ не начато | Миграции со старой схемы, совместимость старого API при upgrade, сбой/lock timeout; воспроизводимый baseline пустой БД |
| OPS-05 | ⬜ не начато | Реальный HTTPS/nginx upload >1 МБ и до разрешённого лимита, типы и частичный retry. Глобальный nginx limit на VPS неизвестен |
| OPS-06 | ⬜ не начато | Найти существующий backup DB+media, retention и секреты доступа; восстановить в изоляции и проверить данные/фото. Внешний backup не подтверждён, отсутствие в repo не равно отсутствию на VPS |
| OPS-07 | ⬜ не начато | Runbook rollback: failed migration, failed app health, совместимость схемы, возврат image и при необходимости восстановление; health должен проверять полезную готовность |
| OPS-08 | 🔴 blocker | Известный дефект закреплённого multipart parser; совместимое обновление перед публичной загрузкой, тесты upload. Проверить image context/secrets и необходимые ограничения запросов |

**Код/инфраструктура:** `.github/workflows/deploy.yml`, Docker/compose, Alembic, nginx, requirements, health, backup/runbook. Текущий порядок migrations-before-restart сохранить; успешный deploy не доказывает recoverability.

**Доказательства:** CI run URLs+SHA; PG/browser результаты; журнал restore с проверкой БД и открытием фото/PDF; rollback rehearsal; HTTPS upload и TLS/renewal проверка. Секреты в журнал не помещать. Production data не использовать для разрушающих экспериментов.

**Миграция:** зависит от P0.1–P0.6; применённые production migrations не переписывать. **Риск:** высокий при выпуске/восстановлении; испытания сначала изолированно.

## Финальная приёмка FIXIT PILOT READY

Все P0 DoD выполнены, обязательные сценарии подтверждены runtime/integration; отсутствуют незакрытые blockers. Финальная проверка фиксирует точный SHA кода и среды:

1. Invite → новый Site Manager → вход → только свой Site → Equipment с типом → QR.
2. QR → ServiceRequest с исходными фото; повтор и потеря ответа безопасны.
3. Назначение техника → доступ → проблема/фото → начало → диагностика/работы/детали/фото → approval при необходимости.
4. Completion → один canonical Repair → корректный остаток и StockMovement → Act → одна понятная Equipment History → результат клиенту.
5. Чужие Client/Organization не читают и не меняют данные, включая legacy и media.
6. Pending результат переживает сеть/response loss/restart/account switch без потери или неверного автора.
7. Exact-SHA release, рабочие backup restore и rollback доказаны.

Неподтверждённые обязательные пункты оставляют этап 🟠/🔴, а весь продукт — без отметки FIXIT PILOT READY.

## Журнал этапов — добавлять записи, не заменять историю

### INIT — 07.09.2026

- Запрос: только сверить baseline/main, создать единый roadmap и предложить первый этап; бизнес-код не менять.
- SHA до/после: `80ec53e84402b24c3a8bb263d150e7bf7a0dd865` / тот же.
- Delta после аудита: 0 commits, 0 файлов. Полный аудит не повторялся.
- Изменён только `docs/PILOT_HARDENING_ROADMAP.md`; миграций нет; commit/push/deploy не выполнялись.
- Проверка документа: все P0.1–P0.7 имеют DoD, задачи, доказательства, migration/risk; отсутствуют необоснованные зелёные статусы задач.
- Runtime/integration suites на этом запуске не выполнялись: исправлений нет. Исторические результаты аудита отделены выше.
- Выбор: P0.1. Он устраняет входной разрыв E2E и создаёт проверяемую основу пользователей/Sites/grants для следующих этапов. Не расширять его до всей security-программы; связанные ACL-гарантии для самого onboarding обязательны.
- Остановка: до команды пользователя «Начинай следующий этап».

### Шаблон следующей записи

- Этап и дата:
- Статус:
- Предыдущий сверенный SHA / текущий main / SHA исправления:
- Delta main и влияние на этап:
- Verify: воспроизводится / уже исправлено / не подтверждено / новая связанная проблема:
- Reproduce: команда/маршрут, исходный результат и причина:
- Fix: причина → минимальное изменение, IDs задач:
- Regression: тест, который выявлял дефект до исправления:
- Test: связанные / полный Python / PG / JS / browser; passed/failing/skipped и причина:
- Изменённые файлы:
- Миграция, compatibility и rollout:
- Доказательства DoD и остаточные риски:
- Обновлённые статусы задач (старые записи не удалять):
- Рекомендуемый следующий этап и причина:
- Остановка до команды пользователя:


### P0.1 — 07.09.2026 — локальные исправления, приёмка не завершена

- Статус: 🟠 исправлено, но не полностью подтверждено. Этап не объявлен выполненным.
- Основание запуска: команда пользователя «Начинай следующий этап» после INIT.
- Предыдущий сверенный SHA / текущая main: `80ec53e84402b24c3a8bb263d150e7bf7a0dd865` / тот же; GitHub Compare identical, 0 новых commits/файлов. SHA исправления отсутствует: изменения не закоммичены.
- Verify: три исходных дефекта сохранялись. Уже исправленных после baseline нет. Дополнительно подтверждено отсутствие проверок отключённого доступа/активности объектов при accept и активной membership при fleet grant. PG/browser поведение не подтверждено.
- Reproduce до правок: `tests/test_onboarding_runtime.py` — **6 failed, 3 passed**; actual HTTP routes с тестовой AsyncSession и настоящим PostgreSQL Enum result processor. `onboarding_equipment_runtime_test.js` падал на отсутствии загрузки типов. Ошибка `.value` маскировала downstream lifecycle, поэтому для них добавлены отдельные проверки после устранения первичного исключения.

Изменения:

| Задачи | Причина → исправление | Доказательства и предел |
|---|---|---|
| ONB-01 | str enum → `_role_value` в audit events, как в token/response | HTTP accept с реальным ORM enum converter проходит; actual PG пока skipped |
| ONB-02/07 | User вместо session → отдельные db/user dependencies; active membership в GET/PUT; client row lock для replacement grants | HTTP PUT проходит; реальные PG grant/revoke/concurrent проверки ещё не выполнены |
| ONB-03 | Не загружены types → ожидание справочника внутри общей формы, сообщение при ошибке/пустом каталоге; запрещённый «+ Новый тип» скрыт клиенту, staff сохранён | Реальные JS functions с тестовым DOM/API: payload содержит type/site, вызывается паспорт; browser не выполнен |
| ONB-04/05 | Invite мог использовать отключённые сущности/доступ → проверки active Organization/Client/Site/issuer/User/membership; отозванный scope не реактивируется | HTTP/service runtime для expiry/reuse/revoke/disabled, PG tests подготовлены |
| ONB-04/06 | Existing User с другим Client получал несовместимый scope → 409 до grant; existing User блокируется при accept; конфликт concurrent создания email → rollback и 409 | Runtime новый User, existing password, server role, Director promotion; PG scenarios пока skipped |
| Связанный rollout | Обновлённый JS должен быть доставлен браузеру → версия app.js `20260907-1`, shell v7 и согласованные precache URL | Исполнен install handler SW с тестовым Cache API; очереди/old SW не очищаются |

Принятая семантика отзыва: приглашение не восстанавливает отключённого User/membership или ранее отключённый совпадающий scope. Восстановление требует отдельного явного действия сервисной компании. Полная модель revoke, включая гонку с параллельным отзывом и управление доступами через остальные routes, остаётся P0.2. Не утверждать, что изменения invite закрыли все security boundaries.

Изменённые файлы:

- `app/routers/invites.py`, `app/routers/customers.py`.
- `app/static/app.js`, `app/static/index.html`, `app/static/sw.js`.
- `tests/test_onboarding_runtime.py` — 22 исполняемые HTTP/service проверки с подменённой БД.
- `tests/test_onboarding_postgres.py` — 15 настоящих PG/HTTP scenarios, запускаются только при явном FIXIT_TEST_DATABASE_URL.
- `tests/onboarding_equipment_runtime_test.js` — 5 UI/SW scenarios.
- `tests/onboarding_browser_fixture.py` — изолированная форма на реальных функциях app.js, API fixture, без production/auth; это не полный E2E.
- `tests/test_pilot_client_onboarding.py`, `tests/test_equipment_service_history.py` — обновлены ожидания версии JS, не используются как доказательство работоспособности.
- `.github/workflows/deploy.yml` — добавлен только запуск новой JS-регрессии; deployment logic не изменена.
- `docs/PILOT_HARDENING_ROADMAP.md` — обновлён этот журнал.

Проверки:

- Связанные Python: **44 passed, 15 skipped**.
- Полный Python: **165 passed, 15 skipped, 4 warnings**; skipped — исключительно PostgreSQL tests без FIXIT_TEST_DATABASE_URL. Предупреждения прежних зависимостей не являются новыми test failures.
- Все пять JS runtime-файлов завершились успешно; новый файл исполнил 5 сценариев (первое оборудование, ошибка справочника, пустой каталог, staff action, SW precache).
- `git diff --check`: passed.
- PostgreSQL integration: **не выполнен, 15 skipped**. PostgreSQL/Docker отсутствуют; обычная попытка установки завершилась ошибками setgroups/setuid ограниченной среды. Настройки доступа и sandbox не менялись.
- Browser: Chrome подключён, но переход к локальной fixture `http://127.0.0.1:8766/` отклонён `net::ERR_BLOCKED_BY_CLIENT`. **Browser E2E не выполнен**, не считать успехом JS runtime.
- Миграций нет. Production, пользователи и клиентские данные не изменялись; commit/push/deploy не выполнялись.

Повторяемые команды (из корня репозитория, в тестовом environment с DATABASE_URL/SECRET_KEY/ALLOWED_HOSTS):

```bash
pytest -q tests/test_onboarding_runtime.py tests/test_pilot_client_onboarding.py tests/test_technician_client_access.py
FIXIT_TEST_DATABASE_URL=postgresql+asyncpg://TEST_USER:TEST_PASSWORD@127.0.0.1:5432/fixit_test pytest -q tests/test_onboarding_postgres.py
node tests/onboarding_equipment_runtime_test.js
python tests/onboarding_browser_fixture.py
```

PG fixture создаёт уникальную schema в явно заданной loopback БД `*_test` и удаляет только её. Создание current-model schema не является доказательством upgrade существующей production-схемы; Alembic/restore остаются P0.7. Не использовать production URL.

Остаточные риски и следующий шаг:

1. Прогнать 15 PG scenarios; добавить/пройти необходимые конкурентные cases для разных invites одного email и реальных grant replacements. Тесты написаны, но ещё могут выявить ошибки только реального ORM/PG пути.
2. Пройти browser fresh Site Manager → тип → Equipment с настоящим API/PG, а затем Director и доступ техника. Изолированная fixture проверяет только UI.
3. Валидация active/revoke не является полной транзакционной гарантией относительно одновременного отзыва через все соседние API — проверить и согласовать в P0.2; не расширять scope текущего этапа молча.

Рекомендуется **продолжение приёмки P0.1**, а не объявление его зелёным. После её прохождения следующий функциональный этап — **P0.2 Security boundaries**, потому что до клиентского выпуска нужно закрыть глобальный User и лишние legacy/media/warehouse права. Остановка до следующей команды пользователя.


### P0.1 — запуск удалённой приёмки, 07.09.2026

- Пользователь разрешил публикацию GitHub для завершения приёмки. Предыдущие записи о локальных изменениях относятся к завершённому локальному прогону.
- Подготовлены отдельный PR workflow `pilot-onboarding.yml` с PostgreSQL 16 и Chromium, три настоящих browser E2E и ещё три конкурентных PG-регрессии. Запуск проверяет HEAD PR; production secrets и deployment не используются.
- Browser: свежий Site Manager в desktop/mobile viewport → Equipment → паспорт → доступ техника; existing User с неверным/верным паролем → Director существующего Client. API/auth/SW не мокируются. Mobile viewport не равен испытанию реального Android/iOS.
- PG: 18 scenarios; expected полный suite 165 прежних/runtime + 18 PG + 3 browser. Числа здесь — план, не результат; до завершения Actions остаётся 🟠.
- Связанные файлы: `.github/workflows/pilot-onboarding.yml`, `tests/test_onboarding_browser.py`, `tests/test_onboarding_postgres.py`. Миграция не добавлена.


### P0.1 — завершение приёмки, 08.09.2026

**Статус: 🟢 выполнено и проверено в PR; изменения не выпущены в production.**

Verify: main по-прежнему `80ec53e84402b24c3a8bb263d150e7bf7a0dd865`; compare identical, 0 новых commits/файлов. Повторный аудит не проводился, проверены только результаты P0.1.

Первый удалённый прогон [34151182871](https://github.com/acone87-arch/Fixit/actions/runs/34151182871), SHA `bea8916dcc750935011aadcccd607566fe56bfd4`: **183 passed, 3 failed, 0 skipped**, JS-шаг skipped из-за предыдущей ошибки. Все 18 PostgreSQL-сценариев прошли. Три браузерных теста искали `button[type=submit]`, хотя у реальной кнопки «Продолжить» нет явного атрибута type (submit действует по умолчанию). Причина в тестовом селекторе, не в бизнес-коде. В `tests/test_onboarding_browser.py` использован поиск кнопки по доступной роли/имени в join-form; сценарий и проверки не ослаблены.

Подтверждающий прогон: [34186674204](https://github.com/acone87-arch/Fixit/actions/runs/34186674204), SHA `cde3d81a79b7f29efd17f65bac0538914a75ca1c`. Checkout в логе подтвердил именно этот HEAD PR. Workflow завершился **success**.

| Проверка | Фактический результат |
|---|---|
| Полный Python suite, Python 3.12 | **186 passed, 0 failed, 0 skipped**, 92 DeprecationWarning зависимостей, 42.90 s |
| PostgreSQL 16, HTTP → router → service → ORM | **18 passed**, входят в 186; новый/существующий User, lifecycle invite, scopes, grant/revoke, конкурентное принятие и назначения |
| Chromium → настоящий Pulse/API/PostgreSQL | **3 passed**, входят в 186; Site Manager desktop и mobile viewport → первое Equipment → паспорт → доступ техника; existing User → Director существующего Client |
| JS runtime | **5 файлов прошли**: onboarding (5 сценариев), Pulse offline engine, technician workflow, offline attachment sync, guest photo upload |
| Артефакт | `pilot-onboarding-cde3d81a79b7f29efd17f65bac0538914a75ca1c`, JUnit XML, [artifact 10040767694](https://github.com/acone87-arch/Fixit/actions/runs/34186674204/artifacts/10040767694), хранение 7 дней |
| Локальная проверка этой итерации | Onboarding JS: 5 сценариев пройдено; git diff --check passed. Повтор Python локально не запустился: прежний временный venv уже отсутствует; результат Python подтверждён Actions |

Доказательства закрывают ONB-01–07: исправлены enum conversion и DI TechnicianClientAccess; клиентская форма загружает существующие Equipment Types; проверены новый и существующий аккаунт, неверный пароль, запрет подмены роли/Site, истечение/повтор/отзыв invite и отключение сущностей/доступов; Director использует прежний Client; concurrent accept не дублирует grant/account; техника можно назначить и отозвать, inactive membership не получает доступ. Исправления и история исходных воспроизведений сохранены выше.

В этой итерации изменены только `tests/test_onboarding_browser.py` и этот roadmap. Бизнес-код сверх ранее опубликованного P0.1 не менялся. Миграция: **нет**. PR: [№3](https://github.com/acone87-arch/Fixit/pull/3).

Предел приёмки: PG fixture создаёт schema из моделей, не проверяет Alembic upgrade/restore; браузер — Chromium с desktop/mobile viewport, не реальный iOS/Android; права проверены в пределах onboarding, а не всей legacy/media/warehouse поверхности. Полный Invite → QR → Repair → Act → History E2E, миграции, HTTPS upload, backup/restore/rollback остаются соответствующим P0.2–P0.7. **FIXIT PILOT READY всего продукта не объявляется.**

Следующий рекомендованный этап — **P0.2 Security boundaries**: глобальный User и legacy/media/warehouse ACL остаются подтверждёнными препятствиями безопасному пилоту. Начинать только после команды пользователя «Начинай следующий этап». Merge/deploy не выполнялись.


### P0.2 — Verify / Reproduce, 08.09.2026

- Текущий main: `87e3044f30a40b6d0cff0306e71f9aee83aca329`; после прошлого `80ec53e` ровно один commit, два файла: `app/routers/customers.py`, `tests/test_client_detail_regression.py`. Dependency назначения техника уже исправлена в main — повторное исправление не выполнялось. Сохранены его многострочная сигнатура и тест, а также проверенные P0.1 membership checks/locking.
- PR №3 ещё не слит. Изолированная ветка P0.2 содержит его проверенный HEAD `78947c9` и новый main; конфликт одной сигнатуры разрешён с сохранением обоих изменений. Production не менялся.
- [PR №4](https://github.com/acone87-arch/Fixit/pull/4), воспроизводящий SHA `17784c735db71826501f5d116fb8db69dc02a55d`.
- [Actions 34189991116](https://github.com/acone87-arch/Fixit/actions/runs/34189991116): **24 failed, 192 passed, 0 skipped**, 142 warnings. Все 24 failures — новые HTTP/PostgreSQL security-регрессии. Подтверждены global User mutation, existing-email присоединение без согласия, клиентское чтение Task/warehouses/parts/stock, клиентская и fleet-tech запись Repair media, бесконтекстный/чужой/cancelled legacy sync, чужой sync retry, NULL Site grant → весь Client, подключение директором чужого Client User и восстановление удалённого access старым invite.
- Правильные старые Task/Ticket-пакеты и авторская досылка фото сохраняются. Ошибки unknown ticket/foreign part без stock уже откатывались БД; добавляется явная проверка до записи, не выдавать прежний rollback за новую уязвимость.
- После локальных исправлений: **165 passed, 51 skipped, 4 warnings** (до добавления дополнительных concurrency-регрессий); skipped — PG/browser без локального PostgreSQL. Это не итог приёмки P0.2. Новые tests проверяют одновременный revoke/accept, двух администраторов, canonical sync и старые некорректные связи stock.


### P0.2 — приёмка завершена, 08.09.2026

**Статус: 🟢 выполнено и проверено в PR; production не обновлён.**

Код: `8e46ae7dc552bca00535be414d773de125ad714c`, [PR №4](https://github.com/acone87-arch/Fixit/pull/4). Повторная сверка main: `87e3044f30a40b6d0cff0306e71f9aee83aca329`, новых изменений после начала этапа нет. Полный аудит повторно не выполнялся.

| Задача | Подтверждённая причина → исправление | Доказательство |
|---|---|---|
| SEC-01 | PATCH/DELETE затрагивали глобальный User → отключается membership данного tenant, доступы отзываются; глобальный аккаунт сохраняется. Изменение общего профиля из одного tenant отклоняется, неизменённые поля обычной UI-формы не блокируют переключение доступа | Общий User в двух Organization: A отключён, B продолжает работать; изменение контактов отклонено; последний membership не отключает глобальный User; параллельное удаление администраторов оставляет одного активного |
| SEC-01 | Existing-email POST выдавал membership без участия владельца → 409, клиент подключается по существующему invite с паролем | Чужая учётная запись не присоединяется; создание нового сотрудника и login сохранены; P0.1 existing-account invite проходит |
| SEC-02 | Внутренние Task/parts/warehouses/stock имели только tenant filter → клиентские роли получают 403; техник видит свои склады | Site Manager и Director: восемь отрицательных HTTP-сценариев; старый Task read-only сохранён для staff/назначенного техника |
| SEC-03 | Repair read ACL использовался для upload → отдельная write policy (staff или автор-техник), до проверки upload idempotency | Клиент/fleet-reader читают разрешённое фото, но получают 403 на запись; автор досылает после completed, повтор возвращает прежнее вложение; отключённый membership получает 401 |
| SEC-04 | Legacy sync не требовал проверенного контекста, Ticket/сочетания ID не проверялись; retry возвращал чужой server_id → tenant/equipment/assignment/state/linked-ID checks, retry проверяет автора и ремонт | Валидные Task/Ticket и canonical completion/retry проходят; чужой автор/tenant, cancelled Task, несовпадающий Ticket и отсутствие контекста отклонены без частичной записи; чужая Part отклонена до списания |
| SEC-05/06 | NULL Site расширял менеджера до Client; Director мог присоединить пользователя другого Client → fail-closed scopes, активность Client/Site, запрет несогласованного cross-client grant | Свои документы/паспорт читаются; чужие Site/Client/tenant и изменения фото/перенос оборудования отклонены, с положительным контролем владельца чужого tenant |
| SEC-05/06 | DELETE access терял след отзыва; перенос Site терял прежний scope → сохраняется отключённая запись, pending invite не восстанавливает старый доступ | Revoke/accept, delete-access/accept выполняются конкурентно на PostgreSQL: после отзыва доступ отсутствует; старый invite после переноса Site отклонён |
| Связанные изменения | Выдача и отзыв прав могли пересечься → блокировка строки Organization на время изменения прав и повторная проверка действующего actor; счётчики клиента учитывают Site scope | Конкурентные PG-сценарии пройдены. Счётчики другого Site больше не видны менеджеру; это небольшое уточнение изоляции, не отдельный архитектурный блокер |

Проверки:

- Первое воспроизведение: [34189991116](https://github.com/acone87-arch/Fixit/actions/runs/34189991116), SHA `17784c7`: **24 failed, 192 passed, 0 skipped**. Исходные failure-сценарии сохранены, не заменены source assertions.
- Первые исправления: [34190518647](https://github.com/acone87-arch/Fixit/actions/runs/34190518647), SHA `3b92343`: **227 passed, 0 failed, 0 skipped**, 166 предупреждений зависимостей; включая 41 security PG case.
- Итог кода: [34211731273](https://github.com/acone87-arch/Fixit/actions/runs/34211731273), SHA `8e46ae7dc552bca00535be414d773de125ad714c`: **234 passed, 0 failed, 0 skipped**, 201 DeprecationWarning зависимостей, 150.45 s. Checkout подтвердил точный HEAD; workflow **success**.
- PostgreSQL integration: **66 passed**, входят в 234: 48 security + 18 onboarding. Маршрут HTTP/JWT → router → service → ORM → PostgreSQL 16, отдельные schemas с синтетическими данными.
- Browser E2E: **3 passed**, входят в 234; настоящий Pulse/API/PostgreSQL, Chromium desktop/mobile viewport и Director.
- JS runtime: **все 5 файлов прошли** — onboarding (5 сценариев), Pulse offline engine, technician workflow, offline attachments, guest photo upload.
- [JUnit artifact 10050201396](https://github.com/acone87-arch/Fixit/actions/runs/34211731273/artifacts/10050201396), срок хранения 7 дней; имена сценариев и тесты сохранены в git.
- Локальный suite до расширения матрицы: **165 passed, 51 skipped**, 4 warnings; последующий временный venv недоступен после возобновления сессии, поэтому итоговые Python/PG/browser результаты взяты из Actions. Python AST и git diff --check проходят. Сгенерированные изменения tracked pyc восстановлены, в PR не включены.

Изменённые файлы P0.2:

- `app/core/deps.py` — некорректные UUID в JWT отклоняются как credentials error.
- `app/routers/users.py`, `tasks.py`, `warehouses.py`, `repairs.py`, `client_portal.py`, `invites.py`, `customers.py`.
- `app/services/access_changes.py` (небольшой общий lock для изменений прав), `access_policy.py`, `client_portal.py`, `sync_service.py`.
- `tests/test_security_postgres.py` — 48 настоящих PG/API-сценариев; `test_onboarding_runtime.py`, `test_canonical_repair_relationship.py` — session doubles учитывают новые DB checks; `test_user_deactivation.py`, `test_client_access_management.py` — прежние source contracts приведены к membership-only revoke/tombstone, не используются как доказательство приёмки.
- `tests/test_client_detail_regression.py` — сохранён новый тест текущего main, не самостоятельное исправление P0.2.
- Этот roadmap. Frontend, SW, модели и миграции на этапе P0.2 не менялись. Использован существующий изолированный PR workflow P0.1; production deployment не запускался.

Пределы и следующий этап:

1. Изменения ещё в PR №4; он включает неслитый P0.1 из PR №3 и текущий main. Порядок интеграции нужно сохранить; main не обновлять автоматически, поскольку push запускает production deploy.
2. P0.2 подтверждает серверные границы проверенной матрицы. Очередь на другом аккаунте/после перезапуска, полная устойчивость sync и upload races — P0.5; складские количества/движения — P0.6. Schema fixture не подтверждает Alembic upgrade, restore и rollback — P0.7.
3. Некорректные старые ClientUserAccess (NULL Site у менеджера, другой Client) теперь получают отказ; автоматического расширения прав или массовой правки production-данных нет. Глобально отключённые ранее User также не реактивируются автоматически.
4. **Следующий этап — P0.3 QR + ServiceRequest.** После закрытия ACL остаются подтверждённые ошибки повторного QR, approval contract/locking, completed_at и retry. Начинать только после команды «Начинай следующий этап».

**FIXIT PILOT READY всего продукта ещё не подтверждён.**


### 08.09.2026 — P0.3, воспроизведение и исправления в работе

- Команда пользователя: «Давай следующий этап». Текущий main `87e3044f30a40b6d0cff0306e71f9aee83aca329`, compare от предыдущей точки identical. База ветки — `a369aa70fb963896eb5fc6d81fb7070e4d8efca7`, сохраняет P0.1/P0.2; PR [№5](https://github.com/acone87-arch/Fixit/pull/5).
- Воспроизведение `bbe4c0a4960536d42fc58c5006a8ae60f91993ed`, [Actions 34213791333](https://github.com/acone87-arch/Fixit/actions/runs/34213791333): **15 failed, 238 passed**, JS-шаг skipped после Python failure. Все 15 failures — новые проверки P0.3. Подтверждены QR NameError, раскрытие чужой заявки по ключу другого Equipment, конфликт номера у QR/staff/client, потеря approval snapshot, отсутствие completed_at, конкурентный retry=failed, ошибочное working при другой активной заявке.
- Уже работали: guest partial/photo retry и legacy NULL client_id, проверка изображения/лимита, защита completion без Repair, waiting_parts, конфликт Equipment version. Минимально сужен guest photo row lock до ServiceRequest для единого порядка с sync; поведение фото не переписывается.
- Исправления: транзакционная сериализация intake/номеров; постоянная привязка QR submit к заявке (включая повтор активной); проверка Equipment при повторе; явный internal target в Pulse и совместимость с прежним payload; сохранение/валидация approval snapshot; FOR UPDATE OF service_requests в client approval; completed_at при completed; повторная проверка SyncOperation после Equipment lock с сохранением P0.2 ownership; сохранение needs_repair при другой активной заявке и версионирование ручного/client intake.
- Миграция **0014**, только новая guest_request_receipts. Ticket остаётся fallback для старых ключей. Исторические completed_at не заполняются недоказанными датами. При rollback сохранять таблицу и останавливать QR intake до возврата версии, которая читает receipts: старое приложение игнорирует новые ключи. Downgrade после новых QR удалит ключи повторов, поэтому после приёма данных не применять. Runbook безопасного rollback — P0.7.
- Приёмка в процессе: точные итоги PostgreSQL/Chromium и SHA будут внесены после окончания, статус 🟢 пока не присваивается. Полный migration chain/production backup restore/HTTPS остаются P0.7.

- Второе воспроизведение: `97cdf4d14c12fbee92f799f8697fbd8fb624ee73`, [Actions 34244045250](https://github.com/acone87-arch/Fixit/actions/runs/34244045250): **20 failed, 239 passed, 0 skipped**, 403 предупреждения зависимостей. Реальный Chromium нажал кнопку Pulse и получил 422 «Укажите получателя согласования». PostgreSQL отдельно исполнил client approval и вернул `FOR UPDATE cannot be applied to the nullable side of an outer join`. Все failures — новые P0.3 regression tests.
- Локально после исправлений: связанные Python **32 passed**; весь доступный suite **165 passed, 96 skipped** (PostgreSQL/browser требуют CI), пять JS runtime-файлов проходят. Начальный локальный запуск без обязательных settings дал четыре collection errors, после задания синтетической конфигурации устранены. Старый source assertion ожидал общий `with_for_update()`; актуализирован на `of=ServiceRequest`, а фактическая блокировка проверяется конкурентными HTTP/PG тестами. Mock session канонического sync получил дополнительные ответы для новых SQL-проверок; полноценный PG тест сохранён.

- Дополнительный подтверждённый пробел SR-04: клиентский экран approval использовал problem/outcome вместо proposal; UI техника не давал выбрать уже поддержанный API client target. Добавлен выбор «Диспетчер / Клиент», вывод диагностики, предложенных работ, деталей, комментария и защищённых approval photos в клиентском кабинете. Browser E2E проверяет оба target, настоящий multipart upload, декодирование изображения у Site Manager, его решение и сохранение черновика техника после reload. Результат приёмки пока ожидается.

- Первый успешный прогон исправлений: [34244620120](https://github.com/acone87-arch/Fixit/actions/runs/34244620120), SHA `a2e9ff6cb24600663a729ad1de1cc2bf720778f5`: **263 passed, 0 failed, 0 skipped**, 464 предупреждения зависимостей, 269.33 s; пять JS runtime-файлов — passed. Включены 26 новых workflow PG, две проверки migration 0014, один новый Chromium E2E и все P0.1/P0.2 regression tests.
- Финальное дополнение к приёмке: два одновременных QR с одним ключом в одном/разных tenant; Chromium для обоих approval target с клиентским просмотром proposal/photos. SHA `786f3b8a3e9d427b66c83f9eeb8c748f37c6a068` пока проходит CI. Локально **165 passed, 101 skipped**; пропуски PG/browser компенсируются только фактическим CI, не считаются успехом.

- Прогон дополнения [34245383893](https://github.com/acone87-arch/Fixit/actions/runs/34245383893), SHA `786f3b8`: **1 failed, 265 passed, 0 skipped**, 489 предупреждений. Найден UI regression: добавление фото перерисовывало select и сбрасывало client target в internal. Исправлено сохранением target в существующем RequestDraftStore и восстановлением при draw/reload; browser test сохраняет именно выявившую сбой последовательность. Дополнительно UI внутренних решений приведён к серверным ролям: owner/admin/dispatcher, только internal target; owner проходит реальную браузерную форму согласования.

- Проверка `621600e`, [34246292589](https://github.com/acone87-arch/Fixit/actions/runs/34246292589): **1 failed, 265 passed**, 506 предупреждений; клиентский browser с фото и recipient persistence прошёл. Внутренний browser не обнаружил открытую карточку. Найдена гонка dashboard → request: поздний renderPulse затирал уже открытый раздел. Новый JS runtime-тест исполнил настоящий async renderer с задержанными ответами и воспроизвёл перезапись; после проверки актуального маршрута тест проходит. Браузерная регрессия сохраняет быстрый переход; ожидание окончания dashboard не добавляется.

- Проверка доставки UI в установленную PWA: app.js продолжал использовать прежний URL `v=20260907-1`, который root worker отдаёт cache-first. Реальный fetch handler в JS runtime воспроизвёл получение старого интерфейса. Синхронно обновлены URL app.js в index/SHELL и имя shell cache; test с сохранённым старым кешем теперь получает новую версию. IndexedDB/очередь/старые кеши не удаляются. Полный offline cold-start не объявляется подтверждённым.


### 08.09.2026 — P0.3: итог приёмки

**Статус: 🟢 выполнено и проверено.** Блоки P0.4–P0.7 не объявляются готовыми.

- Проверенный код: `9ed18bb664c6fd82a024624ed83ce6e56ea8c489`; [Actions 34274688219](https://github.com/acone87-arch/Fixit/actions/runs/34274688219), job `102224679630`, **success**. Checkout подтвердил точный SHA.
- **266 passed, 0 failed, 0 skipped**, 511 предупреждений зависимостей, 259.96 s. Внутри общего числа: 96 PostgreSQL cases (18 onboarding + 48 security + 28 workflow + 2 migration) и 5 Chromium E2E (3 onboarding + 2 approval). Остальные 165 — существующий Python suite.
- Новый P0.3: 28 HTTP/PG сценариев; 2 migration cases; 2 настоящих Chromium сценария. Это части 266, а не дополнительные к общему числу тесты.
- Все пять JS runtime-файлов прошли. Добавлены фактический async-render regression и проверка cache-first fetch со старым app.js; последняя воспроизвела stale UI локально и прошла после согласованного изменения URL HTML/SHELL. Финальный commit включает эту смену версии и журнал; его Actions status проверяется отдельно.
- Regression failures сохранены в истории: исходные 15/20 failures, сброс recipient после photo и гонка dashboard. Ничего не скрыто через skip/xfail или замену на source assertion.
- Дополнительный прогон `214952d25e2d29d1c781b77a7acecfb987a630ca`, [Actions 34275528627](https://github.com/acone87-arch/Fixit/actions/runs/34275528627): **2 failed, 264 passed**, 511 предупреждений; JS-шаг не запускался после failure. Обе ошибки — старые source assertions с точным URL `app.js?v=20260907-1` после необходимого обновления PWA. Проверка ассетов теперь сравнивает версии HTML и SHELL, дублирующая привязка onboarding к старой дате удалена. Работоспособность обновления проверяет существующий runtime-тест реального SW fetch-handler со старым кешем; итоговый HEAD требует полного зелёного CI, результат фиксируется в PR №5.

**Что подтверждено:**

1. QR повторяет активную/завершённую заявку по сохранённому ключу, не раскрывает другую Equipment; одновременно отправленный ключ из разных tenant изолирован. Legacy Ticket key работает.
2. Все три intake маршрута безопасно получают номера на PostgreSQL. Guest photo partial/retry/legacy NULL, лимит, валидация изображения и чужой QR проверены.
3. Внутреннее и клиентское согласование имеют сохранённый контекст, правильный recipient/role/scope и PostgreSQL lock. Два конкурирующих решения дают один успех и один 409. В UI client видит proposal/photo и принимает решение, owner проходит внутреннюю форму; technician draft восстанавливается.
4. Completion выполняется только из допустимого workflow через canonical Repair. completed_at фиксируется; конкурентный retry возвращает already_synced, дополнительный canonical Repair не создаётся; запрос с новым UUID не затирает уже принятый результат. Другие активные SR и конфликт Equipment version сохраняют состояние оборудования.
5. Миграция 0014 проходит upgrade/downgrade/upgrade с существующими Equipment/ServiceRequest и rollback незавершённой транзакции.

**Изменённые файлы P0.3** (от базы `a369aa7`, без повторного перечисления файлов P0.1/P0.2):

- `app/models/service_request.py`
- `app/schemas/service_request.py`
- `app/routers/tickets.py`
- `app/routers/service_requests.py`
- `app/routers/client_portal.py`
- `app/services/service_requests.py`
- `app/services/service_request_workflow.py`
- `app/services/sync_service.py`
- `app/static/app.js`
- `app/static/index.html`
- `app/static/sw.js`
- `alembic/versions/20260908_0014_guest_request_receipts.py`
- `tests/test_request_workflow_postgres.py`
- `tests/test_request_receipts_migration_postgres.py`
- `tests/test_request_workflow_browser.py`
- `tests/test_canonical_repair_relationship.py`
- `tests/test_guest_photo_retry.py`
- `tests/technician_workflow_runtime_test.js`
- `tests/onboarding_equipment_runtime_test.js`
- `tests/test_equipment_service_history.py`
- `tests/test_pilot_client_onboarding.py`
- `docs/PILOT_HARDENING_ROADMAP.md`

**Остаточные ограничения:**

- Исторические completed_at не восстановлены из неоднозначных данных; при необходимости сверять с надёжным событием/результатом отдельно. Для новых completion дата подтверждена.
- До выпуска нужна миграция 0014. Старый код не читает receipts, поэтому rollback требует остановки QR intake до возврата поддерживающей версии; после новых submissions таблицу не удалять. Runbook/restore/полный Alembic chain/HTTPS и выпуск — P0.7.
- Chromium viewport не равен приёмке реального Android/iOS. Durable queue, account switch, cold-start и полный ремонт с деталями/актом/историей остаются P0.4–P0.7.
- Последняя сверка main: `87e3044f30a40b6d0cff0306e71f9aee83aca329`, identical. P0.1–P0.3 находятся в draft PR; main и production не изменялись.

**Следующий этап: P0.4 — Technician result.** Проверить полный ремонт с исходными фото, работами, деталями, фото результата, актом и одной записью истории, доступной клиенту. Существующие исправления workflow и ACL служат базой; начинать только по следующей команде пользователя.


### 09.09.2026 — P0.4: начало и воспроизведение

- Main по-прежнему `87e3044f30a40b6d0cff0306e71f9aee83aca329`, изменений после последней сверки нет. База этапа: `e53412dd61ad6a92c546d15fae9b629cd479d5a7`, окончательный P0.3 CI [34276392491](https://github.com/acone87-arch/Fixit/actions/runs/34276392491): 266 passed, 0 skipped и 5 JS runtime файлов.
- Ветка P0.4: `codex/p0-4-technician-result`, зависит от несмерженных P0.1–P0.3. Main/deploy не затрагиваются.
- Подтверждено по коду: workspace использует Repair attachments вместо исходных фото; клиент не видит outcome/parts/result photos; клиентская equipment-card открывает форму заявки; legacy Repair с task/ticket подавляется в истории без canonical записи; пустой description допускается сервером; длинная диагностика Pulse передаётся в VARCHAR(100); conflict не показан в detail/UI.
- Reproduce: добавлены HTTP/PG и Chromium regression cases с полным результатом, запчастями, фото, PDF, повтором, конфликтом версии и legacy историей. Зелёный статус требует runtime приёмки после исправления.
- P0.6 остаётся владельцем общего stock hardening, включая StockMovement.repair_id и concurrent consumption. Здесь проверяется штатное списание/повтор в составе результата.

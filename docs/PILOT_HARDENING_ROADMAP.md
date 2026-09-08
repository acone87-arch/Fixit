# FIXIT PILOT READY — живой roadmap

Главный журнал доведения существующего Fixit 2.0 / Fixit Pulse до пилотной готовности. Обновлять этот файл, не создавать новый roadmap после каждого этапа. Историю решений и исправлений сохранять.

## Контрольная точка

- Репозиторий: `acone87-arch/Fixit`.
- Исходный документ: `Fixit_Audit_2026-09-07.md`, независимый аудит от 07.09.2026.
- Audit SHA: `80ec53e84402b24c3a8bb263d150e7bf7a0dd865`.
- Последняя сверенная main: `80ec53e84402b24c3a8bb263d150e7bf7a0dd865`.
- Последняя сверка: 08.09.2026; GitHub Compare `identical`, ahead/behind `0/0`, новых commits `0`, изменённых файлов `0`. GitHub commit lookup отдельно подтвердил HEAD.
- P0.1 выполнен и проверен в PR [№3](https://github.com/acone87-arch/Fixit/pull/3); проверенный SHA кода: `cde3d81a79b7f29efd17f65bac0538914a75ca1c`. Изменения ещё не в main и не в production.
- Текущий шаг: **P0.1 принят; остановка до команды на следующий этап**. Ветка `codex/p0-1-onboarding`; доказательства приёмки записаны ниже. Merge/deploy и P0.2 не начаты.
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
| P0.2 Security boundaries | 🔴 blocker | Global User, legacy/warehouse scope, Repair media write, legacy sync |
| P0.3 QR + ServiceRequest | 🔴 blocker | Повтор QR, approval, completed_at, конкурентный retry/номер |
| P0.4 Technician result | 🔴 blocker | Исходные фото и клиентский результат не доведены; полный E2E не подтверждён |
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

**Статус: 🔴 blocker. Исполнение не начато.**

**Definition of Done:** Organization A и Client A не могут читать или менять данные Organization B / Client B через основные или legacy API. Отзыв доступа действует сервером; общая учётная запись не позволяет администратору одного tenant отключить другой tenant. Доступ на чтение не даёт права менять ремонт.

| ID | Статус | Задача и актуальное основание |
|---|---|---|
| SEC-01 | 🔴 blocker | Разделить глобальный User и управление membership: текущий PATCH меняет глобальную активность; existing-email POST присоединяет аккаунт без согласия |
| SEC-02 | 🔴 blocker | Ограничить client-role чтение `/tasks`, `/warehouses`, stock и внутреннего parts API; tenant-only filter недостаточен для Client/Site |
| SEC-03 | 🔴 blocker | Разделить Repair media read/write; клиент и fleet-reader не должны дописывать чужой акт; delayed upload автора после completion сохранить |
| SEC-04 | 🔴 blocker | Закрыть бесконтекстный legacy sync; валидировать tenant/equipment/назначение Task и Ticket; разрешённые старые payload сохранить |
| SEC-05 | ⬜ не начато | Полная матрица cross-client/cross-tenant ACL, включая фото/PDF, arbitrary IDs, inactive/deleted memberships, pending invites после revoke |
| SEC-06 | ⬜ не начато | Проверить fail-closed Client/Site grants и multi-client поведение; не менять модель ролей без необходимости |

**Код:** `app/routers/users.py`, `tasks.py`, `warehouses.py`, `repairs.py`, `invites.py`, `app/services/access_policy.py`, `client_portal.py`, `sync_service.py`, `app/core/deps.py`.

**Доказательства:** HTTP+PG с двумя Organization, двумя Client в одном tenant, несколькими Sites, общим User; чтение и запись каждым role; valid/invalid legacy sync; отзыв и повтор с прежним JWT; авторский post-completion upload. Ownership локальной очереди принадлежит P0.5, совместная регрессия обязательна.

**Миграция:** основные ACL-исправления обычно без неё; ограничения grants/FK — по результату Verify данных. **Риск:** высокий, возможен ошибочный запрет старых клиентов или досылки фото.

## P0.3 — QR + ServiceRequest

**Статус: 🔴 blocker. Исполнение не начато.**

**Definition of Done:** повтор QR не падает и не создаёт некорректных дублей; одна бизнес-поломка проходит существующий ServiceRequest workflow. Approval и completion работают, время завершения фиксируется, повтор sync возвращает согласованный результат без нового canonical Repair.

| ID | Статус | Задача и актуальное основание |
|---|---|---|
| SR-01 | 🔴 blocker | Повтор QR с активной заявкой и новым ключом: неимпортированный TicketStatus, NameError |
| SR-02 | 🔴 blocker | `max(number)+1` не сериализован между разными Equipment tenant; нужен безопасный конкурентный номер/повтор |
| SR-03 | ⬜ не начато | Same key, response loss, другой QR с прежним ключом; guest client_id, partial retry и старые NULL client_id. Не переписывать уже работающий частичный retry |
| SR-04 | 🔴 blocker | UI отправляет details.approval без approval_target; 422. Сохранить необходимое содержание согласования |
| SR-05 | 🔴 blocker | Client approval: LEFT OUTER JOIN + общий FOR UPDATE; проблемный SQL скомпилирован в аудите, фактическое исполнение на PG ещё требуется |
| SR-06 | 🔴 blocker | completed_at не заполняется на completed; исключение из 30-дневной сводки |
| SR-07 | 🔴 blocker | Повтор sync после ожидания row lock не перепроверяет SyncOperation; возможен ошибочный ответ вместо already_synced |
| SR-08 | ⬜ не начато | Прямой API не закрывает SR без Repair; waiting_parts, internal/client approval/reject, cancellation, версии Equipment и несколько активных SR дают согласованный результат |

**Код:** `app/routers/tickets.py`, `service_requests.py`, `client_portal.py`, `app/services/service_requests.py`, `service_request_workflow.py`, `sync_service.py`, guest upload/UI, Pulse approval payload.

**Доказательства:** реальные PG-транзакции двух обращений/двух sync; настоящий UI payload; полный переход с approve/reject; запрет status bypass; guest response loss и photo retry. Не приравнивать автоматически все разные неисправности одного Equipment к одной поломке — сохранять подтверждённую продуктовую семантику.

**Миграция:** возможно data migration completed_at по надёжным Repair/events; неоднозначные старые даты не придумывать. Нумерация не обязательно требует новой модели. **Риск:** высокий — canonical lifecycle и старые данные.

## P0.4 — Technician result

**Статус: 🔴 blocker. Исполнение не начато.**

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

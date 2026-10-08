# Fixit 2.0 / Fixit Pulse — устранение F01, этап 1

Дата: 2026-10-09. Репозиторий: `acone87-arch/Fixit`.
Ветка: `codex/fixit-webpush-ssrf-p1`, база `origin/main` — `7d3bf1896286bb7b5a7c58f0b1fb322a9cdbfbd5`.
Проверяемый runtime SHA: `0f3a08d38642118ba5f709e446b0815127b8323e`. Дополнительный pytest gate для JS lifecycle: `3fef2cff63b948ed56a5902b2f8fe6497af061c9`; runtime не изменён.
PR: [#22 — security: harden Web Push endpoint validation and bounded delivery](https://github.com/acone87-arch/Fixit/pull/22), **Draft, без merge/deploy**.

## 1. Подготовка и F09

Прочитаны полный исходный аудит, `AGENTS.md`, `GLOSSARY.md`, четыре project-local skills, domain/runbook/workflows и инструкции Matt Pocock. Исходный аудит сохранён в worktree `.codex-worktrees/fixit-engineering-audit/docs/audits/FIXIT_SECURITY_AUDIT_2026-10-08.md`; чужие untracked файлы не включены в F01. `codex plugin list` подтвердил `mattpocock-skills@mattpocock`, installed/enabled, **1.3.1**. Применены diagnosing-bugs, tdd, code-review, fixit-security, fixit-release, fixit-mobile-qa; для инструкций/PR также writing-for-agents и pr.

Главная папка была на `codex/equipment-qr-reprint`, с пользовательскими untracked файлами. Существующий audit worktree также содержал untracked результаты. Ни один из них не переключался и не очищался. Созданы отдельные worktrees F09, F01 и baseline. `git fetch origin` подтвердил актуальную базу; инструкции из PR #21 не переносились в runtime-ветку F01.

F09 исправлена отдельным **docs-only коммитом `bc74508`** в [Draft PR #21](https://github.com/acone87-arch/Fixit/pull/21). Изменены `AGENTS.md`, `.agents/skills/fixit-mobile-qa/SKILL.md`, связанная карта в `fixit-feature` и `docs/agents/domain.md`. Проверены frontmatter четырёх skills и буквальные пути к source/tests/docs. PR description обновлён.

Сверено с `app/main.py`: активный Pulse — `app/static/`, офлайн-логика — `app/static/offline/`; `app/static-tech/` не монтируется и сохранён для compatibility/rollback. `/tech` и legacy paths ведут в `/#requests`; `/tech/sw.js` отдаёт совместимый offline worker. **Коммит F09 не меняет runtime/PWA.** В F01 есть отдельное минимальное изменение VAPID lifecycle и версий активного shell, описанное ниже.

## 2. Docker, WSL и изолированный PostgreSQL

Windows sandbox не мог запустить даже `git status`: `helper_unknown_error: setup refresh had errors`. Резервный Node REPL также аварийно завершался. Разрешённый терминальный запуск вне неисправного sandbox работал; системные настройки не менялись.

- Docker Desktop процессы отвечают, но Docker Engine недоступен. `docker info` и explicit contexts `default`/`desktop-linux` не ответили в ограниченные интервалы 12–15 s. `docker desktop start` возвращает «already running»; штатный запуск `Docker Desktop.exe` не восстановил движок.
- Context `desktop-linux` выбран; `default` — `npipe:////./pipe/docker_engine`, Desktop — `npipe:////./pipe/dockerDesktopLinuxEngine`. Глобальный context не переключался. `docker compose version` работает: **v5.3.0**; это не подтверждение работающего Engine/compose services.
- WSL **2.7.10.0**, kernel **6.18.33.2-2**, default version 2. Единственный зарегистрированный `docker-desktop` — **Stopped**; WSLService работает, com.docker.service остановлен.
- Последний зафиксированный сбой старта backend в Docker log от 2026-10-08: `initializing Inference manager ... dockerInference ... The file cannot be accessed by the system ... listener: The filename, directory name, or volume label syntax is incorrect`. Лог согласуется с незапущенным движком; повторного успешного старта не обнаружено.
- Финальная проверка вернула конкретное отсутствие `dockerDesktopLinuxEngine` named pipe. Дополнительный штатный `docker desktop restart --timeout 60` завис сверх собственного timeout; остановлен только идентифицированный CLI plugin этой команды, Desktop/backend/WSL/data принудительно не завершались. Engine не восстановлен. Для следующего шага предлагается отдельное окно обслуживания Desktop/Inference runtime с vendor diagnostics; reset/WSL reconfiguration/обновление Desktop без согласования не выполнялись.
- Reset, удаление socket/volumes/контейнеров, WSL unregister/shutdown, обновление Desktop и изменение системных настроек не выполнялись. Возможное восстановление Desktop требует отдельной диагностики Inference manager/Windows socket и согласования действий, влияющих на другие проекты.

Альтернатива восстановлена: **настоящий PostgreSQL 16.15**, официальный portable ZIP EDB, без installer/system service. Источники: [PostgreSQL Windows](https://www.postgresql.org/download/windows/), [EDB binaries](https://www.enterprisedb.com/download-postgresql-binaries). Архив `postgresql-16.15-1-windows-x64-binaries.zip`, SHA256 `25e6fcdfb8caec38691bf461125e7564508760666f7b8e5dc6a5f0818f58f81e` (локально вычислен; не выдаётся за отдельно опубликованный vendor checksum).

Cluster/binaries находятся в `.codex-worktrees/fixit-f01-tools/`, слушает **только `127.0.0.1:65432`**. Отдельный пользователь `fixit_f01`, случайный локальный пароль вне Git, SCRAM. Созданы `fixit_f01_test` и первоначально пустая `fixit_f01_migrations_test`. `SELECT version()` подтвердил 16.15. Для API integration fixtures создаются отдельные schemas со случайными именами; удаляются только их собственные синтетические schemas. Production URL/данные не читались. Параметры VAPID/SMTP тестового процесса отключены.

При старте `pg_ctl` диагностический Python harness завис на inherited pipes уже запущенного сервера; готовность проверена прямым asyncpg, затем остановлен только собственный harness. PostgreSQL остался работающим. Все cluster/data/архивы сохранены.

## 3. Root cause и путь F01

`PushSubscriptionIn.endpoint` проверял только длину. `/api/push/subscribe` сохранял адрес активного авторизованного пользователя. `_send` передавал сохранённый URL в `pywebpush.webpush`, тот — в `requests.post`, по умолчанию следовавший redirects. Проверок провайдера, специального IP, DNS pinning и конечного timeout не было.

Версии исследованного окружения: pywebpush **2.0.3**, requests **2.34.2**, urllib3 **2.8.0**, asyncpg **0.29.0**. Pins приложения не обновлялись. Исходник pywebpush подтвердил `webpush(timeout=None)` и возможность передать `requests_session`; явный tuple timeout передаётся в `.post` без изменения.

Предпосылки: настроенный VAPID, активная учётная запись и уведомление, адресованное этому пользователю. Подтверждён **blind SSRF**, включая loopback; чтение внутренних ответов/эксфильтрация не утверждаются. Доставка ожидалась после успешных бизнес-коммитов в назначении, согласовании и repair sync; зависание удерживало HTTP handler и thread pool, хотя бизнес-запись уже сохранена.

Первое воспроизведение: failing regression на `http://127.0.0.1/push`. Второе: настоящий sender/шифрование/VAPID с синтетическими EC-ключами и перехватом HTTP до сокета — unsafe сохранённый endpoint дошёл в `requests.post`, `timeout=None`. Итоговый baseline прогон использует исходные schema/service из `origin/main` и запрещённую реальную сеть; дополнительные transport helpers присутствуют только для импорта тестов и исходным sender не используются. Их наличие не меняет проверенный исходный runtime.

## 4. Реализованная защита

| Файлы | Поведение |
| --- | --- |
| `app/services/push_endpoint.py`, `app/schemas/push.py` | Только HTTPS, стандартный 443, ASCII authority, без userinfo/control/backslash/fragment, числовых и альтернативных IP-форм, произвольных provider domains; ограничение длины. p256dh — реальная точка P-256, auth — 16 bytes, ограниченные base64url-ключи. |
| `app/services/push_transport.py` | Проверяет **все** DNS-ответы, отклоняет special/mixed addresses, IPv4-mapped/6to4/Teredo/NAT64 и не-global-unicast IPv6. Соединение открывается к проверенному **числовому IP**, исходные Host/SNI/hostname сохраняются; CA verification обязательна. Нет повторного разрешения исходного hostname при connect. Redirects/retries/environment proxies запрещены. |
| `app/services/push_service.py` | Повторная URL/DNS-проверка при доставке, в том числе старых сохранённых подписок. Connect/read **2/3 s**, response body не читается. Общий async budget **2 s** на notification/fanout; максимум **4 outstanding jobs на процесс**, без backlog. Работающий после deadline поток удерживает слот до завершения. Sender получает snapshot, независимый от закрытия ORM session. |
| `app/routers/push.py` | Максимум 10 сохранённых подписок пользователя, User row lock для конкурентной регистрации. Renewal текущего endpoint разрешён на лимите. При новой регистрации освобождается одна явно inactive запись; active devices не удаляются. Unsubscribe допускает старый unsafe endpoint, оставаясь user/tenant-scoped. |
| `app/static/app.js` | При изменении VAPID public key сначала server unsubscribe старого endpoint, затем browser unsubscribe/new subscribe. При ошибке API старая браузерная подписка сохраняется. |
| `app/static/index.html`, `sw.js`, `offline/engine.js`, `offline/sw.js` | Согласованные asset/worker versions `20261009-1`, shell cache v22. IndexedDB schema, queues и payload formats сохранены; `app/static-tech/` не изменён. |

Notification DB work выполняется в **отдельной AsyncSession**: SQL cancellation/cleanup commit errors не повреждают исходную бизнес-сессию и уже сохранённый batch. Сбой push не превращается в отмену успешной операции. Логи содержат только subscription UUID/тип исключения, без URL capability, auth/p256dh/VAPID, payload, email или фото.

Allowlist основан на первичных источниках, а не произвольном suffix matching: `fcm.googleapis.com`, `updates.push.services.mozilla.com`, корректные subdomains `*.push.apple.com`, `*.notify.windows.com`.

- [Google: Web Push subscription endpoint](https://web.dev/articles/codelab-notifications-push-server).
- [Mozilla: production Autopush endpoint](https://autopush.readthedocs.io/en/stable/index.html).
- [Apple: sending standards-based Web Push](https://developer.apple.com/documentation/usernotifications/sending-web-push-notifications-in-web-apps-and-browsers).
- [Microsoft: WNS endpoint domain](https://learn.microsoft.com/en-us/windows/apps/develop/notifications/push-notifications/wns-overview).
- [urllib3: custom SNI / connecting to a numeric address](https://urllib3.readthedocs.io/en/stable/advanced-usage.html).

Один preflight DNS lookup без pinning не считался достаточной защитой; адрес закреплён на уровне используемого connection pool. При неизвестном провайдере/некорректном DNS/redirect доставка прекращается. Старые unsafe подписки деактивируются при попытке доставки; прямого изменения live subscriptions во время этой работы не выполнялось.

## 5. Проверки и доказательства

Локальный harness `.hardening/run.py` задаёт только синтетические env, loopback PostgreSQL URL, `FIXIT_RUN_BROWSER=1`, testserver allowlist, `PYTHONDONTWRITEBYTECODE=1`, UTF-8 и redaction случайного test password. Raw JUnit/logs лежат в F01 worktree `test-results/`, в Git включается только отчёт/санитизированная сводка. Mock sender tests не используются как доказательство PostgreSQL.

| Проверка | Фактический результат | Артефакт |
| --- | --- | --- |
| Первый registration regression ДО | 1 failed | `f01-red-registration.xml` |
| Saved unsafe sender ДО | 1 failed, 1 passed, HTTP перехвачен, timeout=None | `f01-red-saved.xml` |
| Некорректные/чрезмерные keys ДО | 3 failed | `f01-red-keys.xml` |
| Итоговый набор на исходных schema/service | **60 failed, 9 passed** | `f01-red-baseline.xml`, `.log` |
| Security regression ПОСЛЕ | **69 passed, 0 failed/skipped** | `f01-security.xml` |
| Targeted Web Push/PWA + настоящий PostgreSQL после review | **89 passed, 0 failed/skipped** | `f01-push-pwa-final.xml`, `.log` |
| JWT/ACL/security + настоящий PostgreSQL | **87 passed, 0 failed/skipped** | `f01-security-acl.xml`, `.log` |
| Review regression SQL cancellation ДО | **1 failed**, настоящий `PendingRollbackError` после pg_sleep cancellation | `f01-red-session.xml` |
| Review fixes PG targeted ПОСЛЕ | **2 passed**, cancellation isolation + budget/rotation | `f01-green-session.xml` |
| Profile Chromium → HTTP → PG, 390×844 и 1440×1000 | **2 passed**; PushManager синтетический | `f01-profile-browser.xml` |
| JS lifecycle | **4 сценария PASS**: rotation at capacity, renewal, disable, unavailable API; до исправления rotation assertion FAILED | `tests/push_subscription_runtime_test.js` |
| Полный Python + PG + Chromium, Windows | **405 passed, 8 failed, 3 skipped**; 1604 s | `f01-full.xml`, `.log` |
| Повтор всех 8 Windows failures с коротким basetemp | **8 passed, 0 failed/skipped**, 60 s; runtime не изменён | `f01-windows-retry.xml`, `.log` |
| Windows path на исходном origin/main | длинный basetemp: **1 failed**; короткий: **1 passed** | `f01-baseline-windows-path-v2.xml`, `f01-baseline-windows-path-short.xml` |
| Полный Python + PG + Chromium, Linux CI, runtime SHA | **416 passed, 0 failed/skipped**, 275 s | CI `37835334346`, `release.xml` |
| Полный Python + PG + Chromium, Linux CI, final code/test SHA | **417 passed, 0 failed/skipped**, 376 s | CI `37844084658`; дополнительный JS wrapper включён |
| Новый JS lifecycle в стандартном pytest gate | **1 passed**, 4 JS-сценария; включён в оба существующих workflow без их изменения | `f01-runtime-gate.xml` |
| Clean Alembic upgrade, PostgreSQL 16.15 | **PASS**, пустая БД → `20261002_0018 (head)`, 31 таблица | `f01-alembic-clean.log` |
| JavaScript runtime | **6/6 наборов PASS**, включая новый Push lifecycle | `f01-js-*.log` |
| Настоящие Chromium IndexedDB / Service Worker | **16/16 сценариев PASS** | `f01-idb-sw.log` |
| Request queue Chromium | **PASS**: sorting, filters, reload, navigation, client tabs, responsive | `f01-request-queue.log` |
| Contrast / совместимость shell | **298 экранов, 0 failures** | `f01-theme-contrast.log`, `theme-contrast.json` |
| Backup restore drill в Linux CI | **PASS**: 3 таблицы, 2 media-файла, SHA256 checks | CI `37835334346` |
| `pip check` | **PASS**, broken requirements отсутствуют | `f01-pip-check.log` |
| `npm audit --prefix tests --json` | **exit 1**, 1 high advisory Playwright; обновления не выполнялись | `f01-npm-audit.log` |
| pip-audit прямых production pins | **exit 1**, 38 advisory entries в 2 packages, 20 уникальных IDs, проверено 16 packages | `f01-pip-audit-direct.json` |
| pip-audit установленного venv, включая transitive/dev/tools | **exit 1**, 153 advisory entries в 7 packages, 84 уникальных IDs, проверен 101 package | `f01-pip-audit-installed.json`, `f01-pip-audit-summary.json` |

Основные команды (пароль только через локальный process env):

```text
python -B -m pytest -q tests/test_push_endpoint_security.py
python -B -m pytest -q tests/test_push_endpoint_security.py tests/test_push_events_postgres.py tests/test_pwa_push_foundation.py
python -B -m pytest -q tests/test_security_postgres.py tests/test_http_origin_security.py tests/test_client_portal_security.py tests/test_media_security.py tests/test_technician_access_policy.py tests/test_client_access_management.py tests/test_user_deactivation.py
python -B -m pytest -q --basetemp=.hardening/tmp-full --junitxml=test-results/f01-full.xml
python -B -m alembic upgrade head
node tests/push_subscription_runtime_test.js
python -B -m pytest -q tests/test_push_subscription_runtime.py
node tests/onboarding_equipment_runtime_test.js
node tests/pulse_offline_engine_runtime_test.js
node tests/technician_workflow_runtime_test.js
node tests/offline_attachment_sync_runtime_test.js
node tests/guest_photo_upload_runtime_test.js
node tests/durable_queue_browser_test.js
node tests/request_queue_browser_test.js
node tests/theme_contrast_browser_test.js
python -B -m pip check
npm audit --prefix tests --json
python -B -m pip_audit -r requirements.txt --disable-pip --no-deps -f json
python -B -m pip_audit --path <application-venv>/Lib/site-packages -f json
```

69 security cases включают localhost/HTTP/private/loopback/link-local/IPv6/числовые обходы/userinfo/ports/provider spoofing/control chars; special/mixed DNS, DNS rebinding pinning, 301/302/303/307/308 на внутренний Location без follow, явные timeouts, медленный/недоступный endpoint, старую unsafe подписку, saturation/no backlog и допустимые provider URLs. Сеть synthetic tests запрещена автоматически.

Ошибки harness учтены: первый расширенный baseline harness завершился timeout 40 s. В нём один путь исходного sender не был полностью закрыт mock/общим network guard; поэтому **нельзя подтвердить отсутствие попытки реального сетевого вызова в этом отброшенном запуске**. Это отклонение от требования полной mock-изоляции, а не доказательство безопасного воспроизведения. Фактический сетевой запрос/получение данных этим запуском не установлены; production targets/credentials не использовались. Повтор выполнен с безусловным network guard и отдельным baseline worktree; только его **60 failed / 9 passed** используются как итоговое red evidence. Guard блокирует requests, urllib3 и DNS до сокета, а разрешённые тестовые вызовы перехватываются mocks.

Первый новый profile test ожидал неправильное состояние после сброса synthetic fixture при reload (2 failed); ожидание исправлено на «Уведомления выключены», затем 2 passed. Печать Playwright diagnostics обнаружила cp1251 UnicodeEncodeError; harness переведён на UTF-8. Эти первые попытки не скрыты и не выдаются за успех.

### Разбор локального полного прогона

Вложенный `--basetemp=.hardening/tmp-full` дал media paths длиной **274–275 символов**. Четыре traceback явно содержат `FileNotFoundError` на записи фото, остальные failures — HTTP 500 либо дальнейшие UI-ожидания. Безопасный синтетический probe подтвердил ограничение Windows: обычный файл с путём 280 символов — `FileNotFoundError`, тот же с extended prefix — PASS, короткий — PASS. Системные параметры LongPaths не менялись.

На неизменённом `origin/main` `test_guest_photo_partial_retry_and_legacy` воспроизвёл HTTP 500 с длинным basetemp (**1 failed**) и прошёл с коротким (**1 passed**). Первоначальный baseline probe дал **1 setup error** из-за отсутствия собственного `.hardening/`; каталог создан, первый артефакт сохранён. Все восемь исходных failures повторены с коротким workspace basetemp `.t-f01-retry`: **8 passed**. Это отдельный повтор; исходный полный Windows результат не переименовывается в чистый PASS. Linux CI выполнил весь набор без skips. Новый JS wrapper отдельно дал 1 passed и запускается в последующем CI.

Повторены: `test_client_filters_search_and_authenticated_problem_photo`, `test_new_site_batch_pdf_mobile_scan_fill_retry_and_next`, `test_pulse_approval_payload_and_dispatcher_result[client]`, `test_guest_photo_partial_retry_and_legacy`, `test_concurrent_guest_photo_retry_and_foreign_qr`, `test_technician_sees_original_guest_photo`, `test_client_opens_passport_and_complete_result[True]`, `test_pulse_long_diagnosis_parts_photo_completion_and_reload`.

### Dependency audit

Прямые findings повторяют F07: python-jose 3.3.0 и Pillow 10.4.0. Полный установленный venv также содержит findings для ecdsa, pip, pypdf, pytest и Starlette. Installed scan включает dev/tooling и не равен production dependency graph контейнера. Количество advisory entries содержит дубликаты/aliases и не означает столько подтверждённых путей эксплуатации Fixit. Полный JSON сохранён; applicability и обновления требуют отдельного F07 scope, pins/lockfiles в F01 не менялись.

Тестовый Playwright 1.55.0: [GHSA-7mvr-c777-76hp](https://github.com/advisories/GHSA-7mvr-c777-76hp), исправлен в 1.55.1. Здесь использовался Chromium; уязвимый macOS Chrome/Edge installer path не запускался. Изолированный ранее установленный pip-audit 2.10.1 использован без `--fix` и без dependency resolution. Wrapper завершился 0 после сохранения обоих результатов; **это не PASS аудита** — оба scanner exit code равны 1.

### GitHub CI

На runtime `0f3a08d` прошли оба workflow: [release/PG/browser/backup restore](https://github.com/acone87-arch/Fixit/actions/runs/37835334346) и [pilot acceptance](https://github.com/acone87-arch/Fixit/actions/runs/37835334341). Release pytest: **416 passed, 0 failed/skipped**. Deploy job **skipped**: PR event не удовлетворяет условию push/main. Внешние deploy команды не выполнялись.

CI дополнительного regression gate `3fef2cf`: [release](https://github.com/acone87-arch/Fixit/actions/runs/37844084658), [pilot](https://github.com/acone87-arch/Fixit/actions/runs/37844084655) — **оба success**, release pytest **417 passed, 0 failed/skipped**; JS/IDB/SW, 298 contrast screens и backup restore также PASS, deploy skipped. CI последнего docs-only HEAD дополнительно фиксируется в PR; runtime/test code соответствует указанным SHA.

## 6. Статус 162 прежних skips

Исходный JUnit: **138 PostgreSQL/Alembic**, **21 browser**, **3 Linux deploy shell**. Сопоставление по `(classname, name)` с настоящим Linux CI JUnit подтвердило: **все 162 ранее skipped сценария теперь passed, missing/failed/skipped — 0**. Локальный PG/Chromium восстановлены; Windows имеет 3 явных Linux shell skips, выполненных в CI. Восемь локальных media/UI failures устранены коротким test path и проверены отдельным повтором, а не скрыты через skip.

## 7. Независимый code-review

Проверки выполнены двумя отдельными агентами по `code-review`/`fixit-security`, fixed base `7d3bf18`; scope — весь F01 diff, проектные стандарты и запрос пользователя. Агенты не меняли файлы и не запускали PG-тесты одновременно с основным gate.

### Standards

Первый review: **2 P2** — лимит inactive history и invalidation общей AsyncSession при cancellation. Оба исправлены; cancellation подтверждена настоящим PostgreSQL red→green тестом. Повторный review на `0f3a08d`: **0 открытых подтверждённых дефектов**, значимых Fowler smells нет. Проверены DNS/IP/TLS, redirects, endpoint/keys, concurrency, error paths, business call sites и PWA version consistency.

Ограничения: вложенные notification wrappers открывают дополнительные DB sessions; системный DNS/работающий поток не прерывается async deadline, но outstanding sends ограничены четырьмя. Это best-effort, не guaranteed delivery.

### Spec

Первый review: **1 P2** — historical budget ломал новый endpoint/rotation; дополнительно предложена PG cancellation проверка. Budget reclaim и server unsubscribe перед VAPID rotation исправлены и покрыты тестами. Повторный review на `0f3a08d`: **0 открытых находок**, scope creep не обнаружен, подтверждённого обхода F01 в просмотренном diff нет. Full gate и Safari/iOS не считаются доказанными по targeted тестам. Дополнительные проверки нового pytest/JS wrapper (Standards) и итогового отчёта/JSON (Spec) также завершились без замечаний.

## 8. Остаточные риски и следующий этап

1. Доставка best-effort: budget/saturation может пропустить событие; работающий thread/DNS сохраняет слот до завершения. Connect/read timeout не является общей гарантией wall-clock для системного DNS. Число таких workers ограничено 4 на процесс, а business handler имеет отдельный deadline.
2. Дополнительные notification sessions потребляют connection pool. При высокой нагрузке возможен пропуск push в пределах budget. Нужны отдельно согласованные outbox/ограниченная очередь, retry/deduplication, срок жизни события и метрики. Новая инфраструктура не внедрялась.
3. Allowlist намеренно закрытый; появление нового provider требует проверки официальной документации и regression. Реальная доставка провайдерами/физический Safari/iOS не тестировались. Синтетический PushManager доказывает lifecycle/API, а не APNs/FCM доставку.
4. Лимит 10 устройств — новый ресурсный предел; существующие endpoint сохраняют renewal, inactive slots освобождаются, active devices не удаляются при регистрации. При более 10 исторически активных устройствах отправка ограничена 10 последними. Перед выпуском нужен отдельный сценарий принятия этого предела, без чтения live данных данным агентом.
5. Docker Engine локально остаётся неисправным; portable PG не доказывает локальный Docker restore drill. Сам restore drill прошёл в Linux CI. F02–F08 и dependency advisories не исправлялись в этом узком PR.

## 9. Приёмка и безопасный выпуск

**Вердикт: NO-GO для выпуска; PR #22 остаётся Draft.** Исправление F01 подтверждено red→green regression, настоящим PostgreSQL, Chromium и независимыми review. Автоматические functional/security gates runtime прошли в Linux CI; Windows failures разобраны и повторены успешно. Для выпуска нужны ручная приёмка provider/browser delivery и нового subscription budget, решение по известным dependency advisories вне F01 и GO ответственного за выпуск. CI последнего docs-only HEAD фиксируется в PR. Создание PR не означает разрешение merge/deploy.

До любого выпуска: полный PG/Chromium/JS gate и CI точного final SHA, разбор всех failed/skipped, проверка synthetic provider devices/VAPID rotation, backup/restore evidence и rollback по runbook; отдельное ручное GO. Миграций/новых инфраструктурных зависимостей нет. При rollback вернуть предыдущий application image, не стирать IndexedDB/DB/media и не выполнять Alembic downgrade. Merge/main push запускает deploy; merge/deploy/VPS/nginx/production DB/live subscriptions не изменялись.

F09 — исправлена в PR #21. F01 — реализована и проверена в отдельном Draft PR #22. PostgreSQL test environment — восстановлено; Docker blocker — точно зафиксирован. Пользовательские файлы, Docker volumes, production DB и реальные подписки не менялись. Санитизированные числа и соответствие старых skips сохранены рядом в `FIXIT_SECURITY_F01_TEST_RESULTS.json`; raw logs/JUnit остаются в изолированном worktree, CI artifacts доступны по приведённым ссылкам.

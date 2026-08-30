from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.routers import auth, client_portal, customers, equipment, organizations, repairs, service_requests, sync, tasks, tickets, users, warehouses

app = FastAPI(title="Service & Warehouse Management API", version="0.1.0")

# В проде сузить до конкретных origin (админ-панель, домен мобильного PWA).
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(organizations.router)
app.include_router(customers.router)
app.include_router(customers.sites_router)
app.include_router(users.router)
app.include_router(equipment.router)
app.include_router(equipment.types_router)
app.include_router(tasks.router)
app.include_router(warehouses.router)
app.include_router(warehouses.parts_router)
app.include_router(tickets.public_router)
app.include_router(tickets.admin_router)
app.include_router(sync.router)
app.include_router(repairs.router)
app.include_router(service_requests.router)
app.include_router(client_portal.router)


@app.get("/health", tags=["meta"])
async def health():
    return {"status": "ok"}


@app.get("/e/{qr_token}", tags=["meta"])
async def qr_redirect(qr_token: str):
    """Физическая QR-наклейка на оборудовании кодирует именно этот URL (см.
    services→equipment_qr). Гость сканирует её обычной камерой телефона —
    сюда попадает без авторизации и уходит на гостевую страницу заявки."""
    # Версия в URL не даёт мобильному браузеру повторно использовать
    # закэшированную гостевую страницу со старой логикой idempotency.
    return RedirectResponse(
        url=f"/guest/?token={qr_token}&v=20260829-1",
        headers={"Cache-Control": "no-store"},
    )


# StaticFiles(html=True), смонтированный на "/tech" или "/guest", отдаёт
# index.html только по пути СО слэшем на конце ("/tech/"). Без него запрос
# всё равно попадает в примонтированное приложение (совпадение по префиксу),
# но там такого файла нет — 404. Ловим оба случая явными редиректами,
# зарегистрированными раньше самих mount() ниже.
@app.get("/tech", include_in_schema=False)
async def tech_redirect():
    return RedirectResponse(url="/#requests", status_code=307)


@app.get("/tech/{legacy_path:path}", include_in_schema=False)
async def legacy_tech_redirect(legacy_path: str):
    """The legacy shell stays in the repository for rollback only.

    Fixit Pulse is the single technician product; the shared offline engine
    keeps the same IndexedDB repair/attachment queue before this redirect.
    """
    return RedirectResponse(url="/#requests", status_code=307)


@app.get("/guest", include_in_schema=False)
async def guest_redirect():
    return RedirectResponse(url="/guest/")


# Примечание: таблицы создаются через Alembic-миграции (см. README), а не через
# Base.metadata.create_all в lifespan — это единственный источник правды о схеме
# и для локальной разработки, и для прода.

# /tech routes are redirects only. app/static-tech remains in the repository
# for rollback for now, but is deliberately not mounted or runnable in prod.

# Гостевая страница заявки — без авторизации, открывается по QR (см. /e/{qr_token} выше).
app.mount("/guest", StaticFiles(directory="app/static-guest", html=True), name="guest-frontend")

# Веб-панель администратора — статика, смонтирована последней, чтобы не
# перехватывать /api/*, /docs, /tech/* и /guest/*. html=True отдаёт index.html
# на "/" и на неизвестные пути (частая надобность для SPA с client-side роутингом).
app.mount("/static", StaticFiles(directory="app/static"), name="static-assets")
app.mount("/", StaticFiles(directory="app/static", html=True), name="frontend")

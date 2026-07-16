from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.routers import auth, equipment, sync, tasks, tickets, users, warehouses

app = FastAPI(title="Service & Warehouse Management API", version="0.1.0")

# В проде сузить до конкретных origin (админ-панель, домен мобильного PWA).
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(users.router)
app.include_router(equipment.router)
app.include_router(equipment.types_router)
app.include_router(tasks.router)
app.include_router(warehouses.router)
app.include_router(warehouses.parts_router)
app.include_router(tickets.public_router)
app.include_router(tickets.admin_router)
app.include_router(sync.router)


@app.get("/health", tags=["meta"])
async def health():
    return {"status": "ok"}


# Примечание: таблицы создаются через Alembic-миграции (см. README), а не через
# Base.metadata.create_all в lifespan — это единственный источник правды о схеме
# и для локальной разработки, и для прода.

# Веб-панель администратора — статика, смонтирована последней, чтобы не
# перехватывать /api/* и /docs. html=True отдаёт index.html на "/" и на
# неизвестные пути (частая надобность для SPA с client-side роутингом).
app.mount("/static", StaticFiles(directory="app/static"), name="static-assets")
app.mount("/", StaticFiles(directory="app/static", html=True), name="frontend")

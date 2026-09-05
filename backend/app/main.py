from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.database import Base, SessionLocal, engine, migrate_job_columns
from app.routers import jobs, knowledge, lexicon, profiles, settings as settings_router, sites
from app.services.seed import seed_defaults
from app.services.sensevoice import start_sensevoice_prefetch
from app.services.settings_store import load_settings, migrate_settings_defaults


@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(bind=engine)
    migrate_job_columns()
    transcribe_model = ""
    db = SessionLocal()
    try:
        seed_defaults(db)
        migrate_settings_defaults(db)
        transcribe_model = load_settings(db).transcribe_model
    finally:
        db.close()
    start_sensevoice_prefetch(transcribe_model)
    yield


app = FastAPI(title=settings.app_name, lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[item.strip() for item in settings.cors_origins.split(",") if item.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(profiles.router)
app.include_router(sites.router)
app.include_router(settings_router.router)
app.include_router(lexicon.router)
app.include_router(jobs.router)
app.include_router(knowledge.router)


@app.get("/api/health")
def health() -> dict:
    return {"ok": True, "name": settings.app_name}


def _mount_frontend(application: FastAPI) -> None:
    static = settings.resolved_static_dir()
    if static is None:
        return
    assets = static / "assets"
    if assets.exists():
        application.mount("/assets", StaticFiles(directory=assets), name="assets")

    @application.get("/{full_path:path}")
    def spa(full_path: str):
        candidate = static / full_path
        if full_path and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(static / "index.html")


_mount_frontend(app)

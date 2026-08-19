from pathlib import Path
import os

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from .config import settings
from .db import ensure_schema
from . import models  # noqa: F401
from .routers_auth import router as auth_router
from .routers_catalog import router as catalog_router
from .routers_more import router as more_router
from .routers_ops import router as ops_router
from .routers_pos import router as pos_router

ensure_schema()

WEB_DIR = Path(__file__).parent / "web"
ASSETS_DIR = os.path.normpath(str(WEB_DIR / "assets"))

app = FastAPI(title=settings.app_name, version="0.1.0")
origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins or ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(catalog_router)
app.include_router(pos_router)
app.include_router(ops_router)
app.include_router(more_router)


@app.get("/api/health")
def health():
    return {"ok": True, "service": "FINEX-POS"}


@app.get("/assets/{file_path:path}")
def assets(file_path: str):
    full = os.path.normpath(os.path.join(ASSETS_DIR, file_path))
    if full != ASSETS_DIR and not full.startswith(ASSETS_DIR + os.sep):
        raise HTTPException(404)
    if not os.path.isfile(full):
        raise HTTPException(404)
    return FileResponse(full)


@app.get("/")
def home():
    return FileResponse(str(WEB_DIR / "index.html"))

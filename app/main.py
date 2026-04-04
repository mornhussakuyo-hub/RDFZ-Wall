from __future__ import annotations

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from .config import SECRET_KEY, SESSION_COOKIE_NAME, SITE_NAME, STATIC_DIR
from .db import initialize_database
from .routers import admin, public


initialize_database()

app = FastAPI(title=SITE_NAME)
app.add_middleware(
    SessionMiddleware,
    secret_key=SECRET_KEY,
    session_cookie=SESSION_COOKIE_NAME,
    same_site='lax',
    https_only=False,
)
app.mount('/static', StaticFiles(directory=str(STATIC_DIR)), name='static')
app.include_router(public.router)
app.include_router(admin.router)

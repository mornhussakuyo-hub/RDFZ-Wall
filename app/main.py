from __future__ import annotations

import logging
import sys

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from .config import SECRET_KEY, SESSION_COOKIE_NAME, SITE_NAME, STATIC_DIR
from .db import initialize_database
from .routers import admin, public


def configure_app_logging() -> None:
    uvicorn_logger = logging.getLogger('uvicorn.error')
    app_logger = logging.getLogger('app')
    app_logger.handlers.clear()
    if uvicorn_logger.handlers:
        for handler in uvicorn_logger.handlers:
            app_logger.addHandler(handler)
    else:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(logging.Formatter('%(levelname)s:%(name)s:%(message)s'))
        app_logger.addHandler(handler)
    app_logger.setLevel(logging.INFO)
    app_logger.propagate = False


initialize_database()
configure_app_logging()

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

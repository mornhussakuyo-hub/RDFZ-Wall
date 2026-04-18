from __future__ import annotations

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import DATABASE_URL


class Base(DeclarativeBase):
    pass


connect_args = {'check_same_thread': False} if DATABASE_URL.startswith('sqlite') else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def initialize_database() -> None:
    from . import models  # noqa: F401

    Base.metadata.create_all(bind=engine)

    if not DATABASE_URL.startswith('sqlite'):
        return

    with engine.begin() as conn:
        inspector = inspect(conn)
        tables = set(inspector.get_table_names())

        if 'posts' in tables:
            columns = {column['name'] for column in inspector.get_columns('posts')}
            if 'videos_json' not in columns:
                conn.execute(text("ALTER TABLE posts ADD COLUMN videos_json TEXT NOT NULL DEFAULT '[]'"))
            if 'ai_summary' not in columns:
                conn.execute(text("ALTER TABLE posts ADD COLUMN ai_summary TEXT"))
            if 'ai_summary_updated_at' not in columns:
                conn.execute(text("ALTER TABLE posts ADD COLUMN ai_summary_updated_at DATETIME"))
            if 'ai_summary_generating' not in columns:
                conn.execute(text("ALTER TABLE posts ADD COLUMN ai_summary_generating BOOLEAN NOT NULL DEFAULT 0"))

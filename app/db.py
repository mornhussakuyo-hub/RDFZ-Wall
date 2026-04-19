from __future__ import annotations

import uuid

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

        if 'users' in tables:
            columns = {column['name'] for column in inspector.get_columns('users')}
            if 'public_uuid' not in columns:
                conn.execute(text("ALTER TABLE users ADD COLUMN public_uuid TEXT"))
            if 'signature' not in columns:
                conn.execute(text("ALTER TABLE users ADD COLUMN signature VARCHAR(40)"))
            if 'next_comment_at' not in columns:
                conn.execute(text("ALTER TABLE users ADD COLUMN next_comment_at DATETIME"))
            conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ix_users_public_uuid ON users (public_uuid)"))
            missing_public_ids = conn.execute(
                text("SELECT id FROM users WHERE public_uuid IS NULL OR public_uuid = ''")
            ).fetchall()
            for row in missing_public_ids:
                conn.execute(
                    text("UPDATE users SET public_uuid = :public_uuid WHERE id = :user_id"),
                    {'public_uuid': str(uuid.uuid4()), 'user_id': row.id},
                )

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

        if 'comments' in tables:
            columns = {column['name'] for column in inspector.get_columns('comments')}
            if 'parent_id' not in columns:
                conn.execute(text("ALTER TABLE comments ADD COLUMN parent_id INTEGER"))

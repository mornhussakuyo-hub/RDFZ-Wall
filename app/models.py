from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, List
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def cn_now():
    try:
        return datetime.now(ZoneInfo("Asia/Shanghai"))
    except ZoneInfoNotFoundError:
        return datetime.now(timezone(timedelta(hours=8)))


def generate_public_uuid() -> str:
    return str(uuid.uuid4())


class JsonListFieldMixin:
    def _read_json_list(self, raw: str | None) -> List[str]:
        try:
            data = json.loads(raw or '[]')
            return data if isinstance(data, list) else []
        except json.JSONDecodeError:
            return []

    def _write_json_list(self, value: List[str]) -> str:
        return json.dumps(value or [], ensure_ascii=False)


class Admin(Base):
    __tablename__ = 'admins'

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    username: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=cn_now)


class User(Base):
    __tablename__ = 'users'

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    public_uuid: Mapped[str] = mapped_column(String(36), unique=True, index=True, default=generate_public_uuid)
    username: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    signature: Mapped[str | None] = mapped_column(String(40), nullable=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=cn_now)
    next_comment_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    comments: Mapped[list['Comment']] = relationship(back_populates='user', cascade='all, delete-orphan')
    likes: Mapped[list['PostLike']] = relationship(back_populates='user', cascade='all, delete-orphan')
    comment_likes: Mapped[list['CommentLike']] = relationship(back_populates='user', cascade='all, delete-orphan')
    summary_usages: Mapped[list['PostSummaryUsage']] = relationship(
        back_populates='user',
        cascade='all, delete-orphan',
    )
    notifications_received: Mapped[list['Notification']] = relationship(
        'Notification',
        back_populates='recipient',
        cascade='all, delete-orphan',
        foreign_keys='Notification.recipient_user_id',
    )
    notifications_sent: Mapped[list['Notification']] = relationship(
        'Notification',
        back_populates='actor',
        foreign_keys='Notification.actor_user_id',
    )


class Post(Base, JsonListFieldMixin):
    __tablename__ = 'posts'

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    title: Mapped[str | None] = mapped_column(String(200), nullable=True)
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    images_json: Mapped[str] = mapped_column(Text, default='[]')
    videos_json: Mapped[str] = mapped_column(Text, default='[]')
    is_pinned: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=cn_now)
    published_at: Mapped[datetime] = mapped_column(DateTime, default=cn_now, index=True)
    ai_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    ai_summary_updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    ai_summary_generating: Mapped[bool] = mapped_column(Boolean, default=False)

    comments: Mapped[list['Comment']] = relationship(back_populates='post', cascade='all, delete-orphan')
    likes: Mapped[list['PostLike']] = relationship(back_populates='post', cascade='all, delete-orphan')
    summary_usages: Mapped[list['PostSummaryUsage']] = relationship(
        back_populates='post',
        cascade='all, delete-orphan',
    )

    @property
    def images(self) -> List[str]:
        return self._read_json_list(self.images_json)

    @images.setter
    def images(self, value: List[str]) -> None:
        self.images_json = self._write_json_list(value)

    @property
    def videos(self) -> List[str]:
        return self._read_json_list(self.videos_json)

    @videos.setter
    def videos(self, value: List[str]) -> None:
        self.videos_json = self._write_json_list(value)

    @property
    def cover(self) -> str | None:
        if self.images:
            return self.images[0]
        return None


class Comment(Base):
    __tablename__ = 'comments'

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    post_id: Mapped[int] = mapped_column(ForeignKey('posts.id', ondelete='CASCADE'), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'), index=True)
    parent_id: Mapped[int | None] = mapped_column(ForeignKey('comments.id', ondelete='CASCADE'), nullable=True, index=True)
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=cn_now, index=True)

    post: Mapped['Post'] = relationship(back_populates='comments')
    user: Mapped['User'] = relationship(back_populates='comments')
    likes: Mapped[list['CommentLike']] = relationship(back_populates='comment', cascade='all, delete-orphan')
    notifications: Mapped[list['Notification']] = relationship(back_populates='comment')
    parent: Mapped['Comment | None'] = relationship(
        'Comment',
        back_populates='replies',
        remote_side='Comment.id',
        foreign_keys=[parent_id],
    )
    replies: Mapped[list['Comment']] = relationship(
        'Comment',
        back_populates='parent',
        cascade='all, delete-orphan',
        foreign_keys=[parent_id],
    )


class PostLike(Base):
    __tablename__ = 'post_likes'
    __table_args__ = (UniqueConstraint('post_id', 'user_id', name='uq_post_like_user'),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    post_id: Mapped[int] = mapped_column(ForeignKey('posts.id', ondelete='CASCADE'), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=cn_now)

    post: Mapped['Post'] = relationship(back_populates='likes')
    user: Mapped['User'] = relationship(back_populates='likes')


class PostSummaryUsage(Base):
    __tablename__ = 'post_summary_usages'
    __table_args__ = (UniqueConstraint('post_id', 'user_id', name='uq_post_summary_usage_user'),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    post_id: Mapped[int] = mapped_column(ForeignKey('posts.id', ondelete='CASCADE'), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=cn_now, index=True)

    post: Mapped['Post'] = relationship(back_populates='summary_usages')
    user: Mapped['User'] = relationship(back_populates='summary_usages')


class CommentLike(Base):
    __tablename__ = 'comment_likes'
    __table_args__ = (UniqueConstraint('comment_id', 'user_id', name='uq_comment_like_user'),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    comment_id: Mapped[int] = mapped_column(ForeignKey('comments.id', ondelete='CASCADE'), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=cn_now, index=True)

    comment: Mapped['Comment'] = relationship(back_populates='likes')
    user: Mapped['User'] = relationship(back_populates='comment_likes')


class Notification(Base):
    __tablename__ = 'notifications'

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    recipient_user_id: Mapped[int] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'), index=True)
    actor_user_id: Mapped[int | None] = mapped_column(
        ForeignKey('users.id', ondelete='SET NULL'),
        nullable=True,
        index=True,
    )
    post_id: Mapped[int | None] = mapped_column(ForeignKey('posts.id', ondelete='CASCADE'), nullable=True, index=True)
    comment_id: Mapped[int | None] = mapped_column(
        ForeignKey('comments.id', ondelete='CASCADE'),
        nullable=True,
        index=True,
    )
    type: Mapped[str] = mapped_column(String(50), index=True)
    title: Mapped[str] = mapped_column(String(120))
    body: Mapped[str | None] = mapped_column(Text, nullable=True)
    payload_json: Mapped[str] = mapped_column(Text, default='{}')
    is_read: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=cn_now, index=True)
    read_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    recipient: Mapped['User'] = relationship(
        back_populates='notifications_received',
        foreign_keys=[recipient_user_id],
    )
    actor: Mapped['User | None'] = relationship(
        back_populates='notifications_sent',
        foreign_keys=[actor_user_id],
    )
    comment: Mapped['Comment | None'] = relationship(back_populates='notifications')

    @property
    def payload(self) -> dict[str, Any]:
        try:
            data = json.loads(self.payload_json or '{}')
            return data if isinstance(data, dict) else {}
        except json.JSONDecodeError:
            return {}

    @payload.setter
    def payload(self, value: dict[str, Any] | None) -> None:
        self.payload_json = json.dumps(value or {}, ensure_ascii=False)

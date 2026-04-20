from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Comment, Notification, Post, User, cn_now


NOTIFICATION_TYPE_COMMENT_REPLY = 'comment_reply'
NOTIFICATION_TYPE_COMMENT_LIKE = 'comment_like'
NOTIFICATION_TYPE_SYSTEM = 'system'


def build_comment_snippet(content: str, limit: int = 48) -> str:
    normalized = ' '.join(content.split())
    if len(normalized) <= limit:
        return normalized
    return normalized[:limit].rstrip() + '...'


def create_notification(
    db: Session,
    *,
    recipient_user_id: int,
    notification_type: str,
    title: str,
    body: str | None = None,
    actor_user_id: int | None = None,
    post_id: int | None = None,
    comment_id: int | None = None,
    payload: dict[str, object] | None = None,
) -> Notification:
    notification = Notification(
        recipient_user_id=recipient_user_id,
        actor_user_id=actor_user_id,
        post_id=post_id,
        comment_id=comment_id,
        type=notification_type,
        title=title,
        body=body,
        is_read=False,
        read_at=None,
        created_at=cn_now(),
    )
    notification.payload = payload
    db.add(notification)
    return notification


def notify_comment_reply(
    db: Session,
    *,
    replier: User,
    reply_comment: Comment,
    parent_comment: Comment,
    post: Post,
) -> Notification | None:
    if parent_comment.user_id == replier.id:
        return None

    return create_notification(
        db,
        recipient_user_id=parent_comment.user_id,
        notification_type=NOTIFICATION_TYPE_COMMENT_REPLY,
        actor_user_id=replier.id,
        post_id=post.id,
        comment_id=reply_comment.id,
        title=f'{replier.username} 回复了你的评论',
        body=build_comment_snippet(reply_comment.content),
        payload={
            'parent_comment_id': parent_comment.id,
            'reply_comment_id': reply_comment.id,
            'post_title': post.title or f'帖子 #{post.id}',
        },
    )


def notify_comment_liked(
    db: Session,
    *,
    actor: User,
    liked_comment: Comment,
    post: Post,
) -> Notification | None:
    if liked_comment.user_id == actor.id:
        return None

    existing = db.scalar(
        select(Notification).where(
            Notification.type == NOTIFICATION_TYPE_COMMENT_LIKE,
            Notification.recipient_user_id == liked_comment.user_id,
            Notification.actor_user_id == actor.id,
            Notification.comment_id == liked_comment.id,
        )
    )
    title = f'{actor.username} 点赞了你的评论'
    body = build_comment_snippet(liked_comment.content)
    payload = {
        'liked_comment_id': liked_comment.id,
        'post_title': post.title or f'帖子 #{post.id}',
    }
    if existing:
        existing.title = title
        existing.body = body
        existing.post_id = post.id
        existing.is_read = False
        existing.read_at = None
        existing.created_at = cn_now()
        existing.payload = payload
        return existing

    return create_notification(
        db,
        recipient_user_id=liked_comment.user_id,
        notification_type=NOTIFICATION_TYPE_COMMENT_LIKE,
        actor_user_id=actor.id,
        post_id=post.id,
        comment_id=liked_comment.id,
        title=title,
        body=body,
        payload=payload,
    )


def remove_comment_like_notification(
    db: Session,
    *,
    actor_user_id: int,
    comment_owner_user_id: int,
    comment_id: int,
) -> Notification | None:
    existing = db.scalar(
        select(Notification).where(
            Notification.type == NOTIFICATION_TYPE_COMMENT_LIKE,
            Notification.recipient_user_id == comment_owner_user_id,
            Notification.actor_user_id == actor_user_id,
            Notification.comment_id == comment_id,
        )
    )
    if existing:
        db.delete(existing)
    return existing


def create_system_notification(
    db: Session,
    *,
    recipient_user_id: int,
    title: str,
    body: str | None = None,
    payload: dict[str, object] | None = None,
) -> Notification:
    return create_notification(
        db,
        recipient_user_id=recipient_user_id,
        notification_type=NOTIFICATION_TYPE_SYSTEM,
        title=title,
        body=body,
        payload=payload,
    )

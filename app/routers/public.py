from __future__ import annotations

import logging
from datetime import datetime, timedelta
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session, selectinload

from ..auth import (
    get_current_admin,
    get_current_user,
    hash_password,
    login_user,
    logout_user,
    pop_flash,
    set_flash,
    verify_password,
)
from ..config import AI_SUMMARY_MAX_IMAGES, SITE_NAME, STATIC_VERSION, TEMPLATE_DIR
from ..db import get_db
from ..models import Comment, CommentLike, Notification, Post, PostLike, PostSummaryUsage, User, cn_now
from ..services.markdown_utils import build_markdown_excerpt, render_markdown
from ..services.notifications import notify_comment_liked, notify_comment_reply, remove_comment_like_notification
from ..services.ai_summary import (
    AISummaryConfigurationError,
    AISummaryGenerationError,
    is_ai_summary_configured,
    summarize_post,
)


templates = Jinja2Templates(directory=str(TEMPLATE_DIR))
router = APIRouter()
logger = logging.getLogger(__name__)
DEFAULT_SIGNATURE = '这个人很懒，什么也没写(❁´◡`❁)'
COMMENT_COOLDOWN = timedelta(minutes=1)
COMMENT_RATE_LIMIT_MESSAGE = '发送评论太频繁啦！歇一下吧！'


def normalize_local_datetime(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is not None:
        return value.replace(tzinfo=None)
    return value


def build_comment_tree(comments: list[Comment]) -> list[dict[str, object]]:
    nodes = {comment.id: {'comment': comment, 'replies': []} for comment in comments}
    roots: list[dict[str, object]] = []

    for comment in comments:
        node = nodes[comment.id]
        parent_node = nodes.get(comment.parent_id) if comment.parent_id else None
        if parent_node:
            parent_node['replies'].append(node)
        else:
            roots.append(node)

    return roots


def collect_comment_subtree_ids(db: Session, root_comment_id: int) -> list[int]:
    pending = [root_comment_id]
    collected: list[int] = []

    while pending:
        current_id = pending.pop()
        collected.append(current_id)
        child_ids = db.scalars(select(Comment.id).where(Comment.parent_id == current_id)).all()
        pending.extend(child_ids)

    return collected


def build_context(request: Request, db: Session, **extra):
    context = {
        'site_name': SITE_NAME,
        'current_user': get_current_user(request, db),
        'current_admin': get_current_admin(request, db),
        'flash': pop_flash(request),
        'ai_summary_configured': is_ai_summary_configured(),
        'static_version': STATIC_VERSION,
    }
    context.update(extra)
    return context


def redirect_login(next_url: str = '/') -> RedirectResponse:
    return RedirectResponse(url=f'/login?next={quote(next_url, safe="/%?:=&")}', status_code=status.HTTP_303_SEE_OTHER)


def load_user_notification_context(
    db: Session,
    user: User,
    *,
    unread_limit: int = 20,
    archived_limit: int = 30,
) -> dict[str, object]:
    unread_notifications = db.scalars(
        select(Notification)
        .where(
            Notification.recipient_user_id == user.id,
            Notification.is_read.is_(False),
        )
        .options(selectinload(Notification.actor))
        .order_by(Notification.created_at.desc(), Notification.id.desc())
        .limit(unread_limit)
    ).all()
    archived_notifications = db.scalars(
        select(Notification)
        .where(
            Notification.recipient_user_id == user.id,
            Notification.is_read.is_(True),
        )
        .options(selectinload(Notification.actor))
        .order_by(Notification.read_at.desc(), Notification.created_at.desc(), Notification.id.desc())
        .limit(archived_limit)
    ).all()
    notification_unread_count = db.scalar(
        select(func.count(Notification.id)).where(
            Notification.recipient_user_id == user.id,
            Notification.is_read.is_(False),
        )
    ) or 0
    notification_archived_count = db.scalar(
        select(func.count(Notification.id)).where(
            Notification.recipient_user_id == user.id,
            Notification.is_read.is_(True),
        )
    ) or 0
    return {
        'unread_notifications': unread_notifications,
        'archived_notifications': archived_notifications,
        'notification_unread_count': notification_unread_count,
        'notification_archived_count': notification_archived_count,
        'notification_total_count': notification_unread_count + notification_archived_count,
    }


@router.get('/', response_class=HTMLResponse)
def index(request: Request, db: Session = Depends(get_db)):
    posts = db.scalars(
        select(Post)
        .where(Post.is_deleted.is_(False))
        .order_by(Post.is_pinned.desc(), Post.published_at.desc(), Post.id.desc())
    ).all()

    like_rows = db.execute(
        select(PostLike.post_id, func.count(PostLike.id)).group_by(PostLike.post_id)
    ).all()
    comment_rows = db.execute(
        select(Comment.post_id, func.count(Comment.id)).group_by(Comment.post_id)
    ).all()

    like_counts = {post_id: count for post_id, count in like_rows}
    comment_counts = {post_id: count for post_id, count in comment_rows}
    post_excerpts = {
        post.id: build_markdown_excerpt(post.content, max_length=120) or '这条帖子没有正文，点击查看完整内容。'
        for post in posts
    }

    return templates.TemplateResponse(
        request,
        'index.html',
        build_context(
            request,
            db,
            posts=posts,
            like_counts=like_counts,
            comment_counts=comment_counts,
            post_excerpts=post_excerpts,
            total_like_count=sum(like_counts.values()),
            total_comment_count=sum(comment_counts.values()),
        ),
    )


@router.get('/posts/{post_id}', response_class=HTMLResponse)
def post_detail(post_id: int, request: Request, db: Session = Depends(get_db)):
    post = db.get(Post, post_id)
    if not post or post.is_deleted:
        raise HTTPException(status_code=404, detail='Post not found')

    comments = db.scalars(
        select(Comment)
        .where(Comment.post_id == post_id)
        .options(
            selectinload(Comment.user),
            selectinload(Comment.parent).selectinload(Comment.user),
        )
        .order_by(Comment.created_at.asc(), Comment.id.asc())
    ).all()
    comment_tree = build_comment_tree(comments)
    like_count = db.scalar(select(func.count(PostLike.id)).where(PostLike.post_id == post_id)) or 0
    current_user = get_current_user(request, db)
    liked_by_me = False
    summary_used_by_me = False
    comment_like_counts: dict[int, int] = {}
    liked_comment_ids: set[int] = set()
    comment_ids = [comment.id for comment in comments]
    if comment_ids:
        like_rows = db.execute(
            select(CommentLike.comment_id, func.count(CommentLike.id))
            .where(CommentLike.comment_id.in_(comment_ids))
            .group_by(CommentLike.comment_id)
        ).all()
        comment_like_counts = {comment_id: count for comment_id, count in like_rows}
    if current_user:
        liked_by_me = db.scalar(
            select(PostLike.id).where(PostLike.post_id == post_id, PostLike.user_id == current_user.id)
        ) is not None
        summary_used_by_me = db.scalar(
            select(PostSummaryUsage.id).where(
                PostSummaryUsage.post_id == post_id,
                PostSummaryUsage.user_id == current_user.id,
            )
        ) is not None
        if comment_ids:
            liked_comment_ids = set(
                db.scalars(
                    select(CommentLike.comment_id).where(
                        CommentLike.comment_id.in_(comment_ids),
                        CommentLike.user_id == current_user.id,
                    )
                ).all()
            )

    return templates.TemplateResponse(
        request,
        'post_detail.html',
        build_context(
            request,
            db,
            post=post,
            comments=comments,
            comment_tree=comment_tree,
            like_count=like_count,
            comment_count=len(comments),
            comment_like_counts=comment_like_counts,
            liked_comment_ids=liked_comment_ids,
            liked_by_me=liked_by_me,
            summary_used_by_me=summary_used_by_me,
            summary_visible=bool(current_user and summary_used_by_me and post.ai_summary),
            comment_rate_limit_message=COMMENT_RATE_LIMIT_MESSAGE,
            post_content_html=render_markdown(post.content),
        ),
    )


@router.post('/posts/{post_id}/ai-summary')
def generate_ai_summary(post_id: int, request: Request, db: Session = Depends(get_db)):
    if request.headers.get('x-requested-with') != 'fetch':
        raise HTTPException(status_code=400, detail='Invalid request')

    post = db.get(Post, post_id)
    if not post or post.is_deleted:
        raise HTTPException(status_code=404, detail='Post not found')

    current_user = get_current_user(request, db)
    if not current_user:
        logger.info('AI summary rejected for post_id=%s reason=not_logged_in', post_id)
        return JSONResponse({'ok': False, 'error': '请先登录后再使用 AI 总结。'}, status_code=401)

    used_record = db.scalar(
        select(PostSummaryUsage).where(
            PostSummaryUsage.post_id == post_id,
            PostSummaryUsage.user_id == current_user.id,
        )
    )
    if used_record:
        logger.info('AI summary rejected for post_id=%s user_id=%s reason=already_used', post_id, current_user.id)
        return JSONResponse({'ok': False, 'error': '你已经使用过本帖 AI 总结了。'}, status_code=403)

    like_count = db.scalar(select(func.count(PostLike.id)).where(PostLike.post_id == post_id)) or 0
    comment_texts = db.scalars(
        select(Comment.content)
        .where(Comment.post_id == post_id)
        .order_by(Comment.created_at.desc(), Comment.id.desc())
        .limit(8)
    ).all()

    try:
        if post.ai_summary:
            logger.info('AI summary cache hit for post_id=%s user_id=%s', post_id, current_user.id)
            summary = post.ai_summary
            used_image_count = min(len(post.images), AI_SUMMARY_MAX_IMAGES)
            generated_now = False
        else:
            logger.info('AI summary cache miss for post_id=%s user_id=%s', post_id, current_user.id)
            summary, used_image_count = summarize_post(
                post,
                like_count=like_count,
                comments=comment_texts,
            )
            post.ai_summary = summary
            post.ai_summary_updated_at = cn_now()
            generated_now = True
    except AISummaryConfigurationError as exc:
        return JSONResponse({'ok': False, 'error': str(exc)}, status_code=503)
    except AISummaryGenerationError as exc:
        return JSONResponse({'ok': False, 'error': str(exc)}, status_code=422)
    except Exception:
        logger.exception('Failed to generate AI summary for post %s', post_id)
        return JSONResponse({'ok': False, 'error': 'AI 总结生成失败，请稍后重试。'}, status_code=500)

    db.add(PostSummaryUsage(post_id=post_id, user_id=current_user.id))
    db.commit()
    logger.info(
        'AI summary served for post_id=%s user_id=%s generated_now=%s used_image_count=%s',
        post_id,
        current_user.id,
        generated_now,
        used_image_count,
    )

    return JSONResponse(
        {
            'ok': True,
            'summary': summary,
            'updated_at': post.ai_summary_updated_at.strftime('%Y-%m-%d %H:%M') if post.ai_summary_updated_at else None,
            'used_image_count': used_image_count,
            'generated_now': generated_now,
        }
    )


@router.get('/login', response_class=HTMLResponse)
def user_login_page(request: Request, next: str = '/', db: Session = Depends(get_db)):
    current_user = get_current_user(request, db)
    if current_user:
        return RedirectResponse(url=next or '/', status_code=status.HTTP_303_SEE_OTHER)
    return templates.TemplateResponse(
        request,
        'user_login.html',
        build_context(request, db, error=None, next_url=next or '/', encoded_next_url=quote(next or '/', safe='')), 
    )


@router.post('/login', response_class=HTMLResponse)
def user_login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    next_url: str = Form('/'),
    db: Session = Depends(get_db),
):
    user = db.scalar(select(User).where(User.username == username.strip()))
    if not user or not verify_password(password, user.password_hash):
        return templates.TemplateResponse(
            request,
            'user_login.html',
            build_context(request, db, error='用户名或密码错误。', next_url=next_url or '/', encoded_next_url=quote(next_url or '/', safe='')), 
            status_code=400,
        )

    login_user(request, user)
    set_flash(request, 'success', f'欢迎回来，{user.username}！')
    return RedirectResponse(url=next_url or '/', status_code=status.HTTP_303_SEE_OTHER)


@router.get('/register', response_class=HTMLResponse)
def register_page(request: Request, next: str = '/', db: Session = Depends(get_db)):
    current_user = get_current_user(request, db)
    if current_user:
        return RedirectResponse(url=next or '/', status_code=status.HTTP_303_SEE_OTHER)
    return templates.TemplateResponse(
        request,
        'user_register.html',
        build_context(request, db, error=None, next_url=next or '/', encoded_next_url=quote(next or '/', safe='')), 
    )


@router.post('/register', response_class=HTMLResponse)
def register_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    confirm_password: str = Form(...),
    next_url: str = Form('/'),
    db: Session = Depends(get_db),
):
    clean_username = username.strip()
    if len(clean_username) < 3:
        return templates.TemplateResponse(
            request,
            'user_register.html',
            build_context(request, db, error='用户名至少 3 个字符。', next_url=next_url or '/', encoded_next_url=quote(next_url or '/', safe='')), 
            status_code=400,
        )
    if len(clean_username) > 20:
        return templates.TemplateResponse(
            request,
            'user_register.html',
            build_context(request, db, error='昵称不能超过 20 个字。', next_url=next_url or '/', encoded_next_url=quote(next_url or '/', safe='')),
            status_code=400,
        )
    if len(password) < 6:
        return templates.TemplateResponse(
            request,
            'user_register.html',
            build_context(request, db, error='密码至少 6 位。', next_url=next_url or '/', encoded_next_url=quote(next_url or '/', safe='')), 
            status_code=400,
        )
    if password != confirm_password:
        return templates.TemplateResponse(
            request,
            'user_register.html',
            build_context(request, db, error='两次输入的密码不一致。', next_url=next_url or '/', encoded_next_url=quote(next_url or '/', safe='')), 
            status_code=400,
        )
    existing = db.scalar(select(User).where(User.username == clean_username))
    if existing:
        return templates.TemplateResponse(
            request,
            'user_register.html',
            build_context(request, db, error='用户名已存在，请换一个。', next_url=next_url or '/', encoded_next_url=quote(next_url or '/', safe='')), 
            status_code=400,
        )

    user = User(username=clean_username, password_hash=hash_password(password))
    db.add(user)
    db.commit()
    db.refresh(user)
    login_user(request, user)
    set_flash(request, 'success', f'注册成功，欢迎加入 {SITE_NAME}！')
    return RedirectResponse(url=next_url or '/', status_code=status.HTTP_303_SEE_OTHER)


@router.post('/logout')
def user_logout(request: Request):
    logout_user(request)
    return RedirectResponse(url='/', status_code=status.HTTP_303_SEE_OTHER)


@router.get('/me', response_class=HTMLResponse)
def user_profile_page(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return redirect_login('/me')

    comment_count = db.scalar(select(func.count(Comment.id)).where(Comment.user_id == user.id)) or 0

    return templates.TemplateResponse(
        request,
        'user_profile.html',
        build_context(
            request,
            db,
            profile_user=user,
            profile_comment_count=comment_count,
            profile_signature_value=user.signature or '',
            profile_signature_text=user.signature or DEFAULT_SIGNATURE,
            error=None,
            **load_user_notification_context(db, user),
        ),
    )


@router.post('/me/notifications/{notification_id}/read')
def mark_notification_read(notification_id: int, request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return redirect_login('/me')

    notification = db.scalar(
        select(Notification).where(
            Notification.id == notification_id,
            Notification.recipient_user_id == user.id,
        )
    )
    if not notification:
        raise HTTPException(status_code=404, detail='Notification not found')

    if not notification.is_read:
        notification.is_read = True
        notification.read_at = cn_now()
        db.commit()
        set_flash(request, 'success', '消息已标记为已读，并移入归档。')

    return RedirectResponse(url='/me#notifications-archive', status_code=status.HTTP_303_SEE_OTHER)


@router.post('/me/notifications/{notification_id}/delete')
def delete_notification(notification_id: int, request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return redirect_login('/me')

    notification = db.scalar(
        select(Notification).where(
            Notification.id == notification_id,
            Notification.recipient_user_id == user.id,
        )
    )
    if not notification:
        raise HTTPException(status_code=404, detail='Notification not found')

    db.delete(notification)
    db.commit()
    set_flash(request, 'success', '消息已删除。')
    return RedirectResponse(url='/me#notifications-archive', status_code=status.HTTP_303_SEE_OTHER)


@router.post('/me', response_class=HTMLResponse)
def user_profile_update(
    request: Request,
    username: str = Form(...),
    signature: str = Form(''),
    db: Session = Depends(get_db),
):
    user = get_current_user(request, db)
    if not user:
        return redirect_login('/me')

    comment_count = db.scalar(select(func.count(Comment.id)).where(Comment.user_id == user.id)) or 0
    clean_username = username.strip()
    clean_signature = signature.strip()
    if len(clean_username) < 3:
        return templates.TemplateResponse(
            request,
            'user_profile.html',
            build_context(
                request,
                db,
                profile_user=user,
                profile_comment_count=comment_count,
                profile_signature_value=clean_signature,
                profile_signature_text=clean_signature or DEFAULT_SIGNATURE,
                error='昵称至少需要 3 个字符。',
                **load_user_notification_context(db, user),
            ),
            status_code=400,
        )
    if len(clean_username) > 20:
        return templates.TemplateResponse(
            request,
            'user_profile.html',
            build_context(
                request,
                db,
                profile_user=user,
                profile_comment_count=comment_count,
                profile_signature_value=clean_signature,
                profile_signature_text=clean_signature or DEFAULT_SIGNATURE,
                error='昵称不能超过 50 个字符。',
                **load_user_notification_context(db, user),
            ),
            status_code=400,
        )

    if len(clean_signature) > 40:
        set_flash(request, 'error', '个性签名不能超过 40 个字。')
        return RedirectResponse(url='/me', status_code=status.HTTP_303_SEE_OTHER)

    existing = db.scalar(select(User).where(User.username == clean_username, User.id != user.id))
    if existing:
        return templates.TemplateResponse(
            request,
            'user_profile.html',
            build_context(
                request,
                db,
                profile_user=user,
                profile_comment_count=comment_count,
                profile_signature_value=clean_signature,
                profile_signature_text=clean_signature or DEFAULT_SIGNATURE,
                error='这个昵称已经被别人使用了。',
                **load_user_notification_context(db, user),
            ),
            status_code=400,
        )

    user.username = clean_username
    user.signature = clean_signature or None
    db.commit()
    db.refresh(user)
    login_user(request, user)
    set_flash(request, 'success', '个人信息已更新。')
    return RedirectResponse(url='/me', status_code=status.HTTP_303_SEE_OTHER)


@router.get('/users/{public_uuid}', response_class=HTMLResponse)
def public_profile_page(public_uuid: str, request: Request, db: Session = Depends(get_db)):
    profile_user = db.scalar(select(User).where(User.public_uuid == public_uuid))
    if not profile_user:
        raise HTTPException(status_code=404, detail='User not found')

    current_user = get_current_user(request, db)
    if current_user and current_user.id == profile_user.id:
        return RedirectResponse(url='/me', status_code=status.HTTP_303_SEE_OTHER)

    comment_count = db.scalar(select(func.count(Comment.id)).where(Comment.user_id == profile_user.id)) or 0

    return templates.TemplateResponse(
        request,
        'public_profile.html',
        build_context(
            request,
            db,
            profile_user=profile_user,
            profile_comment_count=comment_count,
            profile_signature_text=profile_user.signature or DEFAULT_SIGNATURE,
        ),
    )


@router.post('/posts/{post_id}/like')
def toggle_like(post_id: int, request: Request, db: Session = Depends(get_db)):
    post = db.get(Post, post_id)
    if not post or post.is_deleted:
        raise HTTPException(status_code=404, detail='Post not found')

    user = get_current_user(request, db)
    if not user:
        return redirect_login(f'/posts/{post_id}')

    existing = db.scalar(select(PostLike).where(PostLike.post_id == post_id, PostLike.user_id == user.id))
    if existing:
        db.delete(existing)
        set_flash(request, 'success', '已取消点赞。')
    else:
        db.add(PostLike(post_id=post_id, user_id=user.id))
        set_flash(request, 'success', '点赞成功。')
    db.commit()
    return RedirectResponse(url=f'/posts/{post_id}#interact', status_code=status.HTTP_303_SEE_OTHER)


@router.post('/posts/{post_id}/comments/{comment_id}/like')
def toggle_comment_like(
    post_id: int,
    comment_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    post = db.get(Post, post_id)
    if not post or post.is_deleted:
        raise HTTPException(status_code=404, detail='Post not found')

    comment = db.get(Comment, comment_id)
    if not comment or comment.post_id != post_id:
        raise HTTPException(status_code=404, detail='Comment not found')

    user = get_current_user(request, db)
    if not user:
        return redirect_login(f'/posts/{post_id}#comment-{comment_id}')

    existing = db.scalar(
        select(CommentLike).where(CommentLike.comment_id == comment_id, CommentLike.user_id == user.id)
    )
    if existing:
        db.delete(existing)
        remove_comment_like_notification(
            db,
            actor_user_id=user.id,
            comment_owner_user_id=comment.user_id,
            comment_id=comment.id,
        )
        set_flash(request, 'success', '已取消评论点赞。')
    else:
        db.add(CommentLike(comment_id=comment_id, user_id=user.id))
        notify_comment_liked(db, actor=user, liked_comment=comment, post=post)
        set_flash(request, 'success', '评论点赞成功。')
    db.commit()
    return RedirectResponse(url=f'/posts/{post_id}#comment-{comment_id}', status_code=status.HTTP_303_SEE_OTHER)


@router.post('/posts/{post_id}/comments')
def create_comment(
    post_id: int,
    request: Request,
    content: str = Form(...),
    parent_id: str = Form(''),
    db: Session = Depends(get_db),
):
    post = db.get(Post, post_id)
    if not post or post.is_deleted:
        raise HTTPException(status_code=404, detail='Post not found')

    user = get_current_user(request, db)
    if not user:
        return redirect_login(f'/posts/{post_id}#comments')

    clean_content = content.strip()
    if not clean_content:
        set_flash(request, 'error', '评论不能为空。')
        return RedirectResponse(url=f'/posts/{post_id}#comments', status_code=status.HTTP_303_SEE_OTHER)
    if len(clean_content) > 1000:
        set_flash(request, 'error', '评论不能超过 1000 个字符。')
        return RedirectResponse(url=f'/posts/{post_id}#comments', status_code=status.HTTP_303_SEE_OTHER)

    reply_parent: Comment | None = None
    clean_parent_id = parent_id.strip()
    if clean_parent_id:
        if not clean_parent_id.isdigit():
            set_flash(request, 'error', '回复目标不存在。')
            return RedirectResponse(url=f'/posts/{post_id}#comments', status_code=status.HTTP_303_SEE_OTHER)
        reply_parent = db.get(Comment, int(clean_parent_id))
        if not reply_parent or reply_parent.post_id != post_id:
            set_flash(request, 'error', '回复目标不存在。')
            return RedirectResponse(url=f'/posts/{post_id}#comments', status_code=status.HTTP_303_SEE_OTHER)

    now = normalize_local_datetime(cn_now())
    next_comment_at = normalize_local_datetime(user.next_comment_at)
    if now and next_comment_at and now < next_comment_at:
        set_flash(request, 'error', COMMENT_RATE_LIMIT_MESSAGE)
        return RedirectResponse(url=f'/posts/{post_id}#comments', status_code=status.HTTP_303_SEE_OTHER)

    comment = Comment(
        post_id=post_id,
        user_id=user.id,
        parent_id=reply_parent.id if reply_parent else None,
        content=clean_content,
    )
    db.add(comment)
    db.flush()
    if reply_parent:
        notify_comment_reply(
            db,
            replier=user,
            reply_comment=comment,
            parent_comment=reply_parent,
            post=post,
        )
    if now:
        user.next_comment_at = now + COMMENT_COOLDOWN
    db.commit()
    set_flash(request, 'success', '评论已发布。')
    return RedirectResponse(url=f'/posts/{post_id}#comment-{comment.id}', status_code=status.HTTP_303_SEE_OTHER)


@router.post('/posts/{post_id}/comments/{comment_id}/delete')
def delete_comment(
    post_id: int,
    comment_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    admin = get_current_admin(request, db)
    if not admin:
        return RedirectResponse(url='/admin/login', status_code=status.HTTP_303_SEE_OTHER)

    post = db.get(Post, post_id)
    if not post or post.is_deleted:
        raise HTTPException(status_code=404, detail='Post not found')

    comment = db.get(Comment, comment_id)
    if not comment or comment.post_id != post_id:
        raise HTTPException(status_code=404, detail='Comment not found')

    delete_ids = collect_comment_subtree_ids(db, comment.id)
    db.execute(delete(Comment).where(Comment.id.in_(delete_ids)))
    db.commit()
    set_flash(request, 'success', '评论已删除。')
    return RedirectResponse(url=f'/posts/{post_id}#comments', status_code=status.HTTP_303_SEE_OTHER)

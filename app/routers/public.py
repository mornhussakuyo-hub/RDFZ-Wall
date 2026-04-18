from __future__ import annotations

import logging
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
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
from ..config import AI_SUMMARY_MAX_IMAGES, SITE_NAME, TEMPLATE_DIR
from ..db import get_db
from ..models import Comment, Post, PostLike, PostSummaryUsage, User, cn_now
from ..services.ai_summary import (
    AISummaryConfigurationError,
    AISummaryGenerationError,
    is_ai_summary_configured,
    summarize_post,
)


templates = Jinja2Templates(directory=str(TEMPLATE_DIR))
router = APIRouter()
logger = logging.getLogger(__name__)


def build_context(request: Request, db: Session, **extra):
    context = {
        'site_name': SITE_NAME,
        'current_user': get_current_user(request, db),
        'current_admin': get_current_admin(request, db),
        'flash': pop_flash(request),
        'ai_summary_configured': is_ai_summary_configured(),
    }
    context.update(extra)
    return context


def redirect_login(next_url: str = '/') -> RedirectResponse:
    return RedirectResponse(url=f'/login?next={quote(next_url, safe="/%?:=&")}', status_code=status.HTTP_303_SEE_OTHER)


@router.get('/', response_class=HTMLResponse)
def index(request: Request, db: Session = Depends(get_db)):
    posts = db.scalars(
        select(Post).where(Post.is_deleted.is_(False)).order_by(Post.published_at.desc(), Post.id.desc())
    ).all()

    like_rows = db.execute(
        select(PostLike.post_id, func.count(PostLike.id)).group_by(PostLike.post_id)
    ).all()
    comment_rows = db.execute(
        select(Comment.post_id, func.count(Comment.id)).group_by(Comment.post_id)
    ).all()

    like_counts = {post_id: count for post_id, count in like_rows}
    comment_counts = {post_id: count for post_id, count in comment_rows}

    return templates.TemplateResponse(
        request,
        'index.html',
        build_context(
            request,
            db,
            posts=posts,
            like_counts=like_counts,
            comment_counts=comment_counts,
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
        .options(selectinload(Comment.user))
        .order_by(Comment.created_at.asc(), Comment.id.asc())
    ).all()
    like_count = db.scalar(select(func.count(PostLike.id)).where(PostLike.post_id == post_id)) or 0
    current_user = get_current_user(request, db)
    liked_by_me = False
    summary_used_by_me = False
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

    return templates.TemplateResponse(
        request,
        'post_detail.html',
        build_context(
            request,
            db,
            post=post,
            comments=comments,
            like_count=like_count,
            comment_count=len(comments),
            liked_by_me=liked_by_me,
            summary_used_by_me=summary_used_by_me,
            summary_visible=bool(current_user and summary_used_by_me and post.ai_summary),
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


@router.post('/posts/{post_id}/comments')
def create_comment(
    post_id: int,
    request: Request,
    content: str = Form(...),
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

    comment = Comment(post_id=post_id, user_id=user.id, content=clean_content)
    db.add(comment)
    db.commit()
    set_flash(request, 'success', '评论已发布。')
    return RedirectResponse(url=f'/posts/{post_id}#comments', status_code=status.HTTP_303_SEE_OTHER)

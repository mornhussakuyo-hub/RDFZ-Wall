from __future__ import annotations

from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
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
from ..config import SITE_NAME, TEMPLATE_DIR
from ..db import get_db
from ..models import Comment, Post, PostLike, User


templates = Jinja2Templates(directory=str(TEMPLATE_DIR))
router = APIRouter()


def build_context(request: Request, db: Session, **extra):
    context = {
        'site_name': SITE_NAME,
        'current_user': get_current_user(request, db),
        'current_admin': get_current_admin(request, db),
        'flash': pop_flash(request),
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
    if current_user:
        liked_by_me = db.scalar(
            select(PostLike.id).where(PostLike.post_id == post_id, PostLike.user_id == current_user.id)
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
        ),
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

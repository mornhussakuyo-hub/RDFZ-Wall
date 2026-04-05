from __future__ import annotations

import secrets
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo
from pathlib import Path
from typing import List

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import get_current_admin, get_current_user, login_admin, logout_admin, pop_flash, verify_password
from ..config import (
    ALLOWED_IMAGE_EXTENSIONS,
    ALLOWED_VIDEO_EXTENSIONS,
    MAX_SINGLE_FILE_MB,
    MAX_SINGLE_VIDEO_MB,
    MAX_UPLOAD_FILES,
    MAX_VIDEO_FILES,
    SITE_NAME,
    TEMPLATE_DIR,
    UPLOAD_DIR,
)
from ..db import get_db
from ..models import Admin, Post


templates = Jinja2Templates(directory=str(TEMPLATE_DIR))
router = APIRouter(prefix='/admin', tags=['admin'])



def cn_now():
    return datetime.now(ZoneInfo("Asia/Shanghai"))

def redirect_to_login() -> RedirectResponse:
    return RedirectResponse(url='/admin/login', status_code=status.HTTP_303_SEE_OTHER)


def build_context(request: Request, db: Session, **extra):
    context = {
        'site_name': SITE_NAME,
        'current_user': get_current_user(request, db),
        'current_admin': get_current_admin(request, db),
        'flash': pop_flash(request),
    }
    context.update(extra)
    return context


def save_upload_files(
    files: List[UploadFile],
    *,
    allowed_extensions: set[str],
    max_files: int,
    max_single_file_mb: int,
    label: str,
) -> List[str]:
    if len(files) > max_files:
        raise ValueError(f'最多只能上传 {max_files} 个{label}。')

    saved_paths: List[str] = []
    now = datetime.now()
    target_dir = UPLOAD_DIR / now.strftime('%Y') / now.strftime('%m') / now.strftime('%d')
    target_dir.mkdir(parents=True, exist_ok=True)

    for file in files:
        if not file.filename:
            continue

        suffix = Path(file.filename).suffix.lower()
        if suffix not in allowed_extensions:
            raise ValueError(f'不支持的{label}格式：{file.filename}')

        content = file.file.read()
        if len(content) > max_single_file_mb * 1024 * 1024:
            raise ValueError(f'单个{label}不能超过 {max_single_file_mb}MB：{file.filename}')

        filename = f'{uuid.uuid4().hex}{suffix}'
        file_path = target_dir / filename
        file_path.write_bytes(content)
        relative_path = '/static/' + str(file_path.relative_to(UPLOAD_DIR.parent)).replace('\\', '/')
        saved_paths.append(relative_path)

    return saved_paths


@router.get('/', response_class=HTMLResponse)
def admin_root(request: Request, db: Session = Depends(get_db)):
    admin = get_current_admin(request, db)
    if not admin:
        return redirect_to_login()
    return RedirectResponse(url='/admin/posts', status_code=status.HTTP_303_SEE_OTHER)


@router.get('/login', response_class=HTMLResponse)
def login_page(request: Request, db: Session = Depends(get_db)):
    admin = get_current_admin(request, db)
    if admin:
        return RedirectResponse(url='/admin/posts', status_code=status.HTTP_303_SEE_OTHER)

    csrf_token = secrets.token_urlsafe(24)
    request.session['login_csrf'] = csrf_token
    return templates.TemplateResponse(
        request,
        'admin_login.html',
        build_context(
            request,
            db,
            error=None,
            csrf_token=csrf_token,
        ),
    )


@router.post('/login', response_class=HTMLResponse)
def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    csrf_token: str = Form(...),
    db: Session = Depends(get_db),
):
    session_token = request.session.get('login_csrf')
    if not session_token or not secrets.compare_digest(csrf_token, session_token):
        new_token = secrets.token_urlsafe(24)
        request.session['login_csrf'] = new_token
        return templates.TemplateResponse(
            request,
            'admin_login.html',
            build_context(request, db, error='登录已过期，请重试。', csrf_token=new_token),
            status_code=400,
        )

    admin = db.scalar(select(Admin).where(Admin.username == username.strip()))
    if not admin or not verify_password(password, admin.password_hash):
        new_token = secrets.token_urlsafe(24)
        request.session['login_csrf'] = new_token
        return templates.TemplateResponse(
            request,
            'admin_login.html',
            build_context(request, db, error='用户名或密码错误。', csrf_token=new_token),
            status_code=400,
        )

    login_admin(request, admin)
    request.session.pop('login_csrf', None)
    return RedirectResponse(url='/admin/posts', status_code=status.HTTP_303_SEE_OTHER)


@router.post('/logout')
def logout(request: Request):
    logout_admin(request)
    return RedirectResponse(url='/admin/login', status_code=status.HTTP_303_SEE_OTHER)


@router.get('/posts', response_class=HTMLResponse)
def admin_posts(request: Request, db: Session = Depends(get_db)):
    admin = get_current_admin(request, db)
    if not admin:
        return redirect_to_login()

    posts = db.scalars(select(Post).order_by(Post.published_at.desc(), Post.id.desc())).all()
    return templates.TemplateResponse(
        request,
        'admin_posts.html',
        build_context(request, db, posts=posts, admin=admin),
    )


@router.get('/posts/new', response_class=HTMLResponse)
def new_post_page(request: Request, db: Session = Depends(get_db)):
    admin = get_current_admin(request, db)
    if not admin:
        return redirect_to_login()

    csrf_token = secrets.token_urlsafe(24)
    request.session['post_csrf'] = csrf_token
    return templates.TemplateResponse(
        request,
        'admin_new_post.html',
        build_context(
            request,
            db,
            admin=admin,
            error=None,
            csrf_token=csrf_token,
            title_value='',
            content_value='',
        ),
    )


@router.post('/posts/new', response_class=HTMLResponse)
def create_post(
    request: Request,
    title: str | None = Form(None),
    content: str | None = Form(None),
    csrf_token: str = Form(...),
    images: List[UploadFile] = File(default=[]),
    videos: List[UploadFile] = File(default=[]),
    db: Session = Depends(get_db),
):
    admin = get_current_admin(request, db)
    if not admin:
        return redirect_to_login()

    session_token = request.session.get('post_csrf')
    if not session_token or not secrets.compare_digest(csrf_token, session_token):
        new_token = secrets.token_urlsafe(24)
        request.session['post_csrf'] = new_token
        return templates.TemplateResponse(
            request,
            'admin_new_post.html',
            build_context(
                request,
                db,
                admin=admin,
                error='表单已过期，请刷新页面后重试。',
                csrf_token=new_token,
                title_value=title or '',
                content_value=content or '',
            ),
            status_code=400,
        )

    clean_title = (title or '').strip() or None
    clean_content = (content or '').strip() or None
    real_image_files = [file for file in images if file and file.filename]
    real_video_files = [file for file in videos if file and file.filename]

    if not clean_title and not clean_content and not real_image_files and not real_video_files:
        new_token = secrets.token_urlsafe(24)
        request.session['post_csrf'] = new_token
        return templates.TemplateResponse(
            request,
            'admin_new_post.html',
            build_context(
                request,
                db,
                admin=admin,
                error='标题、正文、图片、视频至少填写一项。',
                csrf_token=new_token,
                title_value=title or '',
                content_value=content or '',
            ),
            status_code=400,
        )

    try:
        image_paths = save_upload_files(
            real_image_files,
            allowed_extensions=ALLOWED_IMAGE_EXTENSIONS,
            max_files=MAX_UPLOAD_FILES,
            max_single_file_mb=MAX_SINGLE_FILE_MB,
            label='图片',
        )
        video_paths = save_upload_files(
            real_video_files,
            allowed_extensions=ALLOWED_VIDEO_EXTENSIONS,
            max_files=MAX_VIDEO_FILES,
            max_single_file_mb=MAX_SINGLE_VIDEO_MB,
            label='视频',
        )
    except ValueError as exc:
        new_token = secrets.token_urlsafe(24)
        request.session['post_csrf'] = new_token
        return templates.TemplateResponse(
            request,
            'admin_new_post.html',
            build_context(
                request,
                db,
                admin=admin,
                error=str(exc),
                csrf_token=new_token,
                title_value=title or '',
                content_value=content or '',
            ),
            status_code=400,
        )

    post = Post(
        title=clean_title,
        content=clean_content,
        created_at=cn_now(),
        published_at=cn_now(),
    )
    post.images = image_paths
    post.videos = video_paths
    db.add(post)
    db.commit()
    db.refresh(post)

    request.session.pop('post_csrf', None)
    return RedirectResponse(url=f'/posts/{post.id}', status_code=status.HTTP_303_SEE_OTHER)


@router.post('/posts/{post_id}/delete')
def delete_post(post_id: int, request: Request, db: Session = Depends(get_db)):
    admin = get_current_admin(request, db)
    if not admin:
        return redirect_to_login()

    post = db.get(Post, post_id)
    if not post:
        raise HTTPException(status_code=404, detail='Post not found')
    post.is_deleted = True
    db.commit()
    return RedirectResponse(url='/admin/posts', status_code=status.HTTP_303_SEE_OTHER)

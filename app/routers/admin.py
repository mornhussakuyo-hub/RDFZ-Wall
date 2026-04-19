from __future__ import annotations

import logging
import secrets
import uuid
from pathlib import Path
from typing import List

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..auth import (
    get_current_admin,
    get_current_user,
    login_admin,
    logout_admin,
    pop_flash,
    set_flash,
    verify_password,
)
from ..config import (
    ALLOWED_IMAGE_EXTENSIONS,
    ALLOWED_VIDEO_EXTENSIONS,
    MAX_SINGLE_FILE_MB,
    MAX_SINGLE_VIDEO_MB,
    MAX_UPLOAD_FILES,
    MAX_VIDEO_FILES,
    SITE_NAME,
    STATIC_VERSION,
    TEMPLATE_DIR,
    UPLOAD_DIR,
)
from ..db import get_db
from ..models import Admin, Comment, Post, PostLike, cn_now
from ..services.ai_summary import (
    AISummaryConfigurationError,
    AISummaryGenerationError,
    summarize_post,
)


templates = Jinja2Templates(directory=str(TEMPLATE_DIR))
router = APIRouter(prefix='/admin', tags=['admin'])
logger = logging.getLogger(__name__)


def is_fetch_request(request: Request) -> bool:
    return request.headers.get('x-requested-with') == 'fetch'

def redirect_to_login() -> RedirectResponse:
    return RedirectResponse(url='/admin/login', status_code=status.HTTP_303_SEE_OTHER)


def build_context(request: Request, db: Session, **extra):
    context = {
        'site_name': SITE_NAME,
        'current_user': get_current_user(request, db),
        'current_admin': get_current_admin(request, db),
        'flash': pop_flash(request),
        'static_version': STATIC_VERSION,
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
    now = cn_now()
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


@router.post('/posts/{post_id}/ai-summary/regenerate')
def regenerate_ai_summary(post_id: int, request: Request, db: Session = Depends(get_db)):
    admin = get_current_admin(request, db)
    if not admin:
        if is_fetch_request(request):
            return JSONResponse({'ok': False, 'error': '请先登录管理员账号。'}, status_code=401)
        return redirect_to_login()

    post = db.get(Post, post_id)
    if not post:
        raise HTTPException(status_code=404, detail='Post not found')
    if post.is_deleted:
        if is_fetch_request(request):
            return JSONResponse({'ok': False, 'error': '已删除帖子无法生成 AI 总结。'}, status_code=400)
        set_flash(request, 'error', '已删除帖子无法生成 AI 总结。')
        return RedirectResponse(url='/admin/posts', status_code=status.HTTP_303_SEE_OTHER)
    if post.ai_summary_generating:
        if is_fetch_request(request):
            return JSONResponse({'ok': False, 'error': '这条帖子正在生成 AI 总结，请稍后刷新查看。'}, status_code=409)
        set_flash(request, 'error', '这条帖子正在生成 AI 总结，请稍后刷新查看。')
        return RedirectResponse(url='/admin/posts', status_code=status.HTTP_303_SEE_OTHER)

    like_count = db.scalar(select(func.count(PostLike.id)).where(PostLike.post_id == post_id)) or 0
    comment_texts = db.scalars(
        select(Comment.content)
        .where(Comment.post_id == post_id)
        .order_by(Comment.created_at.desc(), Comment.id.desc())
        .limit(8)
    ).all()

    logger.info('Admin requested AI summary regeneration for post_id=%s admin=%s', post_id, admin.username)
    post.ai_summary_generating = True
    db.commit()
    try:
        summary, used_image_count = summarize_post(
            post,
            like_count=like_count,
            comments=comment_texts,
        )
    except AISummaryConfigurationError as exc:
        post.ai_summary_generating = False
        db.commit()
        if is_fetch_request(request):
            return JSONResponse({'ok': False, 'error': str(exc)}, status_code=503)
        set_flash(request, 'error', str(exc))
        return RedirectResponse(url='/admin/posts', status_code=status.HTTP_303_SEE_OTHER)
    except AISummaryGenerationError as exc:
        post.ai_summary_generating = False
        db.commit()
        if is_fetch_request(request):
            return JSONResponse({'ok': False, 'error': str(exc)}, status_code=422)
        set_flash(request, 'error', str(exc))
        return RedirectResponse(url='/admin/posts', status_code=status.HTTP_303_SEE_OTHER)
    except Exception:
        logger.exception('Admin AI summary regeneration failed for post_id=%s admin=%s', post_id, admin.username)
        post.ai_summary_generating = False
        db.commit()
        if is_fetch_request(request):
            return JSONResponse({'ok': False, 'error': 'AI 总结生成失败，请稍后重试。'}, status_code=500)
        set_flash(request, 'error', 'AI 总结生成失败，请稍后重试。')
        return RedirectResponse(url='/admin/posts', status_code=status.HTTP_303_SEE_OTHER)

    post.ai_summary = summary
    post.ai_summary_updated_at = cn_now()
    post.ai_summary_generating = False
    db.commit()
    logger.info(
        'Admin regenerated AI summary for post_id=%s admin=%s used_image_count=%s',
        post_id,
        admin.username,
        used_image_count,
    )
    if is_fetch_request(request):
        return JSONResponse(
            {
                'ok': True,
                'post_id': post.id,
                'updated_at': post.ai_summary_updated_at.strftime('%Y-%m-%d %H:%M'),
                'used_image_count': used_image_count,
                'message': f'帖子 #{post.id} 的 AI 总结已重新生成。',
                'generating': False,
            }
        )
    set_flash(request, 'success', f'帖子 #{post.id} 的 AI 总结已重新生成。')
    return RedirectResponse(url='/admin/posts', status_code=status.HTTP_303_SEE_OTHER)

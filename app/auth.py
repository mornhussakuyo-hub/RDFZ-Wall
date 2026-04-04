from __future__ import annotations

import hashlib
import hmac
import secrets
from typing import Optional

from fastapi import Request
from sqlalchemy.orm import Session

from .config import SESSION_COOKIE_NAME
from .models import Admin, User


PBKDF2_ITERATIONS = 390000


def hash_password(password: str, *, salt: Optional[str] = None) -> str:
    if not password:
        raise ValueError('Password cannot be empty.')
    real_salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), real_salt.encode('utf-8'), PBKDF2_ITERATIONS)
    return f'pbkdf2_sha256${PBKDF2_ITERATIONS}${real_salt}${digest.hex()}'


def verify_password(password: str, stored_hash: str) -> bool:
    try:
        algorithm, iteration_str, salt, hex_digest = stored_hash.split('$', 3)
        if algorithm != 'pbkdf2_sha256':
            return False
        iterations = int(iteration_str)
    except ValueError:
        return False

    digest = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt.encode('utf-8'), iterations)
    return hmac.compare_digest(digest.hex(), hex_digest)


def login_admin(request: Request, admin: Admin) -> None:
    request.session['admin_id'] = admin.id
    request.session['admin_username'] = admin.username


def logout_admin(request: Request) -> None:
    request.session.pop('admin_id', None)
    request.session.pop('admin_username', None)


def get_current_admin(request: Request, db: Session) -> Admin | None:
    admin_id = request.session.get('admin_id')
    if not admin_id:
        return None
    return db.get(Admin, admin_id)


def login_user(request: Request, user: User) -> None:
    request.session['user_id'] = user.id
    request.session['username'] = user.username


def logout_user(request: Request) -> None:
    request.session.pop('user_id', None)
    request.session.pop('username', None)


def get_current_user(request: Request, db: Session) -> User | None:
    user_id = request.session.get('user_id')
    if not user_id:
        return None
    return db.get(User, user_id)


def is_logged_in(request: Request) -> bool:
    return SESSION_COOKIE_NAME in request.cookies and (
        'admin_id' in request.session or 'user_id' in request.session
    )


def set_flash(request: Request, level: str, message: str) -> None:
    request.session['flash'] = {'level': level, 'message': message}


def pop_flash(request: Request) -> dict | None:
    return request.session.pop('flash', None)

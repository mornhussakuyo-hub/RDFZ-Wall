from __future__ import annotations

import getpass
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.auth import hash_password
from app.db import SessionLocal, initialize_database
from app.models import Admin



def main() -> None:
    initialize_database()
    db = SessionLocal()
    try:
        username = input('管理员用户名（默认 admin）：').strip() or 'admin'
        existing = db.query(Admin).filter(Admin.username == username).first()
        if existing:
            print(f'管理员 {username} 已存在。')
            return

        while True:
            password = getpass.getpass('管理员密码：')
            confirm = getpass.getpass('再次输入密码：')
            if password != confirm:
                print('两次输入不一致，请重试。')
                continue
            if len(password) < 6:
                print('密码至少 6 位。')
                continue
            break

        admin = Admin(username=username, password_hash=hash_password(password))
        db.add(admin)
        db.commit()
        print(f'管理员 {username} 创建成功。')
    finally:
        db.close()


if __name__ == '__main__':
    main()

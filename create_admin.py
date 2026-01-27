#!/usr/bin/env python3
"""
创建管理员账号
"""
import sys
import os

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from database import SessionLocal, create_user, create_invite_code
from auth import get_password_hash

def create_admin_user():
    db = SessionLocal()
    try:
        # 检查是否已存在
        from database import get_user_by_email
        email = "admin@qq.com"
        existing = get_user_by_email(db, email)
        if existing:
            print("⚠️  管理员账号已存在")
            return

        # 创建邀请码
        invite_code = "admin123"
        create_invite_code(db, invite_code)
        print(f"✓ 邀请码已创建: {invite_code}")

        # 创建管理员账号
        hashed_password = get_password_hash("admin")
        user = create_user(db, email, hashed_password, invite_code)
        print(f"✓ 管理员账号已创建:")
        print(f"  - 邮箱: {email}")
        print(f"  - 密码: admin")
        print(f"  - 邀请码: {invite_code}")
        print(f"  - 用户ID: {user.id}")
    finally:
        db.close()

if __name__ == "__main__":
    create_admin_user()

#!/usr/bin/env python3
import os
import sys

sys.path.insert(0, '/app')

from database import SessionLocal, get_user_by_email, create_user, engine, Base
from auth import get_password_hash

Base.metadata.create_all(bind=engine)

db = SessionLocal()
admin_email = "admin@qq.com"
admin_password = "admin"

existing = get_user_by_email(db, admin_email)
if existing:
    print(f"用户 {admin_email} 已存在，id={existing.id}")
else:
    hashed_pw = get_password_hash(admin_password)
    user = create_user(db, admin_email, hashed_pw, invite_code="admin")
    print(f"用户 {admin_email} 创建成功! id={user.id}")

db.close()

"""
Clears all rows from the users table, then creates the admin account.
Run once from the backend directory:
    .\\venv\\Scripts\\python reset_and_seed_admin.py
"""
import sys, os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app.database import SessionLocal, engine, Base
from app.models.models import User, RoleEnum, UserStatusEnum
from app.auth import hash_password
from sqlalchemy import text
import json

Base.metadata.create_all(bind=engine)
db = SessionLocal()

# Delete in FK-safe order: comments → notifications → issues → users
db.execute(text("DELETE FROM comments"))
db.execute(text("DELETE FROM notifications"))
db.execute(text("DELETE FROM issues"))
deleted = db.query(User).delete()
db.commit()
print(f"Deleted {deleted} user(s) and all related rows.")

# 2. Create admin
admin = User(
    name="Ibrahim",
    email="ibraheemziyad45@gmail.com",
    hashed_password=hash_password("worldwar2"),
    role=RoleEnum.admin,
    status=UserStatusEnum.approved,
    permissions=json.dumps({"can_add": True, "can_delete": True, "can_edit_permissions": True})
)
db.add(admin)
db.commit()
db.refresh(admin)
print(f"Admin created: id={admin.id} | {admin.email} | role={admin.role} | status={admin.status}")
db.close()

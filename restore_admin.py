"""
Emergency Admin Recovery Script
================================
Run this anytime you lose admin access:
    .\venv\Scripts\python restore_admin.py

Or to create a brand new admin account:
    .\venv\Scripts\python restore_admin.py --create
"""
import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app.database import SessionLocal, engine, Base
from app.models.models import User, RoleEnum, UserStatusEnum
from app.auth import hash_password
import json

Base.metadata.create_all(bind=engine)
db = SessionLocal()

def restore_existing_admin():
    users = db.query(User).all()
    if not users:
        print("No users found. Use --create to make a new admin.")
        return

    print("\nExisting users:")
    for u in users:
        print(f"  [{u.id}] {u.name} | {u.email} | role={u.role} | status={u.status}")

    user_id = input("\nEnter user ID to make admin (or press Enter for first user): ").strip()

    if user_id:
        user = db.query(User).filter(User.id == int(user_id)).first()
    else:
        user = users[0]

    if not user:
        print("User not found.")
        return

    user.role = RoleEnum.admin
    user.status = UserStatusEnum.approved
    user.permissions = json.dumps({
        "can_add": True,
        "can_delete": True,
        "can_edit_permissions": True
    })
    db.commit()
    print(f"\n✅ SUCCESS: '{user.name}' ({user.email}) is now a Super Admin!")

def create_new_admin():
    print("\n=== Create New Admin Account ===")
    name = input("Name: ").strip()
    email = input("Email: ").strip()
    password = input("Password: ").strip()

    existing = db.query(User).filter(User.email == email).first()
    if existing:
        print(f"Email already exists. Upgrading to admin instead...")
        existing.role = RoleEnum.admin
        existing.status = UserStatusEnum.approved
        existing.permissions = json.dumps({
            "can_add": True,
            "can_delete": True,
            "can_edit_permissions": True
        })
        db.commit()
        print(f"✅ SUCCESS: '{existing.name}' upgraded to Super Admin!")
        return

    user = User(
        name=name,
        email=email,
        hashed_password=hash_password(password),
        role=RoleEnum.admin,
        status=UserStatusEnum.approved,
        permissions=json.dumps({
            "can_add": True,
            "can_delete": True,
            "can_edit_permissions": True
        })
    )
    db.add(user)
    db.commit()
    print(f"\n✅ SUCCESS: New admin '{name}' created successfully!")
    print(f"   Email: {email}")
    print(f"   Password: {password}")

if __name__ == "__main__":
    if "--create" in sys.argv:
        create_new_admin()
    else:
        restore_existing_admin()

db.close()

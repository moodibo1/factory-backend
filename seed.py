import os
import sys

# Ensure the app module can be imported
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app.database import SessionLocal, engine, Base
from app.models.models import User, RoleEnum, UserStatusEnum, CategoryEnum
from app.auth import hash_password

def seed_admin():
    print("Initializing database connection...")
    
    # Create tables if they do not exist
    print("Ensuring tables exist...")
    Base.metadata.create_all(bind=engine)
    
    db = SessionLocal()
    try:
        admin_email = "admin@factory.com"
        admin_password = "admin" # Set a temporary default password
        
        # Check if admin already exists
        existing_admin = db.query(User).filter(User.email == admin_email).first()
        
        if existing_admin:
            print(f"An admin account with email '{admin_email}' already exists.")
            
            # Optionally reset the password if it already exists to guarantee access
            # existing_admin.hashed_password = hash_password(admin_password)
            # db.commit()
            
            return
            
        print("Creating new admin user...")
        
    admin_user = User(
        name="Primary Admin",
        email=admin_email,
        hashed_password=hash_password(admin_password),
        role=RoleEnum.admin,
        status=UserStatusEnum.approved,
        categories=["admin"],
        # Granting total permissions admin
        permissions='{"can_add": true, "can_delete": true, "can_edit_permissions": true}'
    )
        
        db.add(admin_user)
        db.commit()
        db.refresh(admin_user)
        
        print("\n✅ Success! Admin user created successfully.")
        print("-" * 30)
        print(f"Email:    {admin_email}")
        print(f"Password: {admin_password}")
        print("-" * 30)
        print("Important: Please log in and change this password immediately.")
        
    except Exception as e:
        print(f"❌ Error seeding database: {e}")
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    seed_admin()

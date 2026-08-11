from app.database import SessionLocal
from app.models.models import User

db = SessionLocal()
users = db.query(User).all()
print("Users in DB:", [{"email": u.email, "status": u.status} for u in users])
db.close()

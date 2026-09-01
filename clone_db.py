from sqlalchemy import create_engine, MetaData

# 1. روابط الاتصال
SUPABASE_URL = "postgresql://postgres.cokwmyuqduksewbheeth:[AbRqQywzd5WGYleY]@aws-0-eu-central-1.pooler.supabase.com:6543/postgres"
LOCAL_URL = "postgresql://postgres:sswaffen-88@localhost:5432/factory_issues"

print("جاري الاتصال بقواعد البيانات...")
supa_engine = create_engine(SUPABASE_URL)
local_engine = create_engine(LOCAL_URL)

meta = MetaData()

# 2. استنساخ هيكل الجداول
print("جاري قراءة هيكل الجداول من Supabase...")
meta.reflect(bind=supa_engine)

print("جاري إنشاء الجداول محلياً...")
meta.create_all(bind=local_engine)

# 3. نقل البيانات
with supa_engine.connect() as supa_conn:
    with local_engine.begin() as local_conn:
        for table in meta.sorted_tables:
            print(f"جاري نسخ بيانات جدول: {table.name}...")
            
            # مسح البيانات القديمة إن وُجدت لتجنب التكرار
            local_conn.execute(table.delete())
            
            # سحب الداتا من الاونلاين
            data = supa_conn.execute(table.select()).fetchall()
            
            # إدراج الداتا في القاعدة المحلية
            if data:
                insert_data = [dict(row._mapping) for row in data]
                local_conn.execute(table.insert(), insert_data)

print("تم الاستنساخ بنجاح! قاعدتك المحلية جاهزة ومطابقة 100%.")
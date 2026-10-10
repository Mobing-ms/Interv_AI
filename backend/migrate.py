import sqlite3
from app.database import Base, engine
import app.models  # Ensure all models are registered with Base.metadata

Base.metadata.create_all(bind=engine)

conn = sqlite3.connect('intervai.db')
cursor = conn.cursor()
cursor.execute("PRAGMA table_info(users)")
cols = [col[1] for col in cursor.fetchall()]
if "onboarding_status" not in cols:
    cursor.execute("ALTER TABLE users ADD COLUMN onboarding_status VARCHAR(50) DEFAULT 'not_started'")
    conn.commit()
    print("Added onboarding_status column to users successfully")
else:
    print("onboarding_status already exists in users")

cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
tables = [t[0] for t in cursor.fetchall()]
print("Current database tables:", tables)
conn.close()

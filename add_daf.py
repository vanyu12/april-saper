import os
import secrets
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import auth
from config import config
from db import Database

uid = 9000001
db = Database(config.db_path)
if not db.user(uid):
    db.ensure_user(uid, "DAF", "DAF")

password = sys.argv[1] if len(sys.argv) > 1 else "DAF-" + secrets.token_urlsafe(6)
password_hash, salt = auth.hash_password(password)
db.set_account(uid, "DAF", password_hash, salt)

print("login: DAF")
print("password:", password)
print("user_id:", uid)

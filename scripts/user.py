"""Create or update an agency user without exposing passwords in shell history."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import argparse,getpass
from app.config import load_dotenv,Config
from app.db import Database
from app.auth import hash_password
from app.core import validate_email,email_key,iso
from app.service import uid
p=argparse.ArgumentParser();p.add_argument('email');p.add_argument('--name',default='Agency team member');p.add_argument('--role',choices=['admin','reviewer','viewer'],default='reviewer')
a=p.parse_args();password=getpass.getpass('New password (16+ characters): ')
if len(password)<16:raise SystemExit('Use at least 16 characters.')
load_dotenv();cfg=Config();db=Database(cfg.database_path,cfg.database_url);db.migrate()
with db.transaction() as tx:
 email=email_key(validate_email(a.email));old=tx.one('SELECT id FROM users WHERE email=?',(email,));id=old['id'] if old else uid()
 tx.execute('INSERT INTO users(id,email,name,password_hash,role,created_at) VALUES(?,?,?,?,?,?) ON CONFLICT(email) DO UPDATE SET name=excluded.name,password_hash=excluded.password_hash,role=excluded.role',(id,email,a.name,hash_password(password),a.role,iso()))
 tx.execute('DELETE FROM sessions WHERE user_id=?',(id,))
print('User saved. Existing sessions for this user were revoked.')

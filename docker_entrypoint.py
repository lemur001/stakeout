"""Initialize the Railway volume, then permanently drop privileges before serving."""
import os
import sys
from pathlib import Path


def main():
    os.umask(0o077)
    if hasattr(os,'getuid') and os.getuid()==0:
        root=Path('/app/data')
        if root.is_symlink():raise SystemExit('The data directory must not be a symlink.')
        root.mkdir(mode=0o700,parents=True,exist_ok=True)
        os.chown(root,10001,10001)
        os.chmod(root,0o700)
        if not os.getenv('DATABASE_URL'):
            db=Path(os.getenv('DATABASE_PATH','/app/data/civic.sqlite3'))
            if db.parent!=root or db.is_symlink():
                raise SystemExit('The container SQLite database must be directly inside /app/data.')
            for path in (db,Path(str(db)+'-wal'),Path(str(db)+'-shm')):
                if path.is_symlink():raise SystemExit('Database files must not be symlinks.')
                if path.exists():
                    os.chown(path,10001,10001)
                    os.chmod(path,0o600)
        os.setgroups([])
        os.setgid(10001)
        os.setuid(10001)
    os.execv(sys.executable,[sys.executable,'run.py'])


if __name__=='__main__':main()

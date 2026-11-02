"""Consistent SQLite backup including WAL contents. Never copy only a live .sqlite3 file."""
import sys,argparse,sqlite3
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.config import Config,load_dotenv
p=argparse.ArgumentParser(description=__doc__);p.add_argument('destination');args=p.parse_args()
load_dotenv();cfg=Config()
if cfg.database_url:raise SystemExit('Use your PostgreSQL managed backups or pg_dump; this script is for SQLite only.')
source=Path(cfg.database_path).resolve();dest=Path(args.destination).resolve()
if not source.is_file():raise SystemExit('No application database exists at the configured path.')
if dest.exists():raise SystemExit('Choose a new backup filename; existing files will not be overwritten.')
dest.parent.mkdir(parents=True,exist_ok=True)
with sqlite3.connect(source.as_uri()+'?mode=ro',uri=True) as src,sqlite3.connect(dest) as dst:src.backup(dst)
print('Consistent backup created:',dest)

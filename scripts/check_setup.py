"""Show configuration gaps without displaying any credential values or contacting providers."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.config import load_dotenv,Config
from app.db import Database
from app.service import Service
from app.vault import IntegrationStore
load_dotenv();cfg=Config()
try:cfg.validate()
except ValueError as e:print('Startup configuration:',e);raise SystemExit(1)
if cfg.database_url or Path(cfg.database_path).exists():
 db=Database(cfg.database_path,cfg.database_url)
 store=IntegrationStore(Service(db,cfg));store.load();store.verify_keys()
for name,issues in [('Research',cfg.research_readiness()),('Live email',cfg.email_readiness())]:
 print(name+': '+('configured; live verification still required' if not issues else 'setup needed'))
 for issue in issues:print(' - '+issue)
print('This check does not call any provider or send email.')

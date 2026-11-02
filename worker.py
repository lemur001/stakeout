"""Optional separate worker. Web service should use RUN_WORKER=false in this topology."""
from app.config import load_dotenv,Config
from app.db import Database
from app.service import Service
from app.worker import Worker
if __name__=='__main__':
    load_dotenv();cfg=Config();cfg.validate();db=Database(cfg.database_path,cfg.database_url);db.migrate()
    try:Worker(Service(db,cfg)).run()
    except KeyboardInterrupt:pass

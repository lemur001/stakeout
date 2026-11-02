"""Optional separate worker. Web service should use RUN_WORKER=false in this topology."""
from app.config import load_dotenv,Config
from app.db import Database
from app.service import Service
from app.worker import Worker
from app.prospecting.worker import DiscoveryWorker
from app.vault import IntegrationStore
if __name__=='__main__':
    load_dotenv();cfg=Config();cfg.validate();db=Database(cfg.database_path,cfg.database_url);db.migrate()
    service=Service(db,cfg);IntegrationStore(service).load()
    discovery=DiscoveryWorker(service);discovery.start()
    try:Worker(service).run()
    except KeyboardInterrupt:pass
    finally:discovery.stop()

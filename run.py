"""Start the standalone application: python run.py"""
from app.config import load_dotenv,Config
import uvicorn
if __name__=='__main__':
    load_dotenv();config=Config();config.validate()
    from app.api import create_app
    print(f'Stakeout Civic: {config.base_url}')
    print('Live email is OFF.' if not config.allow_live_send else 'Live email requires approvals, provider checks and an unpaused campaign.')
    uvicorn.run(create_app(config),host=config.host,port=config.port,proxy_headers=False,
                log_level='info',access_log=False,server_header=False,limit_concurrency=64,timeout_keep_alive=5)

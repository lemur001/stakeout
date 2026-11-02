"""Re-encrypt vault and MFA records with ENCRYPTION_KEY, retaining old-key read access."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.config import Config,load_dotenv
from app.db import Database
from app.vault import Vault
from app.core import iso


def main():
    load_dotenv();config=Config();config.validate()
    if not config.encryption_key_previous:raise SystemExit('Set ENCRYPTION_KEY_PREVIOUS before rotating.')
    db=Database(config.database_path,config.database_url);vault=Vault(config)
    with db.transaction() as tx:
        for row in tx.all('SELECT name,ciphertext FROM secret_store'):
            value=vault.decrypt(row['name'],row['ciphertext'])
            tx.execute('UPDATE secret_store SET ciphertext=?,updated_at=? WHERE name=?',(vault.encrypt(row['name'],value),iso(),row['name']))
        for row in tx.all('SELECT user_id,ciphertext FROM user_mfa'):
            purpose='mfa:'+row['user_id'];value=vault.decrypt(purpose,row['ciphertext'])
            tx.execute('UPDATE user_mfa SET ciphertext=? WHERE user_id=?',(vault.encrypt(purpose,value),row['user_id']))
    print('Encrypted records rotated. Verify a restart and login before removing ENCRYPTION_KEY_PREVIOUS.')
    print('Keep the old key securely for any backups encrypted with it.')


if __name__=='__main__':main()

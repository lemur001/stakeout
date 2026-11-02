"""Generate boot secrets privately, never on stdout. Does not overwrite a file."""
import argparse
import base64
import os
from pathlib import Path
import secrets


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=Path(__file__).resolve().parents[1]/'.env.railway')
    args=parser.parse_args()
    values={
        'APP_MODE':'production','HOST':'0.0.0.0','RUN_WORKER':'true',
        'ALLOW_LIVE_SEND':'false','DATABASE_PATH':'/app/data/civic.sqlite3',
        'ENCRYPTION_KEY':base64.urlsafe_b64encode(secrets.token_bytes(32)).decode(),
        'APP_SECRET':secrets.token_urlsafe(48),'SETUP_TOKEN':secrets.token_urlsafe(48),
    }
    fd=os.open(args.output,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'w',encoding='utf-8') as file:
        file.write('# PRIVATE: transfer to Railway variables and your password manager. Never commit.\n')
        file.write('\n'.join(key+'='+value for key,value in values.items())+'\n')
    print('Private deployment variables saved to '+str(args.output.resolve()))
    print('Keep ENCRYPTION_KEY and APP_SECRET backed up separately from the database.')
    print('Add APP_URL after Railway generates the public HTTPS domain, if it is not auto-detected.')


if __name__=='__main__':main()

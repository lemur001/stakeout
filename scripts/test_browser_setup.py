"""Exercise the real first-run wizard over local HTTPS using synthetic credentials."""
import base64
import datetime
import ipaddress
from pathlib import Path
import secrets
import socket
import sys
import tempfile
import threading
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from cryptography import x509
from cryptography.hazmat.primitives import hashes,serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from playwright.sync_api import sync_playwright
import pyotp
import uvicorn
from app.api import create_app
from app.config import Config,ROOT


def main():
    output=ROOT/'.local';output.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(dir=output,prefix='browser-') as folder:
        folder=Path(folder)
        private=rsa.generate_private_key(public_exponent=65537,key_size=2048)
        name=x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,'localhost')])
        now=datetime.datetime.now(datetime.timezone.utc)
        cert=(x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(private.public_key())
              .serial_number(x509.random_serial_number()).not_valid_before(now-datetime.timedelta(minutes=1))
              .not_valid_after(now+datetime.timedelta(hours=1))
              .add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address('127.0.0.1'))]),critical=False)
              .sign(private,hashes.SHA256()))
        (folder/'cert.pem').write_bytes(cert.public_bytes(serialization.Encoding.PEM))
        (folder/'key.pem').write_bytes(private.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()))
        with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
        config=Config(mode='production',base_url=f'https://127.0.0.1:{port}',database_path=str(folder/'browser.sqlite3'),database_url='',
                      app_secret=secrets.token_urlsafe(48),encryption_key=base64.urlsafe_b64encode(secrets.token_bytes(32)).decode(),
                      setup_token=secrets.token_urlsafe(48),admin_email='',admin_password='',run_worker=False,seed_on_start=True,allow_live_send=False)
        app=create_app(config)
        server=uvicorn.Server(uvicorn.Config(app,host='127.0.0.1',port=port,access_log=False,log_level='error',
                                           ssl_certfile=str(folder/'cert.pem'),ssl_keyfile=str(folder/'key.pem')))
        thread=threading.Thread(target=server.run,daemon=True);thread.start()
        try:
            for _ in range(100):
                if server.started:break
                time.sleep(.05)
            assert server.started,'HTTPS test server failed to start'
            with sync_playwright() as p:
                chrome=Path('C:/Program Files/Google/Chrome/Application/chrome.exe')
                browser=p.chromium.launch(headless=True,**({'executable_path':str(chrome)} if chrome.exists() else {}))
                context=browser.new_context(ignore_https_errors=True,viewport={'width':1440,'height':1000})
                page=context.new_page();errors=[]
                page.on('pageerror',lambda error:errors.append(str(error)))
                page.goto(config.base_url)
                page.get_by_label('One-time setup token').wait_for()
                page.screenshot(path=str(output/'setup-desktop.png'),full_page=True)
                page.set_viewport_size({'width':390,'height':844})
                page.screenshot(path=str(output/'setup-mobile.png'),full_page=True)
                assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth'),'Mobile overflow'
                page.set_viewport_size({'width':1440,'height':1000})
                page.get_by_label('One-time setup token').fill(config.setup_token)
                page.get_by_label('Your name',exact=True).fill('Test Operator')
                page.get_by_label('Sign-in email').fill('owner@example.org')
                password='synthetic browser test passphrase only'
                page.get_by_label('Choose a strong password').fill(password)
                page.get_by_label('Confirm password').fill(password)
                page.get_by_role('button',name='Set up two-factor authentication').click()
                secret=page.get_by_label('Authenticator setup key').input_value()
                page.get_by_label('Six-digit authenticator code').fill(pyotp.TOTP(secret).now())
                page.get_by_role('button',name='Create secure account').click()
                recovery_codes=page.locator('.recovery-codes').inner_text().splitlines()
                recovery=recovery_codes[0]
                page.get_by_label('I saved these codes in a secure password manager.').check()
                page.get_by_role('button',name='Continue',exact=True).click()
                page.get_by_label('Agency name').fill('Test Agency')
                page.get_by_label('Sender name',exact=True).fill('Test Operator')
                page.get_by_label('Sender email',exact=True).fill('owner@example.org')
                page.get_by_label('Business postal address').fill('Synthetic test address')
                page.get_by_role('button',name='Save and continue',exact=True).click()
                page.get_by_label('Gemini API key',exact=True).fill('synthetic-gemini-key')
                page.get_by_label('DataForSEO API login',exact=True).fill('synthetic-dataforseo-login')
                page.get_by_label('DataForSEO API password',exact=True).fill('synthetic-dataforseo-password')
                page.get_by_label('I confirmed permission to retrieve and retain the source content.').check()
                page.get_by_role('button',name='Save and continue',exact=True).click()
                page.get_by_label('SMTP hostname').fill('smtp.example.org')
                page.get_by_label('SMTP username').fill('owner@example.org')
                page.get_by_label('SMTP password',exact=True).fill('synthetic-smtp-password')
                page.get_by_label('From email').fill('owner@example.org')
                page.get_by_role('button',name='Save and continue',exact=True).click()
                page.get_by_role('button',name='Open workspace').wait_for()
                page.screenshot(path=str(output/'setup-review.png'),full_page=True)
                page.get_by_role('button',name='Open workspace').click()
                page.locator('#page').wait_for()
                assert page.evaluate('localStorage.length===0 && sessionStorage.length===0')
                page.reload();page.locator('#page').wait_for()
                from browser_discovery import exercise_discovery
                exercise_discovery(page,app.state.service,output)
                # Use a fresh browser session: secure cookie and recovery-based login.
                context.clear_cookies();page.reload()
                page.get_by_label('Email address',exact=True).fill('owner@example.org')
                page.get_by_label('Password',exact=True).fill(password)
                page.get_by_label('Authenticator or recovery code').fill(recovery)
                page.get_by_role('button',name='Sign in',exact=True).click()
                page.locator('#page').wait_for()
                page.goto(config.base_url+'/#settings')
                page.get_by_role('button',name='Authenticator & recovery codes',exact=True).click()
                page.get_by_label('Current password',exact=True).fill(password)
                page.get_by_label('Current authenticator or recovery code').fill(recovery_codes[1])
                page.get_by_role('button',name='Set up authenticator',exact=True).click()
                new_secret=page.get_by_label('New authenticator setup key').input_value()
                page.get_by_label('New authenticator code',exact=True).fill(pyotp.TOTP(new_secret).now())
                page.get_by_label('Current authenticator or recovery code').fill(recovery_codes[2])
                page.get_by_role('button',name='Confirm authenticator',exact=True).click()
                page.get_by_label('I saved these recovery codes securely.').check()
                page.get_by_role('button',name='Done',exact=True).click()
                assert not errors,errors
                browser.close()
            print('Browser setup passed: real HTTPS, MFA, recovery login, encrypted settings, page-reload session, desktop/mobile layout; zero page errors.')
            print('Screenshots saved under .local/setup-*.png (no real credentials).')
        finally:
            server.should_exit=True;thread.join(timeout=10)


if __name__=='__main__':main()

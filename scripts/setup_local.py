from pathlib import Path
import secrets
root=Path(__file__).resolve().parents[1]
p=root/'.env'
if p.exists():
    print('.env already exists; left unchanged.')
else:
    text=(root/'.env.example').read_text()
    text=text.replace('WEBHOOK_SECRET=','WEBHOOK_SECRET='+secrets.token_urlsafe(32),1)
    text=text.replace('ADMIN_TOKEN=','ADMIN_TOKEN='+secrets.token_urlsafe(32),1)
    p.write_text(text)
    try:
        p.chmod(0o600)
    except OSError:
        pass
    print('Created .env with random credentials. Open it locally to copy ADMIN_TOKEN into the dashboard. Do not commit it.')

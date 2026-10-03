import hmac
from fastapi import Header, HTTPException, Request


def webhook_auth(request: Request, x_webhook_secret: str = Header(default='')):
    if not hmac.compare_digest(x_webhook_secret, request.app.state.settings.webhook_secret):
        raise HTTPException(401, 'invalid_webhook_secret')


def admin_auth(request: Request, authorization: str = Header(default='')):
    if not hmac.compare_digest(authorization, 'Bearer ' + request.app.state.settings.admin_token):
        raise HTTPException(401, 'admin_auth_required')

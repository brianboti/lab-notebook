"""Who is calling. The app never builds its own sign-in: the platform puts one in front of it.

- exposure: lab-members: Google's Identity-Aware Proxy has signed the person in and passes their address in
  X-Goog-Authenticated-User-Email (`accounts.google.com:name@example.edu`).
- exposure: authenticated: Cloud Run has already verified the caller's Google identity token before the request
  arrives, so the token's `email` claim can be read without checking the signature again. This is safe only because
  the platform refuses public services; an app that could be reached without that check must verify the token.

Programs that create or delete records through the JSON API also present the API key (a Secret Manager secret).
"""

import base64
import hmac
import json

from fastapi import HTTPException, Request

IAP_HEADER = "x-goog-authenticated-user-email"


def current_user(request: Request) -> str:
    proxied = request.headers.get(IAP_HEADER, "")
    if proxied:
        return proxied.split(":", 1)[-1]
    authorization = request.headers.get("authorization", "")
    if authorization.lower().startswith("bearer "):
        return token_email(authorization[7:]) or "service-caller"
    return "anonymous"


def token_email(token: str) -> str | None:
    try:
        payload = token.split(".")[1]
        claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    except (IndexError, ValueError):
        return None
    email = claims.get("email")
    return email if isinstance(email, str) else None


def require_api_key(request: Request, expected: str | None) -> None:
    if not expected:
        raise HTTPException(503, "The API key is not configured for this service")
    if not hmac.compare_digest(request.headers.get("x-api-key", ""), expected):
        raise HTTPException(401, "Missing or wrong X-API-Key")

"""
Google Identity Services (GIS) Token Verification Service.
Verifies Google OAuth2 ID tokens (JWTs) using the official google-auth library.

Checks performed:
1. Valid cryptographic RSA signature matching Google public certs.
2. Audience matches configured GOOGLE_CLIENT_ID.
3. Issuer is 'accounts.google.com' or 'https://accounts.google.com'.
4. Token expiration timestamp.
5. Presence of verified email address.
"""

import logging
from typing import Dict, Any, Optional

from google.oauth2 import id_token as google_id_token
from google.auth.transport import requests as google_requests

from app.config import settings

logger = logging.getLogger("intervai.google_auth")


def verify_google_id_token(
    token: str,
    client_id: Optional[str] = None,
    http_request: Optional[Any] = None,
) -> Dict[str, Any]:
    """
    Verifies a Google ID token received from the frontend Google Identity Services flow.

    Returns the verified token payload dictionary containing:
    - 'email': user email
    - 'name': user display name
    - 'sub': Google unique user identifier
    - 'picture': user avatar URL (if provided)
    - 'email_verified': True / False

    Raises ValueError with a descriptive message if verification fails.
    """
    if not token or not token.strip():
        raise ValueError("Google ID token (credential) is required.")

    expected_client_id = client_id if client_id is not None else settings.GOOGLE_CLIENT_ID
    if not expected_client_id:
        raise ValueError("Google Client ID is not configured on the server.")

    req = http_request if http_request is not None else google_requests.Request()

    try:
        id_info = google_id_token.verify_oauth2_token(
            token.strip(),
            req,
            audience=expected_client_id,
        )
    except Exception as e:
        logger.warning(f"Google ID token cryptographic/audience verification failed: {e}")
        raise ValueError(f"Google token verification failed: {str(e)}")

    # Verify issuer
    issuer = id_info.get("iss", "")
    if issuer not in ("accounts.google.com", "https://accounts.google.com"):
        logger.warning(f"Rejected Google token with invalid issuer: {issuer}")
        raise ValueError(f"Invalid Google token issuer: {issuer}")

    # Verify email
    email = id_info.get("email")
    if not email:
        logger.warning("Rejected Google token without email claim")
        raise ValueError("Google ID token does not contain an email address.")

    if not id_info.get("email_verified", False):
        logger.warning(f"Rejected Google token with unverified email: {email}")
        raise ValueError("Google email address is not verified.")

    return id_info

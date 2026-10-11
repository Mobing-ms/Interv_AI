"""
Signed URL Service.
Generates and verifies time-limited, cryptographically signed URLs (HMAC-SHA256)
for accessing interview recordings (audio streams and video manifests) securely.
"""

import hmac
import hashlib
import time
from typing import Dict, Any, Optional
from app.config import settings


def generate_signed_recording_url(
    session_id: int,
    file_type: str,
    expires_in_seconds: int = 3600,
    base_url: str = "",
) -> Dict[str, Any]:
    """
    Generates a signed, expiring URL for a session recording file.
    
    Args:
        session_id: The interview session ID.
        file_type: The recording asset type ('audio', 'video', 'manifest').
        expires_in_seconds: Expiry window in seconds (default 1 hour / 3600s).
        base_url: Optional host prefix (e.g. 'http://localhost:8000').
        
    Returns:
        Dict with url, expires_at timestamp, and signature.
    """
    expires_at = int(time.time()) + expires_in_seconds
    token_payload = f"{session_id}:{file_type}:{expires_at}".encode("utf-8")
    secret_str = getattr(settings, "SECRET_KEY", getattr(settings, "JWT_SECRET_KEY", "intervai-secret"))
    secret = secret_str.encode("utf-8")
    signature = hmac.new(secret, token_payload, hashlib.sha256).hexdigest()

    path = f"/session/{session_id}/recording/{file_type}?expires={expires_at}&sig={signature}"
    full_url = f"{base_url.rstrip('/')}{path}" if base_url else path

    return {
        "url": full_url,
        "expires_at": expires_at,
        "signature": signature,
        "file_type": file_type,
        "session_id": session_id,
    }


def verify_signed_recording_url(
    session_id: int,
    file_type: str,
    expires_at: int,
    signature: str,
) -> bool:
    """
    Validates the cryptographic signature and ensures the URL has not expired.
    
    Returns True if valid, False otherwise.
    """
    # 1. Check expiration
    now = int(time.time())
    if now > expires_at:
        return False

    # 2. Check HMAC signature
    token_payload = f"{session_id}:{file_type}:{expires_at}".encode("utf-8")
    secret_str = getattr(settings, "SECRET_KEY", getattr(settings, "JWT_SECRET_KEY", "intervai-secret"))
    secret = secret_str.encode("utf-8")
    expected_sig = hmac.new(secret, token_payload, hashlib.sha256).hexdigest()

    return hmac.compare_digest(expected_sig, signature)

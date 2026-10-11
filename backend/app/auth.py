from datetime import datetime, timedelta, timezone
from typing import Optional
import bcrypt
import jwt
from fastapi import Depends, HTTPException, status, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from app.config import settings
from app.database import get_db
from app.models import User

security = HTTPBearer(auto_error=False)


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain_password: str, hashed_password: Optional[str]) -> bool:
    if not hashed_password:
        return False
    try:
        return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))
    except Exception:
        return False


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    to_encode.update({"exp": expire, "type": "access"})
    return jwt.encode(to_encode, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def create_refresh_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    )
    to_encode.update({"exp": expire, "type": "refresh"})
    return jwt.encode(to_encode, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def decode_token(token: str) -> dict:
    try:
        payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
            headers={"WWW-Authenticate": "Bearer"},
        )


def get_current_user(
    auth_credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    db: Session = Depends(get_db)
) -> User:
    if not auth_credentials or not auth_credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication credentials were not provided",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = auth_credentials.credentials
    payload = decode_token(token)

    if payload.get("type") != "access":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token type for authentication",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token subject",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        uid = int(user_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid user ID in token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user = db.query(User).filter(User.id == uid).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return user


def create_guest_token(guest_id: str, session_id: int, expires_delta: Optional[timedelta] = None) -> str:
    """
    Creates a signed JWT guest access token valid for 24 hours.
    Stores guest subject identifier and the specific authorized session ID.
    """
    to_encode = {
        "sub": guest_id,
        "session_id": session_id,
        "is_guest": True,
        "type": "guest_access",
    }
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(hours=settings.GUEST_RETENTION_HOURS)
    )
    to_encode["exp"] = expire
    return jwt.encode(to_encode, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def decode_guest_token(token: str) -> dict:
    """
    Decodes and validates a guest access token.
    Raises HTTPException 401 if invalid or expired.
    """
    try:
        payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
        if payload.get("type") != "guest_access" or not payload.get("is_guest"):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token type for guest access",
            )
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Guest session token has expired (24-hour limit)",
        )
    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid guest session token",
        )


class AuthContext:
    """
    Represents the authenticated caller context:
    - Registered User: user is populated, is_guest=False
    - Anonymous Guest: user=None, is_guest=True, guest_id & guest_session_id populated
    """
    def __init__(
        self,
        user: Optional[User] = None,
        is_guest: bool = False,
        guest_id: Optional[str] = None,
        guest_session_id: Optional[int] = None,
    ):
        self.user = user
        self.is_guest = is_guest
        self.guest_id = guest_id
        self.guest_session_id = guest_session_id


def get_current_user_or_guest(
    request: Request,
    db: Session = Depends(get_db),
) -> AuthContext:
    """
    Resolves the caller identity from:
    1. Authorization: Bearer <user_or_guest_token>
    2. X-Guest-Token header
    3. guest_token httpOnly cookie
    """
    auth_header = request.headers.get("Authorization")
    guest_header = request.headers.get("X-Guest-Token")
    guest_cookie = request.cookies.get("guest_token")

    # 1. Try Bearer header
    if auth_header and auth_header.startswith("Bearer "):
        token = auth_header[7:].strip()
        try:
            payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
            token_type = payload.get("type")

            if token_type == "access":
                user_id = payload.get("sub")
                if user_id:
                    user = db.query(User).filter(User.id == int(user_id)).first()
                    if user:
                        return AuthContext(user=user, is_guest=False)
            elif token_type == "guest_access":
                return AuthContext(
                    user=None,
                    is_guest=True,
                    guest_id=str(payload.get("sub")),
                    guest_session_id=payload.get("session_id"),
                )
        except Exception:
            pass  # Fall through to guest header/cookie

    # 2. Try X-Guest-Token header
    if guest_header:
        try:
            payload = decode_guest_token(guest_header.strip())
            return AuthContext(
                user=None,
                is_guest=True,
                guest_id=str(payload.get("sub")),
                guest_session_id=payload.get("session_id"),
            )
        except Exception:
            pass

    # 3. Try guest_token cookie
    if guest_cookie:
        try:
            payload = decode_guest_token(guest_cookie.strip())
            return AuthContext(
                user=None,
                is_guest=True,
                guest_id=str(payload.get("sub")),
                guest_session_id=payload.get("session_id"),
            )
        except Exception:
            pass

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication required. Please sign in or provide a valid guest session token.",
        headers={"WWW-Authenticate": "Bearer"},
    )


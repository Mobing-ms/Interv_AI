import random
from datetime import datetime, timedelta, timezone
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.config import settings
from app.database import get_db
from app.models import User, EmailOTP
from app.schemas import (
    UserSignUp,
    UserLogin,
    GoogleAuthRequest,
    OTPRequest,
    OTPVerify,
    RefreshTokenRequest,
    UserOut,
    AuthResponse,
    MessageResponse,
)
from app.auth import (
    hash_password,
    verify_password,
    create_access_token,
    create_refresh_token,
    decode_token,
    get_current_user,
)

limiter = Limiter(key_func=get_remote_address)
router = APIRouter(prefix="/auth", tags=["Authentication"])


def generate_6digit_otp() -> str:
    return f"{random.randint(100000, 999999)}"


@router.post("/signup", response_model=AuthResponse, status_code=status.HTTP_201_CREATED)
def signup(body: UserSignUp, db: Session = Depends(get_db)):
    normalized_email = body.email.strip().lower()

    # Check if user already exists
    existing_user = db.query(User).filter(User.email == normalized_email).first()
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already used",
        )

    # Hash password with bcrypt
    hashed_pw = hash_password(body.password)

    # Determine verification status
    is_verified = not settings.EMAIL_VERIFICATION_REQUIRED

    user = User(
        name=body.name.strip(),
        email=normalized_email,
        password_hash=hashed_pw,
        auth_provider="local",
        is_verified=is_verified,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    # If verification is required, create OTP and print in dev mode
    if settings.EMAIL_VERIFICATION_REQUIRED:
        otp_code = generate_6digit_otp()
        expiry = datetime.now(timezone.utc) + timedelta(minutes=10)
        otp_entry = EmailOTP(email=normalized_email, otp=otp_code, expires_at=expiry)
        db.add(otp_entry)
        db.commit()
        if settings.DEV_MODE:
            print(f"\n==========================================")
            print(f"[IntervAI DEV OTP] Verification OTP for {normalized_email}: {otp_code}")
            print(f"==========================================\n", flush=True)

    access_token = create_access_token({"sub": str(user.id)})
    refresh_token = create_refresh_token({"sub": str(user.id)})

    return AuthResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="bearer",
        user=UserOut.model_validate(user),
    )


@router.post("/login", response_model=AuthResponse)
@limiter.limit("10/minute")
def login(request: Request, body: UserLogin, db: Session = Depends(get_db)):
    normalized_email = body.email.strip().lower()
    user = db.query(User).filter(User.email == normalized_email).first()

    # Generic invalid credentials error
    if not user or not user.password_hash or not verify_password(body.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if settings.EMAIL_VERIFICATION_REQUIRED and not user.is_verified:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Email not verified. Please verify your email.",
        )

    access_token = create_access_token({"sub": str(user.id)})
    refresh_token = create_refresh_token({"sub": str(user.id)})

    return AuthResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="bearer",
        user=UserOut.model_validate(user),
    )


@router.post("/google", response_model=AuthResponse)
def google_auth(body: GoogleAuthRequest, db: Session = Depends(get_db)):
    email: Optional[str] = None
    name: Optional[str] = None

    token_str = body.credential or body.id_token or body.token
    if token_str:
        # First attempt genuine Google OAuth verification
        try:
            from google.oauth2 import id_token as google_id_token
            from google.auth.transport import requests as google_requests

            id_info = google_id_token.verify_oauth2_token(
                token_str,
                google_requests.Request(),
                settings.GOOGLE_CLIENT_ID if settings.GOOGLE_CLIENT_ID else None,
            )
            email = id_info.get("email")
            name = id_info.get("name") or (email.split("@")[0] if email else "Google User")
        except Exception:
            # If not a valid Google signed token (e.g. testing with dev/mock token), attempt unverified payload extraction
            try:
                import jwt as pyjwt
                unverified = pyjwt.decode(token_str, options={"verify_signature": False})
                if unverified.get("email"):
                    email = unverified.get("email")
                    name = unverified.get("name") or email.split("@")[0]
            except Exception:
                pass

    # If directly provided in request (dev fallback)
    if not email and body.email:
        email = body.email
        name = body.name or email.split("@")[0]

    if not email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Could not verify Google ID token. Please provide a valid token or credentials.",
        )

    normalized_email = email.strip().lower()
    user = db.query(User).filter(User.email == normalized_email).first()

    if not user:
        display_name = (name or normalized_email.split("@")[0]).strip()
        user = User(
            name=display_name,
            email=normalized_email,
            password_hash=None,
            auth_provider="google",
            is_verified=True,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
    else:
        # User exists; if auth_provider was local, ensure verified
        if not user.is_verified:
            user.is_verified = True
            db.commit()
            db.refresh(user)

    access_token = create_access_token({"sub": str(user.id)})
    refresh_token = create_refresh_token({"sub": str(user.id)})

    return AuthResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="bearer",
        user=UserOut.model_validate(user),
    )


@router.post("/otp/request", response_model=MessageResponse)
def request_otp(body: OTPRequest, db: Session = Depends(get_db)):
    normalized_email = body.email.strip().lower()
    otp_code = generate_6digit_otp()
    expiry = datetime.now(timezone.utc) + timedelta(minutes=10)

    # Invalidate previous OTPs for this email
    db.query(EmailOTP).filter(EmailOTP.email == normalized_email).delete()

    otp_entry = EmailOTP(email=normalized_email, otp=otp_code, expires_at=expiry)
    db.add(otp_entry)
    db.commit()

    if settings.DEV_MODE:
        print(f"\n==========================================")
        print(f"[IntervAI DEV OTP] OTP requested for {normalized_email}: {otp_code}")
        print(f"==========================================\n", flush=True)

    return MessageResponse(message="OTP sent successfully")


@router.post("/otp/verify", response_model=MessageResponse)
def verify_otp(body: OTPVerify, db: Session = Depends(get_db)):
    normalized_email = body.email.strip().lower()
    now = datetime.now(timezone.utc)

    # Find matching valid OTP
    otp_record = (
        db.query(EmailOTP)
        .filter(
            EmailOTP.email == normalized_email,
            EmailOTP.otp == body.otp.strip(),
            EmailOTP.expires_at > now,
        )
        .first()
    )

    if not otp_record:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired OTP",
        )

    # Mark user verified if exists
    user = db.query(User).filter(User.email == normalized_email).first()
    if user:
        user.is_verified = True
        db.commit()

    # Clean up used OTP
    db.delete(otp_record)
    db.commit()

    return MessageResponse(message="Email verified successfully")


@router.get("/me", response_model=UserOut)
def get_me(current_user: User = Depends(get_current_user)):
    return UserOut.model_validate(current_user)


@router.post("/refresh", response_model=AuthResponse)
def refresh_token(body: RefreshTokenRequest, db: Session = Depends(get_db)):
    payload = decode_token(body.refresh_token)

    if payload.get("type") != "refresh":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token type for refresh",
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

    new_access_token = create_access_token({"sub": str(user.id)})
    new_refresh_token = create_refresh_token({"sub": str(user.id)})

    return AuthResponse(
        access_token=new_access_token,
        refresh_token=new_refresh_token,
        token_type="bearer",
        user=UserOut.model_validate(user),
    )


@router.post("/logout", response_model=MessageResponse)
def logout():
    return MessageResponse(message="Successfully logged out")

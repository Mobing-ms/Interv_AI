import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
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
from app.services.google_auth_service import verify_google_id_token

limiter = Limiter(key_func=get_remote_address)
logger = logging.getLogger("intervai.auth")
router = APIRouter(prefix="/auth", tags=["Authentication"])


def generate_6digit_otp() -> str:
    return f"{secrets.randbelow(900000) + 100000}"


def _try_link_guest_session(
    request: Request,
    response: Response,
    body_guest_id: Optional[int],
    user_id: int,
    db: Session,
):
    """
    Links an anonymous guest session to a newly created or authenticated user account.
    Checks:
    1. Explicit body.guest_session_id
    2. X-Guest-Token header
    3. guest_token cookie
    """
    # A guest session is only linked when the caller proves they hold its guest token.
    from app.auth import guest_session_ids_proven_by_request
    proven = guest_session_ids_proven_by_request(request)
    if body_guest_id and body_guest_id not in proven:
        logger.warning("Refusing to link guest session #%s: no matching guest token presented", body_guest_id)
        return
    guest_sess_id = body_guest_id or (next(iter(proven)) if len(proven) == 1 else None)

    if guest_sess_id:
        try:
            from app.services.guest_service import link_guest_session_to_user
            link_guest_session_to_user(int(guest_sess_id), user_id, db)
        except Exception:
            logger.exception("Failed to link guest session #%s to user #%s", guest_sess_id, user_id)
        response.delete_cookie("guest_token")


@router.post("/signup", response_model=AuthResponse, status_code=status.HTTP_201_CREATED)
@router.post("/register", response_model=AuthResponse, status_code=status.HTTP_201_CREATED)
def signup(
    request: Request,
    response: Response,
    body: UserSignUp,
    db: Session = Depends(get_db),
):
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

    # Link guest session if candidate practiced as a guest before signing up
    _try_link_guest_session(request, response, body.guest_session_id, user.id, db)

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
def login(
    request: Request,
    response: Response,
    body: UserLogin,
    db: Session = Depends(get_db),
):
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

    # Link guest session if candidate practiced as a guest before logging in
    _try_link_guest_session(request, response, body.guest_session_id, user.id, db)

    access_token = create_access_token({"sub": str(user.id)})
    refresh_token = create_refresh_token({"sub": str(user.id)})

    return AuthResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="bearer",
        user=UserOut.model_validate(user),
    )


@router.post("/google", response_model=AuthResponse)
def google_auth(
    request: Request,
    response: Response,
    body: GoogleAuthRequest,
    db: Session = Depends(get_db),
):
    token_str = body.credential or body.id_token or body.token
    if not token_str or not token_str.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Google ID token (credential) is required.",
        )

    client_id = settings.GOOGLE_CLIENT_ID
    if not client_id:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Google Client ID is not configured on the server. Please set GOOGLE_CLIENT_ID in backend .env",
        )

    try:
        id_info = verify_google_id_token(token_str.strip(), client_id=client_id)
    except ValueError as e:
        # verify_google_id_token raises ValueError with client-facing messages about the
        # caller's own token (audience/issuer/unverified email); safe to return.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(e),
        )
    except Exception:
        logging.getLogger("intervai.auth").exception("Google ID token verification error")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Google ID token verification failed.",
        )

    email = id_info.get("email", "").strip().lower()
    name = (id_info.get("name") or email.split("@")[0]).strip()

    user = db.query(User).filter(User.email == email).first()

    if not user:
        user = User(
            name=name,
            email=email,
            password_hash=None,
            auth_provider="google",
            is_verified=True,
            onboarding_status="not_started",
        )
        db.add(user)
        db.commit()
        db.refresh(user)
    else:
        # User exists; ensure verified since Google verified the email
        if not user.is_verified:
            user.is_verified = True
            db.commit()
            db.refresh(user)

    # Link guest session if candidate practiced as a guest before Google login
    _try_link_guest_session(request, response, body.guest_session_id, user.id, db)

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

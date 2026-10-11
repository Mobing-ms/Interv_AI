from fastapi.testclient import TestClient
from app.main import app
from app.database import Base, engine

# Reset DB for tests
Base.metadata.drop_all(bind=engine)
Base.metadata.create_all(bind=engine)

client = TestClient(app)

def test_signup_and_login_flow():
    # 1. Sign up
    signup_data = {
        "name": "Alex Kumar",
        "email": "alex.kumar@example.com",
        "password": "Password123!"
    }
    res = client.post("/auth/signup", json=signup_data)
    assert res.status_code == 201, res.text
    body = res.json()
    assert "access_token" in body
    assert "refresh_token" in body
    assert body["user"]["name"] == "Alex Kumar"
    assert body["user"]["email"] == "alex.kumar@example.com"
    assert body["user"]["auth_provider"] == "local"
    assert body["user"]["is_verified"] is True
    access_token = body["access_token"]
    refresh_token = body["refresh_token"]

    # Duplicate signup should fail with "Email already used"
    dup_res = client.post("/auth/signup", json=signup_data)
    assert dup_res.status_code == 400
    assert "already used" in dup_res.json()["detail"].lower()

    # 2. Login with correct credentials
    login_res = client.post("/auth/login", json={
        "email": "alex.kumar@example.com",
        "password": "Password123!"
    })
    assert login_res.status_code == 200
    assert "access_token" in login_res.json()
    assert login_res.json()["user"]["name"] == "Alex Kumar"

    # 3. Login with wrong credentials (generic error)
    wrong_res = client.post("/auth/login", json={
        "email": "alex.kumar@example.com",
        "password": "WrongPassword!"
    })
    assert wrong_res.status_code == 401
    assert wrong_res.json()["detail"].lower() == "invalid credentials"

    # 4. GET /auth/me
    me_res = client.get("/auth/me", headers={"Authorization": f"Bearer {access_token}"})
    assert me_res.status_code == 200
    assert me_res.json()["name"] == "Alex Kumar"
    assert me_res.json()["email"] == "alex.kumar@example.com"

    # GET /auth/me without token should fail
    unauth_res = client.get("/auth/me")
    assert unauth_res.status_code == 401

    # 5. POST /auth/refresh
    refresh_res = client.post("/auth/refresh", json={"refresh_token": refresh_token})
    assert refresh_res.status_code == 200
    assert "access_token" in refresh_res.json()

    # 6. POST /auth/logout
    logout_res = client.post("/auth/logout")
    assert logout_res.status_code == 200

    # 7. Google Auth
    from unittest.mock import patch
    from app.config import settings
    orig_cid = settings.GOOGLE_CLIENT_ID
    settings.GOOGLE_CLIENT_ID = "mock-google-client-id"
    try:
        with patch("app.routers.auth.verify_google_id_token") as mock_verify:
            mock_verify.return_value = {
                "email": "sarah.connor@gmail.com",
                "name": "Sarah Connor",
                "sub": "google-sub-sarah-123",
            }
            google_res = client.post("/auth/google", json={"credential": "mocked-valid-token"})
            assert google_res.status_code == 200, google_res.text
            g_body = google_res.json()
            assert g_body["user"]["name"] == "Sarah Connor"
            assert g_body["user"]["email"] == "sarah.connor@gmail.com"
            assert g_body["user"]["auth_provider"] == "google"
            assert g_body["user"]["is_verified"] is True
    finally:
        settings.GOOGLE_CLIENT_ID = orig_cid

    # Check /auth/me with google user's token
    g_me = client.get("/auth/me", headers={"Authorization": f"Bearer {g_body['access_token']}"})
    assert g_me.status_code == 200
    assert g_me.json()["name"] == "Sarah Connor"

    # 8. OTP endpoints
    otp_req = client.post("/auth/otp/request", json={"email": "test@example.com"})
    assert otp_req.status_code == 200

    print("All backend auth tests passed successfully!")

if __name__ == "__main__":
    test_signup_and_login_flow()

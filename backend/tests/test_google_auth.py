"""
Unit and integration tests for Google Sign-In end-to-end flow.
Tests cover:
1. Sign in with valid Google ID token for a new user (creates user, returns JWTs).
2. Sign in with valid Google ID token for an existing user (returns JWTs, no duplicate error).
3. Token refresh using the issued refresh_token.
4. Logout endpoint.
5. Re-signing in after logout.
6. Rejection of wrong-audience token (401 Unauthorized).
7. Rejection of expired or invalid-signature token (401 Unauthorized).
8. Rejection of invalid issuer (401 Unauthorized).
9. Rejection of missing/empty credential (400 Bad Request).
10. Direct unit tests of verify_google_id_token service with mocked google-auth library.
"""

import unittest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

from app.main import app
from app.config import settings
from app.database import Base, engine, SessionLocal
from app.models import User
from app.services.google_auth_service import verify_google_id_token

client = TestClient(app)

TEST_CLIENT_ID = "test-client-id-12345.apps.googleusercontent.com"


class TestGoogleAuthFlow(unittest.TestCase):
    def setUp(self):
        # Configure client ID for testing
        self._orig_client_id = settings.GOOGLE_CLIENT_ID
        settings.GOOGLE_CLIENT_ID = TEST_CLIENT_ID

        # Reset DB tables
        Base.metadata.drop_all(bind=engine)
        Base.metadata.create_all(bind=engine)

    def tearDown(self):
        settings.GOOGLE_CLIENT_ID = self._orig_client_id
        Base.metadata.drop_all(bind=engine)

    @patch("app.routers.auth.verify_google_id_token")
    def test_google_sign_in_new_user(self, mock_verify):
        """1. Signing in with valid Google token creates a new user and issues JWTs."""
        mock_verify.return_value = {
            "email": "jane.doe@gmail.com",
            "name": "Jane Doe",
            "picture": "https://lh3.googleusercontent.com/photo.jpg",
            "sub": "google-user-id-12345",
        }

        response = client.post("/auth/google", json={"credential": "mocked-valid-google-id-token"})
        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()
        self.assertIn("access_token", data)
        self.assertIn("refresh_token", data)
        self.assertEqual(data["token_type"], "bearer")
        self.assertEqual(data["user"]["email"], "jane.doe@gmail.com")
        self.assertEqual(data["user"]["name"], "Jane Doe")
        self.assertEqual(data["user"]["auth_provider"], "google")
        self.assertTrue(data["user"]["is_verified"])

        # Verify access token works with /auth/me
        me_res = client.get("/auth/me", headers={"Authorization": f"Bearer {data['access_token']}"})
        self.assertEqual(me_res.status_code, 200)
        self.assertEqual(me_res.json()["email"], "jane.doe@gmail.com")

    @patch("app.routers.auth.verify_google_id_token")
    def test_google_sign_in_existing_user(self, mock_verify):
        """2. Existing user signs in again: retrieves existing user and succeeds without duplicates."""
        mock_verify.return_value = {
            "email": "jane.doe@gmail.com",
            "name": "Jane Doe",
            "sub": "google-user-id-12345",
        }

        # First sign in
        res1 = client.post("/auth/google", json={"credential": "valid-token"})
        self.assertEqual(res1.status_code, 200)
        user_id_1 = res1.json()["user"]["id"]

        # Second sign in
        res2 = client.post("/auth/google", json={"credential": "valid-token"})
        self.assertEqual(res2.status_code, 200)
        user_id_2 = res2.json()["user"]["id"]

        self.assertEqual(user_id_1, user_id_2)

        # Confirm only one user exists in database
        db = SessionLocal()
        users = db.query(User).filter(User.email == "jane.doe@gmail.com").all()
        db.close()
        self.assertEqual(len(users), 1)

    @patch("app.routers.auth.verify_google_id_token")
    def test_sign_in_refresh_and_logout_cycle(self, mock_verify):
        """3, 4, 5. Full lifecycle: sign in -> refresh token -> logout -> sign in again."""
        mock_verify.return_value = {
            "email": "alex.test@gmail.com",
            "name": "Alex Test",
            "sub": "google-sub-789",
        }

        # Step A: Sign in
        res = client.post("/auth/google", json={"credential": "google-token-abc"})
        self.assertEqual(res.status_code, 200)
        tokens = res.json()
        refresh_token = tokens["refresh_token"]

        # Step B: Refresh token
        refresh_res = client.post("/auth/refresh", json={"refresh_token": refresh_token})
        self.assertEqual(refresh_res.status_code, 200)
        self.assertIn("access_token", refresh_res.json())
        new_access_token = refresh_res.json()["access_token"]

        # Test new access token
        me_res = client.get("/auth/me", headers={"Authorization": f"Bearer {new_access_token}"})
        self.assertEqual(me_res.status_code, 200)
        self.assertEqual(me_res.json()["email"], "alex.test@gmail.com")

        # Step C: Logout
        logout_res = client.post("/auth/logout")
        self.assertEqual(logout_res.status_code, 200)

        # Step D: Sign in again
        res_relogin = client.post("/auth/google", json={"credential": "google-token-abc"})
        self.assertEqual(res_relogin.status_code, 200)
        self.assertEqual(res_relogin.json()["user"]["email"], "alex.test@gmail.com")

    @patch("app.routers.auth.verify_google_id_token")
    def test_wrong_audience_token_rejected(self, mock_verify):
        """6. Token minted for another Google Client ID must be rejected with 401."""
        mock_verify.side_effect = ValueError("Google token verification failed: Token has wrong audience")

        response = client.post("/auth/google", json={"credential": "attacker-token-from-different-client-id"})
        self.assertEqual(response.status_code, 401)
        self.assertIn("wrong audience", response.json()["detail"].lower())

    @patch("app.routers.auth.verify_google_id_token")
    def test_expired_or_invalid_signature_rejected(self, mock_verify):
        """7. Expired or tampered Google token must be rejected with 401."""
        mock_verify.side_effect = ValueError("Google token verification failed: Signature verification failed")

        response = client.post("/auth/google", json={"credential": "tampered-or-expired-token"})
        self.assertEqual(response.status_code, 401)
        self.assertIn("verification failed", response.json()["detail"].lower())

    def test_missing_credential_rejected(self):
        """9. Missing or empty credential payload returns 400."""
        response = client.post("/auth/google", json={})
        self.assertEqual(response.status_code, 400)
        self.assertIn("required", response.json()["detail"].lower())

        response_empty = client.post("/auth/google", json={"credential": "   "})
        self.assertEqual(response_empty.status_code, 400)
        self.assertIn("required", response_empty.json()["detail"].lower())


class TestGoogleAuthServiceDirect(unittest.TestCase):
    """Direct unit tests for verify_google_id_token in google_auth_service.py."""

    @patch("app.services.google_auth_service.google_id_token.verify_oauth2_token")
    def test_service_successful_verification(self, mock_verify_oauth2):
        mock_verify_oauth2.return_value = {
            "iss": "https://accounts.google.com",
            "aud": "my-client-id.apps.googleusercontent.com",
            "email": "user@gmail.com",
            "email_verified": True,
            "name": "User Name",
            "sub": "1234567890",
        }

        result = verify_google_id_token("valid_token", client_id="my-client-id.apps.googleusercontent.com")
        self.assertEqual(result["email"], "user@gmail.com")
        self.assertEqual(result["name"], "User Name")

    @patch("app.services.google_auth_service.google_id_token.verify_oauth2_token")
    def test_service_wrong_audience_raises_value_error(self, mock_verify_oauth2):
        mock_verify_oauth2.side_effect = ValueError("Token has wrong audience 9999.apps.googleusercontent.com")

        with self.assertRaises(ValueError) as cm:
            verify_google_id_token("token_with_bad_aud", client_id="expected-client-id")
        self.assertIn("wrong audience", str(cm.exception).lower())

    @patch("app.services.google_auth_service.google_id_token.verify_oauth2_token")
    def test_service_invalid_issuer_raises_value_error(self, mock_verify_oauth2):
        mock_verify_oauth2.return_value = {
            "iss": "https://evil-issuer.com",
            "aud": "expected-client-id",
            "email": "attacker@gmail.com",
            "email_verified": True,
        }

        with self.assertRaises(ValueError) as cm:
            verify_google_id_token("token_from_wrong_issuer", client_id="expected-client-id")
        self.assertIn("issuer", str(cm.exception).lower())

    @patch("app.services.google_auth_service.google_id_token.verify_oauth2_token")
    def test_service_unverified_email_raises_value_error(self, mock_verify_oauth2):
        mock_verify_oauth2.return_value = {
            "iss": "https://accounts.google.com",
            "aud": "expected-client-id",
            "email": "unverified@gmail.com",
            "email_verified": False,
        }

        with self.assertRaises(ValueError) as cm:
            verify_google_id_token("token_unverified_email", client_id="expected-client-id")
        self.assertIn("not verified", str(cm.exception).lower())


if __name__ == "__main__":
    unittest.main()

"""Unit tests for app.core.security (section 32)."""
import time
import uuid

import pytest

from app.core.security import (
    InvalidTokenError,
    TokenType,
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    new_session_id,
    verify_password,
)


class TestPasswordHashing:
    def test_hash_is_not_plaintext(self):
        assert hash_password("mypassword") != "mypassword"

    def test_verify_correct_password(self):
        hashed = hash_password("correct-horse-battery-staple")
        assert verify_password("correct-horse-battery-staple", hashed) is True

    def test_verify_incorrect_password(self):
        hashed = hash_password("correct-horse-battery-staple")
        assert verify_password("wrong-password", hashed) is False

    def test_hash_uses_argon2id(self):
        hashed = hash_password("anything")
        assert hashed.startswith("$argon2id$")

    def test_same_password_hashes_differently_each_time(self):
        # Argon2 salts randomly — two hashes of the same password must differ.
        assert hash_password("same") != hash_password("same")


class TestJWT:
    def test_access_token_round_trip(self):
        session_id = new_session_id()
        token = create_access_token(subject="user-1", gym_id="gym-1", role="OWNER", session_id=session_id)
        payload = decode_token(token, expected_type=TokenType.ACCESS)
        assert payload["sub"] == "user-1"
        assert payload["gym_id"] == "gym-1"
        assert payload["role"] == "OWNER"
        assert payload["session_id"] == session_id
        assert payload["type"] == "access"

    def test_refresh_token_round_trip(self):
        session_id = new_session_id()
        token = create_refresh_token(subject="user-1", gym_id=None, role="SUPER_ADMIN", session_id=session_id)
        payload = decode_token(token, expected_type=TokenType.REFRESH)
        assert payload["type"] == "refresh"
        assert payload["gym_id"] is None

    def test_access_token_rejected_as_refresh(self):
        session_id = new_session_id()
        token = create_access_token(subject="user-1", gym_id="gym-1", role="OWNER", session_id=session_id)
        with pytest.raises(InvalidTokenError):
            decode_token(token, expected_type=TokenType.REFRESH)

    def test_refresh_token_rejected_as_access(self):
        session_id = new_session_id()
        token = create_refresh_token(subject="user-1", gym_id="gym-1", role="OWNER", session_id=session_id)
        with pytest.raises(InvalidTokenError):
            decode_token(token, expected_type=TokenType.ACCESS)

    def test_garbage_token_raises(self):
        with pytest.raises(InvalidTokenError):
            decode_token("not.a.jwt", expected_type=TokenType.ACCESS)

    def test_empty_token_raises(self):
        with pytest.raises(InvalidTokenError):
            decode_token("", expected_type=TokenType.ACCESS)

    def test_token_signed_with_wrong_secret_is_rejected(self):
        # Simulates an access token being replayed against the refresh secret
        # and vice versa — the type check plus distinct secrets both must hold.
        import jose.jwt as jose_jwt

        from app.core.config import settings

        forged = jose_jwt.encode(
            {"sub": "attacker", "gym_id": None, "role": "SUPER_ADMIN", "session_id": "x", "type": "access"},
            "not-the-real-secret",
            algorithm=settings.JWT_ALGORITHM,
        )
        with pytest.raises(InvalidTokenError):
            decode_token(forged, expected_type=TokenType.ACCESS)

    def test_session_ids_are_unique(self):
        ids = {new_session_id() for _ in range(100)}
        assert len(ids) == 100
        for sid in ids:
            uuid.UUID(sid)  # must parse as a valid UUID

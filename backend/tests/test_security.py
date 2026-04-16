import sys
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, ".")

from app.core.security import create_access_token, decode_access_token


def test_create_and_decode_token():
    token = create_access_token({"sub": "user123"})
    payload = decode_access_token(token)
    assert payload["sub"] == "user123"
    assert "exp" in payload
    assert "iat" in payload


def test_decode_expired_token():
    from datetime import timedelta
    token = create_access_token({"sub": "user123"}, expires_delta=timedelta(seconds=-1))
    with pytest.raises(Exception) as exc_info:
        decode_access_token(token)
    assert exc_info.value.status_code == 401


def test_decode_invalid_token():
    with pytest.raises(Exception) as exc_info:
        decode_access_token("invalid.token.here")
    assert exc_info.value.status_code == 401

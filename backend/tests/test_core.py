"""核心层：脱敏、凭证加密、口令与令牌。"""

from __future__ import annotations

import pytest

from app.core.crypto import CredentialDecryptError, decrypt_secret, encrypt_secret
from app.core.mask import mask_text, mask_value
from app.core.security import (
    TokenError,
    create_access_token,
    decode_token,
    hash_password,
    verify_password,
)


class TestMask:
    def test_key_value_pairs(self):
        assert "***" in mask_text("password=Example!@#$%&*()+=NotARealSecret")
        assert "***" in mask_text('{"app_secret": "abc123def456"}')
        assert "abc123def456" not in mask_text('{"app_secret": "abc123def456"}')

    def test_database_connection_identity_is_hidden(self):
        masked = mask_text(
            "mssql+pymssql://example_user:Example!@#$%&*()+=NotARealSecret@192.0.2.10:11433/BI"
        )
        assert "Example!@#$%&*()+=NotARealSecret" not in masked
        assert "example_user" not in masked
        assert "192.0.2.10:11433" not in masked
        assert "[数据库连接已隐藏]" in masked
        old_log = mask_text("目标：sqlserver://example_user@192.0.2.10:11433/BI 的 示例_营销单")
        assert "example_user" not in old_log
        assert "192.0.2.10" not in old_log
        assert "示例_营销单" in old_log

    def test_webhook_token(self):
        masked = mask_text("https://oapi.dingtalk.com/robot/send?access_token=8a1b2c3d4e5f&sign=xyz")
        assert "8a1b2c3d4e5f" not in masked
        assert "sign=***" in masked

    def test_plain_text_untouched(self):
        assert mask_text("同步完成，新增 120 行") == "同步完成，新增 120 行"

    def test_mask_value_keeps_tail(self):
        assert mask_value("abcdefghij") == "******ghij"
        assert mask_value("") == ""
        assert mask_value("ab") == "**"


class TestCrypto:
    def test_round_trip(self):
        payload = {"app_secret": "SECxxx", "charset": "utf8"}
        token = encrypt_secret(payload)
        assert token.startswith("v1:")
        assert decrypt_secret(token) == payload

    def test_ciphertext_is_not_plaintext(self):
        token = encrypt_secret({"app_secret": "SECxxx"})
        assert "SECxxx" not in token

    def test_empty_ciphertext_rejected(self):
        with pytest.raises(CredentialDecryptError):
            decrypt_secret("")

    def test_unknown_version_rejected(self):
        with pytest.raises(CredentialDecryptError):
            decrypt_secret("v9:whatever")

    def test_tampered_ciphertext_rejected(self):
        token = encrypt_secret({"a": 1})
        with pytest.raises(CredentialDecryptError):
            decrypt_secret(token[:-4] + "AAAA")


class TestSecurity:
    def test_password_round_trip(self):
        hashed = hash_password("Docsync@2026")
        assert verify_password("Docsync@2026", hashed)
        assert not verify_password("wrong", hashed)

    def test_password_too_short(self):
        with pytest.raises(ValueError):
            hash_password("short")

    def test_long_password_supported(self):
        long_password = "x" * 200
        hashed = hash_password(long_password)
        assert verify_password(long_password, hashed)
        assert not verify_password("x" * 199, hashed)

    def test_verify_with_garbage_hash(self):
        assert not verify_password("whatever", "not-a-hash")
        assert not verify_password("", "")

    def test_token_round_trip(self):
        token = create_access_token(7, username="alice", role="admin")
        claims = decode_token(token)
        assert claims["sub"] == "7"
        assert claims["username"] == "alice"
        assert claims["role"] == "admin"

    def test_expired_token_rejected(self):
        token = create_access_token(7, expires_minutes=-1)
        with pytest.raises(TokenError, match="已过期"):
            decode_token(token)

    def test_garbage_token_rejected(self):
        with pytest.raises(TokenError):
            decode_token("not.a.jwt")

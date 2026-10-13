"凭证的对称加密。"

from __future__ import annotations

import json
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import settings

_KEY_VERSION = "v1"


class CredentialDecryptError(RuntimeError):
    """凭证解密失败：主密钥不对，或密文被篡改。"""


_fernet: Fernet | None = None


def _get_fernet() -> Fernet:
    global _fernet
    if _fernet is None:
        _fernet = Fernet(settings.resolve_master_key())
    return _fernet


def reset_fernet_cache() -> None:
    """测试用：主密钥变更后清缓存。"""
    global _fernet
    _fernet = None


def encrypt_secret(payload: dict[str, Any]) -> str:
    """把任意 JSON 可序列化的 secret 字典加密成字符串。"""
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
    return f"{_KEY_VERSION}:{_get_fernet().encrypt(raw).decode()}"


def decrypt_secret(token: str) -> dict[str, Any]:
    if not token:
        raise CredentialDecryptError("密文为空")
    version, _, body = token.partition(":")
    if version != _KEY_VERSION or not body:
        raise CredentialDecryptError(f"未知的密文版本：{version!r}")
    try:
        raw = _get_fernet().decrypt(body.encode())
    except InvalidToken as exc:
        raise CredentialDecryptError("凭证解密失败：DOCSYNC_MASTER_KEY 与加密时不一致，或密文已损坏") from exc
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise CredentialDecryptError("凭证内容不是合法 JSON") from exc


def app_secret_of(token: str) -> str:
    "解出应用记录里的 AppSecret 明文。"
    return str(decrypt_secret(token).get("app_secret") or "")

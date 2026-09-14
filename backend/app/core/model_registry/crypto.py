"""outbound API Key 对称加密（Q82-3：DB 加密 + env 主密钥）。

主密钥取 settings.master_key（环境变量 LOOM_MASTER_KEY）。为使用方便，任意
口令串经 sha256 派生为 Fernet key；也可直接放 urlsafe-base64 的 32 字节 Fernet key。
未配置主密钥时退化为进程内临时密钥并告警——仅限测试/本地，跨进程旧密文不可解。
"""

import base64
import hashlib
import logging
from functools import lru_cache

from cryptography.fernet import Fernet

from app.core.config import get_settings

logger = logging.getLogger(__name__)


class DecryptionFailed(Exception):
    pass


def _derive(raw: str) -> bytes:
    try:
        Fernet(raw.encode())
        return raw.encode()
    except (ValueError, TypeError):
        return base64.urlsafe_b64encode(hashlib.sha256(raw.encode("utf-8")).digest())


@lru_cache(maxsize=1)
def _fernet() -> Fernet:
    raw = get_settings().master_key
    if not raw:
        logger.warning(
            "LOOM_MASTER_KEY not set: using ephemeral process key, "
            "encrypted API keys will not survive restarts (dev/test only)"
        )
        return Fernet(Fernet.generate_key())
    return Fernet(_derive(raw))


def reset_caches() -> None:
    _fernet.cache_clear()


def encrypt(plaintext: str) -> bytes:
    return _fernet().encrypt(plaintext.encode("utf-8"))


def decrypt(ciphertext: bytes) -> str:
    from cryptography.fernet import InvalidToken

    try:
        return _fernet().decrypt(ciphertext).decode("utf-8")
    except InvalidToken as exc:
        raise DecryptionFailed("ciphertext was not produced with the current master key") from exc


def fingerprint(plaintext: str) -> str:
    """明文末 4 位展示码（管理页识别用，永不回显明文）。"""
    tail = plaintext[-4:] if len(plaintext) >= 4 else plaintext
    return tail.rjust(4, "*")

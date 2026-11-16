"""密码哈希与强度校验。

旧库里的 password 是明文；这里保持向后兼容：
`verify_password` 能校验明文，登录成功后由路由把它升级成 scrypt 哈希。
新注册只写哈希。格式：`scrypt$<salt_b64>$<digest_b64>`。
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import re

_PREFIX = "scrypt$"
_N = 2**14
_R = 8
_P = 1
_DKLEN = 32
_MAXMEM = 64 * 1024 * 1024


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=_N,
        r=_R,
        p=_P,
        dklen=_DKLEN,
        maxmem=_MAXMEM,
    )
    return f"{_PREFIX}{base64.b64encode(salt).decode()}${base64.b64encode(digest).decode()}"


def is_legacy_password(stored: str) -> bool:
    return bool(stored) and not stored.startswith(_PREFIX)


def verify_password(password: str, stored: str) -> bool:
    if not stored:
        return False
    if is_legacy_password(stored):
        return hmac.compare_digest(password, stored)
    try:
        _, salt_b64, digest_b64 = stored.split("$", 2)
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(digest_b64)
        actual = hashlib.scrypt(
            password.encode("utf-8"),
            salt=salt,
            n=_N,
            r=_R,
            p=_P,
            dklen=len(expected),
            maxmem=_MAXMEM,
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(actual, expected)


def validate_password_strength(password: str) -> str | None:
    if len(password) < 10:
        return "密码长度不能少于10位"
    if len(password) > 128:
        return "密码不能超过 128 位"
    if not re.search(r"[A-Z]", password):
        return "密码必须包含至少一个大写字母"
    if not re.search(r"[a-z]", password):
        return "密码必须包含至少一个小写字母"
    if not re.search(r"[0-9]", password):
        return "密码必须包含至少一个数字"
    return None

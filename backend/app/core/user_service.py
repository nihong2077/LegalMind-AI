"""用户认证服务：基于 Redis 存储用户账号，使用标准库 hashlib 做密码哈希。

用户数据结构（Redis Hash）：
    key: legalmind:user:{username}
    fields:
        username: 用户名
        password_hash: 密码哈希（格式：pbkdf2_sha256$iterations$salt$hash）
        created_at: 创建时间戳
"""

import hashlib
import hmac
import os
import time
import secrets
from typing import Optional

from .redis_client import get_redis

# Redis key 前缀
USER_PREFIX = "legalmind:user:"
USER_INDEX_KEY = "legalmind:user_index"  # 用户名集合，用于枚举/判重

# 密码哈希参数
PBKDF2_ITERATIONS = 100_000
HASH_ALGORITHM = "sha256"
SALT_BYTES = 16
HASH_BYTES = 32


def hash_password(password: str) -> str:
    """使用 PBKDF2-HMAC-SHA256 哈希密码，返回格式：pbkdf2_sha256$iterations$salt_hex$hash_hex"""
    salt = os.urandom(SALT_BYTES)
    dk = hashlib.pbkdf2_hmac(HASH_ALGORITHM, password.encode("utf-8"), salt, PBKDF2_ITERATIONS, dklen=HASH_BYTES)
    return f"pbkdf2_{HASH_ALGORITHM}${PBKDF2_ITERATIONS}${salt.hex()}${dk.hex()}"


def verify_password(password: str, stored_hash: str) -> bool:
    """验证密码是否匹配存储的哈希值"""
    try:
        parts = stored_hash.split("$")
        if len(parts) != 4:
            return False
        algorithm, iterations, salt_hex, hash_hex = parts
        if algorithm != f"pbkdf2_{HASH_ALGORITHM}":
            return False
        salt = bytes.fromhex(salt_hex)
        expected_hash = bytes.fromhex(hash_hex)
        iterations_int = int(iterations)
        # 使用 hmac.compare_digest 防止时序攻击
        dk = hashlib.pbkdf2_hmac(HASH_ALGORITHM, password.encode("utf-8"), salt, iterations_int, dklen=len(expected_hash))
        return hmac.compare_digest(dk, expected_hash)
    except (ValueError, AttributeError):
        return False


async def create_user(username: str, password: str) -> dict:
    """创建新用户，返回用户信息 dict。若用户已存在则抛出 ValueError。"""
    username = username.strip()
    if not username or not password:
        raise ValueError("用户名和密码不能为空")
    if len(username) < 2 or len(username) > 32:
        raise ValueError("用户名长度需为 2-32 个字符")
    if len(password) < 4 or len(password) > 64:
        raise ValueError("密码长度需为 4-64 个字符")

    r = get_redis()
    user_key = f"{USER_PREFIX}{username}"

    # 检查用户是否已存在
    if await r.exists(user_key):
        raise ValueError("用户名已被注册")

    password_hash = hash_password(password)
    now = str(time.time())
    user_data = {
        "username": username,
        "password_hash": password_hash,
        "created_at": now,
    }
    pipe = r.pipeline()
    pipe.hset(user_key, mapping=user_data)
    pipe.sadd(USER_INDEX_KEY, username)
    await pipe.execute()
    return user_data


async def authenticate_user(username: str, password: str) -> Optional[dict]:
    """验证用户凭据，成功返回用户 dict，失败返回 None。"""
    username = username.strip()
    r = get_redis()
    user_key = f"{USER_PREFIX}{username}"
    data = await r.hgetall(user_key)
    if not data:
        return None
    stored_hash = data.get("password_hash", "")
    if not stored_hash or not verify_password(password, stored_hash):
        return None
    return data


async def get_user(username: str) -> Optional[dict]:
    """获取用户信息（不含密码哈希）"""
    username = username.strip()
    r = get_redis()
    data = await r.hgetall(f"{USER_PREFIX}{username}")
    if not data:
        return None
    # 不返回密码哈希
    return {"username": data.get("username", username), "created_at": data.get("created_at", "")}


async def ensure_default_admin() -> None:
    """确保默认管理员账号存在（admin/admin），便于首次部署登录。"""
    r = get_redis()
    admin_key = f"{USER_PREFIX}admin"
    if not await r.exists(admin_key):
        await create_user("admin", "admin")

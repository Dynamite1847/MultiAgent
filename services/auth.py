"""
Authentication service: multi-user with JWT tokens.
Users stored in users.json, passwords hashed with bcrypt.
"""
import json
import os
import jwt
import bcrypt
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

PROJECT_ROOT = Path(__file__).parent.parent
USERS_FILE = PROJECT_ROOT / "users.json"

# JWT config from env
AUTH_SECRET = os.getenv("AUTH_SECRET", "change-me-to-a-random-secret-key")
JWT_ALGORITHM = "HS256"
JWT_EXPIRY_DAYS = 7


def _load_users() -> list:
    if not USERS_FILE.exists():
        return []
    with open(USERS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_users(users: list):
    with open(USERS_FILE, "w", encoding="utf-8") as f:
        json.dump(users, f, ensure_ascii=False, indent=2)


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))


def authenticate(username: str, password: str) -> Optional[dict]:
    """Verify username + password. Returns user dict (without hash) or None."""
    users = _load_users()
    for user in users:
        if user["username"] == username:
            if verify_password(password, user["password_hash"]):
                return {
                    "user_id": user["user_id"],
                    "username": user["username"],
                    "display_name": user.get("display_name", user["username"]),
                }
            return None
    return None


def create_token(user: dict) -> str:
    """Create a JWT token for the authenticated user."""
    payload = {
        "user_id": user["user_id"],
        "username": user["username"],
        "display_name": user.get("display_name", user["username"]),
        "exp": datetime.now(timezone.utc) + timedelta(days=JWT_EXPIRY_DAYS),
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, AUTH_SECRET, algorithm=JWT_ALGORITHM)


def verify_token(token: str) -> Optional[dict]:
    """Verify and decode a JWT token. Returns payload or None."""
    try:
        payload = jwt.decode(token, AUTH_SECRET, algorithms=[JWT_ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None


def init_default_users():
    """Create default users if users.json doesn't exist."""
    if USERS_FILE.exists():
        return
    default_users = [
        {
            "user_id": "user_dongyu",
            "username": "dongyu",
            "display_name": "东宇",
            "password_hash": hash_password("dongyu123"),
        },
        {
            "user_id": "user_wife",
            "username": "miao",
            "display_name": "喵喵",
            "password_hash": hash_password("miao123"),
        },
    ]
    _save_users(default_users)

"""Password hashing, session tokens, and credential validation."""

from __future__ import annotations

import re
import secrets

import bcrypt

USERNAME_MIN = 3
USERNAME_MAX = 12
PASSWORD_MIN = 8
PASSWORD_MAX = 72  # bcrypt truncates input beyond 72 bytes
TOKEN_TTL_DAYS = 30

_USERNAME_RE = re.compile(r"^[A-Za-z0-9_-]+$")


def hash_password(plain: str) -> str:
    """
    Hash a password with bcrypt.

    Args:
        plain: Plaintext password (already length-validated)

    Returns:
        bcrypt hash string (UTF-8 decoded for storage)
    """
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, encoded: str) -> bool:
    """
    Check a plaintext password against a stored bcrypt hash.

    Args:
        plain: Candidate password
        encoded: Stored bcrypt hash string

    Returns:
        True if the password matches.
    """
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), encoded.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def new_token() -> str:
    """Generate an opaque, URL-safe session token (256 bits)."""
    return secrets.token_urlsafe(32)


def canon_username(raw: str) -> str:
    """Canonical form used for uniqueness: stripped and case-folded."""
    return raw.strip().casefold()


def validate_username(raw: str) -> str | None:
    """
    Validate a username.

    Returns:
        An error string if invalid, otherwise None.
    """
    name = raw.strip()
    if not (USERNAME_MIN <= len(name) <= USERNAME_MAX):
        return f"username must be {USERNAME_MIN}-{USERNAME_MAX} characters"
    if not _USERNAME_RE.match(name):
        return "username may only contain letters, digits, '_' and '-'"
    return None


def validate_password(raw: str) -> str | None:
    """
    Validate a password.

    Returns:
        An error string if invalid, otherwise None.
    """
    # bcrypt operates on bytes; enforce the byte length so multibyte
    # passwords are not silently truncated at 72 bytes.
    length = len(raw.encode("utf-8"))
    if length < PASSWORD_MIN:
        return f"password must be at least {PASSWORD_MIN} characters"
    if length > PASSWORD_MAX:
        return f"password must be at most {PASSWORD_MAX} bytes"
    return None

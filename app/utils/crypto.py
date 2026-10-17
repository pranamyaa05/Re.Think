"""
Cryptographic helpers for securely storing sensitive tokens (e.g. LeetCode session cookies).
Uses Fernet symmetric encryption with key derivation from app settings.
"""

import base64
import hashlib
import logging
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken

from app.config import settings

logger = logging.getLogger(__name__)


def _get_fernet() -> Fernet:
    """Derives a deterministic 32-byte urlsafe-base64 key from configuration."""
    raw_key = settings.encryption_key or settings.api_key or "rethink-secure-platform-encryption-key-v1"
    key_bytes = hashlib.sha256(raw_key.encode("utf-8")).digest()
    b64_key = base64.urlsafe_b64encode(key_bytes)
    return Fernet(b64_key)


def encrypt_token(token: Optional[str]) -> Optional[str]:
    """Encrypts a plaintext token into a Fernet token string. Returns None if input is empty."""
    if not token or not token.strip():
        return None
    f = _get_fernet()
    encrypted = f.encrypt(token.strip().encode("utf-8"))
    return encrypted.decode("utf-8")


def decrypt_token(encrypted_token: Optional[str]) -> Optional[str]:
    """Decrypts a Fernet token string back to plaintext. Returns None if input is empty or invalid."""
    if not encrypted_token or not encrypted_token.strip():
        return None
    f = _get_fernet()
    try:
        decrypted = f.decrypt(encrypted_token.strip().encode("utf-8"))
        return decrypted.decode("utf-8")
    except InvalidToken:
        logger.warning("Failed to decrypt token: Invalid or corrupted ciphertext/key.")
        # If token was stored unencrypted or with mismatched key, return as-is or None
        return None
    except Exception as e:
        logger.exception(f"Unexpected error during token decryption: {e}")
        return None

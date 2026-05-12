"""
Cryptographic utilities: signing, verification, key derivation.
Uses only stdlib (hashlib, hmac, secrets) to avoid heavy dependencies.
For production use, replace with a proper crypto library (e.g. PyNaCl).
"""
from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import base64
from typing import Optional, Tuple


def generate_key_pair(seed: Optional[str] = None) -> Tuple[str, str]:
    """
    Generate a (public_key, private_key) pair as hex strings.
    In production, use Ed25519 from PyNaCl or cryptography package.
    This is a deterministic stub using HKDF-like derivation.
    """
    if seed is None:
        seed = secrets.token_hex(32)
    private_key = hashlib.sha256(seed.encode()).hexdigest()
    public_key = hashlib.sha256((private_key + "pub").encode()).hexdigest()
    return public_key, private_key


def derive_next_key_digest(public_key: str) -> str:
    """Compute the digest commitment for the next key (pre-rotation commitment)."""
    return hashlib.sha256(("next:" + public_key).encode()).hexdigest()


def sign(data: str, private_key: str) -> str:
    """
    Sign data with private key. Returns base64-encoded HMAC-SHA256 signature.
    In production replace with Ed25519 signing.
    """
    sig = hmac.new(private_key.encode(), data.encode(), hashlib.sha256).digest()
    return base64.b64encode(sig).decode()


def verify(data: str, signature: str, public_key: str, private_key: str = "") -> bool:
    """
    Verify a signature. For this stub we re-sign with private key for verification.
    In production, use actual public-key verification.
    """
    if not private_key:
        return False
    expected = sign(data, private_key)
    return hmac.compare_digest(expected, signature)


def hash_data(data: str) -> str:
    """SHA-256 hash returning hex digest."""
    return hashlib.sha256(data.encode()).hexdigest()


def hash_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def prefix_from_public_key(public_key: str) -> str:
    """Derive an AID prefix from a public key."""
    digest = hashlib.sha256(public_key.encode()).digest()
    return "E" + base64.urlsafe_b64encode(digest).decode().rstrip("=")[:43]

"""NIST SP 800-38D AES-256-GCM envelopes for R2 tickets.

Layout: 12-byte nonce, then ciphertext and the 16-byte tag. Associated data
is empty. The key is 32 bytes from hex, standard base64, or raw bytes.
"""

from __future__ import annotations

import base64
import binascii
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


def decode_aes256_key(material: str | bytes) -> bytes:
    """Return 32 key bytes. Hex (64 chars), standard base64, or raw bytes."""
    if isinstance(material, bytes):
        if len(material) == 32:
            return material
        try:
            text = material.decode("ascii")
        except UnicodeDecodeError as exc:
            raise ValueError("AES-256 key must be 32 bytes") from exc
    else:
        text = material
    compact = "".join(text.split())
    if len(compact) == 64 and all(char in "0123456789abcdefABCDEF" for char in compact):
        try:
            key = bytes.fromhex(compact)
        except ValueError as exc:
            raise ValueError("AES-256 key must be 32 bytes") from exc
    else:
        try:
            key = base64.standard_b64decode(compact)
        except (binascii.Error, ValueError) as exc:
            raise ValueError("AES-256 key must be 32 bytes") from exc
    if len(key) != 32:
        raise ValueError("AES-256 key must be 32 bytes")
    return key


def seal_envelope(
    plaintext_bytes: bytes,
    key_hex_or_b64: str | bytes,
    nonce: bytes | None = None,
) -> bytes:
    """Return ``nonce || AESGCM(key).encrypt(nonce, plaintext, None)``."""
    key = decode_aes256_key(key_hex_or_b64)
    if nonce is None:
        nonce = os.urandom(12)
    if len(nonce) != 12:
        raise ValueError("AES-GCM nonce must be 12 bytes")
    return nonce + AESGCM(key).encrypt(nonce, plaintext_bytes, None)


def open_envelope(blob: bytes, key_hex_or_b64: str | bytes) -> bytes:
    """Open a ``nonce || ciphertext || tag`` blob. A bad tag raises ``InvalidTag``."""
    if len(blob) < 28:
        raise ValueError("sealed object is truncated")
    key = decode_aes256_key(key_hex_or_b64)
    return AESGCM(key).decrypt(blob[:12], blob[12:], None)
